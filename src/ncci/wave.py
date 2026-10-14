"""Read-only inventory of the September changes at frozen repository pins."""
import json
import argparse
from pathlib import Path

from .inputs import ROOT, DEFAULT_DATA, git, sha, write_json


def main(data_root=DEFAULT_DATA):
    repos = json.loads((ROOT / 'manifests/data-repositories.json').read_text())
    rows, costs, routes, metadata = [], [], [], []
    for repository in repos:
        path = data_root / repository['path']
        changed = git(path, 'diff', '--name-only', repository['baseline'], repository['head']).decode().splitlines()
        bks_count = instance_count = 0
        for name in changed:
            if not (name.endswith('.vrp.json') or '.bks.' in name and name.endswith('.json')):
                continue
            try:
                before_raw = git(path, 'show', f"{repository['baseline']}:{name}")
                after_raw = git(path, 'show', f"{repository['head']}:{name}")
                before, after = json.loads(before_raw), json.loads(after_raw)
            except Exception:
                continue
            identifier = (Path(repository['path']) / name).as_posix()
            if '.bks.' in name:
                bks_count += 1
                if before['cost'] != after['cost']:
                    costs.append({'id': identifier, 'before': before['cost'], 'after': after['cost']})
                if before['routes'] != after['routes']:
                    routes.append({'id': identifier, 'before_sha256': sha(before_raw), 'after_sha256': sha(after_raw),
                                   'before_routes': len(before['routes']), 'after_routes': len(after['routes'])})
            else:
                instance_count += 1
            old = before.get('metadata', {}).get('optimality', {})
            new = after.get('metadata', {}).get('optimality', {})
            if old != new:
                metadata.append({'id': identifier, 'before': old, 'after': new,
                                 'before_sha256': sha(before_raw), 'after_sha256': sha(after_raw)})
        rows.append({**repository, 'changed_bks': bks_count, 'changed_instances': instance_count})
    result = {'repositories': rows, 'cost_changes': costs, 'route_changes': routes, 'optimality_changes': metadata}
    write_json(ROOT / 'results/wave.json', result)
    print(json.dumps({k: len(v) for k, v in result.items()}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,default=DEFAULT_DATA)
    main(parser.parse_args().data_root)
