"""Evaluation-only control DUTs and separate software mutation predictions."""
import hashlib
import json
import zipfile
from pathlib import Path
import fsm_contract
import templates

ROOT=Path(__file__).resolve().parent
NAMES=['positive','missing_hold','missing_output','wrong_condition','shifted_encoding','constant_zero']

def software(c,name):
    observed=[]
    last_output=max(i for i,values in enumerate(c['state_outputs']) if any(values))
    conditioned=min(t['source'] for t in c['transitions'] if t['condition'])
    for row in c['observations']:
        next_value=0;moore_value=[0]*len(c['moore_names'])
        for t in c['transitions']:
            source=(t['source']+1)%c['width'] if name=='shifted_encoding' else t['source']
            if not row['state']&(1<<source):continue
            if name=='missing_hold' and t['source']==t['target']:continue
            cond=t['condition'];ok=all(row['inputs'][k]==(1-v if name=='wrong_condition' and t['source']==conditioned else v) for k,v in cond.items())
            if ok:next_value|=1<<t['target']
        for i,values in enumerate(c['state_outputs']):
            source=(i+1)%c['width'] if name=='shifted_encoding' else i
            if row['state']&(1<<source) and not (name=='missing_output' and i==last_output):
                for j,v in enumerate(values):moore_value[j]|=v
        packed=0
        for m in c['output_maps']:
            value=next_value if m['kind']=='next_vector' else ((next_value&(1<<m['index']))!=0 if m['kind']=='next_bit' else moore_value[m['index']])
            packed=(packed<<m['width'])|int(value)
        observed.append(0 if name=='constant_zero' else packed)
    return observed

def control(c,name):
    lines=['module TopModule('+','.join(('input wire' if p['direction']=='input' else 'output wire')+(' ['+str(p['width']-1)+':0]' if p['vector'] else '')+' '+p['name'] for p in c['ports'])+');']
    last_output=max(i for i,values in enumerate(c['state_outputs']) if any(values))
    conditioned=min(t['source'] for t in c['transitions'] if t['condition'])
    def active(i):return f'{c["state_name"]}[{(i+1)%c["width"] if name=="shifted_encoding" else i}]'
    def term(t):
        terms=[active(t['source'])]
        for k,v in t['condition'].items():
            v=1-v if name=='wrong_condition' and t['source']==conditioned else v
            terms.append(k if v else '~'+k)
        return '('+' & '.join(terms)+')'
    def expression(m,bit):
        if name=='constant_zero':return "1'b0"
        if m['kind']=='moore':
            terms=[active(i) for i,values in enumerate(c['state_outputs']) if values[m['index']] and not (name=='missing_output' and i==last_output)]
        else:
            wanted=bit if m['kind']=='next_vector' else m['index']
            terms=[term(t) for t in c['transitions'] if t['target']==wanted and not (name=='missing_hold' and t['source']==t['target'])]
        return ' | '.join(terms) if terms else "1'b0"
    for m in c['output_maps']:
        for bit in range(m['width']):
            target=m['name']+(f'[{bit}]' if m['kind']=='next_vector' else '')
            lines.append('assign '+target+' = '+expression(m,bit)+';')
    return '\n'.join(lines+['endmodule',''])

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(data):return hashlib.sha256(data).hexdigest()

def main():
    out=ROOT/'raw_evidence/inputs';assert not out.exists();out.mkdir(parents=True)
    archive=ROOT.parent/'full156_postflight_20261004/raw_evidence/full312.zip'
    assert sha(archive.read_bytes())=='64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    rows=[]
    with zipfile.ZipFile(archive) as z:
        hashes=json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        inputs=[]
        for prefix in ['143','150']:
            p=next(n for n in z.namelist() if n.startswith('kit/bench/tasks_veval/Prob'+prefix+'_') and n.endswith('/prompt.txt'))
            task=p.split('/')[-2];d='run/samples/A/'+task+'/worker/solution.v'
            assert sha(z.read(p))==hashes[p] and sha(z.read(d))==hashes[d]
            inputs.append((task,z.read(p).decode(),z.read(d),{'prompt_member':p,'prompt_sha256':hashes[p],'candidate_member':d,'candidate_sha256':hashes[d]}))
        inputs.extend([('fsm_full6',templates.full()[0],None,None),('fsm_partial5',templates.partial()[0],None,None)])
        for task,prompt,candidate,binding in inputs:
            c=fsm_contract.parse(prompt);assert c['status']=='supported',(task,c)
            folder=out/task;folder.mkdir();(folder/'prompt.txt').write_bytes(prompt.encode());save(folder/'contract.json',c)
            (folder/'tb.sv').write_bytes(fsm_contract.render_tb(c,task).encode())
            for name in NAMES:(folder/(name+'.sv')).write_bytes(control(c,name).encode())
            if candidate is not None:(folder/'candidate.sv').write_bytes(candidate)
            counts={name:sum(v!=o['expected'] for v,o in zip(software(c,name),c['observations'])) for name in NAMES}
            assert counts['positive']==0 and all(counts[name]>0 for name in NAMES[1:]),counts
            rows.append(dict(task=task,checks=c['checks'],group='known_public_development' if candidate else 'constructed_calibration',archived_candidate=candidate is not None,
                             source_binding=binding,positive_names=['positive'],expected_control_mismatches=counts))
    save(ROOT/'CONTROL_PREPARATION.json',dict(cases=rows,model_calls=0,eda_calls=0,control_duts_are_evaluation_only=True))
    old=json.loads((ROOT.parent/'edge_contract_20261005/INPUT_MANIFEST.json').read_text())
    save(ROOT/'INPUT_MANIFEST.json',old)
    print(json.dumps(rows,ensure_ascii=True))

if __name__=='__main__':main()
