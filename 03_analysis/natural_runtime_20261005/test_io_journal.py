"""Invented grant/native callback fixtures only; never invoke native/model IO."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import runtime as r

ROOT = Path(__file__).resolve().parent


class JournalChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'raw_evidence')
        self.root = Path(self.temp.name)
        self.grant = dict(run_root=str(self.root), spec_sha256='a' * 64,
                          http_attempts=0, native_attempts=0)
        r._GRANTS[id(self.grant)] = dict(http=0, native=0)

    def tearDown(self):
        r._GRANTS.pop(id(self.grant), None)
        for key, value in list(r._ACTIVE_IO.items()):
            if value['grant'] is self.grant:
                r._ACTIVE_IO.pop(key)
        self.temp.cleanup()

    def test_attempts_persist_before_count_and_cap_unknown_results(self):
        for number in range(1, 3):
            path, receipt = r._begin_io(self.grant, 'http', 'chat_completions')
            self.assertEqual(r.read_json(path)['number'], number)
            self.assertFalse(receipt['finalized'])
            r._finish_io(path, receipt, confirmed=False, evidence_complete=False, error='invented timeout')
        with self.assertRaises(PermissionError):
            r._begin_io(self.grant, 'http', 'chat_completions')
        counts = r.io_accounting(self.grant)
        self.assertEqual((counts['http_attempts'], counts['http_confirmed'], counts['http_unconfirmed']), (2, 0, 2))

    def test_begin_save_failure_never_consumes_or_admits_effect(self):
        with mock.patch.object(r, 'save', side_effect=OSError('invented disk failure')):
            with self.assertRaises(OSError):
                r._begin_io(self.grant, 'http', 'chat_completions')
        self.assertEqual(self.grant['http_attempts'], 0)
        self.assertFalse(r._ACTIVE_IO)

    def test_missing_final_receipt_is_unconfirmed(self):
        r._begin_io(self.grant, 'native', 'feedback_vvp')
        counts = r.io_accounting(self.grant)
        self.assertEqual((counts['native_attempts'], counts['native_confirmed'], counts['native_unconfirmed']), (1, 0, 1))
        self.assertEqual(counts['native_test_attempts'], 1)
        self.assertEqual(counts['native_tests_confirmed'], 0)

    def test_boolean_counter_is_not_an_integer_admission(self):
        self.grant['http_attempts'] = False
        with self.assertRaises(ValueError):
            r.io_accounting(self.grant)

    def test_native_receipt_deadline_withdraws_confirmation(self):
        current = [0.0]
        real_save = r.save
        def slow_receipt(path, value):
            answer = real_save(path, value)
            if Path(path).name == 'NATIVE_RECEIPT.json': current[0] = 101.0
            return answer
        with (self.native_fixture('normal'), mock.patch.object(r.time, 'monotonic', side_effect=lambda: current[0]),
              mock.patch.object(r, 'save', side_effect=slow_receipt)):
            result = r._native_run(self.grant, {'candidate.sv': b'PURE_SYNTHETIC_NOT_RTL\n'},
                                   ['PURE_SYNTHETIC_NOT_EXECUTED'], 100, 'candidate_compile')
        self.assertEqual(result['outcome'], 'unconfirmed')
        receipt = r.read_json(self.root / 'actual_native_1_candidate_compile/NATIVE_RECEIPT.json')
        self.assertFalse(receipt['command_confirmed'])
        self.assertEqual(r.io_accounting(self.grant)['native_unconfirmed'], 1)

    def test_ledger_extra_misnamed_or_changed_spec_rejected(self):
        path, receipt = r._begin_io(self.grant, 'native', 'candidate_compile')
        original = path.read_bytes()
        for mutation in ('name', 'spec', 'bool_number'):
            with self.subTest(mutation=mutation):
                path.write_bytes(original)
                if mutation == 'name':
                    extra = path.with_name('misnamed.json')
                    extra.write_bytes(original)
                else:
                    changed = r.read_json(path)
                    changed['spec_sha256' if mutation == 'spec' else 'number'] = 'b' * 64 if mutation == 'spec' else True
                    path.write_bytes((json.dumps(changed) + '\n').encode())
                with self.assertRaises(ValueError):
                    r.io_accounting(self.grant)
                if mutation == 'name':
                    extra.unlink()

    def native_fixture(self, outcome):
        spec = dict(toolchain=dict(prefix='/PURE_SYNTHETIC_NO_TOOL', files={}), runtime_libraries={},
                    real_tools={name: dict(path='/PURE_SYNTHETIC_NO_TOOL/' + name, sha256='c' * 64)
                                for name in ('iverilog', 'vvp', 'bwrap', 'prlimit')},
                    limits=dict(native_as_bytes=1024, native_fsize_bytes=1024))

        def fake_command(argv, directory, log, timeout):
            self.assertTrue((self.root / 'io_attempts/native_1.json').is_file())
            self.assertTrue(r.read_json(self.root / 'io_attempts/native_1.json')['invocation_started'])
            self.assertIn('PURE_SYNTHETIC_NO_TOOL', ' '.join(argv))
            log.write_bytes(b'PURE SYNTHETIC LOG: no real compiler was executed\n')
            if outcome == 'raise':
                raise RuntimeError('invented cleanup exception')
            return dict(timeout=outcome == 'timeout', launch_error=None, remaining_live_group=[], returncode=0)

        return mock.patch.object(r, 'revalidate', return_value=(spec, types.SimpleNamespace(owned_command=fake_command)))

    def test_native_exception_seals_unknown_attempt(self):
        with self.native_fixture('raise'):
            with self.assertRaises(RuntimeError):
                r._native_run(self.grant, {'candidate.sv': b'PURE_SYNTHETIC_NOT_RTL\n'}, ['PURE_SYNTHETIC_NOT_EXECUTED'], 100, 'candidate_compile')
        receipt = r.read_json(self.root / 'actual_native_1_candidate_compile/NATIVE_RECEIPT.json')
        self.assertTrue(receipt['finalized'])
        self.assertFalse(receipt['command_confirmed'])
        self.assertIn('invented cleanup exception', receipt['error'])
        self.assertEqual(r.io_accounting(self.grant)['native_unconfirmed'], 1)

    def test_native_timeout_preserves_log_and_unknown_without_retry(self):
        with self.native_fixture('timeout'):
            result = r._native_run(self.grant, {'candidate.sv': b'PURE_SYNTHETIC_NOT_RTL\n'}, ['PURE_SYNTHETIC_NOT_EXECUTED'], 100, 'candidate_compile')
        self.assertEqual(result['outcome'], 'unconfirmed')
        self.assertEqual(self.grant['native_attempts'], 1)
        self.assertTrue((result['directory'] / 'native.log').is_file())
        self.assertEqual(r.io_accounting(self.grant)['native_unconfirmed'], 1)

    def test_native_receipt_save_failure_withdraws_confirmation(self):
        original = r.save
        def broken(path, value):
            if Path(path).name == 'NATIVE_RECEIPT.json':
                raise OSError('invented final write failure')
            return original(path, value)
        with self.native_fixture('known'), mock.patch.object(r, 'save', side_effect=broken):
            with self.assertRaises(OSError):
                r._native_run(self.grant, {'candidate.sv': b'PURE_SYNTHETIC_NOT_RTL\n'}, ['PURE_SYNTHETIC_NOT_EXECUTED'], 100, 'candidate_compile')
        self.assertEqual(r.io_accounting(self.grant)['native_confirmed'], 0)
        self.assertEqual(r.io_accounting(self.grant)['native_unconfirmed'], 1)

    def test_no_forged_real_helper_admission(self):
        with self.assertRaises(PermissionError):
            r.http_exchange({}, 'unused', 1, self.root / 'forged', r.socket.create_connection,
                            mode='REAL', attempt_path=self.root / 'invented.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
