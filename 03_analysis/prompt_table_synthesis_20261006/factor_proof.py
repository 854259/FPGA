"""Read-only byte binding to the approved phase-P generation path."""
from pathlib import Path
import hashlib,json

ORIGINAL_SPEC_SHA = "3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1"
CONTRACT_SHA = "46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206"
SYNTHESIS_SHA = "a18ac21891dc229b3252df9ac3122517874a08bb8d269e5763d9146eae1279e5"
COMMON_EDIT = ("candidate=args.arm == 'P')", "candidate=True)")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(root):
    root=Path(root)
    upstream=root/"upstream"
    assert sha(upstream/"RUN_SPEC.json")==ORIGINAL_SPEC_SHA
    spec=json.loads((upstream/"RUN_SPEC.json").read_bytes())
    assert len(spec["source_hashes"])==44
    for name,digest in spec["source_hashes"].items():
        assert sha(upstream/name)==digest,name
    copy=json.loads((root/"COPY_PHASE_BASE.json").read_bytes())
    assert copy["original_spec_sha256"]==ORIGINAL_SPEC_SHA
    assert copy["original_assets"]==copy["exact_archival_copies"]==44
    for name,digest in copy["copied_hashes"].items():
        assert sha(root/name)==digest,name
    old=(upstream/"worker.py").read_bytes()
    before,after=(v.encode() for v in COMMON_EDIT)
    assert old.count(before)==1
    assert (root/"baseline_worker.py").read_bytes()==old.replace(before,after)
    assert sha(root/"contract.py")==CONTRACT_SHA
    assert sha(root/"synthesis.py")==SYNTHESIS_SHA
    assert (root/"reserved_keywords.py").read_bytes()==(upstream/"reserved_keywords.py").read_bytes()
    return dict(schema="prompt_table_synthesis_single_factor_proof_v1",
        common_control="original phase_full156 P; candidate=True for C and P fallback",
        original_spec_sha256=ORIGINAL_SPEC_SHA,upstream_source_hashes=spec["source_hashes"],
        exact_runtime_copy_hashes={k:v for k,v in copy["copied_hashes"].items() if not k.startswith("upstream/")},
        baseline_worker_sha256=sha(root/"baseline_worker.py"),
        worker_sha256=sha(root/"worker.py"),contract_sha256=CONTRACT_SHA,
        synthesis_sha256=SYNTHESIS_SHA,
        only_arm_difference="P can generate RTL from a fully consumed explicit combinational prompt table; C and all abstentions use the common original phase-P worker",
        maximum_model_requests_per_sample=2,model_output_token_budget=8192,
        absolute_solver_deadline_s=300,
        mechanical_route_actual_model_requests=0,
        prompt_only_algorithm=True,new_execution_or_quality_proved=False)
