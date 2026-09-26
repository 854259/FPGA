"""Create a clean, pinned development kit. Never packages local credentials."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PREFIX = '04_project/amd_rtl_agent/'
COMMIT = 'a53e343ed9f02434050fdf86e61bae1b4a0c11a7'
DATA_COMMIT = 'c498220d0a52248f8e3fdffe279075215bde2da6'
KIT = HERE / 'kit'
PROJECT = KIT / 'project'

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def main():
    git('cat-file', '-e', COMMIT + '^{commit}')
    PROJECT.mkdir(parents=True, exist_ok=True)
    for name in git('ls-tree', '-r', '--name-only', COMMIT, '--', PREFIX).decode().splitlines():
        rel = name.removeprefix(PREFIX)
        if rel.startswith(('outputs/', 'runtime/', 'bench/results/', 'model/')):
            continue
        dest = PROJECT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git('show', f'{COMMIT}:{name}'))

    cache = HERE / 'verilog-eval-source.zip'
    if not cache.exists():
        url = f'https://codeload.github.com/NVlabs/verilog-eval/zip/{DATA_COMMIT}'
        with urllib.request.urlopen(url, timeout=120) as response:
            content = response.read()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Invalid dataset archive')
        cache.write_bytes(content)
    dataset = PROJECT / 'bench/verilog-eval/dataset_spec-to-rtl'
    dataset.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cache) as archive:
        root = f'verilog-eval-{DATA_COMMIT}/'
        for item in archive.infolist():
            if item.is_dir() or not item.filename.startswith(root):
                continue
            rel = item.filename[len(root):]
            if rel.startswith('dataset_spec-to-rtl/') or rel in ('LICENSE', 'README.md'):
                target = PROJECT / 'bench/verilog-eval' / rel
                if not target.resolve().is_relative_to((PROJECT / 'bench/verilog-eval').resolve()):
                    raise RuntimeError('Unsafe archive path')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    counts = {suffix: len(list(dataset.glob('*' + suffix))) for suffix in ('_prompt.txt', '_ref.sv', '_test.sv')}
    if set(counts.values()) != {156}:
        raise RuntimeError(f'Incomplete dataset: {counts}')
    converted = PROJECT / 'bench/tasks_veval'
    if not converted.exists():
        subprocess.run([sys.executable, '-B', str(PROJECT / 'official_reference/selftest/veval_import.py'),
                        '--src', str(dataset), '--out', str(converted)], check=True)
    if len(list(converted.glob('*/task.json'))) != 156:
        raise RuntimeError('Converted tasks incomplete')
    upstream = json.loads((PROJECT / 'official_reference/UPSTREAM.json').read_text())
    for rel, expected in upstream['files'].items():
        if hashlib.sha256((PROJECT / rel).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Upstream checksum mismatch: ' + rel)
    write_json(KIT / 'source-lock.json', {
        'code_commit': COMMIT, 'dataset_commit': DATA_COMMIT,
        'official_commit': upstream['commit'], 'dataset_counts': counts,
        'dataset_zip_sha256': hashlib.sha256(cache.read_bytes()).hexdigest(),
        'purpose': 'Development evaluator kit; NOT an isolated final submission image',
        'contains_model_weights': False, 'contains_vivado': False})
    checksums = {p.relative_to(KIT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in KIT.rglob('*') if p.is_file() and p.name != 'SHA256.json'
                 and '__pycache__' not in p.parts}
    write_json(KIT / 'SHA256.json', checksums)
    target = HERE / 'autodl-rtl-kit.tar.gz'
    executable = {'run.sh', 'run_baseline.sh', 'sv-xsim-analyze', 'veval-judge'}
    with tarfile.open(target, 'w:gz') as archive:
        for p in sorted(KIT.rglob('*')):
            if not p.is_file() or '__pycache__' in p.parts:
                continue
            info = archive.gettarinfo(str(p), arcname='autodl-rtl-kit/' + p.relative_to(KIT).as_posix())
            info.mode = 0o755 if p.name in executable or p.suffix == '.sh' else 0o644
            with p.open('rb') as stream:
                archive.addfile(info, stream)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (HERE / 'autodl-rtl-kit.tar.gz.sha256').write_text(f'{digest}  {target.name}\n', encoding='ascii')
    print(json.dumps({'bundle': str(target), 'bytes': target.stat().st_size, 'sha256': digest,
                      'files': len(checksums), 'dataset': counts}, ensure_ascii=False))

if __name__ == '__main__':
    main()
