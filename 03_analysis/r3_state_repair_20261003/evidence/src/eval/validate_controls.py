"""Revalidate the six frozen R3 probe controls before any model generation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

TASK_CHECKS = {'Prob086_lfsr5': 269, 'Prob085_shift4': 209,
               'Prob033_ece241_2014_q1c': 65536}
HELPER_SHA = '954a1bcac0015e9d0d104eade9d75d111e819ad827343cc4a462e4eb055beac0'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool_ids():
    paths = {name: shutil.which(name) for name in ('xvlog', 'xelab', 'xsim')}
    if not all(paths.values()):
        raise ValueError('all three EDA executables are required before controls')
    return {name: {'path': path, 'sha256': digest(path)} for name, path in paths.items()}


def validate(args):
    helper_path, root = Path(args.probes).resolve(), Path(args.probe_root).resolve()
    if digest(helper_path) != HELPER_SHA or digest(root / 'probe_runner.py') != HELPER_SHA:
        raise ValueError('original bottom-level probe runner changed')
    spec = importlib.util.spec_from_file_location('r3_control_helper', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.ROOT, helper.TASK_CHECKS = root, dict(TASK_CHECKS)
    before_tools = tool_ids()
    result = helper.validate_controls(args.out)
    after_tools = tool_ids()
    result.update(tools_before=before_tools, tools_after=after_tools,
                  tools_unchanged=before_tools == after_tools,
                  validator_sha256=digest(__file__))
    if not result['tools_unchanged']:
        result['valid'] = False
    # Preserve the helper's schema; append tool provenance before the run is frozen.
    (Path(args.out) / 'controls_validation.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    # The helper parses the complete simulation summary against TASK_CHECKS.
    # Compile/launch/timeout failures cannot validate a negative control.
    result_ok = (result['complete'] is True and result['valid'] is True
                 and result['assets_unchanged'] is True)
    print(json.dumps({'valid': result_ok, 'controls': {
        task: {role: {key: rows[role][key] for key in
                       ('status', 'failure_kind', 'checks', 'mismatches')}
               for role in ('positive', 'negative')}
        for task, rows in result['tasks'].items()}}, ensure_ascii=False), flush=True)
    return 0 if result_ok else 1


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probes', required=True)
    parser.add_argument('--probe-root', required=True)
    parser.add_argument('--out', type=Path, required=True)
    return validate(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
