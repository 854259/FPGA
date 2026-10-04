"""Q4: recompile every affected archived source on AMD; no model or evaluator input."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
from diagnostic_feedback_20261005 import compact_diagnostics


def error_messages(text):
    return sorted(set(re.sub(r' \[[^\[\]\r\n]+:\d+\]$', '', s)
                      for s in text.splitlines() if re.match(r'^(ERROR|FATAL): \[', s)))


def main():
    ap = argparse.ArgumentParser()
    for flag in ('archive', 'resource-check', 'out'):
        ap.add_argument('--' + flag, required=True, type=Path)
    a = ap.parse_args()
    assert sys.platform == 'linux'
    sys.dont_write_bytecode = True
    sha = lambda b: hashlib.sha256(b).hexdigest()
    assert sha(a.archive.read_bytes()) == '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    resource = json.loads(a.resource_check.read_text())
    assert resource['resource_idle'] is True
    assert sha(Path(resource['slot_lock_path']).read_bytes()) == resource['slot_lock_sha256']
    formatter = Path(__file__).with_name('diagnostic_feedback_20261005.py')
    assert sha(formatter.read_bytes()) == 'a6cc0b71dc3aad780dc3528472bed6b80b00d10ed6a42b2d4af469c50356d849'
    tool = Path('/workspace/AMD/2026.1/Vivado/bin/xvlog')
    assert tool.is_file()
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    cases = []
    with zipfile.ZipFile(a.archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        def read(name):
            data = z.read(name); item = manifest[name]
            assert sha(data) == (item['sha256'] if isinstance(item, dict) else item)
            return data
        for name in sorted(z.namelist()):
            if '/worker/lint_journal/' not in name or not name.endswith('/stdout.log'):
                continue
            original = read(name).decode('utf-8', errors='replace')
            errors = error_messages(original)
            if not errors:
                continue
            source = read(name.replace('/stdout.log', '/source_before.sv'))
            cases.append(dict(name=name, source=source, expected_errors=errors))
    assert len(cases) == 30
    cases.extend([
        dict(name='constructed_positive', source=b'module TopModule(input a, output y); assign y = a; endmodule\n', expected_errors=[]),
        dict(name='constructed_negative', source=b'module TopModule(input a, output y); wire r; always @* r=a; assign y=r; endmodule\n', expected_errors=None),
    ])
    records = []
    summary = dict(complete=False, passed=False, model_calls=0, eda_calls=0,
        archived_cases=30, constructed_controls=2, full_batch_complete=False,
        new_natural_validation_tasks=0, driver_sha256=sha(Path(__file__).read_bytes()),
        formatter_sha256=sha(formatter.read_bytes()), tool_sha256=sha(tool.read_bytes()),
        scope='Real xvlog replay and feedback preservation only; no worker/model quality score')
    try:
        for index, case in enumerate(cases):
            assert time.monotonic() - tick < 105, 'reserve cleanup time inside 120 second guard'
            out = a.out / ('compile_' + str(index)); out.mkdir()
            path = out / 'candidate.sv'; path.write_bytes(case['source'])
            summary['eda_calls'] += 1
            begin = time.monotonic()
            result = subprocess.run([str(tool), '--sv', str(path)], cwd=out,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors='replace', timeout=15)
            (out / 'stdout.log').write_text(result.stdout)
            errors = error_messages(result.stdout)
            feedback = compact_diagnostics(result.stdout)
            (out / 'feedback.txt').write_text(feedback)
            expected = case['expected_errors']
            checks = dict(source_unchanged=path.read_bytes() == case['source'],
                compilation_class=(result.returncode == 0) == (expected == []),
                all_errors_preserved=all(s in feedback for s in errors),
                bounded=len(feedback) <= 2048,
                diagnostics_reproduced=errors == expected if expected is not None else bool(errors))
            row = dict(name=case['name'], source_sha256=sha(case['source']), returncode=result.returncode,
                       errors=errors, expected_errors=expected, checks=checks, passed=all(checks.values()),
                       elapsed_s=time.monotonic() - begin)
            records.append(row)
            print(json.dumps(dict(phase='compile', index=index + 1, total=32, passed=row['passed'])), flush=True)
        summary.update(complete=True, passed=all(r['passed'] for r in records), passed_cases=sum(r['passed'] for r in records))
    finally:
        summary['elapsed_s'] = time.monotonic() - tick
        (a.out / 'private_records.json').write_text(json.dumps(records, indent=2) + '\n')
        (a.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary), flush=True)
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
