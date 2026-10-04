"""AMD-only whole-source public fixture preflight. No model calls or official score."""
import argparse
import ast
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
UPSTREAM = '2cdaae80ae42c211b049aa521fc2b5db1c2037af'
ZIP_SHA = '2f789ccb8684fb22352adc55e4d5f57c58ea32ddbfe3c5020c329ff7b209ed3d'
MANIFEST_SHA = 'b0864aea493587c3fef1ff156b4fa49d52bd2ee712e9f28f94909d9e69252818'
WHEEL = 'cocotb-1.9.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'
WHEEL_SHA = 'ff2460fb60444bfbe28a8119aad7f7297a97b53356426f03d0cdee2b90d3bc1a'
SEED = 20261004


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def worker(a):
    # This fresh process has an allowlisted environment, no provider/hidden-test config.
    from cocotb.runner import get_runner
    config = json.loads(a.case.read_text())
    build = a.case.parent / 'build'
    runner = get_runner('icarus')
    runner.build(sources=[config['design']], hdl_toplevel=config['top'],
                 build_args=['-g2012'], build_dir=build, always=True,
                 timescale=('1ns', '1ps'))
    save(a.case.parent / 'BUILD_OK.json', dict(design_sha256=sha(config['design'])))
    runner.test(hdl_toplevel=config['top'], test_module=config['test_module'],
                build_dir=build, test_dir=config['test_dir'],
                results_xml=str(a.case.parent / 'results.xml'),
                timescale=('1ns', '1ps'), seed=SEED)


def cvdp_public_input(materials, out):
    raw = materials / 'cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl'
    assert sha(raw) == 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    inventory = module(HERE / 'cvdp_inventory_20261004.py', 'cvdp_static')
    records = []
    for row in map(json.loads, raw.read_text().splitlines()):
        top = inventory.entrypoint_map(row)['resolved_top']
        # Pinned upstream dataset_processor.py:1088-1119; no output CONTENT/harness.
        prompt = ''.join(f'\nConsider the following content for the file {p}:\n```\n{c}\n```'
                         for p, c in row['input']['context'].items())
        prompt += f"\nProvide me one answer for this request: {row['input']['prompt']}\n"
        prompt += f"Name the files as: {list(row['output']['context'])}.\n"
        token = r'(?<![A-Za-z0-9_$])' + re.escape(top) + r'(?![A-Za-z0-9_$])'
        records.append(dict(id=row['id'], public_input_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                            in_prompt=bool(re.search(token, row['input']['prompt'])),
                            in_full_public_input=bool(re.search(token, prompt)),
                            top=top, admitted=False))
    assert len(records) == 302
    save(out / 'PRIVATE_CVDP_PUBLIC_INPUT.json', records)
    return dict(records=302, missing_top_in_prompt=sum(not r['in_prompt'] for r in records),
                missing_top_in_full_public_input=sum(not r['in_full_public_input'] for r in records),
                literal_token_audit_only=True, functional_admission=0)


