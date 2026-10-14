"""Differentially verify the harness against both complete frozen packages."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from ncci.contracts import fold
from ncci.inputs import write_json

requests = []
for entry in json.loads((root / 'manifests/original-inputs.json').read_text()):
    record = json.loads((root / entry['cache']).read_text())
    for route in record['bks']['routes']:
        requests.append({'record': record, 'route': route})
for record in json.loads((root / 'fixtures/synthetic.json').read_text()):
    requests.append({'record': record, 'route': record['bks']['routes'][0]})
payload = ''.join(json.dumps(r) + '\n' for r in requests)
rows = []
for version in ('v011', 'v012'):
    worker = subprocess.run([sys.executable, str(root / 'src/ncci/tagged_worker.py'), version], input=payload,
                            text=True, capture_output=True, check=True)
    tagged = [json.loads(line) for line in worker.stdout.splitlines()]
    if len(tagged) != len(requests):
        raise AssertionError('tagged checker omitted records')
    mismatches = []
    for request, reference in zip(requests, tagged):
        result = fold(request['record'], request['route'], version)
        if any(result.get(key) != reference[key] for key in ('feasible', 'duration', 'departure')):
            mismatches.append({'id': request['record'].get('id'), 'route': request['route'], 'harness': result, 'tagged': reference})
    rows.append({'version': version, 'routes': len(requests), 'mismatches': mismatches,
                 'request_sha256': hashlib.sha256(payload.encode()).hexdigest(),
                 'result_sha256': hashlib.sha256(worker.stdout.encode()).hexdigest()})
write_json(root / 'results/conformance.json', rows)
print(json.dumps(rows))
assert all(not row['mismatches'] for row in rows)
