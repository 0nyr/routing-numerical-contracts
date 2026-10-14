"""Generate auditable numerical summaries and standalone report tables/figures."""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import statistics

from .inputs import ROOT, write_json
from .contracts import ulps


def load(name):
    return json.loads((ROOT / 'results' / name).read_text())


def evaluated(name):
    rows = []
    for entry in load(name):
        if entry['status'] != 'complete':
            continue
        path = ROOT / entry['result']
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f'result hash differs: {entry["id"]}')
        rows.append(json.loads(path.read_text()))
    return rows


def summarize_exact(rows):
    counters = defaultdict(Counter)
    errors, times, cuts, bits = defaultdict(list), defaultdict(list), [], []
    models = Counter()
    model_errors = []
    for solution in rows:
        for row in solution['current']['routes']:
            binary = row.get('exact', {}).get('binary', {})
            decimal = row.get('exact', {}).get('decimal', {})
            if 'feasible' in binary and 'feasible' in decimal:
                models['routes'] += 1
                models['feasibility_disagreements'] += binary['feasible'] != decimal['feasible']
                if binary['feasible'] and decimal['feasible']:
                    qb, qd = Q(binary['duration']), Q(decimal['duration'])
                    models['exact_value_differences'] += qb != qd
                    models['rounded_value_differences'] += float(qb) != float(qd)
                    model_errors.append(float(abs(qb - qd)))
            for version, a in row['folds'].items():
                c = counters[version]
                c['routes'] += 1
                c['temporal_feasible'] += a['feasible']
                if a['feasible']:
                    c['generic_forward_rejection'] += not a['generic_forward_feasible']
                    c['generic_forward_mismatch_or_rejection'] += not a['generic_forward_reproduces_cost']
                    c['variant_forward_rejection'] += not a['forward_feasible']
                    c['variant_forward_mismatch_or_rejection'] += not a['forward_reproduces_cost']
                    times[version].append(a['seconds'])
                reference = row.get('exact', {}).get('binary', {})
                c['reference_resource_limit'] += reference.get('status') == 'resource-limit'
                if 'feasible' not in reference:
                    continue
                c['reference_routes'] += 1
                c['reference_feasibility_disagreement'] += a['feasible'] != reference['feasible']
                if a['feasible'] and reference['feasible']:
                    value = Q(reference['duration'])
                    c['rational_value_equal'] += Q(a['duration']) == value
                    c['rounded_rational_value_equal'] += a['duration'] == float(value)
                    c['rational_forward_rejection'] += not a['binary_feasible_at_departure']
                    errors[version].append(a['binary_abs_error'])
                if version == 'v011':
                    times['rational_binary'].append(reference['seconds'])
                    cuts.append(reference['cuts']); bits.append(reference['max_bits'])
    return {'variants': {v: {**dict(c), 'maximum_absolute_error': max(errors[v], default=None),
                             'median_fold_seconds': statistics.median(times[v]) if times[v] else None}
                         for v, c in counters.items()},
            'median_rational_seconds': statistics.median(times['rational_binary']) if times['rational_binary'] else None,
            'maximum_rational_cuts': max(cuts, default=None), 'maximum_rational_cut_bits': max(bits, default=None),
            'input_models': {**dict(models), 'maximum_absolute_difference': max(model_errors, default=None)}}


def csv_write(path, rows):
    if not rows: return
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); writer.writeheader(); writer.writerows(rows)


def tex(s):
    return str(s).replace('_', r'\_').replace('&', r'\&').replace('%', r'\%')