def run(a):
    assert sys.platform == 'linux'
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    paired = module(REPO / '03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py', 'gt_owned')
    paired.check_resource(a.resource_check, a.kit, first=True)
    a.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = dict(schema='gatetruth_public_fixture_preflight_v1', complete=False,
                  source_commit=(REPO / 'DELIVERY_COMMIT').read_text().strip(), upstream=UPSTREAM,
                  model_calls=0, full_experiment_complete=False, independent_tasks_admitted=0,
                  scope='60 public references and empty-interface controls; no hidden tests/PPA/official score',
                  environment_difference='Icarus 13 / Python 3.12; upstream pins Icarus 12 / Python 3.11',
                  controls=[], commands=[], error=None)

    def publish(phase):
        result.update(phase=phase, elapsed_s=time.monotonic() - started)
        save(a.out / 'summary.json', result)
        print(json.dumps(dict(phase=phase, completed_controls=len(result['controls']),
                              model_calls=0, elapsed_s=result['elapsed_s'])), flush=True)

    def command(label, argv, cwd, cap, env=None):
        paired.check_resource(a.resource_check, a.kit)
        if time.monotonic() - started > 840 or shutil.disk_usage(a.out).free < 3 * 1024**3:
            raise RuntimeError('frozen time/disk gate')
        if env is not None:
            argv = ['/usr/bin/env', '-i'] + [k + '=' + v for k, v in env.items()] + [str(x) for x in argv]
        receipt = paired.owned_command([str(x) for x in argv], cwd, a.out / (label + '.log'), cap)
        result['commands'].append(dict(label=label, **receipt))
        if receipt.get('timeout') or receipt.get('launch_error') or receipt.get('remaining_live_group') != []:
            raise RuntimeError('owned command supervision: ' + label)
        return receipt

    try:
        source_zip = a.materials / ('GateTruth_' + UPSTREAM + '.zip')
        assert sha(source_zip) == ZIP_SHA
        assert sha(a.toolchain_manifest) == MANIFEST_SHA
        tool = json.loads(a.toolchain_manifest.read_text())
        prefix = Path(tool['prefix'])
        assert {str(p.relative_to(prefix)): sha(p) for p in prefix.rglob('*') if p.is_file()} == tool['files']
        assert sha(a.materials / WHEEL) == WHEEL_SHA
        root = a.out / 'upstream'
        with zipfile.ZipFile(source_zip) as z:
            base = 'GateTruth-' + UPSTREAM + '/'
            # Materialize only public task fixtures and the reviewed no-op hidden loader.
            for name in z.namelist():
                rel = name.removeprefix(base)
                if not (rel.startswith('tasks/') or rel in ('harness/__init__.py', 'harness/hidden.py', 'harness/env_compat.py')):
                    continue
                path = root / rel
                assert path.resolve().is_relative_to(root.resolve())
                assert ((z.getinfo(name).external_attr >> 16) & 0o170000) != 0o120000
                if name.endswith('/'):
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(z.read(name))
            requirements = z.read(base + 'flows/requirements.txt').decode()
        assert WHEEL_SHA in requirements
        find_wheel = a.materials / 'wheels/find_libpython-0.5.1-py3-none-any.whl'
        assert sha(find_wheel) == '723a8cfe6fed255a1f58b53c62ed556fb340ec0d456e9863ebc01a5cc047607d'
        tasks = sorted(p for p in (root / 'tasks').iterdir() if p.is_dir())
        assert len(tasks) == 60
        frozen = []
        for task in tasks:
            interface = (task / 'interface.sv').read_text()
            clean = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', interface)
            names = re.findall(r'\bmodule\s+([A-Za-z_]\w*)', clean)
            assert len(names) == 1, 'ambiguous interface module'
            assert not re.search(r'\b(assign|always|always_comb|always_ff|initial)\b', clean), 'nonempty interface'
            test = task / 'tb' / ('test_' + task.name + '.py')
            tree = ast.parse(test.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(n.name in ('random', 'cocotb') for n in node.names), 'unexpected TB import'
                if isinstance(node, ast.ImportFrom):
                    assert node.module in ('random', 'collections', 'cocotb.clock', 'cocotb.triggers', 'harness.hidden'), 'unexpected TB import'
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in ('open', 'eval', 'exec', '__import__', 'compile'), 'unexpected TB IO/code'
            files = {str(p.relative_to(task)): sha(p) for p in task.rglob('*') if p.is_file()}
            assert 'ref/ref.sv' in files and 'spec.md' in files
            assert not re.search(r'\$(system|fopen)\b|`include', (task / 'ref/ref.sv').read_text()), 'reference external IO'
            frozen.append(dict(task_id=task.name, top=names[0], files=files,
                               controls=['original_reference', 'empty_interface'], admitted=False))
        save(a.out / 'PRIVATE_FROZEN_INPUTS.json', dict(tasks=frozen, seed=SEED,
             source_sha256=ZIP_SHA, interfaces_used_only_for_negative_controls=True,
             exposure='All task metadata/interfaces/test AST inspected for admission; no solver tuning. Not untouched holdout.'))
        result['cvdp_public_input'] = cvdp_public_input(a.materials, a.out)
        publish('all_60_inputs_and_both_controls_frozen')
        site = a.out / 'python_site'
        env = dict(PATH=str(prefix / 'bin') + ':/usr/local/bin:/usr/bin:/bin',
                   PYTHONPATH=str(site) + ':' + str(root), PYTHONDONTWRITEBYTECODE='1',
                   PYTHONHASHSEED='0', HOME=str(a.out), LANG='C.UTF-8',
                   RANDOM_SEED=str(SEED), GATETRUTH_HIDDEN_ROOT='', SILICONBENCH_HIDDEN_ROOT='')
        receipt = command('install_pinned_cocotb', ['/usr/bin/python3', '-m', 'pip', 'install',
            '--target', site, '--no-deps', '--no-cache-dir', '--no-index', a.materials / WHEEL, find_wheel], a.out, 60)
        assert receipt['returncode'] == 0, 'dependency installation failed'
        result['environment'] = dict(toolchain_manifest_sha256=MANIFEST_SHA,
                                      cocotb_wheel_sha256=WHEEL_SHA, seed=SEED)
        for index, (task, record) in enumerate(zip(tasks, frozen)):
            for label in record['controls']:
                folder = a.out / 'controls' / task.name / label
                folder.mkdir(parents=True)
                design = task / ('ref/ref.sv' if label == 'original_reference' else 'interface.sv')
                case = folder / 'case.json'
                save(case, dict(design=str(design), top=record['top'],
                                test_module='test_' + task.name, test_dir=str(task / 'tb')))
                receipt = command(f'{index:02d}_{label}', ['/usr/bin/python3', '-B', __file__, '--case', case], folder, 60, env)
                xml = folder / 'results.xml'
                tests = list(ET.parse(xml).getroot().iter('testcase')) if xml.exists() else []
                failures = sum(t.find('failure') is not None or t.find('error') is not None for t in tests)
                skips = sum(t.find('skipped') is not None for t in tests)
                build_ok = (folder / 'BUILD_OK.json').exists()
                passed = build_ok and bool(tests) and failures == skips == 0 and receipt['returncode'] == 0
                item = dict(task_id=task.name, label=label, build_ok=build_ok, tests=len(tests),
                            failures=failures, skips=skips, passed=passed,
                            negative_detected=label == 'empty_interface' and build_ok and failures > 0,
                            returncode=receipt['returncode'], elapsed_s=receipt['elapsed_s'])
                result['controls'].append(item)
                publish('public_fixture_controls')
        result['complete'] = len(result['controls']) == 120
        result['reference_passes'] = sum(c['passed'] for c in result['controls'] if c['label'] == 'original_reference')
        result['empty_detected'] = sum(c['negative_detected'] for c in result['controls'])
        result['paired_control_passes'] = sum(
            result['controls'][2*i]['passed'] and result['controls'][2*i+1]['negative_detected'] for i in range(60))
        publish('complete_public_preflight')
    except BaseException as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        publish('failed_preserved')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', type=Path)
    parser.add_argument('--materials', type=Path)
    parser.add_argument('--toolchain-manifest', type=Path)
    parser.add_argument('--kit', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--resource-check', type=Path)
    args = parser.parse_args()
    worker(args) if args.case else run(args)
