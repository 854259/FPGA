"""Prepare private prompt-only controls, never freeze or submit a RUN_SPEC."""
import argparse
import ast
import json
import zipfile
from pathlib import Path

import controls as c

ROOT = Path(__file__).resolve().parent
ARCHIVE_SHA = 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
OLD_SPEC_SHA = '43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'


def prepare(root, archive):
    root, archive = Path(root), Path(archive)
    c.require(not (root / 'RUN_SPEC.json').exists() and not (root / 'raw_evidence/CONTROLS.json').exists(),
              'refuse frozen/existing preparation')
    c.require(c.sha(archive.read_bytes()) == ARCHIVE_SHA, 'exact completed full archive required')
    raw = root / 'raw_evidence'
    raw.mkdir(exist_ok=False)
    private = {'schema': 'prompt_table_private_25_controls_v1', 'model_calls': 0,
               'generated_research_test': True, 'original_harness': False,
               'archive_sha256': ARCHIVE_SHA, 'old_run_spec_sha256': OLD_SPEC_SHA,
               'prompt_sha256': {}, 'controls': []}
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))
        c.require(c.sha(z.read('run/RUN_SPEC.json')) == OLD_SPEC_SHA, 'old archive/spec binding')
        for task in c.TASKS:
            member = 'kit/bench/tasks_veval/' + task + '/prompt.txt'
            prompt = z.read(member)
            c.require(c.sha(prompt) == manifest['files'][member], 'prompt archive SHA binding')
            private['prompt_sha256'][task] = c.sha(prompt)
            prompt_path = 'raw_evidence/inputs/' + task + '/prompt.txt'
            path = root / prompt_path
            path.parent.mkdir(parents=True)
            path.write_bytes(prompt)
            for item in c.generate(prompt.decode(), task):
                item.update(task=task, index=len(private['controls']), prompt_path=prompt_path,
                            rtl_path='raw_evidence/controls/' + item['label'] + '/candidate.sv',
                            tb_path='raw_evidence/controls/' + item['label'] + '/tb.sv')
                folder = (root / item['rtl_path']).parent
                folder.mkdir(parents=True)
                (root / item['rtl_path']).write_bytes(item['rtl'].encode())
                (root / item['tb_path']).write_bytes(item['tb'].encode())
                meta = {k: v for k, v in item.items() if k not in ('rtl', 'tb')}
                meta.update(rtl_sha256=c.sha(item['rtl'].encode()), tb_sha256=c.sha(item['tb'].encode()))
                private['controls'].append(meta)
        # Copy authenticated hash metadata only. No reference/official TB bodies are read.
        data = z.read('run/INPUT_MANIFEST.json')
        c.require(c.sha(data) == manifest['files']['run/INPUT_MANIFEST.json'], 'protected hash manifest binding')
        (root / 'INPUT_MANIFEST.json').write_bytes(data)
        protected_bytes = z.read('guard/resource_check.json')
        c.require(c.sha(protected_bytes) == manifest['files']['guard/resource_check.json'], 'old protected resource metadata binding')
        protected = json.loads(protected_bytes)['protected']
        inputs = json.loads(data)
        c.require(protected['tasks'] == inputs['input_sha256'] and protected['official'] == inputs['official_sha256'],
                  'historical protected snapshot disagrees with authenticated input metadata')
    c.save(raw / 'CONTROLS.json', private)
    project = root.parents[1]
    phase = project / '03_analysis/phase_full156_20261005'
    preflight = c.read(phase / 'LINUX_PREFLIGHT_RECEIPT.json')
    phase_spec = c.read(phase / 'RUN_SPEC.json')
    c.require(preflight['environment']['verified'] and preflight['model_calls'] == 0 and preflight['eda_calls'] == 0,
              'existing actual environment preflight required')
    bindings = {'schema': 'prompt_table_review_dependency_bindings_v1',
                'existing_environment_only_not_new_live_admission': True,
                'phase_spec_sha256': c.sha((phase / 'RUN_SPEC.json').read_bytes()),
                'phase_preflight_sha256': c.sha((phase / 'LINUX_PREFLIGHT_RECEIPT.json').read_bytes()),
                'environment': preflight['environment'], 'kit': phase_spec['kit'],
                'protected': protected,
                'dependencies_cloud': phase_spec['dependencies_cloud'],
                'dependency_hashes': phase_spec['dependency_hashes'],
                'reused_guard_sha256': c.sha((root / 'guard_wrapper.py').read_bytes()),
                'reused_collector_sha256': c.sha((root / 'collect_evidence.py').read_bytes()),
                'fresh_guard_and_compiler_library_manifest_required_before_freeze': True}
    c.save(raw / 'DEPENDENCY_BINDINGS.json', bindings)
    _, prepared = c.validate_assets(root)
    files = c.source_paths(private)
    for name in files:
        data = c.contained(root, name).read_bytes()
        if name.endswith('.py'):
            ast.parse(data, filename=name)
            compile(data, name, 'exec')
    receipt = {'schema': 'unfrozen_prompt_table_preparation_v1', 'source_hashes': {
        name: c.sha(c.contained(root, name).read_bytes()) for name in files},
        'prepared_controls': len(prepared), 'planned_xvlog': 25, 'planned_xelab': 25, 'planned_xsim': 25,
        'planned_actual_native_commands': 75, 'actual_native_commands': 0,
        'actual_model_calls': 0, 'actual_eda_calls': 0, 'actual_cloud_calls': 0, 'actual_FIFO_calls': 0,
        'RUN_SPEC_frozen': False, 'generated_research_test': True, 'original_harness': False,
        'score_gain_measured': False, 'qualified_for_independent_models': False}
    c.save(root / 'PREPARATION_RECEIPT.json', receipt)
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, default=ROOT.parents[1] / '03_analysis/functional_full156_20261005/raw_evidence/terminal_v1.zip')
    args = p.parse_args()
    receipt = prepare(ROOT, args.archive)
    print(json.dumps({k: v for k, v in receipt.items() if k != 'source_hashes'} | {'source_count': len(receipt['source_hashes'])}))
