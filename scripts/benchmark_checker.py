"""Time a complete frozen checker in an isolated interpreter."""
import json
from pathlib import Path
import sys
import time

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'vendor'/sys.argv[1]/'src'))
sys.path.insert(0,str(root/'src'))
from mamut_routing_lib.td.artifacts import InstanceATFs, LoadedTDInstance, td_instance_from_payload
from mamut_routing_lib.td.checker import check_td_solution
from mamut_routing_lib.td.pwlf import NDCPWLF
from mamut_routing_lib.models import BenchmarkSolution
from mamut_routing_lib.enums import ObjectiveFunction
from ncci.study import timed
from ncci.contracts import fold

request=json.load(sys.stdin);rows=[]
for item in request['panel']:
    record=item['record']
    start=time.perf_counter()
    instance=td_instance_from_payload(record['instance'])
    arcs={(i,j):NDCPWLF(xs,ys) for i,j,xs,ys in record['arcs']}
    atfs=InstanceATFs(instance.instance_name,instance.benchmark_name.value,tuple(instance.horizon),instance.num_customers,arcs)
    solution=BenchmarkSolution(instance_name=instance.instance_name,routes=record['bks']['routes'],cost=None)
    loaded=LoadedTDInstance(instance,atfs,Path(record['id']),None)
    setup=time.perf_counter()-start
    objective=ObjectiveFunction(record['bks']['objective_function'])
    def run():
        result=check_td_solution(loaded,solution,objective_function=objective)
        return result.status.value,result.routing_cost,tuple((r.feasible,r.duration,r.departure_time) for r in result.route_evaluations)
    output=run()
    references=[fold(record,route,sys.argv[1]) for route in record['bks']['routes']]
    expected=tuple((r['feasible'],r.get('duration'),r.get('departure')) for r in references)
    total=0.
    for route,result in sorted(zip(record['bks']['routes'],references),key=lambda pair:pair[0][0]):
        total+=result['duration']
    if objective.value=='FleetCostDuration':total+=record['instance']['fleet_fixed_cost']*len(references)
    if output!=('valid',total,expected):raise AssertionError('full checker differs from the frozen fold')
    seconds,repeats=timed(run,target=request['target'])
    rows.append({'panel':item['panel'],'id':record['id'],'setup_seconds':setup,'seconds':seconds,'repeats':repeats,'status':output[0],'cost':output[1]})
print(json.dumps(rows))
