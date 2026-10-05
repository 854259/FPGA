"""Pure exact worker transformation proof from frozen phase-full source bytes."""
import hashlib,json
from pathlib import Path

EDITED={'COPY_RECEIPT.json','worker.py','pilot.py','audit.py','prepare.py','metrics.py',
        'test_metrics.py','test_full.py','test_fresh.py','test_edge_integration.py'}
REMOVED={'full_metrics.py'}
CHANGES=(
 ('import edge_contract\n','import edge_contract\nimport semantic_policy\n'),
 ('    root, out = ROOT, args.out.resolve()',"    assert args.arm in ('C', 'P')\n    root, out = ROOT, args.out.resolve()"),
 ("    runtime = load('map_'+args.arm+'_runtime', root/'package/agent'/\n                   ('runtime.py' if args.arm == 'A' else 'map_runtime.py'))",
  "    runtime = load('map_'+args.arm+'_runtime', root/'package/agent/map_runtime.py')\n    original_skills = semantic_policy.install(runtime, args.arm, root)"),
 ("candidate=args.arm == 'P')",'candidate=True)'),
 ('    finally:\n        urllib.request.urlopen, subprocess.run = original_open, original_run',
  '    finally:\n        runtime.skill_texts = original_skills\n        urllib.request.urlopen, subprocess.run = original_open, original_run'),
 ("choices=['A','C','P']","choices=['C','P']"),
)


def verify(root):
    root=Path(root);copy=json.loads((root/'COPY_RECEIPT.json').read_bytes())
    assert copy['source_spec_sha256']=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    hashes=copy['copied_source_hashes'];assert len(hashes)==44
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    oldspec=root/'raw_evidence/source_binding/upstream_RUN_SPEC.json'
    assert sha(oldspec)==copy['source_spec_sha256']
    assert hashes==json.loads(oldspec.read_bytes())['source_hashes']
    upstream=root/'raw_evidence/source_binding/upstream_worker.py';assert sha(upstream)==hashes['worker.py']
    expected=upstream.read_text(encoding='utf-8')
    for before,after in CHANGES:
        assert expected.count(before)==1;expected=expected.replace(before,after)
    assert (root/'worker.py').read_text(encoding='utf-8')==expected
    unchanged=sorted(set(hashes)-EDITED-REMOVED)
    for name in unchanged:assert sha(root/name)==hashes[name],name
    for name in REMOVED:assert not (root/name).exists()
    assert sha(root/'APPENDIX.txt')=='8728d9f3a6d32ee785082771d1c28a08d6c4dbfa59fc5daa55b93e191ddbba36'
    assert not (root/'elaboration_feedback.py').exists() and not (root/'guidance.py').exists()
    return dict(schema='semantic_edge_shared_worker_single_factor_proof_v1',common_control='phasefull original P policy',
                worker_sha256=sha(root/'worker.py'),upstream_worker_sha256=sha(upstream),upstream_spec_sha256=sha(oldspec),
                appendix_sha256=sha(root/'APPENDIX.txt'),unchanged_assets_sha256={name:hashes[name] for name in unchanged},
                only_arm_difference='skill_texts returns G+A,R for P; G,R for C; initial and repair systems both include A',
                transport_compile_budget_extract_runtime_skills_unchanged=True,real_execution_proved=False)
