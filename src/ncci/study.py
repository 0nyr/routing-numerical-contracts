"""Controlled arithmetic comparisons on declared finite input models."""
import argparse
from collections import defaultdict
from fractions import Fraction
import gc
import gzip
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import time

from .contracts import fold, OLD, NEW
from .exact import evaluate_route
from .inputs import ROOT, write_json
from .static import left


def timed(call, target=.01):
    expected = call()
    start=time.perf_counter();call();estimate=time.perf_counter()-start
    repeats=min(10000,max(1,math.ceil(target/max(estimate,1e-9))))
    gc.collect()
    enabled=gc.isenabled();gc.disable()
    try:
        start=time.perf_counter_ns()
        for _ in range(repeats):
            actual=call()
        elapsed=(time.perf_counter_ns()-start)/1e9/repeats
    finally:
        if enabled:gc.enable()
    if actual != expected:
        raise AssertionError('nondeterministic benchmark result')
    return elapsed,repeats


def environment():
    return {'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),
            'processor':platform.processor(),'cpu_affinity':sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,
            'clock':time.get_clock_info('perf_counter')._asdict() if hasattr(time.get_clock_info('perf_counter'),'_asdict') else str(time.get_clock_info('perf_counter')),
            'gc':'disabled inside timed batches','parallel_workers':1}


