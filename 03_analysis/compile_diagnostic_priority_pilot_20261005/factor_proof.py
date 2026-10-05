"""Pure byte/source proof: common latest phaseP plus one P stdout factor."""
from pathlib import Path
import hashlib,json

PRIORITY_SHA='9c820ad49aec9d2525093d1350ebf80c44b2671a5ea349f34faed5a5257d4edd'
CHANGES=(
 ('import edge_contract\n','import edge_contract\nimport diagnostic_policy\n'),
 ('    root, out = ROOT, args.out.resolve()',"    assert args.arm in ('C', 'P')\n    root, out = ROOT, args.out.resolve()"),
 ("    runtime = load('map_'+args.arm+'_runtime', root/'package/agent'/\n                   ('runtime.py' if args.arm == 'A' else 'map_runtime.py'))", "    runtime = load('map_'+args.arm+'_runtime', root/'package/agent/map_runtime.py')"),
 ("        return subprocess.CompletedProcess(argv, result['returncode'], log.read_text(errors='replace'))", "        stdout = diagnostic_policy.record(args.arm, result, log, evidence, save, sha)\n        return subprocess.CompletedProcess(argv, result['returncode'], stdout)"),
 ("candidate=args.arm == 'P'",'candidate=True'),
 ("choices=['A','C','P']","choices=['C','P']"))


def verify(root):
    root=Path(root);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    copied=json.loads((root/'COPY_RECEIPT.json').read_bytes())
    assert copied['phase_frozen_assets']==44
    assert copied['phase_spec_sha256']=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    upstream=root/'raw_evidence/source_binding/upstream_worker.py'
    assert sha(upstream)==copied['upstream_source_hashes']['worker.py']
    expected=upstream.read_text(encoding='utf-8')
    for before,after in CHANGES:
        assert expected.count(before)==1
        expected=expected.replace(before,after)
    assert (root/'worker.py').read_text(encoding='utf-8')==expected
    assert sha(root/'priority.py')==PRIORITY_SHA
    for name,digest in copied['copied_source_hashes'].items():assert sha(root/name)==digest,name
    assert not (root/'elaboration_feedback.py').exists() and not (root/'guidance.py').exists()
    return dict(schema='compile_diag_shared_phaseP_single_factor_proof_v1',
        upstream_worker_sha256=sha(upstream),worker_sha256=sha(root/'worker.py'),
        priority_sha256=PRIORITY_SHA,unchanged_assets=copied['copied_source_hashes'],
        same_worker_both_arms=True,common_control='latest phase_full156 P policy; no added candidate xelab',
        only_arm_policy='P failed normal nativecompile fullstdout priority; C full original stdout',
        transport_budget_extract_runtime_skills_unchanged=True,
        successful_ansi_patch_early_return_unchanged=True,real_execution_proved=False)
