"""Read-only all-record dispatch coverage for the actual frozen C/P candidate."""
from pathlib import Path
import argparse,hashlib,json,sys
R=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--full-root',type=Path,default=R.parent/'phase_full156_20261005');parser.add_argument('--dataset',type=Path,default=R.parent/'natural_harness_calibration_20261005/raw_evidence/ORIGINAL_DATASET.jsonl');args=parser.parse_args()
    root=args.full_root;spec=json.loads((root/'RUN_SPEC.json').read_bytes())
    assert sha((root/'RUN_SPEC.json').read_bytes())=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    for n,h in spec['source_hashes'].items():assert sha((root/n).read_bytes())==h,n
    data=args.dataset.read_bytes();assert sha(data)=='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    sys.path.insert(0,str(root));import prompt_map,edge_dispatch
    rows=[]
    for r in map(json.loads,data.decode().splitlines()):
        # Same public-prompt-only parse boundary as the frozen worker, not its hidden harness.
        c=prompt_map.parse(r['input']['prompt']);p=edge_dispatch.parse(r['input']['prompt'])
        rows.append(dict(record_id=r['id'],prompt_sha256=sha(r['input']['prompt'].encode()),C_status=c['status'],P_status=p['status'],C_reason=c.get('reason'),P_reason=p.get('reason'),P_family=p.get('family')))
    assert len(rows)==len({r['record_id'] for r in rows})==302
    private=R/'raw_evidence/DISPATCH_BINDINGS.json';private.write_bytes((json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode())
    out=dict(schema='frozen_CP_natural_prompt_dispatch_inventory_v1',source_sha256=sha(Path(__file__).read_bytes()),dataset_sha256=sha(data),full_spec_sha256=sha((root/'RUN_SPEC.json').read_bytes()),binding_sha256=sha(private.read_bytes()),records=302,C_supported=sum(r['C_status']=='supported' for r in rows),P_supported=sum(r['P_status']=='supported' for r in rows),candidate_only_supported=sum(r['C_status']!='supported' and r['P_status']=='supported' for r in rows),model_calls=0,eda_calls=0,independent_quality_admitted=0,limits=['Prompt-only parser applicability, not complete natural solver behavior or judge discrimination. Public contexts preserved by a separate file adapter, not fed to a parser with a changed signature.','No matched dispatch on this dataset would mean no evidence to attribute new C/P native-feedback gains here; model ability and broader verification methods remain untested.','A native-name/reset/port contract extension would be a new isolated factor requiring calibration, guards and regression; the running frozen full source must remain unchanged.'])
    (R/'APPLICABILITY.json').write_bytes((json.dumps(out,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps({k:out[k] for k in ['records','C_supported','P_supported','candidate_only_supported','model_calls','eda_calls']}))
