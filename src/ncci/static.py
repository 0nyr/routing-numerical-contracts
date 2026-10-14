"""Static checker arithmetic, exact ranking, and temporal feasibility audit."""
import argparse
from collections import Counter
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

from .inputs import ROOT, DEFAULT_DATA, snapshot_repositories, pinned_bytes, write_json, sha


def left(values):
    total = 0
    for value in values:
        total += value
    return total


def structural(instance, routes):
    visited = [v for r in routes for v in r]
    n = instance['num_customers']
    errors = []
    if any(not r for r in routes):
        errors.append('empty-route')
    if sorted(visited) != list(range(1, n + 1)):
        errors.append('customer-partition')
    if any(sum(instance['demands'][v] for v in r) > instance['vehicle_capacity'] for r in routes):
        errors.append('capacity')
    if instance.get('num_vehicles') is not None and len(routes) > instance['num_vehicles']:
        errors.append('fleet')
    return errors


def temporal(instance, routes, convert):
    windows = instance.get('time_windows')
    if not windows:
        return True
    depot = instance.get('depot', 0)
    for route in routes:
        t = convert(0)
        previous = depot
        for vertex in [*route, depot]:
            arrival = t + convert(instance['arc_costs'][previous][vertex])
            e, l = map(convert, windows[vertex])
            arrival = max(arrival, e)
            if arrival > l:
                return False
            t = arrival + convert(instance['service_times'][vertex])
            previous = vertex
    return True


def evaluate(instance, routes):
    depot = instance.get('depot', 0)
    matrix = instance['arc_costs']
    def costs(order):
        return [[matrix[a][b] for a, b in zip([depot, *r], [*r, depot])] for r in order]
    canonical = sorted(routes, key=lambda r: r[0])
    arcs = costs(routes)
    flattened = [v for r in arcs for v in r]
    exact_binary = sum(map(Q, flattened), Q(0))
    exact_decimal = sum((Q(str(v)) for v in flattened), Q(0))
    variants = {'submitted_flat': left(flattened),
                'canonical_flat': left(v for r in costs(canonical) for v in r),
                'route_grouped_sum': sum(left(r) for r in arcs),
                'fsum': math.fsum(flattened)}
    rng = random.Random(20260930)
    shuffled = list(routes)
    rng.shuffle(shuffled)
    order_totals = [left(v for r in costs(order) for v in r) for order in (routes, canonical, list(reversed(routes)), shuffled)]
    scaled = exact_decimal * 1000
    scaled_arcs = [Q(str(v)) * 1000 for v in flattened]
    integral_arcs = all(v.denominator == 1 for v in scaled_arcs)
    bounded_arcs = all(0 <= v <= 2**63 - 1 for v in scaled_arcs)
    return {'costs': variants, 'binary_exact': str(exact_binary), 'decimal_exact': str(exact_decimal),
            'binary_errors': {k: str(Q(v) - exact_binary) for k, v in variants.items()},
            'decimal_errors': {k: str(Q(v) - exact_decimal) for k, v in variants.items()},
            'order_distinct_totals': len(set(order_totals)), 'order_range': max(order_totals) - min(order_totals),
            'scale1000_exact': integral_arcs,
            'scale1000_fits_int64': integral_arcs and bounded_arcs and 0 <= scaled <= 2**63 - 1,
            'structural_errors': structural(instance, routes),
            'temporal': {name: temporal(instance, routes, conv) for name, conv in
                         [('binary64', lambda x: x), ('rational_binary', Q), ('rational_decimal', lambda x: Q(str(x)))]}}


def run(data_root=DEFAULT_DATA):
    sys.path.insert(0, str(ROOT / 'vendor/v012/src'))
    from mamut_routing_lib.artifacts import load_benchmark_instance, hydrate_collection_instance
    from mamut_routing_lib.models import BenchmarkSolution
    from mamut_routing_lib.enums import ObjectiveFunction
    from mamut_routing_lib.checker import check_solution, compute_exact_solution_cost
    repos = snapshot_repositories(data_root)
    rows = []
    previous_path = None
    instance = None
    for path in sorted((data_root / 'benchmarks').rglob('*.bks.*.json')):
        relative = path.relative_to(data_root).as_posix()
        if '/TDVRP/' in relative or '/TDVRPTW/' in relative:
            continue
        start = time.perf_counter()
        row = {'id': relative}
        try:
            current_raw = pinned_bytes(path, data_root, repos)
            bks = json.loads(current_raw)
            instance_path = path.with_name(path.name.split('.bks.')[0] + '.vrp.json')
            instance_raw = pinned_bytes(instance_path, data_root, repos)
            if instance_path.read_bytes() != instance_raw:
                raise ValueError('live instance differs from frozen Git input')
            if previous_path != instance_path:
                model = hydrate_collection_instance(load_benchmark_instance(instance_path), instance_path)
                instance = model.model_dump(mode='json')
                previous_path = instance_path
            current = evaluate(instance, bks['routes'])
            tagged = check_solution(model, BenchmarkSolution(instance_name=model.instance_name, routes=bks['routes'], cost=None))
            current['tagged_status'] = tagged.status.value
            current['tagged_cost'] = tagged.routing_cost
            current['tagged_exact_matches'] = str(compute_exact_solution_cost(model, bks['routes'])) == current['decimal_exact']
            if tagged.routing_cost is not None and tagged.routing_cost != current['costs']['submitted_flat']:
                raise AssertionError('independent static arithmetic differs from tagged checker')
            row.update(status='complete', size=instance['num_customers'], family=instance['benchmark_name'],
                       current=current, declared=bks['cost'], objective=bks['objective_function'],
                       source={'instance_sha256': sha(instance_raw), 'bks_sha256': sha(current_raw)})
            try:
                old_raw = pinned_bytes(path, data_root, repos, True)
                old = json.loads(old_raw)
                row['source']['baseline_bks_sha256'] = sha(old_raw)
                row['routes_changed'] = old['routes'] != bks['routes']
                if row['routes_changed']:
                    row['baseline'] = evaluate(instance, old['routes'])
                    row['baseline_declared'] = old['cost']
                    row['binary_canonical_rank'] = (current['costs']['canonical_flat'] > row['baseline']['costs']['canonical_flat']) - (current['costs']['canonical_flat'] < row['baseline']['costs']['canonical_flat'])
                    row['decimal_rank'] = (Q(current['decimal_exact']) > Q(row['baseline']['decimal_exact'])) - (Q(current['decimal_exact']) < Q(row['baseline']['decimal_exact']))
            except subprocess.CalledProcessError:
                row['baseline_missing'] = True
        except Exception as error:
            row.update(status='error', error=f'{type(error).__name__}: {error}')
        row['seconds'] = time.perf_counter() - start
        rows.append(row)
        if len(rows) % 50 == 0:
            print(f'Static {len(rows)}: {relative}', flush=True)
            write_json(ROOT / 'results/static.json', rows)
    write_json(ROOT / 'results/static.json', rows)
    print(json.dumps(Counter(r['status'] for r in rows)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', type=Path, default=DEFAULT_DATA)
    run(parser.parse_args().data_root)
