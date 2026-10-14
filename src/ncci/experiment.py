"""Fixed-route experiments. Outputs are evidence, never replacement BKS."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time

from .contracts import fold, forward_float, ulps, VARIANTS
from .exact import evaluate_route, stages_for, forward, number
from .inputs import ROOT, write_json
from .static import structural


def rational_payload(result):
    return {k: str(v) if isinstance(v, Fraction) else v for k, v in result.items()}


def summarize_solution(record, bks, variants, exact=False):
    solution_deadline = time.monotonic() + 300
    routes = bks["routes"]
    evaluations = []
    for route in routes:
        row = {"route": route, "folds": {variant: fold(record, route, variant) for variant in variants}}
        for variant, result in row["folds"].items():
            if result["feasible"]:
                schedule = forward_float(record, route, result["departure"], slope=variant in ("v012", "slope", "strict"), strict=variant == "strict")
                generic = forward_float(record, route, result["departure"])
                result["generic_forward_feasible"] = generic["feasible"]
                result["generic_forward_duration"] = generic.get("duration")
                result["generic_forward_reproduces_cost"] = generic["feasible"] and generic["duration"] == result["duration"]
                result["forward_feasible"] = schedule["feasible"]
                result["forward_duration"] = schedule.get("duration")
                result["forward_reproduces_cost"] = schedule["feasible"] and schedule["duration"] == result["duration"]
        if exact:
            row["exact"] = {}
            for interpretation in ("binary", "decimal"):
                start = time.perf_counter()
                try:
                    remaining = solution_deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("per-solution rational budget exhausted")
                    result = evaluate_route(record, route, interpretation, timeout=min(120, remaining))
                    result["seconds"] = time.perf_counter() - start
                    row["exact"][interpretation] = rational_payload(result)
                    for variant, evaluated in row["folds"].items():
                        if evaluated["feasible"] and result["feasible"]:
                            error = Fraction(evaluated["duration"]) - result["duration"]
                            evaluated[f"{interpretation}_error"] = str(error)
                            evaluated[f"{interpretation}_abs_error"] = float(abs(error))
                            evaluated[f"{interpretation}_feasible_at_departure"] = forward(stages_for(record, route, interpretation)[0], number(evaluated["departure"], "binary")) is not None
                except (TimeoutError, MemoryError) as error:
                    row["exact"][interpretation] = {"status": "resource-limit", "error": str(error), "seconds": time.perf_counter() - start}
        evaluations.append(row)
    totals = {}
    for variant in variants:
        feasible = all(r["folds"][variant]["feasible"] for r in evaluations)
        total = 0.
        if feasible:
            for row in sorted(evaluations, key=lambda r: r["route"][0]):
                total += row["folds"][variant]["duration"]
            if bks["objective_function"] == "FleetCostDuration":
                total += record["instance"]["fleet_fixed_cost"] * len(routes)
        totals[variant] = {"feasible": feasible, "cost": total if feasible else None,
                           "matches_declared": feasible and total == bks.get("cost")}
    return {"structural_errors": structural(record["instance"], routes), "num_routes": len(routes), "totals": totals, "routes": evaluations}


def process_entry(entry, exact, variants, source_name):
    start = time.perf_counter()
    raw = (ROOT / entry["cache"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("input cache hash changed")
    record = json.loads(raw)
    result = {"id": record["id"], "source": source_name, "input_sha256": entry["sha256"],
              "size": record["instance"]["num_customers"],
              "family": record["instance"]["benchmark_name"],
              "current": summarize_solution(record, record["bks"], variants, exact)}
    old = record.get("baseline_bks")
    if old and old["routes"] != record["bks"]["routes"]:
        result["baseline"] = summarize_solution(record, old, variants, False)
    if "published" in record:
        traces = []
        for route, published in zip(record["bks"]["routes"], record["published"]["routes"]):
            traces.append({"published": published,
                           "forward": forward_float(record, route, published["t0"]),
                           "exact_binary_forward": rational_payload({"arrival": forward(stages_for(record, route, "binary")[0], number(published["t0"]))})})
        result["published_traces"] = traces
        result["published_cost"] = record["published"]["value"]
    result["seconds"] = time.perf_counter() - start
    result["worker_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result


def run(manifest_name, jobs=4, exact=False, all_variants=False, limit=None, resume=False):
    entries = json.loads((ROOT / "manifests" / manifest_name).read_text())
    available = [e for e in entries if e["status"] == "ready"]
    if limit is not None:
        available = available[:limit]
    selected_count = len(available)
    variants = list(VARIANTS) if all_variants else ["v011", "v012"]
    output = ROOT / "outputs/experiments" / manifest_name.removesuffix(".json")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    if resume:
        pending = []
        for entry in available:
            path = output / (hashlib.sha256(entry['id'].encode()).hexdigest() + '.json')
            prior = json.loads(path.read_text()) if path.exists() else {}
            valid = prior.get('input_sha256') == entry['sha256'] and prior.get('id') == entry['id']
            valid = valid and all(set(r['folds']) == set(variants) and ('exact' in r) == exact for r in prior.get('current', {}).get('routes', []))
            if valid:
                rows.append({'id': entry['id'], 'result': str(path.relative_to(ROOT)), 'status': 'complete', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            else:
                pending.append(entry)
        available = pending
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(process_entry, entry, exact, variants, manifest_name): entry for entry in available}
        for done, future in enumerate(as_completed(futures), 1):
            entry = futures[future]
            try:
                result = future.result()
                path = output / (hashlib.sha256(entry["id"].encode()).hexdigest() + ".json")
                write_json(path, result)
                rows.append({"id": entry["id"], "result": str(path.relative_to(ROOT)), "status": "complete", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            except Exception as error:
                rows.append({"id": entry["id"], "status": "error", "error": f"{type(error).__name__}: {error}"})
            if done % 10 == 0:
                print(f"Evaluated {done}/{len(available)}: {entry['id']}", flush=True)
                write_json(ROOT / "results" / manifest_name, sorted(rows, key=lambda r: r["id"]))
    write_json(ROOT / "results" / manifest_name, sorted(rows, key=lambda r: r["id"]))
    write_json(ROOT / "results" / (manifest_name.removesuffix(".json") + "-environment.json"),
               {"python": sys.version, "platform": platform.platform(), "variants": variants,
                "exact": exact, "jobs": jobs, "input_count": selected_count,
                "evaluated_count": len(available), "reused_count": selected_count - len(available),
                "unavailable": [e for e in entries if e["status"] != "ready"]})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="td-inputs.json")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--all-variants", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    rows = run(args.manifest, args.jobs, args.exact, args.all_variants, args.limit, args.resume)
    print(json.dumps({"complete": sum(r["status"] == "complete" for r in rows), "errors": [r for r in rows if r["status"] != "complete"]}))
