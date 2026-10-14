"""Independent exact forward partitioning. No checker composition is imported."""
from bisect import bisect_left
from dataclasses import dataclass
from fractions import Fraction as Q
import time


def number(value, interpretation="binary"):
    if interpretation == "binary":
        return Q(float(value))
    return Q(str(value))


@dataclass(frozen=True)
class Stage:
    xs: tuple = ()
    ys: tuple = ()
    earliest: object = None
    latest: object = None
    service: object = Q(0)

    def boundaries(self):
        if self.xs:
            return self.xs
        return tuple(v for v in (self.earliest, self.latest) if v is not None)

    def evaluate(self, t):
        if self.xs:
            if t < self.xs[0] or t > self.xs[-1]:
                return None
            k = bisect_left(self.xs, t)
            if self.xs[k] == t:
                return self.ys[k]
            a, b = k - 1, k
            return self.ys[a] + (t - self.xs[a]) * (self.ys[b] - self.ys[a]) / (self.xs[b] - self.xs[a])
        if self.latest is not None and t > self.latest:
            return None
        return max(t, self.earliest) + self.service if self.earliest is not None else t + self.service


def forward(stages, departure):
    t = departure
    for stage in stages:
        t = stage.evaluate(t)
        if t is None:
            return None
    return t


def stages_for(record, route, interpretation="binary"):
    conv = lambda x: number(x, interpretation)
    instance = record["instance"]
    arcs = {(i, j): (xs, ys) for i, j, xs, ys in record["arcs"]}
    windows = instance.get("time_windows")
    depot = instance.get("depot", 0)
    stages = []
    previous = depot
    for v in [*route, depot]:
        xs, ys = arcs[previous, v]
        stages.append(Stage(tuple(map(conv, xs)), tuple(map(conv, ys))))
        if v != depot:
            e, l = map(conv, windows[v]) if windows else (None, None)
            stages.append(Stage(earliest=e, latest=l, service=conv(instance["service_times"][v])))
        elif windows:
            stages.append(Stage(latest=conv(windows[depot][1])))
        previous = v
    low, high = map(conv, instance["horizon"])
    if windows:
        low = max(low, conv(windows[depot][0]))
        high = min(high, conv(windows[depot][1]))
    return stages, low, high


def partition(stages, low, high, timeout=120):
    """Pull each next-stage boundary back through affine prefix intervals.

    Prefix endpoints and open intervals are separate, so jumps never become
    vertical connectors in the selected function. Infeasible prefix intervals
    cannot recover feasibility at a later stage.
    """
    deadline = time.monotonic() + timeout
    cuts = {low, high} if low <= high else set()
    prefix = []
    max_bits = 0
    for stage in stages:
        if time.monotonic() > deadline:
            raise TimeoutError("rational partition exceeded per-route time limit")
        ordered = sorted(cuts)
        new = set()
        for a, b in zip(ordered, ordered[1:]):
            p, q = (2 * a + b) / 3, (a + 2 * b) / 3
            u, v = forward(prefix, p), forward(prefix, q)
            if u is None or v is None or u == v:
                continue
            slope = (v - u) / (q - p)
            for boundary in stage.boundaries():
                x = p + (boundary - u) / slope
                if a < x < b:
                    new.add(x)
            if time.monotonic() > deadline:
                raise TimeoutError("rational partition exceeded per-route time limit")
        cuts.update(new)
        prefix.append(stage)
        for x in cuts:
            max_bits = max(max_bits, x.numerator.bit_length(), x.denominator.bit_length())
    return sorted(cuts), max_bits


def optimize(stages, low, high, timeout=120):
    deadline = time.monotonic() + timeout
    cuts, max_bits = partition(stages, low, high, timeout)
    candidates = []
    for t in cuts:
        if time.monotonic() > deadline:
            raise TimeoutError("rational optimization exceeded per-route time limit")
        value = forward(stages, t)
        if value is not None:
            candidates.append((value - t, t, True))
    # Inspect open-interval limits as well. They may define an unattained
    # infimum for more general domain conventions than the routing corpus.
    for a, b in zip(cuts, cuts[1:]):
        if time.monotonic() > deadline:
            raise TimeoutError("rational optimization exceeded per-route time limit")
        p, q = (2 * a + b) / 3, (a + 2 * b) / 3
        u, v = forward(stages, p), forward(stages, q)
        if u is None or v is None:
            continue
        slope = (v - u) / (q - p)
        for t in (a, b):
            value = u + slope * (t - p)
            selected = forward(stages, t)
            candidates.append((value - t, t, selected == value))
    if not candidates:
        return {"feasible": False, "cuts": len(cuts), "max_bits": max_bits}
    best = min(x[0] for x in candidates)
    minimizers = [x for x in candidates if x[0] == best]
    attained = [x for x in minimizers if x[2]]
    selected = min(attained or minimizers, key=lambda x: x[1])
    return {"feasible": True, "duration": best, "departure": selected[1],
            "attained": bool(attained), "cuts": len(cuts), "max_bits": max_bits}


def evaluate_route(record, route, interpretation="binary", timeout=120):
    stages, low, high = stages_for(record, route, interpretation)
    return optimize(stages, low, high, timeout)
