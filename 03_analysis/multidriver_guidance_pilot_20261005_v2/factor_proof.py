"""Pure source proof of one shared worker with a P-only exact appendix policy."""
import hashlib
import json
from pathlib import Path

GUIDANCE_SHA = '4891253991f3a0b1f23755698d079ba7a161dc7ccaa9ee4fae400bcc87a23a7a'
EDITED = {'COPY_RECEIPT.json', 'worker.py', 'pilot.py', 'prepare.py', 'audit.py',
          'replay.py', 'metrics.py', 'test_fresh.py', 'test_stage.py', 'test_metrics.py', 'test_audit.py'}
CHANGES = (
 ('import elaboration_feedback\n',
  "import elaboration_feedback\nimport guidance\n\n\ndef candidate_diagnostic(arm, diagnostic):\n    assert arm in ('C', 'P')\n    return guidance.augment_diagnostics(diagnostic) if arm == 'P' else diagnostic\n"),
 ('    root, out = ROOT, args.out.resolve()',
  "    assert args.arm in ('C', 'P')\n    root, out = ROOT, args.out.resolve()"),
 ("    runtime = load('map_'+args.arm+'_runtime', root/'package/agent'/\n                   ('runtime.py' if args.arm == 'A' else 'map_runtime.py'))",
  "    runtime = load('map_'+args.arm+'_runtime', root/'package/agent/map_runtime.py')"),
 ("        # Both arms use the same already-tested phase feedback policy. Only P adds\n        # self-contained candidate elaboration before that semantic feedback.\n        if args.arm == 'P':\n            diagnostic = elaboration_feedback.check(\n                code, work / ('compile-' + str(attempt)), target, attempt,\n                paired.owned_command, runtime.vivado_tool('xelab'))\n            gate()\n            if diagnostic:\n                return diagnostic",
  "        # C/P share the old65 P elaboration and phase policy. The only arm\n        # policy difference is exact deterministic augmentation of real facts.\n        diagnostic = elaboration_feedback.check(\n            code, work / ('compile-' + str(attempt)), target, attempt,\n            paired.owned_command, runtime.vivado_tool('xelab'))\n        gate()\n        if diagnostic:\n            return candidate_diagnostic(args.arm, diagnostic)"),
 ("choices=['A','C','P']", "choices=['C','P']"),
)


def verify(root):
    """Read only: exact transformations, unchanged assets and guidance bytes."""
    root = Path(root)
    copied = json.loads((root/'COPY_RECEIPT.json').read_bytes())
    assert copied['source_spec_sha256'] == '87cb93c00f386f3f16ece9f0ec9a7f49b18fd260faac9c75e83d4db9d31038bf'
    hashes = copied['copied_source_hashes']; assert len(hashes) == 38
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    upstream = root/'raw_evidence/source_binding/upstream_worker.py'
    assert sha(upstream) == hashes['worker.py']
    expected = upstream.read_text(encoding='utf-8')
    for before, after in CHANGES:
        assert expected.count(before) == 1
        expected = expected.replace(before, after)
    assert (root/'worker.py').read_text(encoding='utf-8') == expected
    assert sha(root/'guidance.py') == GUIDANCE_SHA
    unchanged = sorted(set(hashes) - EDITED)
    for name in unchanged:
        assert sha(root/name) == hashes[name], name
    return {'schema': 'multidriver_shared_worker_single_factor_proof_v1',
            'upstream_worker_sha256': sha(upstream), 'worker_sha256': sha(root/'worker.py'),
            'guidance_sha256': GUIDANCE_SHA, 'unchanged_assets': unchanged,
            'unchanged_assets_sha256': {name:hashes[name] for name in unchanged},
            'same_worker_both_arms': True, 'common_control': 'old65 P xelab + phase policy',
            'only_arm_policy': 'P exact guidance.augment_diagnostics(native_diagnostic); C original native_diagnostic',
            'transport_compile_budget_extract_runtime_skills_unchanged': True,
            'successful_ansi_patch_early_return_unchanged': True,
            'real_execution_proved': False}