def td_panel():
    rows=[]
    for panel, name in [('original','original-inputs.json'),('broader','rational-panel.json')]:
        for entry in json.loads((ROOT/'manifests'/name).read_text()):
            raw=(ROOT/entry['cache']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise AssertionError('TD input hash differs')
            record=json.loads(raw)
            rows.append({'panel':panel,'record':record,'sha256':entry['sha256']})
    return rows


def td_benchmark(rounds=7):
    panel=td_panel();results=[];solutions=[]
    for item in panel:
        record=item['record']
        prepared={v:{(i,j):mod.NDCPWLF(xs,ys) for i,j,xs,ys in record['arcs']} for v,mod in [('v011',OLD),('v012',NEW)]}
        for route_index, route in enumerate(record['bks']['routes']):
            samples={v:[] for v in prepared}
            expected={v:fold(record,route,v) for v in prepared}
            for v in prepared:
                actual=fold(record,route,v,prepared_arcs=prepared[v])
                if any(actual.get(k)!=expected[v].get(k) for k in ['feasible','duration','departure','chain_sha256']):
                    raise AssertionError('preloaded fold changed numerical output')
            for iteration in range(rounds):
                for v in (['v011','v012'] if iteration%2==0 else ['v012','v011']):
                    def call(v=v):
                        result=fold(record,route,v,prepared_arcs=prepared[v])
                        return tuple(result.get(k) for k in ['feasible','duration','departure'])
                    seconds,repeats=timed(call,target=.002)
                    samples[v].append({'seconds':seconds,'repeats':repeats})
            results.append({'panel':item['panel'],'id':record['id'],'route_index':route_index,'customers':len(route),'input_sha256':item['sha256'],
                            'samples':samples,'median_seconds':{v:statistics.median(s['seconds'] for s in a) for v,a in samples.items()}})
        print('TD kernel',record['id'],flush=True)
    # Alternate isolated interpreters so both complete packages keep their own imports.
    for iteration in range(rounds):
        for version in (['v011','v012'] if iteration%2==0 else ['v012','v011']):
            request={'panel':panel,'target':.002}
            proc=subprocess.run([sys.executable,str(ROOT/'scripts/benchmark_checker.py'),version],input=json.dumps(request),text=True,capture_output=True,check=True)
            solutions.extend(dict(version=version,round=iteration,**row) for row in json.loads(proc.stdout))
    rational=[]
    for name in ['original','broader']:
        choices=[(item,k,route) for item in panel if item['panel']==name for k,route in enumerate(item['record']['bks']['routes']) if len(route)<=25]
        choices.sort(key=lambda x:hashlib.sha256((x[0]['record']['id']+':'+str(x[1])+':s113').encode()).hexdigest())
        for item,k,route in choices[:12]:
            record=item['record'];row={'panel':name,'id':record['id'],'route_index':k,'customers':len(route),'samples':{},'status':'complete'}
            for interpretation in ['binary','decimal']:
                samples=[]
                try:
                    for _ in range(3):
                        start=time.perf_counter();result=evaluate_route(record,route,interpretation,timeout=10)
                        samples.append(time.perf_counter()-start)
                    row['samples'][interpretation]=samples
                    row[interpretation+'_duration']=str(result.get('duration'))
                except TimeoutError as error:
                    row['status']='resource-limit';row['error']=str(error)
            rational.append(row)
    summary={}
    for name in ['original','broader']:
        group=[r for r in results if r['panel']==name]
        ratios=[r['median_seconds']['v012']/r['median_seconds']['v011'] for r in group]
        summary[name]={'routes':len(group),'median_new_over_old':statistics.median(ratios),
                       'ratio_quartiles':statistics.quantiles(ratios,n=4),
                       'median_seconds':{v:statistics.median(r['median_seconds'][v] for r in group) for v in ['v011','v012']}}
    write_json(ROOT/'results/controlled-td.json',{'environment':environment(),'rounds':rounds,'summary':summary,'routes':results,'full_checkers':solutions,'rational':rational})
    print(json.dumps(summary))


def static_benchmark(rounds=7):
    sys.path.insert(0,str(ROOT/'vendor/v012/src'))
    from mamut_routing_lib.checker import exact_cost_value
    data=json.loads(gzip.decompress((ROOT/'data/static-history.json.gz').read_bytes()))
    groups=defaultdict(list)
    for row in data:
        if row['candidates']:groups[row['family']].append(row)
    selected=[]
    for family, rows in groups.items():
        rows.sort(key=lambda r:(r['size'],r['id']))
        selected.extend(rows[k] for k in sorted(set([0,len(rows)//4,len(rows)//2,3*len(rows)//4,len(rows)-1])))
    results=[]
    for row in selected:
        a=row['candidates'][0];b=row['candidates'][-1]
        vectors=[[v for route in c['vectors'] for v in route] for c in [a,b]]
        binary=[list(map(Fraction,v)) for v in vectors]
        decimal=[[Fraction(str(x)) for x in v] for v in vectors]
        operations={'flat':lambda:left(vectors[0]),'fsum':lambda:math.fsum(vectors[0]),
                    'binary-rational':lambda:sum(binary[0],Fraction()),'decimal-rational':lambda:sum(decimal[0],Fraction()),
                    'binary-rational-with-conversion':lambda:sum(map(Fraction,vectors[0]),Fraction()),
                    'decimal-rational-with-conversion':lambda:sum(map(exact_cost_value,vectors[0]),Fraction()),
                    'flat-ranking':lambda:objective_key(left(vectors[0]),a['num_routes'],row['objective'])<objective_key(left(vectors[1]),b['num_routes'],row['objective']),
                    'decimal-ranking':lambda:objective_key(sum(map(exact_cost_value,vectors[0]),Fraction()),a['num_routes'],row['objective'])<objective_key(sum(map(exact_cost_value,vectors[1]),Fraction()),b['num_routes'],row['objective']),
                    'flat-key-only':lambda:objective_key(a['flat'],a['num_routes'],row['objective'])<objective_key(b['flat'],b['num_routes'],row['objective']),
                    'decimal-key-with-parsing':lambda:objective_key(Fraction(a['decimal']),a['num_routes'],row['objective'])<objective_key(Fraction(b['decimal']),b['num_routes'],row['objective'])}
        scales={}
        for scale in [1,1000,1000000]:
            scaled=[x*scale for x in decimal[0]]
            eligible=all(x.denominator==1 and 0<=x<=2**63-1 for x in scaled) and sum(scaled)<=2**63-1
            scales[str(scale)]=eligible
            if eligible:
                integers=[int(x) for x in scaled]
                operations['integer-'+str(scale)]=lambda integers=integers:left(integers)
                if Fraction(left(integers),scale)!=Fraction(a['decimal']):raise AssertionError('scaled sum differs')
        samples={key:[] for key in operations}
        for iteration in range(rounds):
            keys=list(operations);random.Random(113+iteration).shuffle(keys)
            for key in keys:
                seconds,repeats=timed(operations[key])
                samples[key].append({'seconds':seconds,'repeats':repeats})
        results.append({'id':row['id'],'family':row['family'],'size':row['size'],'arcs':len(vectors[0]),'integer_scales':scales,
                        'candidate_pair_distinct':a['route_sha256']!=b['route_sha256'],'samples':samples,
                        'median_seconds':{key:statistics.median(x['seconds'] for x in s) for key,s in samples.items()}})
        print('Static timing',row['id'],flush=True)
    write_json(ROOT/'results/controlled-static.json',{'environment':environment(),'rounds':rounds,'records':results,
               'integer_note':'Python arbitrary-size integers, with signed-64-bit eligibility checked. No native fixed-width throughput claim.'})


def objective_key(cost,count,objective):
    return (cost,) if objective=='MonoCost' else (count,cost)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('experiment',choices=['td','static'])
    parser.add_argument('--rounds',type=int,default=7)
    args=parser.parse_args()
    if args.rounds<3:parser.error('at least 3 timing rounds are required')
    (td_benchmark if args.experiment=='td' else static_benchmark)(args.rounds)


if __name__=='__main__':main()
