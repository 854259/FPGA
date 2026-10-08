"""Original common phase-P plus the already-qualified optional declaration callback."""
import hashlib,json
from pathlib import Path
import core_source_proof
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(root):
 root=Path(root);base=core_source_proof.verify(root)
 production=['worker.py','baseline_worker.py','package/agent/map_runtime.py','internal_wire_hook.py','internal_wire_repair.py','agent_extract_boundary.py','wire_capture.py','request_proof.py','declaration_replay.py','core_source_proof.py','DECLARATION_SOURCE_DELTAS.json']
 assert sha(root/'internal_wire_repair.py')=='7f0a05aaa7cb89616c6936ee2b87067bd29ea7cde897b48abc0860aeb22c666a'
 return dict(schema='internal_declaration_original_phaseP_factor_proof_v1',base=base,production_source_hashes={n:sha(root/n) for n in production},
  only_arm_difference='P enables compiler-triggered guarded internal wire declaration callback after original ANSI abstention. C and all first/repair request rules unchanged.',
  original_reply_extraction_unchanged=True,original_judge_sha256=sha(root/'upstream/official_eval_guarded.py'),
  maximum_model_requests_per_sample=2,model_output_token_budget=8192,absolute_solver_deadline_s=300,new_score=False)
