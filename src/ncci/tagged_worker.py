"""Evaluate the entire original checker package in a separate interpreter."""
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "vendor" / sys.argv[1] / "src"))
from mamut_routing_lib.td.artifacts import InstanceATFs, td_instance_from_payload
from mamut_routing_lib.td.checker import compute_route_duration
from mamut_routing_lib.td.pwlf import NDCPWLF

for line in sys.stdin:
    request = json.loads(line)
    record = request["record"]
    instance = td_instance_from_payload(record["instance"])
    arcs = {(i, j): NDCPWLF(xs, ys) for i, j, xs, ys in record["arcs"]}
    atfs = InstanceATFs(instance.instance_name, instance.benchmark_name.value, tuple(instance.horizon), instance.num_customers, arcs)
    evaluation = compute_route_duration(instance, atfs, request["route"])
    print(json.dumps({"feasible": evaluation.feasible, "duration": evaluation.duration, "departure": evaluation.departure_time}), flush=True)
