"""Exercise the real shell functions without Vivado, GPU, or shared processes.

The Linux /proc ownership gate is checked with synthetic process identities;
live recovery remains a separate Linux acceptance test.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
ACCEPT = REPO / '03_analysis/deploy_accept_20261003/deploy_accept_v2.sh'
SERVE = ROOT / 'submission/serve/serve_all.sh'
BASH = shutil.which('bash')


@unittest.skipUnless(BASH, 'Bash is required for shell behavior tests')
class DeploymentShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.env = dict(os.environ, ACCEPT_LOG_DIR=self.work.as_posix(),
                        LOG_DIR=self.work.as_posix(), FPGACHINA_TOKEN='unit-only')

    def shell(self, code, service=False):
        path = SERVE if service else ACCEPT
        marker = '# ---- 首次启动 ----' if service else '# ---------------------------------------------------------------- main'
        prefix = path.read_text(encoding='utf-8').split(marker)[0]
        result = subprocess.run([BASH, '-s'], input=prefix + '\n' + code,
                                text=True, encoding='utf-8', capture_output=True,
                                env=self.env, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def fake_judge(self):
        judge = self.work / 'fake_judge.py'
        judge.write_text("""import json, os, pathlib, sys
if os.environ.get('FAKE_FAIL') == '1':
    raise SystemExit(7)
out = pathlib.Path(sys.argv[sys.argv.index('--json') + 1])
out.write_text(json.dumps({'level': int(os.environ.get('FAKE_LEVEL', '3')),
                          'tool_error': os.environ.get('FAKE_TOOL_ERROR')}))
