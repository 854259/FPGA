"""Validate the actual tarball, not just its source directory."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tarfile

root = Path(__file__).resolve().parent
bundle = root / 'autodl-rtl-kit.tar.gz'
expected = (root / 'autodl-rtl-kit.tar.gz.sha256').read_text().split()[0]
assert hashlib.sha256(bundle.read_bytes()).hexdigest() == expected
with tarfile.open(bundle, 'r:gz') as archive:
    members = {m.name: m for m in archive.getmembers()}
    assert all(m.isfile() and '..' not in Path(m.name).parts for m in members.values())
    def read(rel):
        return archive.extractfile('autodl-rtl-kit/' + rel).read()
    manifest = json.loads(read('SHA256.json'))
    for name, digest in manifest.items():
        assert hashlib.sha256(read(name)).hexdigest() == digest, name
        if name.endswith('.py'):
            ast.parse(read(name).decode('utf-8-sig'), filename=name)
    for name in ('project/submission/run.sh', 'project/submission/run_baseline.sh',
                 'project/official_reference/selftest/judge/sv-xsim-analyze',
                 'project/official_reference/selftest/judge/veval-judge'):
        assert members['autodl-rtl-kit/' + name].mode & 0o111, name
    tasks = [n for n in members if n.startswith('autodl-rtl-kit/project/bench/tasks_veval/') and n.endswith('/task.json')]
    assert len(tasks) == 156
bash = shutil.which('bash')
if not bash:
    raise SystemExit('Install Bash (or Git for Windows) to validate shell syntax.')
for script in ('load_env.sh', 'start_model.sh', 'env.example.sh'):
    subprocess.run([bash, '-n', str(root/'kit'/script)], check=True)
report = {'tar_sha256': expected, 'verified_manifest_files': len(manifest),
          'converted_tasks': len(tasks), 'python_syntax': 'pass',
          'shell_syntax': 'pass', 'judge_executable_bits': 'pass',
          'real_gpu_tested': False, 'real_linux_vivado_tested': False}
(root/'logs/bundle-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps(report, indent=2))
