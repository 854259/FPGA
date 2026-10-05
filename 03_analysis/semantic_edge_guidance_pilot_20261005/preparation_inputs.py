"""Pure metadata validation; review/captures never become model messages."""
from pathlib import Path
import hashlib,json
import metrics,semantic_policy
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def validate_capture(capture,groups,inputs,old):
    assert capture['schema'].startswith('actual_') and groups['schema'].startswith('actual_')
    assert capture['model_calls']==capture['eda_calls']==groups['model_calls']==groups['eda_calls']==0
    assert not capture.get('policy_installed',False) and not capture.get('task_submitted',False)
    assert capture['protected']['tasks']==inputs['input_sha256'] and capture['protected']['official']==inputs['official_sha256']
    assert len(capture['protected']['package'])==18 and len(capture['protected']['tasks'])==936 and len(capture['protected']['official'])==35
    assert set(capture['compiler_tools'])=={'xvlog','xelab','xsim','vivado'}
    assert set(capture['model_identity'])=={'pid','starttime','exe','command_sha256'}
    assert capture['dependency_hashes']==old['dependency_hashes']
    assert groups['source_assets']==sum(len(g['source_hashes']) for g in groups['groups'].values())
    assert len(groups['groups'])>=11
    for prefix in ['multidriver_guidance_pilot_20261005_','bit_mapping_guidance_pilot_20261005','compile_diagnostic_priority_pilot_20261005']:
        assert any(k.startswith(prefix) for k in groups['groups']), 'Root must supply actual later installed groups: '+prefix
    assert all(set(['cloud_root','local_root','spec_name','spec_sha256','source_hashes'])<=set(g) for g in groups['groups'].values())
    return dict(protected_group_count=len(groups['groups']),protected_source_assets=groups['source_assets'])
def validate_motivation(root):
    root=Path(root);report=read(root/'raw_evidence/SEMANTIC_REVIEW.json');binding=read(root/'raw_evidence/SEMANTIC_REVIEW_BINDING.json')
    support=read(root/'raw_evidence/SEMANTIC_SUPPORT_BINDINGS.json');auth=read(root/'raw_evidence/SEMANTIC_AUTHENTICATION.json');inputs=read(root/'INPUT_MANIFEST.json')
    assert report['schema']=='latest_semantic_improvement_review_v1' and report['review_denominator']==39
    assert report['full_P_level_counts']=={'0':4,'1':39,'3':113} and len(report['classified_samples'])==39
    assert report['all_39_failures_retained'] and not report['oracle_body_semantics_read']
    assert report['new_model_calls']==report['new_eda_calls']==report['actual_new_score_measurements']==0
    for own,old in [('SEMANTIC_REVIEW.json','REVIEW.json'),('SEMANTIC_SUPPORT_BINDINGS.json','raw_evidence/ACTUAL_39_MEMBER_BINDINGS.json'),('SEMANTIC_AUTHENTICATION.json','raw_evidence/AUTHENTICATION.json')]:
        assert binding['files'][old]['sha256']==sha(root/'raw_evidence'/own)
    assert binding['files']['raw_evidence/PROPOSED_GENERIC_APPENDIX.txt']['sha256']==semantic_policy.APPENDIX_SHA==sha(root/'APPENDIX.txt')
    assert auth['inputs']['RUN_SPEC.json']['sha256']=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    proposal=report['highest_priority_new_factor'];assert proposal['name']=='pre_generation_clock_edge_and_state_contract_appendix'
    assert sorted(proposal['support_tasks'])==metrics.TARGETS and proposal['direct_prompt_semantic_support_count']==8
    assert proposal['appendix_sha256']==semantic_policy.APPENDIX_SHA
    assert proposal['proposed_generic_appendix'].encode('utf-8')==(root/'APPENDIX.txt').read_bytes()
    for task in metrics.TARGETS:
        assert support[task]['native_mismatch_receipt_confirmed'] is True
        assert support[task]['actual_member_bindings']['worker/prompt_only/prompt.txt']['sha256']==inputs['input_sha256'][task+'/prompt.txt']
        assert 'precise_prompt_support' in support[task] and 'precise_final_rtl_support' in support[task]
    return dict(schema='semantic_edge_motivation_metadata_binding_v1',semantic_review_sha256=sha(root/'raw_evidence/SEMANTIC_REVIEW.json'),
        semantic_review_binding_sha256=sha(root/'raw_evidence/SEMANTIC_REVIEW_BINDING.json'),semantic_support_sha256=sha(root/'raw_evidence/SEMANTIC_SUPPORT_BINDINGS.json'),
        semantic_authentication_sha256=sha(root/'raw_evidence/SEMANTIC_AUTHENTICATION.json'),targets=metrics.TARGETS,metadata_only=True,model_input=False,
        original_review_gate_is_proposal_only=True,actual_gate_authority='Root latest: >=3 target gains, guard P calls do not increase; no extra cross-family/equal-call gate.')
