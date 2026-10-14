"""Deterministic adversarial and random fixtures, frozen before measurement."""
import json
import math
import random
from fractions import Fraction as Q

from .contracts import ROOT, NEW, fold, VARIANTS, forward_float
from .exact import evaluate_route
from .inputs import write_json


def record(arcs, services, windows=None, horizon=(0., 2000.), name="synthetic"):
    n = len(services) - 1
    inst = dict(instance_name=name, instance_origin="Solomon1987", benchmark_name="Rifki2020",
                num_customers=n, num_vehicles=None, vehicle_capacity=1000,
                coordinates=[[float(i), 0.] for i in range(n + 1)], demands=[0] * (n + 1),
                service_times=services, depot=0, horizon=list(horizon),
                td={"model": "atf-ndcpwlf", "atf_path": "unused.atf.json"}, metadata={})
    if windows is not None:
        inst["time_windows"] = windows
    return {"id": name, "instance": inst, "arcs": arcs,
            "bks": {"routes": [list(range(1, n + 1))], "objective_function": "Duration"}}


def cases():
    result = []
    result.append(record([[0, 1, [0., 5., 20.], [7., 7., 25.]],
                          [1, 0, [0., 7., 7., 20.], [1., 8., 30., 43.]]], [0., 0.], horizon=(0., 20.), name="step-toy"))
    result.append(record([[0, 1, [0., 5., 20.], [7., 7., 25.]],
                          [1, 0, [0., 7., 7., 20.], [1., 8., 30., 43.]]], [0., 0.],
                         windows=[[0., 10.], [0., 25.]], horizon=(0., 20.), name="step-deadline"))
    for due in [math.nextafter(1014., -math.inf), 1014., math.nextafter(1014., math.inf)]:
        result.append(record([[0, 1, [0., 2000.], [1009., 3009.]], [1, 2, [0., 2000.], [0., 2000.]],
                              [2, 0, [0., 2000.], [10., 2010.]]], [0., 5., 0.],
                             [[0., 2000.], [250., 12360.], [0., due]], name=f"deadline-{due.hex()}"))
    result.append(record([[0, 1, [100., 110.], [103., 113.]], [1, 0, [100., 110.], [102., 112.]]],
                         [0., 0.], horizon=(100., 110.), name="nonzero-horizon"))
    result.append(record([[0, 1, [0., 20.], [2., 32.]], [1, 0, [0., 20.], [1., 21.]]],
                         [0., 3.], [[0., 20.], [8., 17.]], horizon=(0., 20.), name="nonunit-waiting"))
    rng = random.Random(20260930)
    for seed in range(160):
        n = rng.randint(1, 5)
        arcs = []
        for i, j in zip([0, *range(1, n + 1)], [*range(1, n + 1), 0]):
            x, y = 0, rng.randint(1, 60)
            xs, ys = [float(x)], [float(y)]
            while x < 2000:
                if rng.random() < .2:
                    y += rng.randint(1, 40); xs.append(float(x)); ys.append(float(y))
                width = min(rng.randint(1, 120), 2000 - x)
                if y - x > width + 1 and rng.random() < .3:
                    x += width
                else:
                    x += width; y += width
                xs.append(float(x)); ys.append(float(y))
            arcs.append([i, j, xs, ys])
        services = [0.] + [float(rng.randint(0, 30)) for _ in range(n)]
        windows = [[0., 2000.]] + [[0., float(rng.randint(1000, 2000))] for _ in range(n)] if seed % 2 else None
        result.append(record(arcs, services, windows, name=f"integer-step-{seed:03}"))
    # Small dyadic coordinates can be exact operands without the intermediate
    # differences and additions being exact. This probes that distinction.
    result.append(record([[0, 1, [0., 1.], [2. ** -54, 1.]],
                          [1, 0, [0., 1.], [2. ** -54, 1.]]], [0., 0.], horizon=(0., 1.), name="dyadic-near-unit"))
    return result


def run():
    fixtures = cases()
    write_json(ROOT / "fixtures/synthetic.json", fixtures)
    rows = []
    for k, rec in enumerate(fixtures):
        route = rec["bks"]["routes"][0]
        results = {v: fold(rec, route, v) for v in VARIANTS}
        exact = evaluate_route(rec, route)
        reference = {key: str(value) if isinstance(value, Q) else value for key, value in exact.items()}
        for v, r in results.items():
            r["feasibility_agrees"] = r["feasible"] == exact["feasible"]
            if r["feasible"] and exact["feasible"]:
                r["exact_cost_agrees"] = Q(r["duration"]) == exact["duration"]
                r["error"] = str(Q(r["duration"]) - exact["duration"])
                r["forward"] = forward_float(rec, route, r["departure"], slope=v in ("slope", "v012", "strict"), strict=v == "strict")
        rows.append({"id": rec["id"], "results": results, "exact": reference})
        if k % 20 == 0:
            print(f"Synthetic {k}/{len(fixtures)}", flush=True)
    write_json(ROOT / "results/synthetic.json", rows)
    # The rounded unit-slope test can hold when the exact slope differs.
    xlo, xhi, ylo, yhi = 0., 1., 2. ** -54, 1.
    write_json(ROOT / "results/rounded-slope-witness.json", {
        "xs": [xlo, xhi], "ys": [ylo, yhi],
        "float_rise_equals_run": yhi - ylo == xhi - xlo,
        "exact_rise_equals_run": Q(yhi) - Q(ylo) == Q(xhi) - Q(xlo),
        "exact_slope": str((Q(yhi) - Q(ylo)) / (Q(xhi) - Q(xlo)))})


if __name__ == "__main__":
    run()
