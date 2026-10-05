"""Freeze original edge controls before guarded execution; zero model/EDA calls."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


if __name__ == '__main__':
    assert not (ROOT / 'RUN_SPEC.json').exists()
    private = json.loads((ROOT / 'raw_evidence/CONTROLS.json').read_bytes())
    bindings = json.loads((ROOT / 'raw_evidence/DEPENDENCY_BINDINGS.json').read_bytes())
    assert len(private['cases']) == 1
    case = private['cases'][0]
    assert case['control_order'] == ['positive', 'constant_zero', 'constant_one',
                                     'swapped_edges', 'widened_pulse', 'reset_ignored',
                                     'failure_propagation']
    assert len(case['controls']) == 7 and case['expected_pytest_tests'] == 1
    assert sha(ROOT / 'raw_evidence/ORIGINAL_DATASET.jsonl') == 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    sources = ['stage.py', 'tool_journal.py', 'collect.py', 'audit.py', 'prepare.py',
               'static_check.py', 'guard_wrapper.py', 'INPUT_MANIFEST.json',
               'raw_evidence/CONTROLS.json', 'raw_evidence/DEPENDENCY_BINDINGS.json',
               'raw_evidence/ORIGINAL_DATASET.jsonl']
    for name in sources:
        if name.endswith('.py'):
            source = (ROOT / name).read_bytes()
            ast.parse(source, filename=name)
            compile(source, name, 'exec')
    previous = json.loads((ROOT.parent / 'natural_harness_calibration_20261005/RUN_SPEC.json').read_bytes())
    spec = dict(
        schema='natural_edge_original_harness_frozen_v1',
        identity='natural_edge_calibration_20261005_v1',
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        cloud_root='/workspace/team/runs/fpga_owner/natural_edge_calibration_20261005_v1',
        kit=previous['kit'], dependencies_cloud=previous['dependencies_cloud'],
        dependency_hashes=previous['dependency_hashes'],
        source_hashes={name: sha(ROOT / name) for name in sources},
        dataset_sha256=sha(ROOT / 'raw_evidence/ORIGINAL_DATASET.jsonl'),
        record_ids=[case['record_id']], model_requests_max=0,
        native_test_name='test_sync_pos_neg_edge_detector',
        compiles_max=7, simulations_max=7, controls=7,
        stage_timeout_s=1200, guard_timeout_s=1300, slot_minutes=25,
        inherited_path='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
        slot_owner='codex_natural_edge_calibration_20261005_v1',
        slot_lock_path='/workspace/team/SLOT.lock',
        model_identity=dict(pid=2013333, starttime='823869819', exe='llama-server',
                            command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1'),
        llm_base_url='http://127.0.0.1:8000/v1', model_name='Qwen3.6-27B-Q4_K_M',
        toolchain=bindings['toolchain'], python_site=bindings['python_site'],
        real_tools={name: dict(path=bindings['toolchain']['prefix'] + '/bin/' + name,
                              sha256=bindings['toolchain']['files']['bin/' + name])
                    for name in ['iverilog', 'vvp']},
        acceptance='Complete seven fixed original-harness controls and raw native receipt audit. Positive must pass; every intended wrong control and sentinel must fail for this record to qualify. Retain any reset-ignored false acceptance and exclude original harness; no test/port/domain retuning. Calibration alone permits no independent model score or deployment.',
        policy=dict(original_prompts_context_harness_unchanged=True,
                    original_module_names=True, evaluation_controls_only=True,
                    LLM_calls=0, retries=0, whole_task_FIFO=True,
                    full156_qualification_unchanged=True,
                    independent_model_calls_blocked_until_full_qualification=True))
    save(ROOT / 'RUN_SPEC.json', spec)
    save(ROOT / 'PREPARATION_RECEIPT.json', dict(
        spec_sha256=sha(ROOT / 'RUN_SPEC.json'), assets=len(sources),
        static_parse_compile_passed=True, actual_eda_calls=0, actual_model_calls=0,
        planned_native_trials=7, actual_fifo_submitted=False))
    with zipfile.ZipFile(ROOT / 'raw_evidence/preparation.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ['RUN_SPEC.json', 'PREPARATION_RECEIPT.json']:
            archive.write(ROOT / name, name)
    save(ROOT / 'PREPARATION_ARCHIVE.json', dict(
        archive_sha256=sha(ROOT / 'raw_evidence/preparation.zip'),
        spec_sha256=sha(ROOT / 'RUN_SPEC.json'), assets=len(sources)))
    print(json.dumps(json.loads((ROOT / 'PREPARATION_ARCHIVE.json').read_bytes())))
