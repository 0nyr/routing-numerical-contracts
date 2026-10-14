"""Immutable identifiers and read-only materialization of locally pinned inputs."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("NCCI_ROOT", SOURCE_ROOT if (SOURCE_ROOT / 'vendor').is_dir() else Path.cwd())).resolve()
DEFAULT_DATA = Path(os.environ.get("MAMUT_ROUTING_ROOT", ROOT / 'external/MAMUT-routing'))


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def snapshot_repositories(data_root):
    rows = [{"path": ".", "baseline": "93d9cc4", "head": git(data_root, "rev-parse", "HEAD").decode().strip()}]
    for line in git(data_root, "ls-tree", "-r", "93d9cc4").decode().splitlines():
        meta, name = line.split("\t")
        mode, kind, commit = meta.split()
        if mode == "160000" and name.startswith("benchmarks/"):
            rows.append({"path": name, "baseline": commit, "head": git(data_root / name, "rev-parse", "HEAD").decode().strip()})
    for row in rows:
        row["baseline"] = git(data_root / row["path"], "rev-parse", row["baseline"]).decode().strip()
    write_json(ROOT / "manifests/data-repositories.json", rows)
    return rows


def owner(path, data_root, repos):
    relative = path.relative_to(data_root).as_posix()
    for row in sorted(repos, key=lambda r: len(r["path"]), reverse=True):
        if row["path"] != "." and relative.startswith(row["path"] + "/"):
            return row, path.relative_to(data_root / row["path"]).as_posix()
    return repos[0], relative


def pinned_bytes(path, data_root, repos, baseline=False):
    row, relative = owner(path, data_root, repos)
    return git(data_root / row["path"], "show", f'{row["baseline" if baseline else "head"]}:{relative}')


def read_json(path):
    data = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    return json.loads(data)


def materialize_one(bks_path, data_root, repos):
    # The frozen 0.12 loader is used only to materialize common canonical ATFs.
    # Neither compared route-fold implementation determines these inputs.
    sys.path.insert(0, str(ROOT / "vendor/v012/src"))
    from mamut_routing_lib.td.reprice import load_td_instance_for_routes, route_arcs
    current_bytes = pinned_bytes(bks_path, data_root, repos)
    current = json.loads(current_bytes)
    try:
        old_bytes = pinned_bytes(bks_path, data_root, repos, True)
        old = json.loads(old_bytes)
    except subprocess.CalledProcessError:
        old_bytes, old = None, None
    instance_path = bks_path.with_name(bks_path.name.split(".bks.")[0] + ".vrp.json")
    instance_bytes = pinned_bytes(instance_path, data_root, repos)
    if instance_path.read_bytes() != instance_bytes:
        raise ValueError("working instance differs from frozen Git input")
    instance = json.loads(instance_bytes)
    routes = current["routes"] + (old["routes"] if old else [])
    loaded = load_td_instance_for_routes(instance_path, routes, verify_sidecar_sha256=True)
    selected = route_arcs(routes, instance.get("depot", 0))
    record = {"id": bks_path.relative_to(data_root).as_posix(), "instance": instance,
              "bks": current, "baseline_bks": old,
              "arcs": [[i, j, f.xs, f.ys] for (i, j), f in sorted(loaded.atfs.arcs.items()) if (i, j) in selected],
              "source": {"instance_sha256": sha(instance_bytes), "bks_sha256": sha(current_bytes),
                         "baseline_bks_sha256": sha(old_bytes) if old_bytes else None,
                         "materializer": "v0.12.0 selected canonical ATFs; no route fold"}}
    return record


def prepare_task(path, data_root, repos):
    rel = path.relative_to(data_root).as_posix()
    start = time.monotonic()
    cached = ROOT / "outputs/inputs" / (sha(rel.encode()) + ".json")
    entry = {"id": rel, "cache": str(cached.relative_to(ROOT))}
    try:
        if not cached.exists():
            write_json(cached, materialize_one(path, data_root, repos))
        entry.update(status="ready", sha256=sha(cached.read_bytes()))
    except Exception as error:
        entry.update(status="unavailable", error=f"{type(error).__name__}: {error}")
    entry["materialize_seconds"] = time.monotonic() - start
    return entry


def prepare(data_root=DEFAULT_DATA, limit=None, maximum_size=None, jobs=4):
    repos = snapshot_repositories(data_root)
    paths = [p for p in sorted(data_root.joinpath("benchmarks").rglob("*.bks.*.json"))
             if "/TDVRP/" in p.as_posix() or "/TDVRPTW/" in p.as_posix()]
    if maximum_size is not None:
        paths = [p for p in paths if not any(part.startswith("n=") and int(part[2:]) > maximum_size for part in p.parts)]
    if limit is not None:
        paths = paths[:limit]
    manifest = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(prepare_task, path, data_root, repos) for path in paths]
        for done, future in enumerate(as_completed(futures), 1):
            entry = future.result()
            manifest.append(entry)
            if done % 25 == 0:
                print(f"Prepared {done}/{len(paths)}: {entry['id']}", flush=True)
                write_json(ROOT / "manifests/td-inputs.json", sorted(manifest, key=lambda r: r['id']))
    write_json(ROOT / "manifests/td-inputs.json", sorted(manifest, key=lambda r: r['id']))
    return manifest


def prepare_originals(data_root=DEFAULT_DATA, source=None):
    sys.path.insert(0, str(ROOT / "vendor/v012/src"))
    from mamut_routing_lib.td.reprice import load_td_instance_for_routes, route_arcs
    repos = snapshot_repositories(data_root)
    source = Path(source) if source else ROOT / 'fixtures/lera-original-solutions.json'
    raw = source.read_bytes()
    previous_source=json.loads((ROOT/'manifests/lera-originals-source.json').read_text())
    write_json(ROOT / "manifests/lera-originals-source.json", {"path": str(source), "sha256": sha(raw),
               "repository_commit": previous_source.get('repository_commit') if previous_source['sha256']==sha(raw) else None,
               "num_solutions": len(json.loads(raw))})
    (ROOT / "fixtures/lera-original-solutions.json").write_bytes(raw)
    entries = []
    for solution in json.loads(raw):
        name, size = solution["instance_name"].rsplit("_", 1)
        path = data_root / f"benchmarks/TDVRPTW/Dabia2013/n={size}/{name}.vrp.json"
        source_bytes = pinned_bytes(path, data_root, repos)
        end = int(size) + 1
        routes = [[v for v in r["path"] if v not in (0, end)] for r in solution["routes"]]
        loaded = load_td_instance_for_routes(path, routes, verify_sidecar_sha256=True)
        selected = route_arcs(routes, json.loads(source_bytes).get("depot", 0))
        record = {"id": solution["instance_name"], "instance": json.loads(source_bytes),
                  "bks": {"routes": routes, "cost": solution["value"], "objective_function": "Duration"},
                  "published": solution,
                  "arcs": [[i, j, f.xs, f.ys] for (i, j), f in sorted(loaded.atfs.arcs.items()) if (i, j) in selected],
                  "source": {"instance_sha256": sha(source_bytes), "solutions_sha256": sha(raw)}}
        cached = ROOT / "outputs/originals" / f'{solution["instance_name"]}.json'
        write_json(cached, record)
        entries.append({"id": record["id"], "cache": str(cached.relative_to(ROOT)), "sha256": sha(cached.read_bytes()), "status": "ready"})
    write_json(ROOT / "manifests/original-inputs.json", entries)
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--maximum-size", type=int)
    parser.add_argument("--originals", action="store_true")
    parser.add_argument("--original-solutions",type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    result = prepare_originals(args.data_root,args.original_solutions) if args.originals else prepare(args.data_root, args.limit, args.maximum_size, args.jobs)
    print(json.dumps({"records": len(result), "ready": sum(r["status"] == "ready" for r in result)}))
