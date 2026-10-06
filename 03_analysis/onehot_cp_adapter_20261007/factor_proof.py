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
    binding=json.loads((root/"NATIVE_SOURCE_BINDING.json").read_bytes())
    assert sha(root/"NATIVE_QUALIFICATION_AUDIT.json")==binding['native_audit_sha256']=="a0e506f4799f311caf8ea78b23c8ed838f2954b5d5109015fee56ee921a9e980"
    native=json.loads((root/"NATIVE_QUALIFICATION_AUDIT.json").read_bytes())
    assert native['evidence_valid'] and native['native_qualified'] and native['source_sha256']=="6d0d61c65f49b68a33c825a9ae6ba8f6bb8bef2f2fad05f6f0495cd868866939"
    assert (native['controls'],native['positive_cases'],native['negative_mutants'],native['native_commands'],native['guard_receipts'],native['observations'],native['model_calls'])==(8,6,2,24,49,14144,0)
    assert not native['full_score_measured'] and not native['goal_qualified'] and not native['adoption']
    expected={'synthesis.py': 'fc1af52cd3d76faf9eed812167eb8179ab40b3c3d32740062e6d444459701007', 'reserved_keywords.py': '3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e'}
    assert binding['producer_source_hashes']==expected
    for n,h in expected.items():assert sha(root/n)==h
    assert (root/"reserved_keywords.py").read_bytes()==(upstream/"reserved_keywords.py").read_bytes()
    return dict(schema="prompt_onehot_graph_synthesis_single_factor_proof_v1",
        common_control="original phase_full156 P; candidate=True for C and P fallback",
        original_spec_sha256=ORIGINAL_SPEC_SHA,upstream_source_hashes=spec["source_hashes"],
        exact_runtime_copy_hashes={k:v for k,v in copy["copied_hashes"].items() if not k.startswith("upstream/")},
        baseline_worker_sha256=sha(root/"baseline_worker.py"),
        worker_sha256=sha(root/"worker.py"),contract_sha256=CONTRACT_SHA,
        synthesis_sha256=sha(root/"synthesis.py"),native_source_binding=binding,
        only_arm_difference="P can generate RTL from a fully consumed complete onehot graph with explicit multihot OR semantics; C and all abstentions use the common original phase-P worker",
        maximum_model_requests_per_sample=2,model_output_token_budget=8192,
        absolute_solver_deadline_s=300,
        mechanical_route_actual_model_requests=0,
        prompt_only_algorithm=True,new_execution_or_quality_proved=False)
