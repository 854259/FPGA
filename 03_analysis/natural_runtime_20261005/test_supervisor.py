"""Own dummy/protocol controls, never actual model/EDA/ROCm admission.

Default tests include two actual own portable Python child processes.  Linux
identity/pipe/cleanup integration is opt-in via --linux-owned-controls; every
guard/resource document in that test is an explicit synthetic fixture.
"""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import supervisor as s

LINUX_CONTROLS = '--linux-owned-controls' in sys.argv
if LINUX_CONTROLS:
    sys.argv.remove('--linux-owned-controls')
CONTROL_ROWS = []


def record(pid, ppid=7, pgid=None, sid=None, start='100', state='R'):
    return dict(pid=pid, starttime=start, state=state, ppid=ppid,
                pgid=pid if pgid is None else pgid, sid=pid if sid is None else sid)


def token_fixture():
    parent, child = record(10, 8), record(20, 10)
    stable = {key: parent[key] for key in ['pid', 'starttime', 'ppid', 'pgid', 'sid']}
    snapshot = dict(root='/owned', spec_sha256='a', resource_sha256='b', status_sha256='c',
                    stage=stable, model_pid=99, slot_lock_sha256='d')
    token = dict(schema='owned_natural_solve_pipe_v1', guard=snapshot,
                 parent=stable, child=child, nonce='1' * 32,
                 authorization_path='/owned/raw_evidence/authorization.json', **s.deadlines(100.0))
    return token, snapshot, child, parent


