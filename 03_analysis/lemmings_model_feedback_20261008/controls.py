"""Direct AMD-only qualification functions. Scheduling remains with the owner.

The caller provides the unchanged paired oracle and bounded execution wrapper.
No GPU/model request and no private judge/reference read occurs here.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.request

import lemmings_feedback as feedback
import test_lemmings_feedback as pure_tests

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def no_network(*args, **kwargs):
    raise RuntimeError('qualification controls may not make model/network calls')


def pure(out):
    """Only protocol/contract controls; this result is never native evidence."""
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('AMD-only stage must use Python -B')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    stream = io.StringIO()
    with patch.object(urllib.request, 'urlopen', no_network):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(pure_tests.CompleteContractControls)
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    log = out / 'pure_tests.log'
    log.write_text(stream.getvalue(), encoding='utf-8', newline='\n')
    summary = dict(complete=True, passed=result.wasSuccessful(), tests=result.testsRun,
                   simulated_protocol_only=True, model_calls=0, eda_calls=0,
                   log_sha256=sha(log))
    save(out / 'PURE_RESULT.json', summary)
    if result.testsRun != 7 or not result.wasSuccessful():
        raise RuntimeError('Lemmings pure controls failed; preserve this original output')
    return summary


def native(paired, root, out, before_case=None):
    """Run each frozen synthetic case once via the existing paired oracle.

    before_case is the owner's existing budget/receipt callback. This function
    does not create a FIFO, service, subprocess supervisor or alternate oracle.
    A partial failure is preserved and is not automatically retried.
    """
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('AMD-only stage must use Python -B')
    root, out = Path(root).resolve(), Path(out).resolve()
    out.relative_to(root)
    out.mkdir(parents=True, exist_ok=False)
    plan = json.loads((HERE / 'NATIVE_CASES.json').read_text(encoding='utf-8'))
    if plan['native_cases'] != 21 or plan['max_eda_calls'] != 63 or len(plan['cases']) != 21:
        raise RuntimeError('unexpected native control plan')
    results = []
    with patch.object(urllib.request, 'urlopen', no_network):
        for case in plan['cases']:
            if before_case is not None:
                before_case(case)
            source = HERE / case['file']
            if sha(source) != case['sha256']:
                raise RuntimeError('native fixture source changed')
            prompt = pure_tests.prompt(case['variant'])
            parsed = feedback.parse(prompt)
            if parsed is None:
                raise RuntimeError('complete qualification prompt did not parse')
            case_out = out / case['name']
            text = feedback.check(prompt, source.read_text(encoding='utf-8'), case_out,
                                  0, paired, 'SyntheticLemmings', root)
            check = case_out / 'lemmings_check_0'
            oracle = json.loads((check / 'probe/adapter_receipt.json').read_text(encoding='utf-8'))
            if case['expected'] == 'pass':
                if text != '' or oracle['status'] != 'pass' or oracle['mismatches'] != 0:
                    raise RuntimeError('synthetic positive failed: ' + case['name'])
            else:
                if not text or oracle['status'] != 'fail' or oracle['failure_kind'] != 'semantic_mismatch':
                    raise RuntimeError('synthetic negative was not detected: ' + case['name'])
                point = json.loads((check / 'counterexample.json').read_text(encoding='utf-8'))
                if text != feedback.feedback_text(point):
                    raise RuntimeError('counterexample does not reproduce feedback')
            record = dict(case=case['name'], variant=case['variant'], synthetic=True, passed=True,
                          expected=case['expected'], native_stage_count=len(oracle['stages']),
                          fixture_sha256=sha(source), checks=parsed['checks'],
                          mismatches=oracle['mismatches'],
                          oracle_receipt_sha256=sha(check / 'probe/adapter_receipt.json'),
                          trace_binding_sha256=sha(check / 'trace_binding.json'))
            save(case_out / 'QUALIFICATION_RESULT.json', record)
            results.append(record)
    summary = dict(complete=True, passed=True, artificial_qualification_only=True,
                   score_measured=False, model_calls=0, cases=results,
                   native_cases=len(results), eda_calls=sum(x['native_stage_count'] for x in results))
    if summary['eda_calls'] != 63:
        raise RuntimeError('native stage count differs from the frozen plan')
    save(out / 'NATIVE_RESULT.json', summary)
    return summary
