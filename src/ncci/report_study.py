"""Validate controlled results and generate the concise report comparisons."""
import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import json
from pathlib import Path
import statistics

from .inputs import ROOT, write_json


def median(values):
    return statistics.median(values)


def main(report):
    history=json.loads((ROOT/'results/static-history.json').read_text())
    static=json.loads((ROOT/'results/controlled-static.json').read_text())
    td=json.loads((ROOT/'results/controlled-td.json').read_text())
    expected={}
    for name in ['original-inputs.json','rational-panel.json']:
        for entry in json.loads((ROOT/'results'/name).read_text()):
            record=json.loads((ROOT/entry['result']).read_text())
            expected[record['id']]=record
    for sample in td['full_checkers']:
        target=expected[sample['id']]['current']['totals'][sample['version']]
        if sample['status']!='valid' or sample['cost']!=target['cost']:
            raise AssertionError('complete checker timing output differs from frozen evidence')
    for sample in td['rational']:
        for interpretation in sample['samples']:
            target=expected[sample['id']]['current']['routes'][sample['route_index']]['exact'][interpretation]
            if sample[interpretation+'_duration']!=target['duration']:
                raise AssertionError('rational timing output differs from frozen reference')
    ratio=median(r['median_seconds']['decimal-ranking']/r['median_seconds']['flat-ranking'] for r in static['records'])
    canonical=sum(r['canonical_rank']!=r['decimal_rank'] for r in history['comparisons'])
    maintext=(f"The additional accessible static history provides {history['candidates']:,} distinct ordered candidates on {history['instances']:,} instances, with {history['pairs']} candidate pairs. "
              f"Both policies agree on all {history['pairs']-history['policy_disagreements']} strict decimal improvements. The remaining {history['policy_disagreements']} pairs are decimal ties distinguished by historical submitted-order scoring, with maximum gap ${history['max_disagreement_gap']:.3g}$. "
              f"Canonical binary64 scoring distinguishes {canonical} of these pairs. There are no strict ranking reversals in this accessible history. We exclude the unavailable third Mamut2026 campaign rather than infer its outcome.\n\n")
    maintext+="We measure preloaded route folds and complete released checkers separately, using 7 timing rounds with alternating release order on one Linux x86-64 host under CPython 3.13.13. Setup is outside the checker timing and is recorded separately. Table~\\ref{tab:controlled-td} reports panel medians and paired time ratios. The newer release is faster in these measurements, so efficiency does not support calling the historical TD implementation faster. Its restoration is instead motivated by contract continuity and the simpler shared composition protocol.\n\n"
    maintext+=r'''\begin{table}[htbp]
\centering
\caption{Controlled Python measurements. Times are medians in milliseconds, first within each record's repeated measurements and then across records. Ratios are medians of paired 0.12/0.11 times, rather than ratios of the displayed panel medians. Setup, file loading and process startup are excluded.}\label{tab:controlled-td}
\begin{tabular}{lrrrr}
\toprule
Panel and evaluation & Records & 0.11 (ms) & 0.12 (ms) & Paired ratio\\
\midrule
'''
    summary={}
    for panel in ['original','broader']:
        group=[r for r in td['routes'] if r['panel']==panel]
        medians={v:median(r['median_seconds'][v] for r in group) for v in ['v011','v012']}
        paired=median(r['median_seconds']['v012']/r['median_seconds']['v011'] for r in group)
        maintext+=f"{panel.capitalize()} route folds & {len(group)} & {1000*medians['v011']:.3f} & {1000*medians['v012']:.3f} & {paired:.3f} "+r'\\'+"\n"
        complete=defaultdict(lambda:defaultdict(list))
        for row in td['full_checkers']:
            if row['panel']==panel:complete[row['id']][row['version']].append(row['seconds'])
        values=[{v:median(times) for v,times in item.items()} for item in complete.values()]
        fullratio=median(r['v012']/r['v011'] for r in values)
        maintext+=f"{panel.capitalize()} full checkers & {len(values)} & {1000*median(r['v011'] for r in values):.3f} & {1000*median(r['v012'] for r in values):.3f} & {fullratio:.3f} "+r'\\'+"\n"
        summary[panel]={'route_ratio':paired,'full_checker_ratio':fullratio}
    maintext+=r'''\bottomrule
\end{tabular}
\end{table}

'''
    maintext+=(f"The static timing panel contains {len(static['records'])} records selected at fixed size positions within each family. Forming and comparing two exact-decimal objectives takes a median {ratio:.1f} times the corresponding sequential binary64 reduction and comparison. "
               "This includes the released decimal-conversion primitive and rational additions, not the full store's validation or filesystem work. It is not a solver speed-up estimate. Appendix~\\ref{app:controlled} gives the protocol, dispersion and per-record reduction timings. Accurate summation and integer scaling are measured separately, with their distinct input and output semantics.\n\n")
    route_lookup={(r['id'],r['route_index']):r for r in td['routes']}
    complete=[r for r in td['rational'] if r['status']=='complete']
    rationalratios=[median(r['samples']['binary'])/route_lookup[(r['id'],r['route_index'])]['median_seconds']['v011'] for r in complete]
    rationalratio=median(rationalratios) if rationalratios else None
    maintext+=(f"The bounded rational timing panel selects {len(td['rational'])} routes of at most 25 customers, 12 from each TD panel, by a fixed hash rule. "
               f"Both input interpretations complete on {len(complete)} selected routes. On these matched routes, the median binary-rational-reference/historical-fold time ratio is {rationalratio:.1f}. "
               "This comparison measures our independent partitioning reference, including stage construction, against the preloaded composition kernel. The difference includes algorithmic structure and arithmetic costs. It cannot isolate a universal rational-arithmetic penalty or predict an optimized exact solver.\n")
    (report/'study-results.tex').write_text(maintext)
    appendix=r'''\section{Historical static candidates and controlled measurements}\label{app:controlled}

This appendix records the additional comparison protocol and detailed measurements. Candidate history is read at the original frozen repository pins. A candidate is retained only if the instance bytes equal those of the corresponding frozen record and its routes pass the released structural and temporal checker. Repeated serialized route lists are counted once per instance. Historical declared values are not imposed on the new diagnostic score. The comparisons preserve each objective's fleet tier. Consumed arc operands, serialized routes, original declared costs, BKS byte hashes and source revisions are archived in \path{data/static-history.json.gz}.

The timing experiment runs serially, with no parallel experiment workers. It warms each operation, calibrates a repeated batch, disables garbage collection inside that batch and retains 7 round measurements. Release order alternates for TD and method order uses a fixed per-round shuffle for static reductions. A preloaded fold is first checked against its ordinary harness output. Complete checkers run in separate interpreters with model/ATF construction outside the measured call, and their feasibility, route durations, departures and solution totals are compared with frozen results. The benchmark records the interpreter, platform, clock and CPU affinity. These repeated measurements are descriptive on one host, not confidence intervals for a machine population.

Static selection takes the first, quarter, middle, three-quarter and last size-sorted record in each family, with path order breaking size ties. Reduction kernels use consumed arc vectors. Rational kernel inputs are converted outside the timed sum, while conversion-inclusive methods use the released exact decimal primitive or Python's binary Fraction conversion. The ranking comparison forms both objectives and preserves the fleet tier. Integer methods are eligible only when every scaled operand and the complete nonnegative total are integral and fit signed 64-bit range. Their timing uses Python arbitrary-size integers with conversion excluded, not a native signed-64-bit implementation. The 3 declared scales are 1, 1000 and 1000000.

Rational TD timing selects 12 routes per panel with at most 25 customers, using the minimum SHA-256 ordering of instance identifier, route index and the fixed seed string. Each input interpretation is evaluated 3 times with a 10-second per-call limit. Resource-limited cases remain explicit. Completed optima are checked against the archived exact reference before accepting the timing comparison. Stage construction is included here, and the normal garbage-collection policy is retained for these direct calls. Unlike the calibrated reduction/checker batches, this bounded experiment includes each of its 3 calls without an additional warm-up. It is separate from the full exact-fidelity panel.

\begingroup
\small
\setlength{\tabcolsep}{4pt}
\begin{longtable}{llrrrrrr}
\caption{Static timing panel. Medians in microseconds. Integer column uses scale 1000 where eligible. Decimal sum excludes operand conversion. Ranking ratio includes conversion and reduction of both candidates. A dash denotes ineligibility.}\\
\toprule
Family & Record & Arcs & Flat & \texttt{fsum} & Integer & Decimal & Rank ratio\\
\midrule
\endfirsthead
\toprule
Family & Record & Arcs & Flat & \texttt{fsum} & Integer & Decimal & Rank ratio\\
\midrule
\endhead
\bottomrule
\endfoot
'''
    for r in static['records']:
        identifier=r['id'].split('/')
        name=(identifier[4]+'/'+str(r['size'])) if r['family'] in ('Mamut2026','Poryos2026') else r['id'].split('/')[-1].split('.bks.')[0]
        if r['family']=='Ortec2022':name=name.removeprefix('ORTEC-VRPTW-ASYM-').split('-d1-')[0]+'/'+str(r['size'])
        name=name.replace('_',r'\_')
        times=r['median_seconds'];integer=f"{1e6*times['integer-1000']:.2f}" if 'integer-1000' in times else '--'
        appendix+=f"{r['family']} & {name} & {r['arcs']} & {1e6*times['flat']:.2f} & {1e6*times['fsum']:.2f} & {integer} & {1e6*times['decimal-rational']:.2f} & {times['decimal-ranking']/times['flat-ranking']:.1f} "+r'\\'+"\n"
    appendix+=r'\end{longtable}'+'\n'+r'\endgroup'+'\n\n'
    appendix+="The full identifiers, every method's raw batches and median timings are available in \\path{results/controlled-static.json}. The timing column labels describe different finite computations, so a faster method is not automatically a conforming replacement. The native \\texttt{fsum} routine and the Python loops also differ in implementation language.\n\n"
    for panel in ['original','broader']:
        ratios=[r['median_seconds']['v012']/r['median_seconds']['v011'] for r in td['routes'] if r['panel']==panel]
        q=statistics.quantiles(ratios,n=4)
        appendix+=f"For the {panel} TD route panel, the paired 0.12/0.11 ratio has quartiles {q[0]:.3f}, {q[1]:.3f} and {q[2]:.3f}. These describe route-to-route variation. Raw repeated samples and complete-checker setup fields remain in \\path{{results/controlled-td.json}}.\n\n"
    appendix+=r'''\begin{longtable}{llrrr}
\caption{All 31 historical pairs on which submitted-order scoring distinguishes a decimal tie. Gaps are current minus preceding candidate. Canonical gaps isolate the retained storage-order convention.}\\
\toprule
City & Metric & Customers & Submitted gap & Canonical gap\\
\midrule
\endfirsthead
\toprule
City & Metric & Customers & Submitted gap & Canonical gap\\
\midrule
\endhead
\bottomrule
\endfoot
'''
    for r in history['comparisons']:
        if r['legacy_rank']==r['decimal_rank']:continue
        pieces=r['id'].split('/')
        appendix+=f"{pieces[4].replace('_',chr(92)+'_')} & {pieces[3]} & {pieces[5].split('=')[-1]} & {r['flat_gap']:.3g} & {r['canonical_gap']:.3g} "+r'\\'+"\n"
    appendix+=r'\end{longtable}'+'\n'
    (report/'study-appendix.tex').write_text(appendix)
    write_json(ROOT/'results/controlled-summary.json',{'td':summary,'static_ranking_ratio':ratio,'rational_ratio':rationalratio,
               'rational_complete':len(complete),'rational_selected':len(td['rational']),'canonical_policy_disagreements':canonical,
               'full_checker_numerical_outputs_verified':len(td['full_checkers'])})
    print(json.dumps({'static_ranking_ratio':ratio,'td':summary,'rational_ratio':rationalratio}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',type=Path,default=ROOT/'report')
    main(parser.parse_args().report_dir)
