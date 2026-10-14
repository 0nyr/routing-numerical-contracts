"""Read candidate history without writing to any benchmark repository."""
import argparse
from collections import Counter
from fractions import Fraction
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys

from .inputs import ROOT, DEFAULT_DATA, git, owner, write_json
from .static import left


def score(values):
    decimal = sum((Fraction(str(v)) for v in values), Fraction())
    binary = sum(map(Fraction, values), Fraction())
    return {"flat": left(values), "decimal": str(decimal), "binary": str(binary)}


def objective_key(cost, count, objective):
    return (cost,) if objective == "MonoCost" else (count, cost)


def compare(a, b):
    return (a > b) - (a < b)


def pair_comparison(a, b, objective):
    def key(candidate, recipe):
        value = candidate[recipe]
        if recipe == "decimal":
            value = Fraction(value)
        return objective_key(value, candidate["num_routes"], objective)
    old = compare(key(a, "flat"), key(b, "flat"))
    canonical = compare(key(a, "canonical_flat"), key(b, "canonical_flat"))
    exact = compare(key(a, "decimal"), key(b, "decimal"))
    return {"legacy_rank": old, "canonical_rank": canonical, "decimal_rank": exact,
            "flat_gap": a["flat"] - b["flat"],
            "canonical_gap": a["canonical_flat"] - b["canonical_flat"],
            "decimal_gap": str(Fraction(a["decimal"]) - Fraction(b["decimal"]))}


def run(data_root=DEFAULT_DATA):
    sys.path.insert(0, str(ROOT / "vendor/v012/src"))
    from mamut_routing_lib.artifacts import load_benchmark_instance, hydrate_collection_instance
    from mamut_routing_lib.checker import check_solution
    from mamut_routing_lib.models import BenchmarkSolution
    repos = json.loads((ROOT / "manifests/data-repositories.json").read_text())
    rows = json.loads((ROOT / "results/static.json").read_text())
    datasets, coverage = [], []
    previous_path = None
    for index, row in enumerate(rows):
        if row["status"] != "complete":
            coverage.append({"id": row["id"], "status": "unavailable", "error": row.get("error")})
            continue
        path = data_root / row["id"]
        repo, relative = owner(path, data_root, repos)
        source_repo = data_root / repo["path"]
        instance_relative = relative.split('.bks.')[0] + '.vrp.json'
        instance_path = path.with_name(path.name.split('.bks.')[0] + '.vrp.json')
        try:
            raw = git(source_repo, "show", f'{repo["head"]}:{instance_relative}')
            if hashlib.sha256(raw).hexdigest() != row['source']['instance_sha256'] or raw != instance_path.read_bytes():
                raise ValueError("instance bytes differ from the frozen panel")
            if instance_path != previous_path:
                model = hydrate_collection_instance(load_benchmark_instance(instance_path), instance_path)
                previous_path = instance_path
            revisions = git(source_repo, 'log', '--format=%H', repo['head'], '--', relative).decode().splitlines()
            revisions = list(dict.fromkeys([repo['head'], *revisions]))
            candidates, seen = [], set()
            for revision in revisions:
                try:
                    candidate_bytes=git(source_repo, 'show', f'{revision}:{relative}')
                    candidate = json.loads(candidate_bytes)
                    candidate_instance = git(source_repo, 'show', f'{revision}:{instance_relative}')
                except subprocess.CalledProcessError:
                    continue
                if candidate_instance != raw:
                    coverage.append({'id': row['id'], 'revision': revision, 'status': 'different-instance'})
                    continue
                routes = candidate['routes']
                route_digest = hashlib.sha256(json.dumps(routes, separators=(',', ':')).encode()).hexdigest()
                if route_digest in seen:
                    continue
                seen.add(route_digest)
                checked = check_solution(model, BenchmarkSolution(instance_name=model.instance_name, routes=routes, cost=None))
                if not checked.is_valid():
                    coverage.append({'id': row['id'], 'revision': revision, 'status': 'invalid-candidate', 'message': checked.error_message})
                    continue
                vectors = [[model.arc_costs[a][b] for a, b in zip([model.depot, *route], [*route, model.depot])] for route in routes]
                flat = [v for vector in vectors for v in vector]
                canonical = sorted(range(len(routes)), key=lambda k: routes[k][0])
                values = score(flat)
                if checked.routing_cost != values['flat']:
                    raise AssertionError('tagged static checker differs from the study')
                values.update(num_routes=len(routes), revision=revision, route_sha256=route_digest,
                              canonical_flat=left(v for k in canonical for v in vectors[k]),
                              vectors=vectors, canonical_indices=canonical, routes=routes,
                              declared_cost=candidate.get('cost'), source_bks_sha256=hashlib.sha256(candidate_bytes).hexdigest())
                candidates.append(values)
            datasets.append({'id':row['id'], 'family':row['family'], 'size':row['size'], 'objective':row['objective'],
                             'instance_sha256':row['source']['instance_sha256'], 'candidates':candidates})
        except (FileNotFoundError, ValueError) as error:
            coverage.append({'id':row['id'], 'status':'unavailable', 'error':str(error)})
        if index % 100 == 0:
            print(f'History {index}/{len(rows)}', flush=True)
    with gzip.open(ROOT/'data/static-history.json.gz','wt') as output:
        json.dump(datasets,output,separators=(',',':'),allow_nan=False)
    return summarize(datasets, coverage)


def summarize(datasets, coverage=()):
    for dataset in datasets:
        for candidate in dataset['candidates']:
            recomputed=score([v for route in candidate['vectors'] for v in route])
            canonical=left(v for k in candidate['canonical_indices'] for v in candidate['vectors'][k])
            if any(candidate[k]!=recomputed[k] for k in recomputed) or canonical!=candidate['canonical_flat']:
                raise AssertionError('archived candidate score differs from its arc operands')
    comparisons = []
    for dataset in datasets:
        for a, b in itertools.combinations(dataset['candidates'], 2):
            comparisons.append({'id':dataset['id'], 'a':a['route_sha256'], 'b':b['route_sha256'],
                                **pair_comparison(a, b, dataset['objective'])})
    mismatches = [x for x in comparisons if x['legacy_rank'] != x['decimal_rank']]
    strict = [x for x in mismatches if x['legacy_rank'] * x['decimal_rank'] == -1]
    summary = {'instances':len(datasets), 'candidates':sum(len(d['candidates']) for d in datasets),
               'instances_with_alternatives':sum(len(d['candidates'])>1 for d in datasets),
               'pairs':len(comparisons), 'policy_disagreements':len(mismatches), 'strict_reversals':len(strict),
               'decimal_ties_distinguished_by_legacy':sum(x['decimal_rank']==0 and x['legacy_rank']!=0 for x in comparisons),
               'legacy_ties_distinguished_by_decimal':sum(x['legacy_rank']==0 and x['decimal_rank']!=0 for x in comparisons),
               'max_disagreement_gap':max((abs(x['flat_gap']) for x in mismatches),default=0),
               'rank_counts':dict(Counter(f"{x['legacy_rank']},{x['decimal_rank']}" for x in comparisons)),
               'coverage':coverage, 'comparisons':comparisons}
    write_json(ROOT/'results/static-history.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('coverage','comparisons')}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,default=DEFAULT_DATA)
    parser.add_argument('--from-bundle',action='store_true')
    args=parser.parse_args()
    if args.from_bundle:
        data=json.loads(gzip.decompress((ROOT/'data/static-history.json.gz').read_bytes()))
        previous=json.loads((ROOT/'results/static-history.json').read_text())
        summarize(data,previous['coverage'])
    else:
        run(args.data_root)
