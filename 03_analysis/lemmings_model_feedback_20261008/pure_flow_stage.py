"""AMD-only once stage: existing Lemmings pure controls + adapted three flows.

The caller uses the existing bounded executor (40 seconds) and frozen packet.
No scheduler, native test, model request, or retry is implemented here.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
import urllib.request
from unittest.mock import patch

IMPLEMENTATION_MANIFEST_SHA256 = 'b5608f4d48e68a8c6f1fb40119226dd0685ade946abcdb29ef1e45fa7ae852ad'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forbidden(*args, **kwargs):
    raise RuntimeError('pure/flow stage forbids actual subprocess and network calls')


def stage(args):
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('only the authorized AMD Python -B execution is allowed')
    started = time.monotonic()
    root, out = args.root.resolve(), args.out.resolve()
    out.relative_to(root)
    if root != Path(__file__).resolve().parent or out == root:
        raise ValueError('stage and frozen source must share root; results must be separate')
    out.mkdir(parents=True, exist_ok=False)
    reports, failure = {}, None
    fixed_sources = {}
    manifest_path = root / 'SOURCE_MANIFEST.json'

    def frozen():
        if sha(manifest_path) != args.source_manifest_sha256:
            raise RuntimeError('source manifest changed')
        sources = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(sources, dict) or not sources:
            raise RuntimeError('empty or malformed source manifest')
        for name, digest in sources.items():
            path = (root / name).resolve()
            path.relative_to(root)
            if Path(name).is_absolute() or not isinstance(digest, str) or sha(path) != digest:
                raise RuntimeError('frozen source mismatch: ' + name)
        if sha(root / 'IMPLEMENTATION_MANIFEST.json') != IMPLEMENTATION_MANIFEST_SHA256:
            raise RuntimeError('not the reviewed first checker implementation')
        for name in ('controls.py', 'test_lemmings_feedback.py', 'lemmings_feedback.py',
                     'flow_controls.py', 'pure_flow_stage.py', 'baseline_worker.py',
                     'flow_fixtures/good_entry1.sv', 'flow_fixtures/bad_right_double_bump.sv'):
            if name not in sources:
                raise RuntimeError('source manifest omitted a required control: ' + name)
            fixed_sources[name] = sources[name]
        return sources

    try:
        sources = frozen()
        save(out / 'PURE_FLOW_INTENT.json', dict(real_model_max=0, real_eda_max=0,
             simulated_http_max=4, simulated_compiler_max=4, simulated_oracle_max=2,
             source_manifest_sha256=args.source_manifest_sha256,
             implementation_manifest_sha256=IMPLEMENTATION_MANIFEST_SHA256,
             fixed_control_source_hashes=fixed_sources, retries=0,
             caller_bounded_cap_seconds=40))
        with patch.object(urllib.request, 'urlopen', forbidden), \
             patch.object(subprocess, 'run', forbidden), patch.object(subprocess, 'Popen', forbidden):
            controls = load('lemmings_pure_controls_owned', root / 'controls.py')
            flow_controls = load('lemmings_flow_controls_owned', root / 'flow_controls.py')
            reports['pure'] = controls.pure(out / 'pure')
            frozen()
            reports['flow'] = flow_controls.run_all(root, out / 'flow_results', root / 'baseline_worker.py')
            frozen()
        if reports['pure']['tests'] != 7 or not reports['pure']['passed']:
            raise RuntimeError('pure controls incomplete')
        if not reports['flow']['passed'] or reports['flow']['simulated_http_calls'] != 4:
            raise RuntimeError('three original-worker flows incomplete')
    except BaseException as exc:
        failure = dict(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
    summary = dict(complete=True, passed=failure is None, real_model_calls=0, real_eda_commands=0,
                   implementation_manifest_sha256=IMPLEMENTATION_MANIFEST_SHA256,
                   source_manifest_sha256=args.source_manifest_sha256,
                   fixed_control_source_hashes=fixed_sources, reports=reports, error=failure,
                   simulated_http_calls=reports.get('flow', {}).get('simulated_http_calls'),
                   simulated_compiles=reports.get('flow', {}).get('simulated_compiles'),
                   simulated_oracles=reports.get('flow', {}).get('simulated_oracles'),
                   simulation_scope='wire/protocol integration only; no native or real-model qualification',
                   elapsed_seconds=time.monotonic() - started, scoring_run=False, accuracy_measured=False)
    save(out / 'PURE_FLOW_RESULT.json', summary)
    print(json.dumps(dict(passed=summary['passed'], pure_tests=reports.get('pure', {}).get('tests'),
                          simulated_http_calls=summary['simulated_http_calls'], error=failure)))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    raise SystemExit(stage(parser.parse_args()))
