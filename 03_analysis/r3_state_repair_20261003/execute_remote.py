"""Isolated R3 stages; never manages the shared model or the server instance."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
KIT = Path('/workspace/team/tasks/autodl-rtl-kit/project')
OWNER = 'codex_r3_state_20261003'
PID = 2013333
TASKS = ['Prob086_lfsr5', 'Prob085_shift4', 'Prob033_ece241_2014_q1c']
EVALUATOR = Path('/workspace/team/codex_takeover_20261003/official_eval.py')
PROBES = SRC / 'probes'
RUN = ROOT / 'run'
os.environ.update(PATH='/workspace/AMD/2026.1/Vivado/bin:' + os.environ['PATH'],
                  LD_LIBRARY_PATH='/workspace/team/udev-stub',
                  XILINXD_LICENSE_FILE='/workspace/team/Xilinx.lic',
                  XILINX_VIVADO='/workspace/AMD/2026.1/Vivado',
                  PYTHONDONTWRITEBYTECODE='1', NO_PROXY='127.0.0.1,localhost,::1',
                  no_proxy='127.0.0.1,localhost,::1')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')


def model_identity():
    proc = Path('/proc') / str(PID)
    cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
    assert '/workspace/team/tools/llama-build/bin/llama-server ' in cmd
    start = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    return dict(pid=PID, start_ticks=start, command=cmd)


def check():
    for rel, digest in json.loads((SRC / 'source_manifest.json').read_text()).items():
        assert sha(SRC / rel) == digest, rel
    pre = json.loads((ROOT / 'preflight.json').read_text())
    assert model_identity() == pre['model_identity'], 'shared model identity changed'
    for rel, digest in pre['package_sha256'].items():
        assert sha(KIT / rel) == digest, rel


def stage(name, arguments):
    check()
    start = time.time()
    with (ROOT / (name + '.log')).open('xb') as log:
        rc = subprocess.call([sys.executable, '-B', *map(str, arguments)],
                             stdout=log, stderr=subprocess.STDOUT)
    result = dict(stage=name, rc=rc, started_epoch=start, ended_epoch=time.time())
    write(ROOT / (name + '_status.json'), result)
    check()
    print(json.dumps(result), flush=True)
    if rc:
        raise RuntimeError(name + ' failed; preserve evidence and inspect before continuing')


def main(mode):
    check()
    if mode == 'controls':
        stage('controls', [SRC / 'eval/validate_controls.py', '--probes', PROBES / 'probe_runner.py',
                          '--probe-root', PROBES, '--out', ROOT / 'controls'])
    elif mode == 'freeze':
        files = list(SRC.rglob('*'))
        files = [p for p in files if p.is_file() and '__pycache__' not in p.parts]
        files += [KIT / 'submission/agent/runtime.py', EVALUATOR,
                  KIT / 'official_reference/UPSTREAM.json', Path('/proc') / str(PID) / 'cmdline']
        files += list((KIT / 'official_reference/selftest').glob('*.py'))
        for task in TASKS:
            files += [p for p in (KIT / 'bench/tasks_veval' / task).rglob('*')
                      if p.is_file() and '__pycache__' not in p.parts]
        args = [SRC / 'state_update_repair_pilot.py', 'freeze', '--inputs', SRC / 'input',
                '--package', KIT / 'submission', '--out', RUN,
                '--probe-validation', ROOT / 'controls/controls_validation.json',
                '--probe-runner', PROBES / 'probe_runner.py']
        for path in sorted(set(files)):
            args.extend(['--freeze-file', path])
        stage('freeze', args)
    elif mode == 'run':
        with (ROOT / 'experiment.started').open('x') as marker:
            marker.write(str(time.time()))
        subprocess.run(['/workspace/team/slot.sh', 'acquire', OWNER, '90',
                        'R3 fixed 12-call state-update checklist comparison'], check=True)
        lock = Path('/workspace/team/SLOT.lock').read_bytes()
        assert lock.decode().splitlines()[0] == OWNER
        stage('generation', [SRC / 'state_update_repair_pilot.py', 'run', '--out', RUN,
                             '--slot-owner', OWNER])
        assert Path('/workspace/team/SLOT.lock').read_bytes() == lock
        stage('grading', [SRC / 'eval/grade_pilot.py', '--run', RUN, '--kit', KIT,
                          '--evaluator', EVALUATOR, '--probes', PROBES / 'probe_runner.py',
                          '--probe-root', PROBES, '--slot-owner', OWNER])
        assert Path('/workspace/team/SLOT.lock').read_bytes() == lock
        health = json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5))
        assert health.get('status') == 'ok'
        check()
        subprocess.run(['/workspace/team/slot.sh', 'release', OWNER], check=True)
        write(ROOT / 'postflight.json', dict(
            utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            model_identity=model_identity(), model_health=health,
            package_sha256=json.loads((ROOT / 'preflight.json').read_text())['package_sha256'],
            slot_released=not Path('/workspace/team/SLOT.lock').exists(),
            instance_shutdown_or_release=False))
    else:
        raise ValueError(mode)


if __name__ == '__main__':
    main(sys.argv[1])
