"""Restore archived public evidence and verify its recorded hashes."""
import argparse
import hashlib
import json
import tarfile

from .inputs import ROOT


def restore():
    bundles=json.loads((ROOT/'data/bundles.json').read_text())
    for entry in bundles:
        path=ROOT/entry['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError(f'archive digest differs: {path}')
        if entry.get('kind','tar')=='tar':
            with tarfile.open(path,'r:gz') as archive:
                archive.extractall(ROOT,filter='data')
    return verify()


def verify():
    count=0
    for entry in json.loads((ROOT/'data/bundles.json').read_text()):
        if hashlib.sha256((ROOT/entry['path']).read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('data bundle digest differs: '+entry['path'])
        count+=1
    for category,names in [('inputs',['original-inputs.json','rational-panel.json']),('results',['original-inputs.json','rational-panel.json','td-inputs.json'])]:
        for name in names:
            manifest=ROOT/('manifests' if category=='inputs' else 'results')/name
            for entry in json.loads(manifest.read_text()):
                if entry['status'] not in ('ready','complete'):continue
                path=ROOT/entry['cache' if category=='inputs' else 'result']
                if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                    raise ValueError(f'archived evidence digest differs: {path}')
                count+=1
    for release in json.loads((ROOT/'manifests/checkers.json').read_text()):
        for path,digest in release['files'].items():
            if hashlib.sha256((ROOT/'vendor'/release['version']/path).read_bytes()).hexdigest()!=digest:
                raise ValueError('frozen source differs: '+path)
            count+=1
    print(json.dumps({'verified_files':count}))
    return count


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['restore','verify'])
    args=parser.parse_args();(restore if args.action=='restore' else verify)()


if __name__=='__main__':main()
