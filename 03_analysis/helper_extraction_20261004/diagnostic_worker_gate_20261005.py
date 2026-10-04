"""Q2: replay the actual frozen worker's control flow with zero network/EDA calls.

Compiler outcomes and model replies are constructed controls, not quality scores.
The production runtime is never modified. Both arms execute the same frozen worker.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch
import zipfile
from diagnostic_feedback_20261005 import compact_diagnostics


def candidate_source(original):
    anchor = "        if result.returncode == 0:\n            return  # Compilation is NOT an official L1/L2/L3 judgement.\n"
    assert original.count(anchor) == 1
    addition = '''        if attempt < repairs:
            try:
                feedback = compact_diagnostics(result.stdout)
            except Exception as exc:
                trace(out, 'diagnostic_compaction', fallback=True, error=type(exc).__name__)
'''
    assert original.count('def worker(task, out):') == 1
    return original.replace(anchor, anchor + addition).replace(
        'def worker(task, out):',
        'from diagnostic_feedback_20261005 import compact_diagnostics\n\n\ndef worker(task, out):')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--archive', required=True, type=Path)
    ap.add_argument('--resource-check', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    assert sys.platform == 'linux'
    sys.dont_write_bytecode = True
    sha = lambda x: hashlib.sha256(x).hexdigest()
    archive_sha = '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    assert sha(a.archive.read_bytes()) == archive_sha
    formatter = Path(__file__).with_name('diagnostic_feedback_20261005.py')
    assert sha(formatter.read_bytes()) == 'a6cc0b71dc3aad780dc3528472bed6b80b00d10ed6a42b2d4af469c50356d849'
    resource = json.loads(a.resource_check.read_text())
    assert resource['resource_idle'] is True
    assert sha(Path(resource['slot_lock_path']).read_bytes()) == resource['slot_lock_sha256']
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    with zipfile.ZipFile(a.archive) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        for name in ['run/package/agent/runtime.py', 'run/package/baseline.py']:
            data = z.read(name)
            entry = manifest[name]
            assert sha(data) == (entry['sha256'] if isinstance(entry, dict) else entry)
            target = a.out / Path(name).name
            target.write_bytes(data)
    original = (a.out / 'runtime.py').read_text()
    assert sha(original.encode()) == '22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7'
    candidate = candidate_source(original)
    (a.out / 'candidate_runtime.py').write_text(candidate)
    baseline = types.ModuleType('baseline')
    baseline.__file__ = str(a.out / 'baseline.py')
    exec(compile((a.out / 'baseline.py').read_text(), baseline.__file__, 'exec'), baseline.__dict__)
    sys.modules['baseline'] = baseline
    good = 'module TopModule(input a, output y); assign y = a; endmodule'
    patched = 'module TopModule(input a, output reg y); always @* y = a; endmodule'
    errors = '\n'.join(['WARNING: [VRFC 1] warning'] * 40 + [
        'ERROR: [VRFC 2] bad first [/long/path/candidate.sv:1]',
        'ERROR: [VRFC 3] bad second [/long/path/candidate.sv:2]'])
    # name, compile return codes, declaration patch, repair budget,
    # formatter exception, failed model response index, missing tool, first reply,
    # expected logical requests, expected compaction calls.
    jobs = [
        ('compile_success', [0], None, 1, False, None, False, good, 1, 0),
        ('declaration_success', [1, 0], patched, 1, False, None, False, good, 1, 0),
        ('model_repair', [1, 0], None, 1, False, None, False, good, 2, 1),
        ('declaration_failed_then_model', [1, 1, 0], patched, 1, False, None, False, good, 2, 1),
        ('formatter_failure_fallback', [1, 0], None, 1, True, None, False, good, 2, 1),
        ('repair_budget_zero', [1], None, 0, False, None, False, good, 1, 0),
        ('two_failed_repairs', [1, 1, 1], None, 2, False, None, False, good, 3, 2),
        ('tool_unavailable', [], None, 1, False, None, True, good, 1, 0),
        ('first_model_timeout', [], None, 1, False, 0, False, good, 1, 0),
        ('repair_model_timeout', [1], None, 1, False, 1, False, good, 2, 1),
        # The untouched baseline extractor removes text outside TopModule.
        # Q2's expectation of two calls here was wrong; preserve the input as a regression.
        ('source_boundary', [0], None, 1, False, None, False, '`include "external.v"\n' + good, 1, 0),
        ('inside_source_boundary', [0], None, 1, False, None, False, good.replace('assign y = a;', '`include "external.v"\nassign y = a;'), 2, 0),
        ('unknown_diagnostic_format', [1, 0], None, 1, False, None, False, good, 2, 1),
    ]
    records = []
    starting_cwd = Path.cwd()
    for name, returncodes, decl, repairs, broken, model_error, missing_tool, first, expected_requests, expected_formats in jobs:
        row = dict(name=name, arms={})
        log = 'ERROR cannot launch compilation' if name == 'unknown_diagnostic_format' else errors
        legacy = '\n'.join(s for s in log.splitlines() if any(w in s for w in ('ERROR', 'WARNING', 'FATAL')))[:2048] or log[-2048:]
        for arm, source in [('A', original), ('C', candidate)]:
            out = a.out / 'controls' / name / arm
            out.mkdir(parents=True)
            task = out / 'task'; task.mkdir()
            (task / 'prompt.txt').write_text('TopModule has one-bit input a and output y. Assign y=a.')
            runtime = types.ModuleType('q2_' + name + arm)
            runtime.__file__ = str(a.out / 'runtime.py')
            exec(compile(source, runtime.__file__, 'exec'), runtime.__dict__)
            requests, compiles, patch_inputs, format_inputs = [], [], [], []
            def urlopen(req, timeout=None):
                body = json.loads(req.data); index = len(requests); requests.append(body)
                assert index < expected_requests, 'unexpected extra logical model call'
                if index == model_error:
                    raise TimeoutError('frozen model timeout control')
                return io.StringIO(json.dumps({'choices': [{'message': {'content': '```verilog\n' + (first if index == 0 else good) + '\n```'}, 'finish_reason': 'stop'}]}))
            def compile_reply(argv, **kwargs):
                index = len(compiles)
                assert index < len(returncodes), 'unexpected extra compile'
                compiles.append(dict(source=Path(argv[-1]).read_text(), returncode=returncodes[index]))
                return types.SimpleNamespace(returncode=returncodes[index], stdout=log if returncodes[index] else '')
            def declaration(code, feedback):
                patch_inputs.append(feedback)
                return decl
            def compact(text):
                format_inputs.append(text)
                if broken:
                    raise ValueError('frozen formatting failure')
                return compact_diagnostics(text)
            runtime.compact_diagnostics = compact
            runtime.skill_texts = lambda: ('generation skill', 'repair skill')
            runtime.vivado_tool = lambda _: None if missing_tool else '/frozen/xvlog'
            runtime.repair_ansi_declarations = declaration
            runtime.endpoint = lambda: 'http://offline.invalid/v1'
            try:
                os.chdir(out)
                with patch.dict(os.environ, MODEL_NAME='Qwen3.6-27B-Q4_K_M', RTL_REPAIRS=str(repairs), RTL_TEMPERATURE='0', RTL_MAX_TOKENS='8192'), patch.object(runtime.urllib.request, 'urlopen', urlopen), patch.object(runtime.subprocess, 'run', compile_reply):
                    runtime.worker(task, out)
            finally:
                os.chdir(starting_cwd)
            row['arms'][arm] = dict(requests=requests, compile_calls=compiles, patch_inputs=patch_inputs,
                format_inputs=format_inputs, final_source=(out / 'solution.v').read_text() if (out / 'solution.v').exists() else None)
        left, right = row['arms']['A'], row['arms']['C']
        checks = dict(request_count=len(left['requests']) == len(right['requests']) == expected_requests,
                      first_request_identical=left['requests'][0] == right['requests'][0],
                      compile_path_identical=left['compile_calls'] == right['compile_calls'] and len(left['compile_calls']) == len(returncodes),
                      declaration_inputs_identical=left['patch_inputs'] == right['patch_inputs'] and all(s == legacy for s in left['patch_inputs']),
                      final_fixed_reply_identical=left['final_source'] == right['final_source'],
                      exact_format_count=len(right['format_inputs']) == expected_formats and not left['format_inputs'])
        expected_diag = legacy if broken else compact_diagnostics(log)
        compared = []
        for before, after in zip(left['requests'][1:], right['requests'][1:]):
            normalized = json.loads(json.dumps(after))
            if expected_formats:
                prefix = before['messages'][1]['content'].rsplit('\nCandidate diagnostics:\n', 1)[0]
                compared.append(after['messages'][1]['content'] == prefix + '\nCandidate diagnostics:\n' + expected_diag)
                normalized['messages'][1]['content'] = before['messages'][1]['content']
            compared.append(normalized == before)
        checks['only_expected_feedback_changed'] = all(compared)
        row.update(checks=checks, passed=all(checks.values()))
        records.append(row)
        print(json.dumps(dict(phase='control', name=name, passed=row['passed'])), flush=True)
    summary = dict(complete=True, passed=all(r['passed'] for r in records), controls=len(records),
        passed_controls=sum(r['passed'] for r in records), worker_executions=2 * len(records),
        model_calls=0, eda_calls=0, elapsed_s=time.monotonic() - tick,
        baseline_runtime_sha256=sha(original.encode()), candidate_runtime_sha256=sha(candidate.encode()),
        formatter_sha256=sha(formatter.read_bytes()), driver_sha256=sha(Path(__file__).read_bytes()),
        full_batch_complete=False, deployed=False,
        scope='Actual-worker control-flow test with fixed responses and compiler stubs; not real EDA or model quality')
    (a.out / 'private_records.json').write_text(json.dumps(records, indent=2) + '\n')
    (a.out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    if not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
