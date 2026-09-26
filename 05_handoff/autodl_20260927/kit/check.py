"""Read-only kit / host preflight. No inference request or installs."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', action='store_true')
    args = ap.parse_args()
    failed = []
    manifest = json.loads((ROOT / 'SHA256.json').read_text(encoding='utf-8'))
    for rel, digest in manifest.items():
        p = ROOT / rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            failed.append('File missing/changed: ' + rel)
    spec = importlib.util.spec_from_file_location('official_eval', ROOT / 'project/official_eval.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_upstream()
    print('Converted tasks:', len(list((ROOT / 'project/bench/tasks_veval').glob('*/task.json'))))
    if args.host:
        if sys.platform != 'linux':
            failed.append('Official evaluator requires Linux/WSL')
        for name in ('xvlog', 'xelab', 'xsim', 'vivado', 'nvidia-smi'):
            if not shutil.which(name):
                failed.append(name + ' is missing from PATH')
        if shutil.which('vivado'):
            with __import__('tempfile').TemporaryDirectory() as td:
                proc = subprocess.run(['vivado', '-version'], cwd=td, capture_output=True, text=True, timeout=30)
            if proc.returncode or '2026.1' not in proc.stdout:
                failed.append('Vivado 2026.1 required')
        if shutil.which('nvidia-smi'):
            subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,driver_version', '--format=csv'], check=True)
        model = os.environ.get('MODEL_NAME', '')
        url = os.environ.get('LLM_BASE_URL', '').rstrip('/')
        try:
            with urllib.request.urlopen(url + '/models', timeout=10) as response:
                names = [x['id'] for x in json.load(response)['data']]
            if not model or model not in names:
                failed.append('MODEL_NAME does not match /v1/models')
        except Exception as exc:
            failed.append('Model listing failed: ' + str(exc))
    print(json.dumps({'passed': not failed, 'failures': failed}, ensure_ascii=False, indent=2))
    raise SystemExit(bool(failed))

if __name__ == '__main__':
    main()
