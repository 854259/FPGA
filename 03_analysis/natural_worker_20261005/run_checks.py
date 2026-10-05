"""Run pure FAKE worker tests and record exact counts; never invoke model/EDA."""
from pathlib import Path
import ast
import hashlib
import io
import json
import platform
import unittest

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def main():
    sources = ['adapter.py', 'worker.py', 'test_worker.py', 'run_checks.py']
    for name in sources:
        code = (ROOT / name).read_bytes()
        ast.parse(code, filename=name)
        compile(code, name, 'exec')
    before = {name: sha(ROOT / name) for name in sources}
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern='test_worker.py')
    ids = list(flatten(suite))
    import test_worker
    test_worker.LINK_METHODS.clear()
    stream = io.StringIO()
    outcome = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert {name: sha(ROOT / name) for name in sources} == before
    assert outcome.testsRun == len(ids)
    receipt = dict(schema='natural_worker_fake_test_receipt_v1', python=platform.python_version(),
                   tests_run=outcome.testsRun, failures=len(outcome.failures), errors=len(outcome.errors),
                   skipped=len(outcome.skipped), passed=outcome.wasSuccessful(), test_ids=ids,
                   physical_link_controls=len(test_worker.LINK_METHODS), physical_link_methods=test_worker.LINK_METHODS,
                   output=stream.getvalue(), source_hashes=before,
                   real_model_calls=0, real_eda_calls=0, real_native_tests=0,
                   quality_verified=False, eligible_for_independent_models=False, adoption=False)
    raw = ROOT / 'raw_evidence'
    raw.mkdir(exist_ok=True)
    (raw / 'TEST_RECEIPT.json').write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
    public = {key: value for key, value in receipt.items() if key not in {'test_ids', 'output'}}
    public['limits'] = ['Synthetic fake callbacks test only transport, physical file boundaries, budgets and evidence retention.',
                        'C/P are prototype arm labels sharing the immutable adapter; ANSI early-return, frozen native runtime and functional feedback are not integrated.',
                        'No real HTTP/model/native compiler/runner/judge or process cancellation integration.',
                        'Physical symlink/junction tests execute only filesystem setup; no EDA command is invoked.',
                        'Argument canonical before/after snapshots detect object mutation on return/exception only; no proof of external transport/compiler fidelity, timeout kill or system isolation.',
                        'Include capability is simulated only; native safe isolation is unverified and must abstain before any real compile.',
                        'No natural solved count, solver score, original-harness calibration or training independence claim.']
    (ROOT / 'RESULTS.json').write_bytes((json.dumps(public, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps({key: public[key] for key in ['tests_run', 'failures', 'errors', 'skipped', 'passed', 'real_model_calls', 'real_eda_calls', 'quality_verified']}))
    if not outcome.wasSuccessful():
        print(stream.getvalue())
    return 0 if outcome.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
