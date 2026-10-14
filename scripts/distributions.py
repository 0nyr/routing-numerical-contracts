"""Compare published wheels to the pinned checker source without installing them."""
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from ncci.inputs import write_json

output = root / 'outputs/distributions'
output.mkdir(parents=True, exist_ok=True)
rows = []
for version, tag in [('0.11.0', 'v011'), ('0.12.0', 'v012')]:
    url = f'https://pypi.org/pypi/mamut-routing-lib/{version}/json'
    with urllib.request.urlopen(url, timeout=30) as f:
        metadata = json.load(f)
    wheel = next(f for f in metadata['urls'] if f['packagetype'] == 'bdist_wheel')
    with urllib.request.urlopen(wheel['url'], timeout=30) as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == wheel['digests']['sha256']
    (output / wheel['filename']).write_bytes(data)
    matches, differs = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if not name.startswith('mamut_routing_lib/') or not name.endswith('.py'):
                continue
            pinned = root / 'vendor' / tag / 'src' / name
            raw = archive.read(name)
            if pinned.exists() and raw == pinned.read_bytes():
                matches.append(name)
            else:
                differs.append(name)
    rows.append({'version': version, 'metadata_url': url, 'wheel_url': wheel['url'],
                 'wheel_sha256': digest, 'uploaded_utc': wheel['upload_time_iso_8601'], 'yanked': wheel['yanked'],
                 'identical_source_files': matches, 'different_source_files': differs})
write_json(root / 'manifests/distributions.json', rows)
print(json.dumps([{'version': r['version'], 'identical': len(r['identical_source_files']), 'different': r['different_source_files']} for r in rows]))
