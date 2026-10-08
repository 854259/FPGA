"""AMD-only fixed15 freeze. Pure qualification evidence is reused, never rerun."""
import argparse,datetime,hashlib,importlib.util,json,os,re,shutil,sys,time
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def inventory(groups,external):
    assert external['legacy_groups']==95 and external['legacy_summed_group_source_assets']==6286
    assert external['unique_immutable_files']==len(external['source_hashes'])==6516
    retained={};duplicates=0
    assert groups['source_assets']==sum(len(g['source_hashes']) for g in groups['groups'].values())
    for g in groups['groups'].values():
        cloud=PurePosixPath(g['cloud_root']);assert cloud.is_absolute() and '..' not in cloud.parts
        for n,h in g['source_hashes'].items():
            relative=PurePosixPath(n);assert not relative.is_absolute() and '..' not in relative.parts
            key=(cloud/relative).relative_to(PurePosixPath(external['cloud_root'])).as_posix()
            assert re.fullmatch('[0-9a-f]{64}',h)
            if key in retained:assert retained[key]==h;duplicates+=1
            retained[key]=h
    assert all(retained.get(n)==h for n,h in external['source_hashes'].items())
    return dict(schema='same_path_same_sha_new_fixed15_inventory_v1',protected_record_count=groups['source_assets'],
        protected_unique_files=len(retained),same_sha_duplicate_records=duplicates,
        legacy_anchor_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),legacy_unique_files=6516)

