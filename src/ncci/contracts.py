"""Route folds using untouched, hashed upstream PWLF implementations."""
import hashlib
import importlib.util
import math
from pathlib import Path
import struct
import time
from .inputs import ROOT



def load_pwlf(version):
    name = "ncci_pwlf_" + version
    spec = importlib.util.spec_from_file_location(name, ROOT / "vendor" / version / "src/mamut_routing_lib/td/pwlf.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD, NEW = load_pwlf("v011"), load_pwlf("v012")
STRICT = load_pwlf("v012")


def difference_error(a, b, rounded):
    # Error-free TwoSum applied to a + (-b), with separate binary64 operations.
    z = rounded - a
    return (a - (rounded - z)) + ((-b) - z)


def exact_unit_slope(xlo, ylo, xhi, yhi):
    rise, run = yhi - ylo, xhi - xlo
    return (math.isfinite(rise) and math.isfinite(run) and rise == run
            and difference_error(yhi, ylo, rise) == difference_error(xhi, xlo, run))


_strict_interpolate = STRICT._interpolate
_strict_crossing = STRICT._crossing_x


def strict_interpolate(xlo, ylo, xhi, yhi, x, enabled):
    return _strict_interpolate(xlo, ylo, xhi, yhi, x, enabled and exact_unit_slope(xlo, ylo, xhi, yhi))


def strict_crossing(xlo, ylo, xhi, yhi, value, enabled):
    return _strict_crossing(xlo, ylo, xhi, yhi, value, enabled and exact_unit_slope(xlo, ylo, xhi, yhi))


STRICT._interpolate = strict_interpolate
STRICT._crossing_x = strict_crossing
VARIANTS = {"v011": (False, False, False), "restriction": (True, False, False),
            "vertex": (False, True, False), "slope": (False, False, True),
            "v012": (True, True, True), "strict": (True, True, True)}


def fold(record, route, variant="v011", trace=False, prepared_arcs=None):
    start = time.perf_counter()
    direct_first, direct_vertex, slope = VARIANTS[variant]
    mod = OLD if variant == "v011" else STRICT if variant == "strict" else NEW
    cls = mod.NDCPWLF
    inst = record["instance"]
    arcs = prepared_arcs if prepared_arcs is not None else {(i, j): cls(xs, ys) for i, j, xs, ys in record["arcs"]}
    depot = inst.get("depot", 0)
    windows = inst.get("time_windows")
    lo, hi = inst["horizon"]
    if windows:
        lo, hi = max(lo, windows[depot][0]), min(hi, windows[depot][1])
    if lo > hi:
        return {"feasible": False, "breakpoints": 0, "seconds": time.perf_counter() - start}
    acc = cls.identity(lo, hi)
    previous = depot
    history = []
    peak = len(acc.xs)
    def compose(f, g):
        return f.compose(g) if mod is OLD else f.compose(g, slope_one_exact=slope)
    def remember(label):
        nonlocal peak
        peak = max(peak, len(acc.xs))
        if trace:
            history.append({"stage": label, "xs": list(acc.xs), "ys": list(acc.ys)})
    for k, vertex in enumerate(route):
        arc = arcs[previous, vertex]
        acc = mod.restrict_domain(arc, lo, hi, slope_one_exact=slope) if k == 0 and direct_first else compose(arc, acc)
        remember(f"arc:{previous}:{vertex}")
        if acc.is_empty():
            break
        e, l = windows[vertex] if windows else (None, None)
        service = float(inst["service_times"][vertex])
        if direct_vertex:
            acc = mod.apply_ready_time(acc, earliest=e, latest=l, service_time=service, slope_one_exact=slope)
        else:
            theta = mod.make_theta(e, l, service) if windows else mod.make_service_theta(acc.max_image, service)
            acc = compose(theta, acc)
        remember(f"vertex:{vertex}")
        if acc.is_empty():
            break
        previous = vertex
    if not acc.is_empty():
        acc = compose(arcs[previous, depot], acc)
        remember(f"arc:{previous}:{depot}")
    if not acc.is_empty() and windows:
        if direct_vertex:
            acc = mod.apply_ready_time(acc, earliest=None, latest=windows[depot][1], service_time=0., slope_one_exact=slope)
        else:
            acc = compose(cls.identity(0., windows[depot][1]), acc)
        remember("depot-cut")
    result = {"feasible": not acc.is_empty(), "breakpoints": len(acc.xs), "peak_breakpoints": peak,
              "seconds": time.perf_counter() - start}
    if not acc.is_empty():
        duration, departure = acc.min_shifted_image()
        result.update(duration=duration, departure=departure)
        result["chain_sha256"] = hashlib.sha256(b"".join(struct.pack("!dd", x, y) for x, y in zip(acc.xs, acc.ys))).hexdigest()
    if trace:
        result["trace"] = history
    return result


def forward_float(record, route, departure, slope=False, strict=False):
    inst = record["instance"]
    windows = inst.get("time_windows")
    mod = STRICT if strict else NEW
    arcs = {(i, j): mod.NDCPWLF(xs, ys) for i, j, xs, ys in record["arcs"]}
    depot = inst.get("depot", 0)
    t = departure
    previous = depot
    history = []
    for vertex in [*route, depot]:
        try:
            arrival = arcs[previous, vertex].evaluate(t, slope_one_exact=slope)
        except NEW.PWLFError:
            return {"feasible": False, "reason": "arc-domain", "trace": history}
        history.append({"arc": [previous, vertex], "departure": t, "arrival": arrival})
        if windows and arrival > windows[vertex][1]:
            return {"feasible": False, "reason": "due-date", "trace": history}
        if vertex == depot:
            return {"feasible": True, "duration": arrival - departure, "trace": history}
        t = max(arrival, windows[vertex][0]) if windows else arrival
        t += float(inst["service_times"][vertex])
        previous = vertex


def ulps(a, b):
    if a is None or b is None or not math.isfinite(a) or not math.isfinite(b):
        return None
    # Corpus costs and departures are non-negative.
    return abs(struct.unpack("!Q", struct.pack("!d", a))[0] - struct.unpack("!Q", struct.pack("!d", b))[0])
