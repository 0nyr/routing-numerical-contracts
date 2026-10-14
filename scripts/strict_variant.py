"""Evaluate the strict slope prototype against previously computed exact references."""
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
from ncci.contracts import NEW, STRICT
from ncci.experiment import summarize_solution
from ncci.exact import forward, stages_for, number
from ncci.inputs import write_json

for name in ['original-inputs.json','rational-panel.json']:
    inputs={r['id']:r for r in json.loads((root/'manifests'/name).read_text())}
    manifest=json.loads((root/'results'/name).read_text())
    for entry in manifest:
        if entry['status']!='complete':continue
        path=root/entry['result'];raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==entry['sha256']
        result=json.loads(raw);input_entry=inputs[result['id']];raw_input=(root/input_entry['cache']).read_bytes()
        assert hashlib.sha256(raw_input).hexdigest()==input_entry['sha256']
        record=json.loads(raw_input);new=summarize_solution(record,record['bks'],['strict'])
        result['current']['totals']['strict']=new['totals']['strict']
        for row,added in zip(result['current']['routes'],new['routes']):
            a=added['folds']['strict']
            for interpretation,q in row['exact'].items():
                if a['feasible'] and q.get('feasible'):
                    error=Q(a['duration'])-Q(q['duration']);a[interpretation+'_error']=str(error);a[interpretation+'_abs_error']=float(abs(error))
                    a[interpretation+'_feasible_at_departure']=forward(stages_for(record,row['route'],interpretation)[0],number(a['departure'])) is not None
            row['folds']['strict']=a
        result['input_sha256']=input_entry['sha256'];write_json(path,result);entry['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(root/'results'/name,manifest)
xlo,ylo,xhi,yhi,x=0.,2.**-51,5.,5.,0.011393229166666666
exact=Q(ylo)+(Q(x)-Q(xlo))*(Q(yhi)-Q(ylo))/(Q(xhi)-Q(xlo))
write_json(root/'results/strict-slope-witness.json', {'xs':[xlo,xhi],'ys':[ylo,yhi],'x':x,
           'rational':str(exact),'rounded_rational':float(exact),
           'generic':NEW._interpolate(xlo,ylo,xhi,yhi,x,False),'rounded_slope_rule':NEW._interpolate(xlo,ylo,xhi,yhi,x,True),
           'strict_slope_rule':STRICT._interpolate(xlo,ylo,xhi,yhi,x,True)})
print('strict variant complete')