def main(seed_path):
    assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode
    assert not (ROOT/'RUN_SPEC.json').exists() and not (ROOT/'results').exists() and not (ROOT/'guard').exists()
    seed=read(seed_path)
    assert seed['schema']=='internal_declaration_actual_preparation_inputs_v1'
    assert seed['status']=='CURRENT_AMD_CAPTURE_AND_NEW_SOURCE_CONTROLS_PASSED'
    assert seed['cloud_root']==str(ROOT) and re.fullmatch(r'/workspace/team/runs/fpga_owner/internal_declaration_fixed15_[A-Za-z0-9_]+',str(ROOT))
    assert seed['independent_postexit_passed'] is True
    assert re.fullmatch('[0-9a-f]{40}',seed['base_commit'])
    assert sha(ROOT/'SOURCE_MANIFEST.json')==seed['source_manifest_sha256']
    source=read(ROOT/'SOURCE_MANIFEST.json')
    for n,h in source['runtime_sources'].items():assert sha(ROOT/n)==h,n
    for n,h in seed['additional_input_hashes'].items():assert sha(ROOT/n)==h,n
    required={'raw_evidence/ENVIRONMENT_CAPTURE.json','raw_evidence/PROTECTED_GROUPS_CAPTURE.json','INTEGRATION_CONTROL_BINDING.json','QUALIFYING_FACTOR/PIPELINE4.zip','QUALIFYING_FACTOR/NATIVE121.zip','INPUT_BUDGET_SOURCE_MAP.json','CONTEXT_BUDGET_REVIEW.json'}
    assert required<=set(seed['additional_input_hashes'])
    assert sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json')=='b28df2dc806a0300a71bd295bdee23bdad05fb31e456e478139b7c137fe53a11'
    capture=read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json');groups=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    assert capture['schema'].startswith('actual_') and groups['schema'].startswith('actual_')
    budget_review=read(ROOT/'CONTEXT_BUDGET_REVIEW.json')
    assert budget_review['schema']=='internal_declaration_current_context_budget_review_v1'
    assert budget_review['passed'] is True and budget_review['model_identity']==capture['model_identity']
    assert budget_review['input_budget_source_map_sha256']==sha(ROOT/'INPUT_BUDGET_SOURCE_MAP.json')
    assert budget_review['output_max_tokens']==8192 and budget_review['maximum_requests']==2
    assert budget_review['old112_literal_P_prediction_reused'] is False
    assert budget_review['internal_declaration_inputs_fit_with_output_budget'] is True
    assert budget_review['all_repair_token_capacity_claim'] is False
    deps={n:sha(ROOT/'dependencies'/n) for n in ('full156_postflight_audit.py','paired_checkpoint.py','probe_runner.py')}
    assert capture['dependencies_cloud']==str(ROOT/'dependencies') and capture['dependency_hashes']==deps
    controls=read(ROOT/'INTEGRATION_CONTROL_BINDING.json')
    assert controls['passed'] and controls['schema']=='internal_declaration_scoring_integration_actual_binding_v1'
    assert controls['model_calls']==controls['EDA_calls']==0 and controls['child_retired']
    for n,h in controls['source_hashes'].items():assert sha(ROOT/n)==h,n
    qualifier=load('system_factor_actual_wire_admission',ROOT/'factor_admission.py')
    factor_controls=qualifier.verify(ROOT,live=True)
    protected=load('internal_declaration_pinned_source_protection',ROOT/'protected_sources.py').check(groups)
    proof=load('internal_declaration_pinned_factor_proof',ROOT/'factor_proof.py').verify(ROOT)
    os.environ.update(capture['compiler_env'])
    model=seed['model'];assert isinstance(model,str) and model
    os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=model,LLM_BASE_URL='http://127.0.0.1:8000/v1')
    pilot=load('internal_declaration_pinned_stage_environment',ROOT/'pilot.py')
    env=pilot.validate_environment()
    assert env['tools']==capture['compiler_tools'] and env['compiler_env']==capture['compiler_env'] and env['udev_files']==capture['udev_files']
    guard=load('internal_declaration_pinned_guard_readonly',ROOT/'guard_wrapper.py')
    kit=Path(seed['kit']);assert guard.identity(capture['model_identity']['pid'])==capture['model_identity']
    assert guard.protected(kit)==capture['protected']
    inputs=read(ROOT/'INPUT_MANIFEST.json');assert inputs==read(ROOT/'upstream/INPUT_MANIFEST.json')
    for n,h in inputs['input_sha256'].items():assert sha(kit/'bench/tasks_veval'/n)==h,n
    for n,h in inputs['official_sha256'].items():assert sha(kit/'official_reference'/n)==h,n
    assert capture['protected']['tasks']==inputs['input_sha256'] and capture['protected']['official']==inputs['official_sha256']
    inv=inventory(groups,read(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'))
    selected=load('internal_declaration_pinned_scope',ROOT/'preparation_inputs.py').validate_kit(ROOT,kit)
    assert selected['expected_samples']==30 and len(selected['task_ids'])==15 and len(selected['guard_tasks'])==8
    assert selected['declaration_factor_tasks']==selected['task_ids'] and selected['abstention_tasks']==[]
    for n,j in [('ACTUAL_FACTOR_CONTROL_PROOF.json',factor_controls),('SOURCE_FACTOR_PROOF.json',proof),('PROTECTED_INVENTORY_SUMMARY.json',inv)]:save(ROOT/n,j)
    spec=dict(schema='internal_declaration_fixed15_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit=seed['base_commit'],
        kit=str(kit),model=model,model_pid=capture['model_identity']['pid'],model_identity=capture['model_identity'],
        dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=deps,
        compiler_tools=env['tools'],compiler_env=env['compiler_env'],udev_files=env['udev_files'],protected=capture['protected'],
        solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,max_worker_requests_per_arm=2,retries=0,
        model_output_token_budget=8192,repairs=1,python_major_minor=[3,12],**selected,arms=['C','P'],samples_per_arm_per_task=1,
        max_actual_model_requests=60,expected_protection_receipts=61,stage_timeout_s=43200,guard_timeout_s=43600,slot_minutes=740,
        minimum_disk_free_bytes=seed['minimum_disk_free_bytes'],first_generation_replayed=False,
        original_phase_baseline_spec_sha256='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1',
        source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),
        protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),
        protected_inventory_summary_sha256=sha(ROOT/'PROTECTED_INVENTORY_SUMMARY.json'),protected_group_count=len(groups['groups']),
        protected_source_assets=groups['source_assets'],protected_unique_files=inv['protected_unique_files'],same_sha_duplicate_records=inv['same_sha_duplicate_records'],
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        qualification='Actual declaration full-worker4/18 source-bound controls plus finite native121 reused; new scoring integration bound separately. No old A/literal controls or scores reused.',
        acceptance='30 original judge rows; historical113 intersection8 P L3; paired grades nondecreasing; strict L3 net>=1 and weighted P>C; total, unchanged-grade and historical-correct requests P<=C; no deadline/unconfirmed/source/tool failure; independent complete archive audit required before new full156.',
        limits=['Fixed15 development screen; no full156 score or >=120/.80 goal claim, hidden/independent/five/adoption/deployment qualification.',
            'C original common phase-P; P only guarded internal declaration callback after ANSI abstention; all first/repair raw wire rules unchanged;8192/max2/repair1/fullsolver300/judge300/supervisor360 including original x-z unchanged.',
            'No previous factor score sum, no new onehot/table/timer factor, no task identifier/history/reference/TB or cached answer in production transformer.',
            'Historical113 restore and outside historical113 new L3 reported separately; all-task request cost disclosed without adding a stricter acceptance gate.',
            'Old literal6+156/wire4/pipeline7 and wave/native controls are not rerun. Existing actual pipeline4/18 and finite native121 reused, new scoring integration only; no all-repair token-capacity loop.',
            'Stage43200/guard43600/slot740min remain safety ceilings, not ETA; whole-task FIFO after every currently active or earlier queued task; no stale takeover.'])
    assert type(spec['minimum_disk_free_bytes']) is int and spec['minimum_disk_free_bytes']>0
    names=set(source['runtime_sources'])|set(seed['additional_input_hashes'])|{'SOURCE_MANIFEST.json','ACTUAL_FACTOR_CONTROL_PROOF.json','SOURCE_FACTOR_PROOF.json','PROTECTED_INVENTORY_SUMMARY.json'}
    spec['source_hashes']={n:sha(ROOT/n) for n in sorted(names)}
    save(ROOT/'RUN_SPEC.json',spec)
    assert pilot.frozen(kit)==spec and protected==load('internal_declaration_final_protection',ROOT/'protected_sources.py').check(groups)
    receipt=dict(schema='internal_declaration_actual_preparation_receipt_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),
        outputs=30,max_requests=60,history_guard_subset=8,target_tasks=7,declaration_factor_task_count=15,protection_receipts=61,
        protected_record_count=groups['source_assets'],protected_unique_files=inv['protected_unique_files'],same_sha_duplicate_records=inv['same_sha_duplicate_records'],
        old_literal_controls_reused=False,actual_declaration_controls_reused=True,new_scoring_integration_bound=True,extract_scan_rerun=False,new_tests_in_preparation=0,model_calls=0,eda_calls=0,new_fifo=False,new_score=False)
    save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt));return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--inputs',required=True,type=Path);a=p.parse_args();main(a.inputs)
