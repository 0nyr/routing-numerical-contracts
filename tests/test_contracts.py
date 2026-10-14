import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from ncci.contracts import ROOT, fold
from ncci.exact import evaluate_route


def rifki():
    fixture = json.loads((ROOT / "fixtures/rifki30-route.json").read_text())
    n = len(fixture["route"])
    instance = dict(instance_name="Rifki-30-route", instance_origin="Solomon1987", benchmark_name="Rifki2020",
                    num_customers=n, num_vehicles=None, vehicle_capacity=1,
                    coordinates=[[float(i), 0.] for i in range(n + 1)], demands=[0] * (n + 1),
                    service_times=fixture["service_times"], depot=0, horizon=fixture["horizon"],
                    td={"model": "atf-ndcpwlf", "atf_path": "unused.atf.json"}, metadata={})
    return {"instance": instance, "arcs": [[a["from"], a["to"], a["xs"], a["ys"]] for a in fixture["arcs"]]}, fixture["route"]


def test_frozen_sources_have_recorded_hashes():
    for release in json.loads((ROOT / "manifests/checkers.json").read_text()):
        for path, digest in release["files"].items():
            assert hashlib.sha256((ROOT / "vendor" / release["version"] / path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("version,expected", [("v011", (1768., 1301.)), ("v012", (1743., 1341.))])
def test_rifki_and_whole_tagged_package(version, expected):
    record, route = rifki()
    actual = fold(record, route, version)
    assert (actual["duration"], actual["departure"]) == expected
    worker = ROOT / "src/ncci/tagged_worker.py"
    result = subprocess.run([sys.executable, str(worker), version], input=json.dumps({"record": record, "route": route}) + "\n",
                            text=True, capture_output=True, check=True)
    tagged = json.loads(result.stdout)
    assert (tagged["duration"], tagged["departure"]) == expected


def test_independent_rifki_reference():
    record, route = rifki()
    result = evaluate_route(record, route)
    assert (result["duration"], result["departure"]) == (1743, 1341)
