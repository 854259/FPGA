"""Pure stopped-child ledger recovery controls, using invented local files only.

The files are not model/native receipts from actual execution. These tests call
only the read-only recovery helper and never admit, launch, retry or delete IO.
"""
from pathlib import Path
import hashlib
import json
import os
import socket
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import runtime

ROOT = Path(__file__).resolve().parent
SPEC_SHA = 'a' * 64
COUNTERS = ['http_attempts', 'http_confirmed', 'http_unconfirmed', 'http_invocations_started',
            'native_attempts', 'native_confirmed', 'native_unconfirmed', 'native_invocations_started',
            'native_test_attempts', 'native_tests_confirmed', 'possibly_started_invocations']
PHYSICAL_LINK_CONTROLS = []


def invented_receipt(kind='http', number=1, label=None, **changes):
    value = dict(schema='natural_io_attempt_v1', mode='REAL', kind=kind, number=number,
                 label=label or ('chat_completions' if kind == 'http' else 'candidate_compile'),
                 spec_sha256=SPEC_SHA, attempted=True, invocation_started=True,
                 confirmed=True, evidence_complete=True, finalized=True, error=None,
                 server_job_cancellation_confirmed=False)
    value.update(changes)
    return value


def snapshot(directory):
    """No link following; compare names/content across the read-only helper."""
    value = {}
    if not directory.exists():
        return value
    def visit(folder):
        for path in sorted(folder.iterdir()):
            relative = path.relative_to(directory).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                value[relative] = dict(kind='link', target=os.readlink(path))
            elif stat.S_ISDIR(mode):
                value[relative] = dict(kind='directory')
                visit(path)
            elif stat.S_ISREG(mode):
                data = path.read_bytes()
                value[relative] = dict(kind='file', sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            else:
                value[relative] = dict(kind='special', mode=mode)
    visit(directory)
    return value


class RecoveryControls(unittest.TestCase):
    def setUp(self):
        raw = ROOT / 'raw_evidence'
        raw.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='pure_recovery_', dir=raw)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'io_attempts'
        self.addCleanup(self.temp.cleanup)
        # Any accidental invocation is an error, even if recovery catches it.
        self.forbidden = []
        def forbid(*args, **kwargs):
            self.forbidden.append((args, kwargs))
            raise AssertionError('read-only recovery must never perform network or process IO')
        for owner, name in [(socket, 'socket'), (socket, 'create_connection'), (subprocess, 'Popen')]:
            patch = mock.patch.object(owner, name, side_effect=forbid)
            patch.start()
            self.addCleanup(patch.stop)

    def put(self, name, row=None, raw=None):
        self.folder.mkdir(exist_ok=True)
        path = self.folder / name
        if raw is None:
            raw = (json.dumps(invented_receipt() if row is None else row, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        path.write_bytes(raw)
        return path

    def recover(self):
        before = snapshot(self.root)
        grants_before = set(runtime._GRANTS)
        active_before = set(runtime._ACTIVE_IO)
        result = runtime.recover_io_accounting(self.root, SPEC_SHA)
        self.assertEqual(snapshot(self.root), before, 'recovery must preserve every residue byte and name')
        self.assertEqual(set(runtime._GRANTS), grants_before, 'read-only recovery must never issue a grant')
        self.assertEqual(set(runtime._ACTIVE_IO), active_before, 'recovery must never reactivate an attempt')
        self.assertEqual(self.forbidden, [], 'recovery must never try network/process fallback')
        self.assertIs(type(result['evidence_complete']), bool)
        self.assertIsInstance(result['recovery_errors'], list)
        self.assertIsInstance(result['residual_files'], list)
        for key in COUNTERS:
            self.assertIs(type(result[key]), int)
            self.assertGreaterEqual(result[key], 0)
        self.assertEqual(result['http_attempts'], result['http_confirmed'] + result['http_unconfirmed'])
        self.assertEqual(result['native_attempts'], result['native_confirmed'] + result['native_unconfirmed'])
        self.assertLessEqual(result['native_tests_confirmed'], result['native_test_attempts'])
        entries = {row['name']: row for row in result['residual_files']}
        self.assertEqual(len(entries), len(result['residual_files']), 'residual file names must be unique')
        expected_names = {path.name for path in self.folder.iterdir()} if self.folder.is_dir() else set()
        self.assertEqual(set(entries), expected_names)
        for name, entry in entries.items():
            item = before['io_attempts/' + name]
            self.assertIs(type(entry['parse_valid']), bool)
            self.assertEqual(entry['pending'], name.endswith('.pending'))
            if item['kind'] == 'file':
                self.assertEqual(entry['sha256'], item['sha256'])
                self.assertEqual(entry['bytes'], item['bytes'])
            else:
                self.assertIsNotNone(entry.get('error'))
        return result, entries

    def invalid(self, expected_http=None, expected_native=None):
        result, entries = self.recover()
        self.assertIs(result['evidence_complete'], False)
        self.assertTrue(result['recovery_errors'])
        if expected_http is not None:
            self.assertEqual(result['http_attempts'], expected_http)
        if expected_native is not None:
            self.assertEqual(result['native_attempts'], expected_native)
        return result, entries

    def test_missing_ledger_has_complete_zero_counts_without_creation(self):
        result, _ = self.recover()
        self.assertIs(result['evidence_complete'], True)
        self.assertEqual(result['recovery_errors'], [])
        self.assertEqual(result['residual_files'], [])
        self.assertFalse(self.folder.exists())
        self.assertEqual({key: result[key] for key in COUNTERS}, {key: 0 for key in COUNTERS})

    def test_empty_existing_ledger_has_zero_counts(self):
        self.folder.mkdir()
        result, _ = self.recover()
        self.assertIs(result['evidence_complete'], True)
        self.assertEqual(result['recovery_errors'], [])
        self.assertEqual({key: result[key] for key in COUNTERS}, {key: 0 for key in COUNTERS})

    def test_complete_formal_ledgers_count_http_native_and_native_tests(self):
        self.put('http_1.json', invented_receipt())
        self.put('http_2.json', invented_receipt(number=2, confirmed=False, error='synthetic model unfinished'))
        for number, label in enumerate(['candidate_compile', 'feedback_compile', 'feedback_vvp'], 1):
            self.put('native_' + str(number) + '.json', invented_receipt('native', number, label))
        result, entries = self.recover()
        self.assertIs(result['evidence_complete'], True, 'complete accounting does not mean every attempt is confirmed')
        self.assertEqual((result['http_attempts'], result['http_confirmed'], result['http_unconfirmed']), (2, 1, 1))
        self.assertEqual((result['native_attempts'], result['native_confirmed'], result['native_unconfirmed']), (3, 3, 0))
        self.assertEqual((result['http_invocations_started'], result['native_invocations_started']), (2, 3))
        self.assertEqual((result['native_test_attempts'], result['native_tests_confirmed']), (1, 1))
        self.assertEqual(result['possibly_started_invocations'], 0)
        self.assertTrue(all(row['parse_valid'] for row in entries.values()))

    def test_formal_confirmed_plus_pending_update_is_one_unconfirmed_http(self):
        self.put('http_1.json', invented_receipt())
        self.put('http_1.json.pending', invented_receipt(error='interrupted update', confirmed=False))
        result, entries = self.invalid(expected_http=1, expected_native=0)
        self.assertEqual((result['http_confirmed'], result['http_unconfirmed'], result['http_invocations_started']), (0, 1, 1))
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(row['parse_valid'] for row in entries.values()))

    def test_two_confirmed_forms_with_pending_still_withdraw_confirmation(self):
        self.put('native_1.json', invented_receipt('native', 1, 'feedback_vvp'))
        self.put('native_1.json.pending', invented_receipt('native', 1, 'feedback_vvp'))
        result, _ = self.invalid(expected_native=1)
        self.assertEqual((result['native_confirmed'], result['native_unconfirmed']), (0, 1))
        self.assertEqual((result['native_test_attempts'], result['native_tests_confirmed']), (1, 0))

    def test_pending_only_valid_receipt_is_attempted_but_never_confirmed(self):
        self.put('native_1.json.pending', invented_receipt('native', 1, 'feedback_vvp'))
        result, entries = self.invalid(expected_http=0, expected_native=1)
        self.assertEqual((result['native_confirmed'], result['native_unconfirmed'], result['native_invocations_started']), (0, 1, 1))
        self.assertEqual((result['native_test_attempts'], result['native_tests_confirmed']), (1, 0))
        self.assertIs(entries['native_1.json.pending']['parse_valid'], True)

    def test_pending_only_partial_json_preserves_hash_and_unknown_invocation(self):
        self.put('http_1.json.pending', raw=b'{"schema":"natural_io_attempt_v1","kind":"http","number":1,')
        result, entries = self.invalid(expected_http=1)
        self.assertEqual((result['http_confirmed'], result['http_unconfirmed'], result['http_invocations_started']), (0, 1, 0))
        self.assertEqual(result['possibly_started_invocations'], 1)
        self.assertIs(entries['http_1.json.pending']['parse_valid'], False)
        self.assertIsNotNone(entries['http_1.json.pending'].get('error'))

    def test_partial_formal_json_retains_one_unconfirmed_attempt(self):
        self.put('native_1.json', raw=b'{"schema":')
        result, entries = self.invalid(expected_native=1)
        self.assertEqual((result['native_confirmed'], result['native_unconfirmed']), (0, 1))
        self.assertEqual(result['possibly_started_invocations'], 1)
        self.assertIs(entries['native_1.json']['parse_valid'], False)

    def test_valid_formal_plus_partial_pending_preserves_old_known_invocation(self):
        self.put('http_1.json', invented_receipt())
        self.put('http_1.json.pending', raw=b'{"confirmed":f')
        result, _ = self.invalid(expected_http=1)
        self.assertEqual((result['http_confirmed'], result['http_unconfirmed'], result['http_invocations_started']), (0, 1, 1))
        self.assertEqual(result['possibly_started_invocations'], 0, 'an existing bound row already records the known invocation')

    def test_unknown_file_and_unknown_pending_are_retained_with_errors(self):
        self.put('http_1.json', invented_receipt())
        self.put('unknown_member.json', raw=b'SYNTHETIC UNKNOWN MEMBER\n')
        self.put('native_1.json.pending.pending', invented_receipt('native'))
        result, entries = self.invalid(expected_http=1, expected_native=0)
        self.assertIs(entries['unknown_member.json']['parse_valid'], False)
        self.assertIs(entries['native_1.json.pending.pending']['parse_valid'], False)
        self.assertEqual(len(entries), 3)
        self.assertEqual(result['native_test_attempts'], 0)

    def test_mismatched_spec_is_unconfirmed_and_unknown_not_trusted(self):
        self.put('http_1.json', invented_receipt(spec_sha256='b' * 64))
        result, entries = self.invalid(expected_http=1)
        self.assertEqual((result['http_confirmed'], result['http_unconfirmed'], result['http_invocations_started']), (0, 1, 0))
        self.assertEqual(result['possibly_started_invocations'], 1)
        self.assertIs(entries['http_1.json']['parse_valid'], False)

    def test_unknown_operation_label_is_unconfirmed(self):
        self.put('native_1.json', invented_receipt('native', label='unknown_operation'))
        result, entries = self.invalid(expected_native=1)
        self.assertEqual((result['native_confirmed'], result['native_unconfirmed']), (0, 1))
        self.assertEqual((result['native_test_attempts'], result['native_tests_confirmed']), (0, 0))
        self.assertIs(entries['native_1.json']['parse_valid'], False)

    def test_name_kind_number_schema_mode_and_attempted_bindings_rejected(self):
        changes = [dict(kind='native'), dict(number=True), dict(number=2), dict(schema='wrong'),
                   dict(mode='FAKE'), dict(attempted=False)]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                # Isolate each invented single ledger, while retaining its bytes.
                old_root, old_folder = self.root, self.folder
                self.root = old_root / ('binding_' + str(index))
                self.root.mkdir()
                self.folder = self.root / 'io_attempts'
                self.put('http_1.json', invented_receipt(**change))
                result, entries = self.invalid(expected_http=1)
                self.assertEqual(result['http_confirmed'], 0)
                self.assertEqual(result['possibly_started_invocations'], 1)
                self.assertIs(entries['http_1.json']['parse_valid'], False)
                self.root, self.folder = old_root, old_folder

    def test_duplicate_keys_nonfinite_nonobject_and_utf8_error_retained(self):
        samples = [b'{"schema":"natural_io_attempt_v1","schema":"natural_io_attempt_v1"}',
                   b'{"number":NaN}', b'{"number":Infinity}', b'[]', b'null', b'\xff']
        old_root, old_folder = self.root, self.folder
        for index, raw in enumerate(samples):
            with self.subTest(raw=raw):
                self.root = old_root / ('bad_json_' + str(index))
                self.root.mkdir()
                self.folder = self.root / 'io_attempts'
                self.put('native_1.json', raw=raw)
                result, entries = self.invalid(expected_native=1)
                self.assertEqual(result['native_confirmed'], 0)
                self.assertEqual(result['possibly_started_invocations'], 1)
                self.assertIs(entries['native_1.json']['parse_valid'], False)
        self.root, self.folder = old_root, old_folder

    def test_invalid_number_names_are_unknown_members_without_claimed_attempts(self):
        for name in ['http_0.json', 'http_01.json', 'native_-1.json', 'HTTP_1.json']:
            self.put(name, invented_receipt())
        result, entries = self.invalid(expected_http=0, expected_native=0)
        self.assertEqual(result['possibly_started_invocations'], 0)
        self.assertTrue(all(row['parse_valid'] is False for row in entries.values()))

    def test_sequence_gap_retains_observed_members_and_blocks_complete_accounting(self):
        self.put('http_2.json', invented_receipt(number=2, confirmed=False))
        result, _ = self.invalid(expected_http=1)
        self.assertEqual(result['http_unconfirmed'], 1)
        self.assertTrue(any('sequence' in error or 'cap' in error for error in result['recovery_errors']))

    def test_caps_do_not_hide_extra_observed_attempts(self):
        for number in range(1, 4):
            self.put('http_' + str(number) + '.json', invented_receipt(number=number, confirmed=False))
        for number in range(1, 8):
            self.put('native_' + str(number) + '.json', invented_receipt('native', number, confirmed=False))
        result, entries = self.invalid(expected_http=3, expected_native=7)
        self.assertEqual(len(entries), 10)
        self.assertEqual((result['http_unconfirmed'], result['native_unconfirmed']), (3, 7))
        self.assertTrue(any('http:' in error for error in result['recovery_errors']))
        self.assertTrue(any('native:' in error for error in result['recovery_errors']))

    def test_pending_and_formal_are_grouped_per_kind_number_not_by_contents(self):
        self.put('http_1.json', invented_receipt())
        self.put('http_1.json.pending', invented_receipt(kind='native', label='feedback_vvp'))
        result, entries = self.invalid(expected_http=1, expected_native=0)
        self.assertEqual((result['http_confirmed'], result['http_unconfirmed']), (0, 1))
        self.assertEqual(result['native_test_attempts'], 0)
        self.assertIs(entries['http_1.json.pending']['parse_valid'], False)

    def test_unfinalized_or_false_flags_never_confirm_despite_complete_read(self):
        controls = [dict(finalized=False), dict(evidence_complete=False), dict(confirmed=False),
                    dict(confirmed=1), dict(evidence_complete=1), dict(finalized=1), dict(error='synthetic failure')]
        old_root, old_folder = self.root, self.folder
        for index, change in enumerate(controls):
            with self.subTest(change=change):
                self.root = old_root / ('flags_' + str(index))
                self.root.mkdir()
                self.folder = self.root / 'io_attempts'
                self.put('http_1.json', invented_receipt(**change))
                result, _ = self.recover()
                self.assertIs(result['evidence_complete'], True)
                self.assertEqual((result['http_confirmed'], result['http_unconfirmed']), (0, 1))
        self.root, self.folder = old_root, old_folder

    def test_directory_member_preserved_as_error_without_json_or_hash_claim(self):
        self.folder.mkdir()
        nested = self.folder / 'native_1.json'
        nested.mkdir()
        (nested / 'PRIVATE_SYNTHETIC_RESIDUE.bin').write_bytes(b'own synthetic nested bytes\n')
        result, entries = self.invalid(expected_native=1)
        self.assertIs(entries['native_1.json']['parse_valid'], False)
        self.assertNotIn('sha256', entries['native_1.json'])
        self.assertNotIn('bytes', entries['native_1.json'])
        self.assertEqual(result['possibly_started_invocations'], 1)
        self.assertEqual(result['native_unconfirmed'], 1)

    def test_link_member_is_rejected_without_following_or_modifying_target(self):
        self.folder.mkdir()
        target = self.root / 'OWN_SYNTHETIC_LINK_TARGET.json'
        target.write_bytes((json.dumps(invented_receipt()) + '\n').encode())
        link = self.folder / 'http_1.json'
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('own physical symlink unavailable: ' + type(exc).__name__)
        PHYSICAL_LINK_CONTROLS.append('own_file_symlink_' + sys_platform())
        target_before = target.read_bytes()
        original = Path.read_bytes
        follows = []
        def forbid_link_read(path):
            if path == link:
                follows.append(str(path))
                raise AssertionError('recovery must not follow rejected link member')
            return original(path)
        with mock.patch.object(Path, 'read_bytes', forbid_link_read):
            result, entries = self.invalid(expected_http=1)
        self.assertEqual(follows, [])
        self.assertEqual(target.read_bytes(), target_before)
        self.assertIs(entries['http_1.json']['parse_valid'], False)
        self.assertNotIn('sha256', entries['http_1.json'])
        self.assertEqual(result['http_unconfirmed'], 1)
        self.assertEqual(result['possibly_started_invocations'], 1)


def sys_platform():
    import sys
    return sys.platform


if __name__ == '__main__':
    unittest.main(verbosity=2)