class Controls(unittest.TestCase):
    def test_proc_name_parentheses_and_spaces(self):
        fields = ['R', '7', '20', '20', *['0'] * 15, '12345']
        text = '20 (a command ) with (spaces)) ' + ' '.join(fields)
        self.assertEqual(s.parse_stat(20, text), record(20, 7, start='12345'))
        with self.assertRaises(ValueError):
            s.parse_stat(20, '20 (x) R 7')

    def test_identity_ignores_schedule_but_rejects_reuse_session_and_dead(self):
        row = record(20)
        self.assertTrue(s.same_identity(dict(row, state='S'), row))
        for mutation in [dict(starttime='101'), dict(pid=21), dict(pgid=30), dict(sid=30), dict(state='Z')]:
            self.assertFalse(s.same_identity(dict(row, **mutation), row))
        self.assertTrue(s.same_identity(dict(row, state='Z'), row, live=False))

    def test_fixed_budget_has_24_cleanup_and_4_sealing_seconds(self):
        plan = s.deadlines(10.0)
        self.assertEqual(plan['work_deadline_monotonic'], 282.0)
        self.assertEqual(plan['cleanup_deadline_monotonic'], 306.0)
        self.assertEqual(plan['total_deadline_monotonic'], 310.0)
        for args in [(float('nan'), 300), (0, 301), (0, 299), (float('inf'), 300)]:
            with self.assertRaises(PermissionError):
                s.deadlines(*args)

    def test_parent_start_is_reused_without_new_budget(self):
        self.assertEqual(s.solve_start(None, 100.0), 100.0)
        self.assertEqual(s.solve_start(90.0, 100.0), 90.0)
        self.assertEqual(s.deadlines(s.solve_start(90.0, 100.0))['total_deadline_monotonic'], 390.0)
        for value in [True, False, '90', float('nan'), float('inf'), 100.001]:
            with self.assertRaises(PermissionError):
                s.solve_start(value, 100.0)
        for value in [-172.0, -173.0]:
            with self.assertRaises(TimeoutError):
                s.solve_start(value, 100.0)

    def test_child_actual_identity_and_direct_parent(self):
        token, snapshot, child, parent = token_fixture()
        self.assertEqual(s.validate_child_token(token, snapshot, child, dict(parent, state='S')),
                         s.deadlines(100.0))
        for key, value in [('pid', 21), ('ppid', 9), ('pgid', 10), ('sid', 10), ('starttime', '101')]:
            with self.assertRaises(PermissionError):
                s.validate_child_token(token, snapshot, dict(child, **{key: value}), parent)

    def test_boolean_and_tampered_handshake_cannot_admit(self):
        token, snapshot, child, parent = token_fixture()
        for value in [dict(admitted=True), dict(token, work_deadline_monotonic=399),
                      dict(token, nonce=''), dict(token, guard=dict(snapshot, resource_sha256='tampered'))]:
            with self.assertRaises((PermissionError, KeyError)):
                s.validate_child_token(value, snapshot, child, parent)
        with self.assertRaises(PermissionError):
            s.verify_child_admission(dict(real_io_admitted=True), ROOT)

    def test_admission_requires_inherited_fd(self):
        with patch.object(s, '_linux_requirements'), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PermissionError):
                s.child_admission(ROOT)

    def test_pipe_full_message_terminator(self):
        token, _, _, _ = token_fixture()
        encoded = s.canonical(token)
        with patch.object(s.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)), \
             patch.object(s.select, 'select', return_value=([17], [], [])), \
             patch.object(s.os, 'read', side_effect=[len(encoded).to_bytes(4, 'big'), encoded, b'']):
            self.assertEqual(s._pipe_read(17, time.monotonic() + 1), token)

    def test_pipe_rejects_nonpipe_truncated_extra_and_oversized(self):
        with patch.object(s.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFREG)):
            with self.assertRaises(PermissionError):
                s._pipe_read(17, time.monotonic() + 1)
        for blocks in [[b'\0\0\0\4xx', b''], [b'\0\0\0\2{}X'], [(32769).to_bytes(4, 'big')]]:
            with patch.object(s.os, 'fstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFIFO)), \
                 patch.object(s.select, 'select', return_value=([17], [], [])), \
                 patch.object(s.os, 'read', side_effect=blocks):
                with self.assertRaises(PermissionError):
                    s._pipe_read(17, time.monotonic() + 1)

    def test_path_ownership_and_relative_paths(self):
        self.assertEqual(s.owned_evidence(ROOT, ROOT / 'raw_evidence' / 'future'), ROOT / 'raw_evidence' / 'future')
        for root, path in [(ROOT, ROOT / 'outside'), (ROOT, Path('relative')), (Path('relative'), ROOT)]:
            with self.assertRaises(PermissionError):
                s.owned_evidence(root, path)

    def test_durable_receipt_replace_and_no_overwrite_new(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            first = s.durable_json(path, dict(attempted=True, confirmed=False), new=True)
            self.assertEqual(s.digest(path.read_bytes()), first)
            with self.assertRaises(FileExistsError):
                s.durable_json(path, {}, new=True)
            s.durable_json(path, dict(attempted=True, confirmed=True))
            self.assertEqual(s.read_json(path)[0], dict(attempted=True, confirmed=True))

    def _guard(self, status=None):
        lock_dir = tempfile.TemporaryDirectory()
        self.addCleanup(lock_dir.cleanup)
        lock = Path(lock_dir.name) / 'own.lock'
        lock.write_bytes(b'own_unit_control\nfixture\n')
        spec = dict(schema='natural_runtime_frozen_v1', cloud_root=str(ROOT),
                    execution_authorized_by_root=True, solve_timeout_s=300,
                    source_hashes={'supervisor.py': s.digest((ROOT / 'supervisor.py').read_bytes())},
                    slot_owner='own_unit_control', slot_lock_path=str(lock),
                    model_identity=dict(pid=99, starttime='10', exe='explicit_fixture', command_sha256='not_real'))
        resource = dict(slot_owner=spec['slot_owner'], slot_lock_path=str(lock),
                        slot_lock_sha256=s.digest(lock.read_bytes()), model_identity=spec['model_identity'])
        status = status or dict(complete=False, stage_pid=10)
        wrapper_mock = patch.object(s, 'wrapper_binding', return_value=dict(explicit_pure_wrapper_fixture=True))
        wrapper_mock.start(); self.addCleanup(wrapper_mock.stop)
        return spec, status, resource, lock

    def test_actual_guard_parent_command_binding_and_wrong_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'guard_wrapper.py'; source.write_bytes(b'# explicit pure wrapper fixture\n')
            spec = dict(source_hashes={'guard_wrapper.py': s.digest(source.read_bytes())})
            wrapper = record(8, 6)
            correct = [sys.executable, str(source), '--guard-out', str(root / 'guard')]
            for argv, valid in [(correct, True), ([sys.executable, 'another.py', '--guard-out', str(root / 'guard')], False),
                                ([sys.executable, str(source), '--guard-out', '/other'], False),
                                (correct + ['--guard-out', str(root / 'guard')], False)]:
                with patch.object(s, 'process_record', return_value=wrapper), \
                     patch.object(s, '_proc_command', return_value=b'\0'.join(x.encode() for x in argv) + b'\0'):
                    if valid:
                        value = s.wrapper_binding(root, spec, record(10, 8))
                        self.assertEqual(value['identity']['pid'], 8)
                        self.assertEqual(value['source_sha256'], spec['source_hashes']['guard_wrapper.py'])
                    else:
                        with self.assertRaises(PermissionError):
                            s.wrapper_binding(root, spec, record(10, 8))

    def test_guard_publication_race_and_stable_identity(self):
        spec, status, resource, _ = self._guard()
        outputs = [(spec, 'spec'), FileNotFoundError(), (status, 'status'), (resource, 'resource')]
        with patch.object(s, 'read_json', side_effect=outputs), \
             patch.object(s, 'process_record', return_value=record(10, 8, state='R')):
            first, _ = s.guard_snapshot(ROOT, 10, time.monotonic() + 1)
        with patch.object(s, 'read_json', side_effect=[(spec, 'spec'), (status, 'status'), (resource, 'resource')]), \
             patch.object(s, 'process_record', return_value=record(10, 8, state='S')):
            second, _ = s.guard_snapshot(ROOT, 10, time.monotonic() + 1)
        self.assertEqual(first, second)

    def test_guard_explicit_pending_stage_pid_waits_for_publication(self):
        for pending in [dict(complete=False, passed=False, phase='resource_guard'),
                        dict(complete=False, passed=False, phase='resource_guard', stage_pid=None)]:
            spec, published, resource, _ = self._guard()
            with patch.object(s, 'read_json', side_effect=[(spec, 'spec'), (pending, 'pending'),
                                                         (published, 'published'), (resource, 'resource')]), \
                 patch.object(s, 'process_record', return_value=record(10, 8)):
                bound, _ = s.guard_snapshot(ROOT, 10, time.monotonic() + 1)
            self.assertEqual(bound['status_sha256'], 'published')

    def test_pending_stage_pid_contradictions_fail_immediately(self):
        bad = [dict(complete=True, passed=False, phase='resource_guard'),
               dict(complete=False, passed=False, phase='resource_guard', error='failed'),
               dict(complete=False, passed=False, phase='resource_guard', stage_pid=11),
               dict(complete=False, passed=False, phase='resource_guard', stage_pid=True),
               dict(complete=False), dict(complete=False, passed=True, phase='resource_guard'),
               dict(complete=False, passed=False, phase='unknown')]
        for status in bad:
            spec, _, _, _ = self._guard(status)
            with patch.object(s, 'read_json', side_effect=[(spec, 'spec'), (status, 'pending')]), \
                 patch.object(s.subprocess, 'Popen') as launch, patch.object(s.time, 'sleep') as sleep:
                with self.assertRaises(PermissionError):
                    s.guard_snapshot(ROOT, 10, time.monotonic() + 1)
                launch.assert_not_called(); sleep.assert_not_called()

    def test_pending_stage_pid_cannot_exceed_solve_deadline(self):
        spec, _, _, _ = self._guard()
        def read(path):
            if Path(path).name == 'RUN_SPEC.json':
                return spec, 'spec'
            return dict(complete=False, passed=False, phase='resource_guard'), 'pending'
        with patch.object(s, 'read_json', side_effect=read):
            with self.assertRaises(TimeoutError):
                s.guard_snapshot(ROOT, 10, time.monotonic() + .05)

    def test_guard_contradictions_fail_without_child_start(self):
        for status in [dict(complete=True, stage_pid=10), dict(complete=False, stage_pid=11),
                       dict(complete=False, stage_pid=10, error='failed')]:
            spec, _, _, _ = self._guard(status)
            with patch.object(s, 'read_json', side_effect=[(spec, 'spec'), (status, 'status')]), \
                 patch.object(s.subprocess, 'Popen') as launch:
                with self.assertRaises(PermissionError):
                    s.guard_snapshot(ROOT, 10, time.monotonic() + 1)
                launch.assert_not_called()

    def test_actual_slot_bytes_differ(self):
        spec, status, resource, lock = self._guard()
        lock.write_bytes(b'other_owner\nchanged\n')
        with patch.object(s, 'read_json', side_effect=[(spec, 'spec'), (status, 'status'), (resource, 'resource')]), \
             patch.object(s, 'process_record', return_value=record(10, 8)):
            with self.assertRaises(PermissionError):
                s.guard_snapshot(ROOT, 10, time.monotonic() + 1)

    def test_guard_missing_publication_stops_inside_deadline(self):
        spec, _, _, _ = self._guard()
        def read(path):
            if Path(path).name == 'RUN_SPEC.json':
                return spec, 'spec'
            raise FileNotFoundError()
        with patch.object(s, 'read_json', side_effect=read):
            with self.assertRaises(TimeoutError):
                s.guard_snapshot(ROOT, 10, time.monotonic() + .05)

    def test_pid_pinned_signal_accepts_only_known_identity(self):
        row = record(20)
        tracked = {20: dict(record=row, pidfd=17, ownership='actual_control_child')}
        events = []
        with patch.object(s, 'process_record', return_value=dict(row, state='S')), \
             patch.object(s.signal, 'pidfd_send_signal', create=True) as send:
            s._signal(tracked, signal.SIGTERM, {10, 99}, events)
            send.assert_called_once_with(17, signal.SIGTERM, None, 0)
        self.assertEqual(events[0]['starttime'], '100')
        for changed in [dict(row, starttime='reused'), dict(row, pgid=999), dict(row, state='Z'), None]:
            with patch.object(s, 'process_record', return_value=changed), \
                 patch.object(s.signal, 'pidfd_send_signal', create=True) as send:
                s._signal(tracked, signal.SIGTERM, {10, 99}, [])
                send.assert_not_called()

    def test_protected_pid_never_signalled_even_if_in_tracked(self):
        with patch.object(s.signal, 'pidfd_send_signal', create=True) as send:
            with self.assertRaises(PermissionError):
                s._signal({99: dict(record=record(99), pidfd=17)}, signal.SIGTERM, {99}, [])
            send.assert_not_called()
        with patch.object(s, 'descendants', return_value={99: record(99)}), patch.object(s, '_pin') as pin:
            with self.assertRaises(PermissionError):
                s._observe({}, 10, {99})
            pin.assert_not_called()

    def test_reused_observed_pid_does_not_gain_ownership(self):
        tracked = {20: dict(record=record(20), pidfd=17)}
        with patch.object(s, 'descendants', return_value={20: record(20, start='reused')}), \
             patch.object(s, '_pin') as pin:
            with self.assertRaises(PermissionError):
                s._observe(tracked, 10, {99})
            pin.assert_not_called()

    def test_descendant_ownership_keeps_detached_session_and_new_children(self):
        rows = {20: record(20, 10), 21: record(21, 20, pgid=21, sid=21)}
        tracked = {}
        with patch.object(s, 'descendants', return_value=rows), patch.object(s, '_pin', side_effect=[17, 18]):
            s._observe(tracked, 10, {99})
        self.assertEqual(set(tracked), {20, 21})
        self.assertEqual(tracked[21]['record']['sid'], 21)

    def test_actual_portable_own_normal_dummy(self):
        began = time.monotonic()
        proc = subprocess.Popen([sys.executable, '-c', 'print("OWN_SUPERVISOR_NORMAL_DUMMY")'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(out.strip(), b'OWN_SUPERVISOR_NORMAL_DUMMY')
            CONTROL_ROWS.append(dict(control='actual_portable_own_normal_dummy', pid=proc.pid,
                                     returncode=proc.returncode, stdout_sha256=s.digest(out),
                                     stderr_sha256=s.digest(err), elapsed_s=time.monotonic() - began,
                                     linux_pidfd_supervisor=False, guard_fixture=True))
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)

    def test_actual_portable_own_hanging_dummy_handle_cleanup(self):
        began = time.monotonic()
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                proc.wait(timeout=.1)
            # This is our actual Popen process handle. It is not Linux PID/pgid
            # provenance and never invokes os.kill(pid) or killpg.
            proc.terminate()
            proc.wait(timeout=5)
            self.assertIsNotNone(proc.returncode)
            CONTROL_ROWS.append(dict(control='actual_portable_own_hanging_dummy_handle_cleanup',
                                     pid=proc.pid, returncode=proc.returncode,
                                     elapsed_s=time.monotonic() - began,
                                     linux_pidfd_supervisor=False, guard_fixture=True,
                                     own_Popen_handle_cleanup=True))
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait(timeout=5)


@unittest.skipUnless(LINUX_CONTROLS and sys.platform == 'linux',
                     'actual Linux dummy integration requires explicit --linux-owned-controls')
class LinuxOwnedControls(unittest.TestCase):
    def test_actual_linux_normal_pipe_and_full_supervisor(self):
        # All guard/resource documents are fabricated fixtures; no model/EDA IO.
        with tempfile.TemporaryDirectory(prefix='own_supervisor_linux_') as directory:
            root = Path(directory)
            (root / 'raw_evidence').mkdir(); (root / 'guard').mkdir()
            (root / 'supervisor.py').write_bytes((ROOT / 'supervisor.py').read_bytes())
            (root / 'dummy_child.py').write_text(
                'from pathlib import Path\nimport supervisor\n'
                'g = supervisor.child_admission(Path(__file__).resolve().parent)\n'
                'v = supervisor.verify_child_admission(g, Path(__file__).resolve().parent)\n'
                'assert v["real_io_admitted"] is False\n'
                'print("OWN_LINUX_DUMMY_HANDSHAKE", v["child"]["pid"])\n', encoding='utf-8')
            lock = root / 'fixture.lock'; lock.write_bytes(b'own_dummy_guard_fixture\n')
            # The test's own parent process is protected as the explicit dummy
            # model identity; it is never opened as a socket or signalled.
            model = dict(pid=os.getpid(), starttime='explicit_dummy_not_model',
                         exe='fixture', command_sha256='fixture')
            (root / 'stage_fixture.py').write_text(
                'from pathlib import Path\nimport json,sys,supervisor\n'
                'r=Path(__file__).resolve().parent\n'
                'v=supervisor.run_supervised([str(Path(sys.executable).resolve()),str(r/"dummy_child.py")],r/"raw_evidence"/"normal",r)\n'
                '(r/"fixture_result.json").write_text(json.dumps(v))\n'
                'raise SystemExit(0 if v["passed"] else 1)\n', encoding='utf-8')
            (root / 'guard_wrapper.py').write_text(
                'from pathlib import Path\nimport argparse,json,subprocess,sys\n'
                'p=argparse.ArgumentParser();p.add_argument("--guard-out");a=p.parse_args()\n'
                'r=Path(__file__).resolve().parent\n'
                'c=subprocess.Popen([sys.executable,str(r/"stage_fixture.py")],cwd=r)\n'
                'try:\n'
                ' (Path(a.guard_out)/"status.json").write_text(json.dumps({"complete":False,"stage_pid":c.pid}))\n'
                ' rc=c.wait(timeout=15)\n'
                'finally:\n'
                ' if c.poll() is None: c.terminate();c.wait(timeout=5)\n'
                'raise SystemExit(rc)\n', encoding='utf-8')
            spec = dict(schema='natural_runtime_frozen_v1', cloud_root=str(root),
                        execution_authorized_by_root=True, solve_timeout_s=300,
                        source_hashes={name: s.digest((root / name).read_bytes()) for name in ['supervisor.py', 'dummy_child.py', 'guard_wrapper.py', 'stage_fixture.py']},
                        slot_owner='own_dummy_guard_fixture', slot_lock_path=str(lock), model_identity=model,
                        supervisor=dict(child_entry='dummy_child.py', python_executable=str(Path(sys.executable).resolve()),
                                        python_sha256=s.digest(Path(sys.executable).resolve().read_bytes())))
            s.durable_json(root / 'RUN_SPEC.json', spec, new=True)
            s.durable_json(root / 'guard/resource_check.json',
                           dict(slot_owner=spec['slot_owner'], slot_lock_path=str(lock), model_identity=model,
                                slot_lock_sha256=s.digest(lock.read_bytes())), new=True)
            wrapper = subprocess.Popen([sys.executable, str(root / 'guard_wrapper.py'), '--guard-out', str(root / 'guard')],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = wrapper.communicate(timeout=20)
                self.assertEqual(wrapper.returncode, 0, (stdout, stderr))
            finally:
                if wrapper.poll() is None:
                    wrapper.terminate(); wrapper.wait(timeout=5)
            result = s.read_json(root / 'fixture_result.json')[0]
            self.assertTrue(result['passed'], result)
            self.assertTrue(result['owned_cleanup']['verified'])
            self.assertFalse(result['server_job_cancellation_confirmed'])
            CONTROL_ROWS.append(dict(control='actual_linux_normal_pipe_full_supervisor',
                                     guard_fixture=True, real_model_calls=0, real_eda_calls=0, receipt=result))

    def test_actual_linux_owned_hang_and_detached_grandchild_cleanup(self):
        s._linux_requirements()
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        tracked, proc = {}, None
        protected = {os.getpid(), os.getppid()}
        try:
            self.assertEqual(s.descendants(os.getpid()), {})
            code = ('import subprocess,sys,time,signal\n'
                    'child=subprocess.Popen([sys.executable,"-c",'
                    '"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"],'
                    'start_new_session=True)\n'
                    'print(child.pid,flush=True)\n'
                    'time.sleep(60)\n')
            proc = subprocess.Popen([sys.executable, '-c', code], start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertTrue(select_ready(proc.stdout.fileno(), 3), 'own child did not publish grandchild PID')
            grandchild = int(proc.stdout.readline())
            s._observe(tracked, os.getpid(), protected)
            self.assertIn(proc.pid, tracked); self.assertIn(grandchild, tracked)
            cleanup = s.cleanup_owned(proc, tracked, os.getpid(), protected, time.monotonic() + 5)
            self.assertTrue(cleanup['verified'], cleanup)
            self.assertEqual(cleanup['remaining'], [])
            self.assertFalse(cleanup['process_groups_signalled'])
            CONTROL_ROWS.append(dict(control='actual_linux_own_hang_detached_grandchild_cleanup',
                                     guard_fixture=True, real_model_calls=0, real_eda_calls=0,
                                     grandchild_pid=grandchild, receipt=cleanup))
        finally:
            if proc is not None:
                s.cleanup_owned(proc, tracked, os.getpid(), protected, time.monotonic() + 5)
                if proc.stdout: proc.stdout.close()
                if proc.stderr: proc.stderr.close()
            for item in tracked.values():
                os.close(item['pidfd'])
            libc.prctl(36, previous.value, 0, 0, 0)


def select_ready(fd, seconds):
    return bool(s.select.select([fd], [], [], seconds)[0])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(json.dumps(dict(schema='natural_supervisor_own_controls_v1', tests_run=result.testsRun,
                          failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                          actual_model_calls=0, actual_eda_calls=0, actual_cloud_or_fifo_calls=0,
                          linux_owned_dummy_controls_executed=bool(LINUX_CONTROLS and sys.platform == 'linux'),
                          linux_actual_300s_timeout_verified=False, linux_rocm_verified=False,
                          real_runtime_admitted=False, quality_qualification=False,
                          controls=CONTROL_ROWS), indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