def main(report_dir):
    report_dir.mkdir(parents=True, exist_ok=True)
    tables, figures = report_dir / 'tables', report_dir / 'figures'
    tables.mkdir(exist_ok=True); figures.mkdir(exist_ok=True)
    original = evaluated('original-inputs.json')
    original_summary = summarize_exact(original)
    original_summary.update(solutions=len(original),
        changed_solution_totals=sum(s['current']['totals']['v011']['cost'] != s['current']['totals']['v012']['cost'] for s in original),
        matches_published={v: sum(s['current']['totals'][v]['cost'] == s['published_cost'] for s in original) for v in ('v011', 'v012')},
        published_generic_forward_rejections=sum(not t['forward']['feasible'] for s in original for t in s['published_traces']),
        published_exact_binary_forward_rejections=sum(t['exact_binary_forward']['arrival'] is None for s in original for t in s['published_traces']),
        structural_failures=sum(bool(s['current']['structural_errors']) for s in original))
    static = load('static.json')
    good = [s for s in static if s['status'] == 'complete']
    static_summary = {'enumerated': len(static), 'complete': len(good), 'unavailable': [s for s in static if s['status'] != 'complete'],
        'family_counts': dict(Counter(s['family'] for s in good)),
        'nonvalid': [s['id'] for s in good if s['current']['tagged_status'] != 'valid'],
        'declared_mismatches': sum(s['current']['costs']['submitted_flat'] != s['declared'] for s in good),
        'ordering_sensitive': sum(s['current']['order_distinct_totals'] > 1 for s in good),
        'grouped_helper_differs': sum(s['current']['costs']['route_grouped_sum'] != s['current']['costs']['submitted_flat'] for s in good),
        'binary_rational_temporal_flips': sum(s['current']['temporal']['rational_binary'] != s['current']['temporal']['binary64'] for s in good),
        'decimal_rational_temporal_flips': sum(s['current']['temporal']['rational_decimal'] != s['current']['temporal']['binary64'] for s in good),
        'scale1000_exact_and_fits': sum(s['current']['scale1000_fits_int64'] for s in good),
        'ranking_changes': [dict(id=s['id'], binary_canonical_rank=s['binary_canonical_rank'], decimal_rank=s['decimal_rank']) for s in good if 'baseline' in s]}
    static_summary['rounded_exact_binary_matches'] = {
        key: sum(s['current']['costs'][key] == float(Q(s['current']['binary_exact'])) for s in good)
        for key in ('submitted_flat', 'canonical_flat', 'route_grouped_sum', 'fsum')}
    static_summary['binary_decimal_rounded_differences'] = sum(
        float(Q(s['current']['binary_exact'])) != float(Q(s['current']['decimal_exact'])) for s in good)
    summary = {'original': original_summary, 'static': static_summary}
    if (ROOT / 'results/rational-panel.json').exists():
        summary['panel'] = summarize_exact(evaluated('rational-panel.json'))
    if (ROOT / 'results/td-inputs.json').exists():
        corpus = evaluated('td-inputs.json')
        compact = []
        for s in corpus:
            old, new = [s['current']['totals'][v] for v in ('v011', 'v012')]
            compact.append({'id': s['id'], 'family': s['family'], 'size': s['size'], 'routes': s['current']['num_routes'],
                            'v011_feasible': old['feasible'], 'v012_feasible': new['feasible'],
                            'v011_cost': old['cost'], 'v012_cost': new['cost'],
                            'cost_ulps': ulps(old['cost'], new['cost']),
                            'v012_matches_declared': new['matches_declared'],
                            'structural_errors': '|'.join(s['current']['structural_errors']), 'baseline_evaluated': 'baseline' in s})
        csv_write(ROOT / 'results/td-solutions.csv', compact)
        inputs = json.loads((ROOT / 'manifests/td-inputs.json').read_text())
        summary['td'] = {'enumerated': len(inputs), 'complete': len(corpus), 'unavailable': [s for s in inputs if s['status'] != 'ready'],
            'errors': [s for s in load('td-inputs.json') if s['status'] != 'complete'],
            'changed_totals': sum(s['v011_cost'] != s['v012_cost'] for s in compact),
            'temporal_feasibility_flips': sum(s['v011_feasible'] != s['v012_feasible'] for s in compact),
            'structural_failures': sum(bool(s['structural_errors']) for s in compact),
            'declared_mismatches': sum(not s['v012_matches_declared'] for s in compact),
            'family_counts': dict(Counter(s['family'] for s in corpus)),
            'maximum_absolute_total_difference': max((abs(s['v011_cost'] - s['v012_cost']) for s in compact if s['v011_cost'] is not None and s['v012_cost'] is not None), default=None)}
        ranking = []
        for s in corpus:
            if 'baseline' not in s:
                continue
            row = {'id': s['id']}
            for v in ('v011', 'v012'):
                a, b = s['current']['totals'][v], s['baseline']['totals'][v]
                row[v + '_current'] = a['cost']
                row[v + '_baseline'] = b['cost']
                row[v + '_current_feasible'] = a['feasible']
                row[v + '_baseline_feasible'] = b['feasible']
                row[v + '_rank'] = (a['cost'] > b['cost']) - (a['cost'] < b['cost']) if a['feasible'] and b['feasible'] else None
            ranking.append(row)
        csv_write(ROOT / 'results/td-replacements.csv', ranking)
        summary['td']['replacement_ranks'] = {v: dict(Counter(r[v + '_rank'] for r in ranking)) for v in ('v011', 'v012')}
        summary['td']['replacements'] = len(ranking)
        family = []
        for name in sorted(summary['td']['family_counts']):
            subgroup = [s for s in compact if s['family'] == name]
            family.append(f"{tex(name)} & {len(subgroup)} & {sum(s['v011_cost'] != s['v012_cost'] for s in subgroup)} & {sum(s['v011_feasible'] != s['v012_feasible'] for s in subgroup)} \\")
        (tables / 'td-family.tex').write_text('\n'.join(line.rstrip(chr(92))+chr(92)*2 for line in family)+'\n')
    write_json(ROOT / 'results/summary.json', summary)
    macro = {'OriginalSolutions':len(original), 'OriginalRoutes':original_summary['variants']['v011']['routes'],
             'OriginalChanged':original_summary['changed_solution_totals'], 'StaticEnumerated':len(static),
             'StaticComplete':len(good), 'StaticMissing':len(static)-len(good),
             'StaticOrdering':static_summary['ordering_sensitive'], 'StaticHelper':static_summary['grouped_helper_differs'],
             'StaticScaled':static_summary['scale1000_exact_and_fits']}
    if 'td' in summary:
        macro.update(TDEnumerated=summary['td']['enumerated'], TDComplete=summary['td']['complete'],
                     TDMissing=len(summary['td']['unavailable']), TDChanged=summary['td']['changed_totals'], TDFlips=summary['td']['temporal_feasibility_flips'])
    (tables / 'numbers.tex').write_text('\n'.join(chr(92)+'newcommand{'+chr(92)+k+'}{'+str(v)+'}' for k,v in macro.items())+'\n')
    family=[]
    for name in sorted(static_summary['family_counts']):
        subgroup=[s for s in good if s['family']==name]
        family.append(f"{tex(name)} & {len(subgroup)} & {sum(s['current']['order_distinct_totals'] > 1 for s in subgroup)} & {sum(s['current']['costs']['route_grouped_sum'] != s['current']['costs']['submitted_flat'] for s in subgroup)} & {sum(s['current']['scale1000_fits_int64'] for s in subgroup)} \\")
    (tables / 'static-family.tex').write_text('\n'.join(line.rstrip(chr(92))+chr(92)*2 for line in family)+'\n')
    variant=[]
    for v,a in original_summary['variants'].items():
        variant.append(f"{tex(v)} & {a['rounded_rational_value_equal']} & {a['generic_forward_rejection']} & {a['generic_forward_mismatch_or_rejection']} & {a['maximum_absolute_error']:.3g} \\")
    (tables / 'original-variants.tex').write_text('\n'.join(line.rstrip(chr(92))+chr(92)*2 for line in variant)+'\n')
    if 'panel' in summary:
        rows = []
        for v, a in summary['panel']['variants'].items():
            rows.append(f"{tex(v)} & {a['rounded_rational_value_equal']} & {a['generic_forward_rejection']} & {a['maximum_absolute_error']:.3g} & {a['median_fold_seconds']:.3g} " + chr(92)*2)
        (tables / 'panel-variants.tex').write_text('\n'.join(rows) + '\n')
    synthetic = load('synthetic.json')
    summary['synthetic'] = {'cases': len(synthetic), 'variants': {
        v: {'feasibility_disagreements': sum(not s['results'][v]['feasibility_agrees'] for s in synthetic),
            'exact_cost_disagreements': sum(s['results'][v]['feasibility_agrees'] and not s['results'][v].get('exact_cost_agrees', True) for s in synthetic)}
        for v in synthetic[0]['results']}}
    write_json(ROOT / 'results/summary.json', summary)
    solution_rows=[]; texrows=[]
    for s in sorted(original,key=lambda r:r['id']):
        old,new=[s['current']['totals'][v]['cost'] for v in ('v011','v012')]
        row={'id':s['id'],'routes':s['current']['num_routes'],'published':s['published_cost'],'v011':old,'v012':new,'contract_ulps':ulps(old,new)}
        solution_rows.append(row)
        texrows.append(f"{tex(row['id'])} & {row['routes']} & {row['published']!r} & {old!r} & {new!r} & {row['contract_ulps']} \\")
    csv_write(ROOT / 'results/original-solutions.csv',solution_rows)
    (tables / 'original-solutions.tex').write_text('\n'.join(line.rstrip(chr(92))+chr(92)*2 for line in texrows)+'\n')
    route_rows=[]
    for s in original:
        for k,row in enumerate(s['current']['routes']):
            a,b=row['folds']['v011'],row['folds']['v012'];q=row['exact']['binary']
            route_rows.append({'id':s['id'],'route_index':k,'customers':json.dumps(row['route']),'v011':a['duration'],'v012':b['duration'],
                'exact_binary_duration':q['duration'],'exact_binary_departure':q['departure'],'rational_cut_bits':q['max_bits'],
                'v011_error':a['binary_error'],'v012_error':b['binary_error'],'v011_generic_forward_feasible':a['generic_forward_feasible'],
                'v012_generic_forward_feasible':b['generic_forward_feasible']})
    csv_write(ROOT / 'results/original-routes.csv',route_rows)
    csv_write(ROOT / 'results/static-solutions.csv', [{'id':s['id'],'family':s['family'],'size':s['size'],**s['current']['costs'],
              'declared':s['declared'],'binary_exact':s['current']['binary_exact'],'decimal_exact':s['current']['decimal_exact'],
              'order_distinct':s['current']['order_distinct_totals'],'scale1000_exact':s['current']['scale1000_exact']} for s in good])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'savefig.bbox':'tight'})
    fig, axes=plt.subplots(1,2,figsize=(10,3.5))
    all_errors = [float(Q(r['folds'][v]['duration'])-Q(r['exact']['binary']['duration'])) / math.ulp(float(Q(r['exact']['binary']['duration'])))
                  for s in original for r in s['current']['routes'] for v in ('v011','v012')]
    low, high = math.floor(min(all_errors) * 2) / 2 - .25, math.ceil(max(all_errors) * 2) / 2 + .25
    bins = [low + .5*k for k in range(round((high-low)/.5)+1)]
    for v,label in [('v011','0.11'),('v012','0.12')]:
        values=[]
        for s in original:
            for row in s['current']['routes']:
                q=Q(row['exact']['binary']['duration']);a=row['folds'][v]
                values.append(float(Q(a['duration'])-q)/math.ulp(float(q)))
        axes[0].hist(values,bins=bins,alpha=.55,label=label)
    axes[0].set(xlabel='Route-value error / ulp(exact optimum rounded)',ylabel='Original routes');axes[0].legend()
    lengths=[len(r['route']) for s in original for r in s['current']['routes']]
    times=[r['exact']['binary']['seconds'] for s in original for r in s['current']['routes']]
    axes[1].scatter(lengths,times,s=9,alpha=.45)
    axes[1].set(xlabel='Customers in route',ylabel='Independent rational evaluation (s)',yscale='log')
    fig.tight_layout();fig.savefig(figures/'original-error-runtime.pdf');plt.close(fig)
    fig, ax=plt.subplots(figsize=(7,3.3))
    names=sorted(static_summary['family_counts']);x=range(len(names))
    ax.bar(x,[sum(s['current']['order_distinct_totals']>1 for s in good if s['family']==n) for n in names],label='Order-sensitive sampled permutations')
    ax.bar(x,[sum(s['current']['costs']['route_grouped_sum']!=s['current']['costs']['submitted_flat'] for s in good if s['family']==n) for n in names],alpha=.65,label='Grouped helper differs from flat checker')
    ax.set_xticks(list(x),names,rotation=20,ha='right');ax.set_ylabel('Static BKS records');ax.legend();fig.tight_layout();fig.savefig(figures/'static-ordering.pdf');plt.close(fig)
    print(json.dumps({k:{m:v for m,v in val.items() if m in ('solutions','changed_solution_totals','enumerated','complete','changed_totals','temporal_feasibility_flips')} for k,val in summary.items()}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report-dir',type=Path,default=ROOT/'report')
    main(p.parse_args().report_dir)
