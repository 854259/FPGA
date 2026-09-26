"""Run one explicit official-evaluation stage. Does not silently start the next."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / 'project'
STAGES = {
    'reference3': ('official_reference/tasks', 1, True),
    'smoke3': ('official_reference/tasks', 1, False),
    'pair3x5': ('official_reference/tasks', 5, False),
    'reference156': ('bench/tasks_veval', 1, True),
    'full156': ('bench/tasks_veval', 1, False),
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=STAGES)
    ap.add_argument('--deadline', type=int, default=300)
    args = ap.parse_args()
    if sys.platform != 'linux':
        ap.error('Run this on Linux/WSL with Vivado 2026.1')
    if args.deadline <= 0:
        ap.error('deadline must be positive')
    if os.environ.get('RTL_PROFILE') != 'development':
        ap.error('Set RTL_PROFILE=development for this NVIDIA development run')
    tasks, samples, reference = STAGES[args.stage]
    if not reference and not os.environ.get('MODEL_NAME'):
        ap.error('MODEL_NAME is required')
    for var in ('EDA_TMP', 'SELFTEST_TMP'):
        Path(os.environ.get(var, '/tmp')).mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    out = PROJECT / 'outputs' / (args.stage + '_' + run_id)
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    cmd = [sys.executable, '-B', str(PROJECT / 'official_eval.py'), '--tasks', str(PROJECT / tasks),
           '--out', str(out), '--samples', str(samples), '--deadline', str(args.deadline)]
    if reference:
        cmd.append('--reference')
    allowed = ('MODEL_NAME', 'LLM_BASE_URL', 'RTL_PROFILE', 'RTL_REPAIRS', 'RTL_MAX_TOKENS', 'RTL_TEMPERATURE', 'XILINX_VIVADO')
    record = {'command': cmd, 'environment': {k: os.environ.get(k) for k in allowed},
              'source_lock': json.loads((ROOT / 'source-lock.json').read_text()),
              'output': str(out), 'complete': False}
    record_path = logs / (args.stage + '_' + run_id + '.json')
    record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Output:', out, flush=True)
    print('Log:', logs / (args.stage + '_' + run_id + '.log'), flush=True)
    with (logs / (args.stage + '_' + run_id + '.log')).open('w', encoding='utf-8') as log:
        rc = subprocess.run(cmd, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT).returncode
    meta = out / 'experiment.json'
    record['exit_code'] = rc
    record['complete'] = rc == 0 and meta.exists() and json.loads(meta.read_text()).get('complete') is True
    record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))
    print('Inspect graded_summary.json and excluded tool errors; completion is not a passing score.')
    raise SystemExit(0 if record['complete'] else rc or 1)

if __name__ == '__main__':
    main()