""", encoding='utf-8')
        (self.work / 'task.json').write_text('{}', encoding='utf-8')
        self.env.update(JUDGE=judge.as_posix(), FIXED_TASK=self.work.as_posix())

    def test_judge_keeps_parent_state_and_never_reuses_a_failed_verdict(self):
        self.fake_judge()
        self.shell('''
write_helpers
run_judge "$WORK/a.v" > "$WORK/first.result" || exit 10
[ "$JUDGE_LEVEL" = 3 ] || exit 11
export FAKE_FAIL=1
if run_judge "$WORK/a.v" > "$WORK/second.result"; then exit 12; fi
[ -z "$JUDGE_LEVEL" ] || exit 13
[ "$(find "$WORK" -maxdepth 1 -type d -name 'judge.*' | wc -l)" -eq 2 ] || exit 14
''')

    def recovery(self, level='3', tool_error=None):
        self.fake_judge()
        self.env['FAKE_LEVEL'] = level
        if tool_error:
            self.env['FAKE_TOOL_ERROR'] = tool_error
        return self.shell('''
write_helpers
sleep() { :; }
agent_ready() { echo OK; }
model_identity() { printf '%s|' "$MODEL_NAME"; }
solve_nonempty() { echo 42; }
verify_recovery token unit
result=$?
printf 'recovery=%s failures=%s\n' "$result" "$N_FAIL"
exit 0
''')

    def test_recovery_requires_functional_and_synthesis_success(self):
        self.assertIn('recovery=0 failures=0', self.recovery())
        self.assertIn('recovery=1 failures=1', self.recovery(level='1'))
        self.assertIn('recovery=1 failures=1', self.recovery(tool_error='missing tool'))

    def test_gate_requires_slot_and_refuses_shared_model_handover(self):
        self.shell('''
PRE_AGENT_HTTP=000
PRE_SLOT=''
ACCEPT_SLOT_OWNER=mine
if gate_execute; then exit 10; fi
PRE_SLOT=mine
gate_execute || exit 11
PRE_SLOT=someone_else
if gate_execute; then exit 12; fi
PRE_SLOT=mine
ACCEPT_MODEL_HANDOVER=1
if gate_execute; then exit 13; fi
''')

    def test_two_missing_entries_are_not_a_hash_match(self):
        self.env.update(ENTRY_DEPLOY=(self.work / 'absent_a').as_posix(),
                        ENTRY_SUBMISSION=(self.work / 'absent_b').as_posix())
        self.shell('''
preflight_hash
[ "$HARD_GATE_FAIL" = 1 ] && [ "$N_FAIL" = 1 ] || exit 10
''')

    def test_manifest_entry_hash_is_enforced(self):
        kit = self.work / 'kit'
        sub = kit / 'submission'
        sub.mkdir(parents=True)
        (sub / 'runtime.py').write_text('test', encoding='utf-8')
        import hashlib
        manifest = self.work / 'manifest.json'
        manifest.write_text(json.dumps({
            'runtime': {'path': 'runtime.py', 'sha256': hashlib.sha256(b'test').hexdigest()},
            'serving': {'supervisor': 'serve/serve_all.sh', 'supervisor_sha256': 'wrong'},
        }), encoding='utf-8')
        self.env.update(KIT=kit.as_posix(), MANIFEST=manifest.as_posix())
        self.shell('''
write_helpers
ENTRY_SUBMISSION_SHA=expected
preflight_manifest
[ "$HARD_GATE_FAIL" = 1 ] && [ "$N_FAIL" = 1 ] || exit 10
''')

    def test_solve_serializes_multiline_quoted_prompt(self):
        self.shell('''
write_helpers
http_req() {
  shift
  while [ "$#" -gt 0 ]; do
    if [ "$1" = -d ]; then printf '%s' "$2" > "$WORK/payload.json"; break; fi
    shift
  done
  HTTP_CODE=200; HTTP_BODY='{}'
}
prompt=$'line "one"\\nline two'
solve_to token short1 "$prompt" 1 "$WORK/result.json" 30
python3 - "$WORK/payload.json" <<'PY'
import json, sys
v = json.load(open(sys.argv[1]))
assert v['prompt'] == 'line "one"\\nline two'
assert v['deadline_s'] == 1
PY
''')

    def test_start_agent_records_the_exec_process_not_a_wrapper(self):
        fake = self.work / 'fake-agent.sh'
        fake.write_text('printf "%s\\n" "$BASHPID" > "$LOG_DIR/child.pid"\nsleep 3\n', encoding='utf-8')
        self.env['KIT'] = self.work.as_posix()
        # Use a harmless Bash child; it exits itself and is waited for, never killed.
        self.shell('''
PYTHON_BIN=$(command -v bash)
RUNTIME_PATH="$LOG_DIR/fake-agent.sh"
port_is_free() { return 0; }
remember_pid() { printf '%s\n' "$1" > "$2"; }
agent_state() { [ -s "$LOG_DIR/child.pid" ]; }
start_agent || exit 10
recorded=$(cat "$AGENT_PIDFILE")
actual=$(cat "$LOG_DIR/child.pid")
wait "$recorded"
[ "$recorded" = "$actual" ] || { echo "wrapper=$recorded child=$actual"; exit 11; }
''', service=True)

    def test_stop_refuses_unproven_identity_without_signalling(self):
        self.shell('''
printf '123\n' > "$AGENT_PIDFILE"
pid_is_ours() { return 1; }
kill() {
  [ "$1" = -0 ] && return 0
  printf 'unexpected signal\n' >> "$LOG_DIR/signals"
}
if stop_ours "$AGENT_PIDFILE" agent; then exit 10; fi
[ ! -f "$LOG_DIR/signals" ] || exit 11
''', service=True)


class SupervisorIdentityTests(unittest.TestCase):
    def check_identity(self, birth='500', args=None, executable='/usr/bin/python3'):
        source = SERVE.read_text(encoding='utf-8')
        gate = source.split('pid_is_ours() {', 1)[1].split("<<'PY'", 1)[1].split('\nPY\n', 1)[0]
        fields = ['S'] + ['0'] * 18 + ['500']
        argv = args or ['/usr/bin/python3', '-B', '/kit/submission/agent/runtime.py', 'serve', '--port', '7860']
        cmd = ('\0'.join(argv) + '\0').encode()
        realpath = lambda p: executable if str(p).replace('\\', '/').endswith('/exe') else str(p)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(Path, 'read_text', return_value='123 (name with spaces) ' + ' '.join(fields)))
            stack.enter_context(mock.patch.object(Path, 'read_bytes', return_value=cmd))
            stack.enter_context(mock.patch('os.path.realpath', side_effect=realpath))
            stack.enter_context(mock.patch('sys.argv', ['-', '123', birth, 'agent', '/usr/bin/python3', '/llama', '/model', 'model-name', '7860', '8000', '/kit/submission/agent/runtime.py']))
            with self.assertRaises(SystemExit) as caught:
                exec(compile(gate, '<real supervisor ownership gate>', 'exec'), {})
        return caught.exception.code

    def test_birth_executable_and_exact_port_are_all_required(self):
        self.assertEqual(self.check_identity(), 0)
        self.assertEqual(self.check_identity(birth='499'), 1)
        self.assertEqual(self.check_identity(executable='/usr/bin/bash'), 1)
        self.assertEqual(self.check_identity(args=['/usr/bin/python3', '/kit/submission/agent/runtime.py', 'serve', '--port', '78600']), 1)


if __name__ == '__main__':
    unittest.main()
