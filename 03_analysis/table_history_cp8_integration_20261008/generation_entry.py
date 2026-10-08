"""Shared score7 stage/archive entry; binds the actual imported dependency graph."""
import hashlib, importlib, importlib.util, json, sys
from pathlib import Path

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
ROW_PROOF_FIELDS=('generation_route','selected_provider','parent_recipe_bound','parent_preserved_bound',
    'parent_abstention_bound','parent_route','parent_output_sha256','common_mechanical_strategy_bound',
    'module_source_objects_bound')


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def modules(run):
    run=Path(run).resolve()
    proof=load('cp8_score7_bound_generation_proof',run/'generation_binding.py')
    for name,value in proof.PINNED.items():assert sha(run/name)==value,name
    old=list(sys.path)
    try:
        sys.path[:0]=[str(run),str(run/'package'),str(run/'dependencies')]
        worker=importlib.import_module('worker')
        composition=worker.synthesis;baseline_worker=worker.baseline
        value=dict(composition=composition,selector=composition.selector,
            table_contract=composition.table_synthesis.contract,worker=worker,
            reserved_keywords=importlib.import_module('reserved_keywords'),
            replay=load('cp8_score7_exact_original_replay',run/'original_model_replay.py'),
            baseline_worker=baseline_worker,baseline=load('cp8_score7_exact_original_extract',run/'package/baseline.py'),
            runtime=load('cp8_score7_exact_original_runtime',run/'package/agent/map_runtime.py'),
            parser=baseline_worker.edge_dispatch,feedback=baseline_worker.phase_feedback,
            runner=load('cp8_score7_exact_original_runner',run/'dependencies/probe_runner.py'),
            providers=[('table',composition.table_synthesis),('onehot',composition.onehot_producer),('timer',composition.timer_producer),('serial_framing',composition.serial_framing_producer)])
        proof.bound_modules(run,value)
        return proof,value
    finally:sys.path[:]=old


def verify(work,run,source,arm,spec,deadline,cloudwork):
    run,work,source=Path(run),Path(work),Path(source)
    proof,m=modules(run)
    journal=read(work/'requests.json');route=read(work/'generation_route.json');recipe=read(work/'synthesis_receipt.json')
    selected=recipe['selected_provider'] if recipe['emitted'] else None
    row=dict(task=source.name,arm=arm,generation_route=route['route'],selected_provider=selected,
        actual_model_requests=len(journal),received_model_responses=sum(r['response_received'] for r in journal),
        solve_deadline_reached=deadline)
    helper=run/'dependencies/full156_postflight_audit.py'
    assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
    shared=load('cp8_score7_original_archive_helper',helper)
    probes=load('cp8_score7_original_probe_evidence',run/'probe_evidence.py')
    phase=load('cp8_score7_original_probe_phase',run/'phase_context.py');edge=load('cp8_score7_original_probe_edge',run/'edge_contract.py')
    def verify_probe(check,contract):
        return probes.verify(check,source.name,contract,m['parser'],m['feedback'],m['runner'],shared,run/'dependencies',phase,edge)
    evidence=proof.verify(work,run,source,arm,row,cloudwork,spec,m,verify_probe)
    binding={name:evidence[name] for name in ROW_PROOF_FIELDS}
    binding.update(stage_generation_binding_verified=True,route_receipt_sha256=sha(work/'generation_route.json'),
        synthesis_receipt_sha256=sha(work/'synthesis_receipt.json'),
        producer_contract_sha256=recipe['contract_sha256'] if recipe['emitted'] else None,
        emitted_solution_sha256=recipe['rtl_sha256'] if recipe['emitted'] else None)
    return dict(binding=binding,generation_proof=evidence,solution_sha256=sha(work/'solution.v'))
