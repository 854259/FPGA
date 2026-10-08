"""AMD-only isolated package preparation; no model, EDA or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('bridge', 'scored', 'source', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assert not args.out.exists()
    assert sha(args.bridge / 'RUN_SPEC.json') == 'b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'
    assert sha(args.scored / 'RUN_SPEC.json') == 'b499f6c16fa91868ca7ba60a168929204f02d5b0e164f5ade776a65983aa5c5d'
    parents = {}
    for root in (args.bridge, args.scored):
        spec = json.loads((root / 'RUN_SPEC.json').read_text())
        for name, digest in spec['source_hashes'].items():
            assert sha(root / name) == digest, name
        parents[str(root)] = sha(root / 'RUN_SPEC.json')
    for old, new in [('agent/core.py', 'package/agent/map_runtime.py'),
                     ('agent/probe_runner.py', 'dependencies/probe_runner.py'),
                     ('baseline.py', 'package/baseline.py'),
                     ('skill/rtl-generation/SKILL.md', 'package/skill/rtl-generation/SKILL.md'),
                     ('skill/rtl-feedback-repair/SKILL.md', 'package/skill/rtl-feedback-repair/SKILL.md')]:
        assert sha(args.bridge / 'package' / old) == sha(args.scored / new)
    package = args.out / 'package'
    package.mkdir(parents=True)
    bridge_spec = json.loads((args.bridge / 'RUN_SPEC.json').read_text())
    for name in bridge_spec['source_hashes']:
        if name.startswith('package/') and name != 'package/INTEGRITY.json':
            destination = args.out / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.bridge / name, destination)
    agent = package / 'agent'
    (agent / 'runtime.py').rename(agent / 'bridge_runtime.py')
    research = ['baseline_worker.py', 'table_feedback.py', 'contract.py', 'reserved_keywords.py',
                'prompt_map.py', 'point_feedback.py', 'priority_contract.py', 'shift_contract.py',
                'edge_dispatch.py', 'edge_contract.py', 'edge_feedback.py', 'phase_feedback.py', 'phase_context.py']
    for name in research:
        shutil.copyfile(args.scored / name, agent / name)
    shutil.copyfile(args.source / 'http_runtime.py', agent / 'runtime.py')
    shutil.copyfile(args.source / 'table_http_feedback.py', agent / 'table_http_feedback.py')
    files = {str(p.relative_to(package)): sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
    (package / 'INTEGRITY.json').write_text(json.dumps(dict(files=files), indent=2) + '\n')
    result = dict(prepared=True, parents=parents, files=files,
                  table_feedback_sha256=sha(agent / 'table_feedback.py'),
                  baseline_unchanged=True, core_unchanged=True, skills_unchanged=True,
                  real_model_calls=0, eda_calls=0, deployed=False,
                  note='Staged original132 single-feedback package; not a score or final selection.')
    (args.out / 'PREPARED.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(prepared=True, package_files=len(files), deployed=False)))
