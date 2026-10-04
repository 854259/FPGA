"""Q1: AMD-only diagnostic-information preflight; no runtime integration or model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zipfile


def compact_diagnostics(stdout, limit=2048):
    """Preserve distinct messages and source lines; unknown formats keep legacy behavior."""
    selected = [s for s in stdout.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
    legacy = '\n'.join(selected)[:limit] or stdout[-limit:]
    structured = re.compile(r'^(ERROR|WARNING|FATAL): \[[^\]]+\] .+')
    if not any(structured.match(s) for s in selected):
        return legacy
    # Only shorten a candidate path when it is unambiguous within this invocation.
    location = re.compile(r' \[([^\[\]\r\n]+):(\d+)\]$')
    candidate_paths = set()
    for line in selected:
        match = location.search(line)
        if match and match[1].replace('\\', '/').rsplit('/', 1)[-1] == 'candidate.sv':
            candidate_paths.add(match[1])
    groups = {}
    for line in selected:
        match = location.search(line) if structured.match(line) else None
        message = line[:match.start()] if match else line
        path = match[1] if match else ''
        key = (message, path)
        if key not in groups:
            groups[key] = []
        if match and match[2] not in groups[key]:
            groups[key].append(match[2])
    rendered = []
    for (message, path), lines in groups.items():
        short = 'candidate.sv' if path in candidate_paths and len(candidate_paths) == 1 else path
        suffix = ' [' + short + ':' + ','.join(lines) + ']' if path else ''
        severity = re.search(r'\b(FATAL|ERROR|WARNING)\b', message)
        priority = {'FATAL': 0, 'ERROR': 1, 'WARNING': 2}.get(severity[1] if severity else '', 3)
        rendered.append((priority, message + suffix))
    rendered.sort(key=lambda item: item[0])  # stable within severity
    complete = '\n'.join(line for _, line in rendered)
    if len(complete) <= limit:
        return complete
    marker = '[diagnostic limit: omitted %d group(s); consult raw log]'
    # Reserve enough room for a truthful marker, without splitting a diagnostic.
    allowance = limit - len(marker % len(rendered)) - 1
    kept = []
    used = 0
    for _, line in rendered:
        extra = len(line) + bool(kept)
        if used + extra <= allowance:
            kept.append(line)
            used += extra
    return '\n'.join(kept + [marker % (len(rendered) - len(kept))])


def controls():
    """Fixed literal expectations, including unknown-format and overflow controls."""
    e = 'ERROR: [VRFC 10-1280] assignment to non-register state'
    w = 'WARNING: [VRFC 10-8497] literal truncated'
    other = 'ERROR: [VRFC 10-1280] assignment to non-register input_signal'
    cases = [
        ('empty', '', ''),
        ('plain_fallback', 'tool failed without a diagnostic', 'tool failed without a diagnostic'),
        ('plain_tail', 'q' * 3000, 'q' * 2048),
        ('unknown_error', 'INFO startup\nERROR cannot launch tool\nfooter', 'ERROR cannot launch tool'),
        ('locale_fallback', 'WARNING: locale missing', 'WARNING: locale missing'),
        ('single_error', e, e),
        ('single_warning', w, w),
        ('severity_order', w + '\n' + e, e + '\n' + w),
        ('exact_duplicates', '\n'.join([e] * 30), e),
        ('distinct_symbols', e + '\n' + other, e + '\n' + other),
        ('linux_path', e + ' [/tmp/long/work/candidate.sv:16]', e + ' [candidate.sv:16]'),
        ('windows_path', e + ' [D:\\test\\candidate.sv:17]', e + ' [candidate.sv:17]'),
        ('distinct_lines', e + ' [/tmp/candidate.sv:16]\n' + e + ' [/tmp/candidate.sv:18]', e + ' [candidate.sv:16,18]'),
        ('duplicate_location', '\n'.join([e + ' [/tmp/candidate.sv:16]'] * 8), e + ' [candidate.sv:16]'),
        ('path_collision', e + ' [/one/candidate.sv:1]\n' + e + ' [/two/candidate.sv:2]', e + ' [/one/candidate.sv:1]\n' + e + ' [/two/candidate.sv:2]'),
        ('include_path_retained', e + ' [/tmp/include/defs.svh:2]', e + ' [/tmp/include/defs.svh:2]'),
        ('raw_fatal_retained', w + '\nFATAL launch failure', 'FATAL launch failure\n' + w),
        ('crlf', w + '\r\n' + e + '\r\n', e + '\n' + w),
        ('different_widths', 'ERROR: [VRFC 1] width 8\nERROR: [VRFC 1] width 16', 'ERROR: [VRFC 1] width 8\nERROR: [VRFC 1] width 16'),
        ('literal_brackets', 'ERROR: [VRFC 1] bad foo[3:0]', 'ERROR: [VRFC 1] bad foo[3:0]'),
        ('exact_cap', 'ERROR: [VRFC 1] ' + 'x' * 2032, 'ERROR: [VRFC 1] ' + 'x' * 2032),
        ('warning_flood_before_error', '\n'.join([w] * 100 + [e]), e + '\n' + w),
    ]
    results = []
    for name, source, expected in cases:
        before = hashlib.sha256(source.encode()).hexdigest()
        result = compact_diagnostics(source)
        checks = dict(exact=result == expected, bounded=len(result) <= 2048,
                      deterministic=result == compact_diagnostics(source),
                      input_unchanged=before == hashlib.sha256(source.encode()).hexdigest())
        results.append(dict(name=name, passed=all(checks.values()), checks=checks))
    for name, source in [
        ('oversize_error', 'ERROR: [VRFC 1] ' + 'z' * 5000),
        ('many_distinct_errors', '\n'.join('ERROR: [VRFC 1] distinct error ' + str(i) + ' x' * 30 for i in range(150))),
    ]:
        result = compact_diagnostics(source)
        checks = dict(bounded=len(result) <= 2048, explicit_omission='[diagnostic limit: omitted ' in result,
                      deterministic=result == compact_diagnostics(source),
                      no_partial_error=all(s in source.splitlines() or s.startswith('[diagnostic limit:') for s in result.splitlines()))
        results.append(dict(name=name, passed=all(checks.values()), checks=checks))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', required=True, type=Path)
    ap.add_argument('--resource-check', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    assert sys.platform == 'linux'
    sys.dont_write_bytecode = True
    sha = lambda data: hashlib.sha256(data).hexdigest()
    archive_sha = '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    runtime_sha = '22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7'
    assert sha(args.archive.read_bytes()) == archive_sha
    resource = json.loads(args.resource_check.read_text())
    assert resource['resource_idle'] is True
    assert sha(Path(resource['slot_lock_path']).read_bytes()) == resource['slot_lock_sha256']
    args.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    tests = controls()
    print(json.dumps(dict(phase='controls', passed=sum(x['passed'] for x in tests), total=len(tests))), flush=True)
    records = []
    # Coverage oracle: literal message text and every original location must survive.
    # Only compiler output is read, never a reference, official testbench or score.
    with zipfile.ZipFile(args.archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        def read(name):
            data = z.read(name)
            item = manifest[name]
            assert sha(data) == (item['sha256'] if isinstance(item, dict) else item), name
            return data
        assert sha(read('run/package/agent/runtime.py')) == runtime_sha
        names = sorted(n for n in z.namelist() if '/worker/lint_journal/' in n and n.endswith('/stdout.log'))
        assert len(names) == 338 and len({n.split('/worker/')[0] for n in names}) == 311
        for name in names:
            raw = read(name)
            source = raw.decode('utf-8', errors='replace')
            selected = [s for s in source.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
            old = '\n'.join(selected)[:2048] or source[-2048:]
            new = compact_diagnostics(source)
            errors = []
            warnings = []
            locations = []
            for line in source.splitlines():
                if not re.match(r'^(ERROR|FATAL|WARNING): \[[^\]]+\]', line):
                    continue
                # Strip just the final compiler source location, leaving literal messages.
                core, sep, ending = line.rpartition(' [')
                has_location = sep and ending.endswith(']') and re.search(r':\d+\]$', ending)
                message = core if has_location else line
                bucket = warnings if line.startswith('WARNING:') else errors
                if message not in bucket:
                    bucket.append(message)
                if has_location and not line.startswith('WARNING:'):
                    line_number = ending[:-1].rsplit(':', 1)[1]
                    candidates = [s for s in new.splitlines() if s.startswith(message + ' [')]
                    found = any(line_number in s.rsplit(':', 1)[-1].rstrip(']').split(',') for s in candidates)
                    locations.append(found)
            lost_old = [s for s in errors if s not in old]
            lost_new = [s for s in errors if s not in new]
            checks = dict(bounded=len(new) <= 2048, deterministic=new == compact_diagnostics(source),
                          no_error_loss=not lost_new, all_error_locations=all(locations))
            records.append(dict(name=name, source_sha256=sha(raw), old_chars=len(old), new_chars=len(new),
                distinct_errors=len(errors), old_missing_errors=lost_old, new_missing_errors=lost_new,
                old_missing_warnings=sum(s not in old for s in warnings),
                new_missing_warnings=sum(s not in new for s in warnings),
                changed=old != new, checks=checks, passed=all(checks.values()),
                overflow_marker='[diagnostic limit: omitted ' in new))
    assert sha(args.archive.read_bytes()) == archive_sha
    summary = dict(complete=True, passed=all(r['passed'] for r in records + tests),
        controls=len(tests), controls_passed=sum(r['passed'] for r in tests),
        logs=len(records), workers=311, archived_rows=312, workers_without_compiler_log=1,
        logs_passed=sum(r['passed'] for r in records), error_logs=sum(r['distinct_errors'] > 0 for r in records),
        changed_logs=sum(r['changed'] for r in records),
        distinct_error_occurrences=sum(r['distinct_errors'] for r in records),
        old_missing_error_occurrences=sum(len(r['old_missing_errors']) for r in records),
        new_missing_error_occurrences=sum(len(r['new_missing_errors']) for r in records),
        old_missing_warning_occurrences=sum(r['old_missing_warnings'] for r in records),
        new_missing_warning_occurrences=sum(r['new_missing_warnings'] for r in records),
        overflow_logs=sum(r['overflow_marker'] for r in records),
        model_calls=0, eda_calls=0, elapsed_s=time.monotonic() - tick,
        input_sha256=archive_sha, best_runtime_sha256=runtime_sha,
        driver_sha256=sha(Path(__file__).read_bytes()), runtime_changed=False,
        full_batch_complete=False, new_natural_validation_tasks=0,
        scope='Information-preservation engineering preflight only; no functional quality inference')
    (args.out / 'private_records.json').write_text(json.dumps(dict(controls=tests, logs=records), indent=2) + '\n')
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
