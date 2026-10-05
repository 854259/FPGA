"""All-record input/target fidelity checks only. Synthetic replies are not model scores."""
from pathlib import Path
import argparse,collections,hashlib,json,subprocess,sys,re
import adapter
R=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
def main(args):
    original=args.dataset;data=original.read_bytes()
    assert sha(data)=='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    root=args.full_root;spec=json.loads((root/'RUN_SPEC.json').read_bytes())
    sources=['package/baseline.py','package/agent/map_runtime.py','package/skill/rtl-generation/SKILL.md','package/skill/rtl-feedback-repair/SKILL.md']
    for n in sources:assert sha((root/n).read_bytes())==spec['source_hashes'][n]
    generation=(root/sources[2]).read_text(encoding='utf-8');repair=(root/sources[3]).read_text(encoding='utf-8')
    test=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(R),'-p','test_adapter.py','-v'],capture_output=True,text=True,encoding='utf-8');assert test.returncode==0,test.stderr
    count=re.search(r'Ran (\d+) tests? in',test.stderr);assert count and int(count[1])==15
    rows=[]
    for record in map(json.loads,data.decode().splitlines()):
        view=adapter.task_view(record);assert json.loads(adapter.user_content(view))==view
        assert view['prompt']==record['input']['prompt'] and view['context']==record['input']['context'] and view['output_paths']==list(record['output']['context'])
        # A known synthetic text exercises multi-file transport/assembly, never solving or grading.
        synthetic={n:'ENGINEERING_TRANSPORT_SENTINEL\n'+n+'\n' for n in view['output_paths']}
        received=adapter.candidate_files(json.dumps({'files':synthetic},ensure_ascii=False),view);assert received==synthetic
        merged=adapter.assembled_files(view,received)
        assert all(merged[n]==s for n,s in view['context'].items() if n not in synthetic)
        first=adapter.messages(view,generation,repair)
        assert json.loads(first[1]['content'])==view
        rows.append(dict(record_id=record['id'],**adapter.binding(record,view),input_context_count=len(view['context']),output_file_count=len(view['output_paths']),synthetic_transport_passed=True,actual_model_calls=0,actual_eda_calls=0,independent_quality_admitted=False))
    assert len(rows)==len({r['record_id'] for r in rows})==302
    private=R/'raw_evidence/ALL_RECORD_BINDINGS.json';private.parent.mkdir(exist_ok=True);save(private,rows)
    result=dict(schema='natural_public_input_adapter_engineering_v1',python=sys.version.split()[0],adapter_sha256=sha((R/'adapter.py').read_bytes()),inventory_sha256=sha(Path(__file__).read_bytes()),test_source_sha256=sha((R/'test_adapter.py').read_bytes()),dataset_sha256=sha(data),all_record_binding_sha256=sha(private.read_bytes()),records=302,lossless_prompt_context_records=302,input_context_required=sum(bool(r['input_context_count']) for r in rows),multi_output_records=sum(r['output_file_count']>1 for r in rows),input_context_distribution=dict(collections.Counter(r['input_context_count'] for r in rows)),output_file_distribution=dict(collections.Counter(r['output_file_count'] for r in rows)),tests_passed=15,synthetic_file_transport_cases=302,actual_model_calls=0,actual_eda_calls=0,independent_model_tasks=0,independent_quality_admitted=0,official_baseline_modified=False,full_frozen_runtime_modified=False,adoption=False,source_bindings={n:spec['source_hashes'][n] for n in sources},limits=['Only exact input/file target transport and common research skill format/ABI adaptation; no native module compilation or semantics, model worker integration or fresh model score yet.','Research C/P must share the new format/ABI adaptation; it is not a change to or a measurement of the untouched official baseline.','All original public contexts preserved, including partial designs; hidden harness, output response/answers, record IDs and categories are excluded from model messages.','Synthetic file replies and boundary rejection tests are engineering controls, not 302 solved or admitted natural tasks.','Full original evidence qualification, faithful native runner integration, per-record judge discrimination and exposure review remain necessary before independent real model experiments.'])
    save(R/'RESULTS.json',result);save(R/'LOCAL_CHECK_RECEIPT.json',dict(returncode=test.returncode,stdout=test.stdout,stderr=test.stderr,actual_model_calls=0,actual_eda_calls=0));print(json.dumps({k:result[k] for k in ['records','input_context_required','multi_output_records','tests_passed','synthetic_file_transport_cases','actual_model_calls','actual_eda_calls','independent_quality_admitted']}))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=R.parent/'natural_harness_calibration_20261005/raw_evidence/ORIGINAL_DATASET.jsonl');parser.add_argument('--full-root',type=Path,default=R.parent/'phase_full156_20261005');main(parser.parse_args())
