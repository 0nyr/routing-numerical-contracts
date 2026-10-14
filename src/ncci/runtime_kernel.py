"""Stdlib-only conformance payload runnable under multiple Python versions."""
import hashlib
import json
import platform
import struct
import sys
from .contracts import fold
from .inputs import ROOT


def run():
    rows = []
    manifest = json.loads((ROOT / 'manifests/original-inputs.json').read_text())
    for entry in manifest:
        record = json.loads((ROOT / entry['cache']).read_text())
        for route in record['bks']['routes']:
            row = {'id': entry['id'], 'route': route}
            for version in ('v011', 'v012'):
                result = fold(record, route, version)
                row[version] = {k: result.get(k) for k in ('feasible', 'duration', 'departure', 'chain_sha256')}
            rows.append(row)
    payload = json.dumps(rows, sort_keys=True).encode()
    u, e, l, s = 1009., 250., 12360., 5.
    return {'python': sys.version, 'platform': platform.platform(), 'routes': len(rows),
            'fold_digest': hashlib.sha256(payload).hexdigest(),
            'sum_positive': sum([1e16, 1., 1.]), 'left_positive': (1e16 + 1.) + 1.,
            'theta_interpolation': (e+s) + ((u-e)/(l-e))*((l+s)-(e+s)),
            'theta_direct': max(u,e)+s}


if __name__ == '__main__':
    print(json.dumps(run()))
