"""Engineering checks only: fake IO and explicitly owned dummy Python children."""
from pathlib import Path
import ast
import hashlib
import io
import json
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    sources = sorted(path.name for path in ROOT.glob('*.py')) + ['INPUT_MANIFEST.json']
    for name in sources:
        if name.endswith('.py'):
            ast.parse((ROOT / name).read_bytes(), filename=name)
    before = {name: sha(ROOT / name) for name in sources}
    import test_runtime_protocol
    import test_worker
    import test_supervisor
    test_runtime_protocol.SUBCHECKS = 0
    test_worker.LINK_METHODS.clear()
    test_supervisor.CONTROL_ROWS.clear()
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern='test_*.py')
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    assert {name: sha(ROOT / name) for name in sources} == before
    receipt = dict(schema='natural_runtime_engineering_checks_v1', python=platform.python_version(),
                   platform=sys.platform, tests_run=result.testsRun, passed=result.wasSuccessful(),
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   skipped_controls=[test.id() for test, reason in result.skipped],
                   http_protocol_subchecks=test_runtime_protocol.SUBCHECKS,
                   physical_link_methods=test_worker.LINK_METHODS, source_hashes=before,
                   linux_owned_supervisor_controls_enabled=test_supervisor.LINUX_CONTROLS,
                   owned_python_process_controls=[row['control'] for row in test_supervisor.CONTROL_ROWS],
                   actual_model_calls=0, actual_eda_calls=0, actual_native_tests=0,
                   real_execution_admitted=False, full300s_timeout_verified=False,
                   production_guard_integration_verified=False, offline_target32GB_verified=False,
                   quality_verified=False, independent_models_completed=0, adoption=False)
    raw = ROOT / 'raw_evidence'
    raw.mkdir(exist_ok=True)
    (raw / 'ENGINEERING_TEST_LOG.txt').write_bytes(output.getvalue().encode())
    (raw / 'OWN_PROCESS_CONTROLS.json').write_bytes((json.dumps(test_supervisor.CONTROL_ROWS, ensure_ascii=False, indent=2) + '\n').encode())
    (raw / 'ENGINEERING_CHECKS.json').write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
    receipt['limits'] = [
        'HTTP sockets and native callbacks are synthetic; process controls use explicitly owned Python dummy children only.',
        'Complete-shaped prerequisite fixtures never establish actual qualification or runtime execution admission.',
        'The supervisor guard for opt-in Linux dummy tests is fabricated and differs from the production guard.',
        'This 272-second work allocation is a new integration factor and has not inherited earlier C/P quality.',
        'Client process termination never confirms server-side model cancellation.',
        'Actual OS/include isolation, original-harness projection and full156 terminal qualification remain unavailable.',
    ]
    (ROOT / 'ENGINEERING_CHECKS.json').write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps({key: receipt[key] for key in ['platform', 'python', 'tests_run', 'passed', 'failures', 'errors', 'skipped', 'http_protocol_subchecks', 'actual_model_calls', 'actual_eda_calls']}))
    if not result.wasSuccessful():
        print(output.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
