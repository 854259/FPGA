"""AMD-only S1: audit all302 runner RNG sites; capture safe runner plans, no EDA/LLM."""
import argparse
import ast
from collections import Counter
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import time
import types

DATA_SHA = 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
PAIRED_SHA = '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
PROFILES = [('env_only_11', 11, None), ('env_only_22', 22, None),
            ('fixed_11', 11, 20261005), ('fixed_22', 22, 20261005)]
HELPERS = {'d8e590bce8dce11b529ad6a9552a2117b3b49b1f05f61159bf35a6da12e01f64',
           '9a7b7775d5e1688801e10885bff65a4e643569944bf48c913368deb731e80783',
           'ebb8c0b035365109d160f6d66356a10f91ed62c36c4c312986f19c70787129c8'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')


def dotted(n):
    if isinstance(n, ast.Name): return n.id
    if isinstance(n, ast.Attribute): return dotted(n.value) + '.' + n.attr
    return '?'


def inspect_runner(source):
    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    aliases, imported, unsafe = {}, [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported.append(a.name); aliases[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom):
            imported.append(n.module)
            for a in n.names: aliases[a.asname or a.name] = (n.module or '') + '.' + a.name
    allowed_imports = {'os', 'pathlib', 'random', 'pytest', 'math', 'cocotb_tools.runner',
                       'cocotb', 'pickle', 'datetime', 'harness_library'}
    unsafe += ['import:' + str(x) for x in imported if x not in allowed_imports]
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    safe_calls = {'print','range','int','str','float','bool','list','tuple','dict','set',
                  'len','min','max','sum','abs','enumerate','zip','sorted','round',
                  'os.getenv','os.getcwd','os.path.dirname','os.path.abspath','os.path.join',
                  'pathlib.Path','pytest.mark.parametrize','cocotb_tools.runner.get_runner',
                  'runner','runner.build','runner.test','sim_runner.build','sim_runner.test',
                  'datetime.datetime.now','math.ceil','math.log2','math.gcd','n_rom.bit_length',
                  'harness_library.populate_matrix','harness_library.convert_2d_to_flat'}
    rng = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        name = dotted(n.func); head, *tail = name.split('.')
        name = '.'.join([aliases.get(head, head)] + tail)
        if name.startswith('random.'):
            parent, scope = n, 'module_or_decorator'
            while parent in parents:
                child, parent = parent, parents[parent]
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) and child in parent.body:
                    scope = 'test_or_runner_body'; break
            rng.append(dict(line=n.lineno, call=name, scope=scope))
        permitted_random = {'random.randint','random.randrange','random.choice','random.choices',
                            'random.sample','random.shuffle','random.random','random.uniform',
                            'random.getrandbits','random.seed'}
        getenv_split = (isinstance(n.func, ast.Attribute) and n.func.attr == 'split'
                        and isinstance(n.func.value, ast.Call)
                        and dotted(n.func.value.func) == 'os.getenv' and not n.args and not n.keywords)
        timestamp = (isinstance(n.func, ast.Attribute) and n.func.attr == 'strftime'
                     and isinstance(n.func.value, ast.Call)
                     and dotted(n.func.value.func) == 'datetime.now')
        if name not in safe_calls | functions | permitted_random and not getenv_split and not timestamp:
            unsafe.append('call:' + name)
    return dict(rng_sites=rng, imports=sorted(set(imported)), unsafe=sorted(set(unsafe)))


def helper_functions(source):
    kept=[]
    for n in ast.parse(source).body:
        if isinstance(n, ast.FunctionDef) and n.name in {'populate_matrix','convert_2d_to_flat'}:
            assert hashlib.sha256(ast.get_source_segment(source,n).encode()).hexdigest() in HELPERS
            kept.append(n)
    return kept


def child(a):
    # Real pytest collection/test functions; simulator commands captured by an explicit stub.
    # No cocotb test module, RTL, reference or output candidate is loaded or executed.
    import pytest
    profile, incoming, fixed = next(p for p in PROFILES if p[0] == a.profile)
    records = []
    def clean(x):
        if isinstance(x, Path): x = str(x)
        if isinstance(x, str): return x.replace(str(a.case), '$CASE')
        if isinstance(x, (list, tuple)): return [clean(v) for v in x]
        if isinstance(x, dict): return {str(k):clean(v) for k,v in x.items()}
        if x is None or isinstance(x, (bool, int, float)): return x
        raise TypeError(type(x).__name__)
    class Capture:
        def build(self, *args, **kw): records.append(dict(kind='build',args=clean(args),kwargs=clean(kw)))
        def test(self, *args, **kw): records.append(dict(kind='test',args=clean(args),kwargs=clean(kw)))
    def get_runner(*args, **kw):
        records.append(dict(kind='get_runner', args=clean(args), kwargs=clean(kw)))
        return Capture()
    module = types.ModuleType('cocotb_tools.runner'); module.get_runner = get_runner
    package = types.ModuleType('cocotb_tools'); package.runner = module
    sys.modules['cocotb_tools'] = package; sys.modules['cocotb_tools.runner'] = module
    helper=types.ModuleType('harness_library');helper.random=random
    helper_source=a.case/'harness_library_source.py'
    if helper_source.exists():
        # Only the three reviewed, byte-bound pure array functions; no filesystem/waveform helpers.
        selected=ast.Module(body=helper_functions(helper_source.read_text()),type_ignores=[])
        exec(compile(selected,str(helper_source),'exec'),helper.__dict__)
    sys.modules['harness_library']=helper
    def deny(event, args):
        if event in {'subprocess.Popen','os.system','os.posix_spawn','socket.connect','socket.bind'}:
            raise RuntimeError('S1 forbids actual process/network operations: ' + event)
    sys.addaudithook(deny)
    random.seed(incoming)
    if fixed is not None: random.seed(fixed)
    code = pytest.main(['-q','-s','-p','no:cacheprovider',str(a.case/'test_runner.py')])
    save(a.case/'CAPTURE.json', dict(profile=profile, incoming_rng_seed=incoming,
         wrapper_rng_seed=fixed, pytest_exitcode=int(code), simulator_is_stub=True,
         actual_eda_calls=0, records=records))
    return int(code)


def run(a):
    assert sys.platform == 'linux'
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    assert sha(a.data) == DATA_SHA and sha(a.paired) == PAIRED_SHA
    assert sha(a.previous)=='2aeafda7c51ebbc71e0f6f433f324f89037cb54ee302bf58446c2a751cc17c62'
    previous=json.loads(a.previous.read_text())
    completed={r['task'] for r in previous['rows'] if r.get('capture_valid')}
    assert len(completed)==21 and previous['complete']
    s = importlib.util.spec_from_file_location('s1_owned', a.paired)
    paired = importlib.util.module_from_spec(s); s.loader.exec_module(paired)
    paired.check_resource(a.resource_check, a.kit, first=True)
    a.out.mkdir(parents=True, exist_ok=False); start = time.monotonic()
    source = [json.loads(line) for line in a.data.read_text().splitlines() if line.strip()]
    assert len(source) == len({r['id'] for r in source}) == 302
    result = dict(schema='cvdp_runner_rng_S2', complete=False, source_sha256=DATA_SHA,
        records=302, model_calls=0, eda_calls=0, independent_tasks_admitted=0,
        full_batch_complete=False, scope='Runner plan replay with simulator stub; not RTL or grading',
        profiles=PROFILES, previous_valid_not_repeated=21, previous_sha256=sha(a.previous), rows=[], error=None)
    try:
        for row in source:
            runner = row['harness']['files'].get('src/test_runner.py')
            if runner is None: raise ValueError('Missing previously mapped runner: ' + row['id'])
            info = inspect_runner(runner)
            helper_source=row['harness']['files'].get('src/harness_library.py','')
            if 'harness_library' in info['imports']:
                helper_functions(helper_source)
            result['rows'].append(dict(task=row['id'], runner_sha256=hashlib.sha256(runner.encode()).hexdigest(),
                **info, previous_valid=row['id'] in completed,
                dynamic_eligible=bool(info['rng_sites']) and not info['unsafe'] and row['id'] not in completed))
        # Freeze the entire source-only cohort before observing any runner output.
        save(a.out/'COHORT.json', result['rows'])
        selected = {r['task']:r for r in result['rows'] if r['dynamic_eligible']}
        for row in source:
            if row['id'] not in selected: continue
            if time.monotonic()-start > 780: raise TimeoutError('Stop new work reserve')
            paired.check_resource(a.resource_check, a.kit)
            plans = []
            for profile, _, _ in PROFILES:
                case = a.out/'cases'/row['id']/profile; case.mkdir(parents=True)
                (case/'test_runner.py').write_bytes(row['harness']['files']['src/test_runner.py'].encode())
                if 'src/harness_library.py' in row['harness']['files']:
                    (case/'harness_library_source.py').write_bytes(row['harness']['files']['src/harness_library.py'].encode())
                env = dict(PYTHONPATH=str(a.site), PYTHONHASHSEED='0',
                    PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                    COCOTB_RANDOM_SEED='20261005', SIM='icarus', TOPLEVEL_LANG='verilog',
                    TOPLEVEL='S1_CAPTURE_ONLY', MODULE='S1_NOT_IMPORTED',
                    VERILOG_SOURCES=str(case/'NEVER_COMPILED.sv'))
                argv=['/usr/bin/env']+[k+'='+v for k,v in env.items()]+[
                    '/usr/bin/python3','-B',str(Path(__file__).resolve()),'--child',
                    '--case',str(case),'--profile',profile]
                rc=paired.owned_command(argv,case,case/'driver.log',10)
                save(case/'COMMAND.json',rc)
                if rc.get('timeout') or rc.get('launch_error') or rc.get('remaining_live_group') != []:
                    raise RuntimeError('Runner process supervision failed')
                cap=json.loads((case/'CAPTURE.json').read_text()) if (case/'CAPTURE.json').exists() else None
                plans.append(dict(profile=profile,returncode=rc['returncode'],capture=cap))
            item=selected[row['id']]
            valid=all(p['returncode']==0 and p['capture'] and p['capture']['records'] for p in plans)
            item['capture_valid']=valid
            item['plans']=[dict(profile=p['profile'],returncode=p['returncode'],
                trace_sha256=hashlib.sha256(json.dumps(p['capture']['records'],sort_keys=True).encode()).hexdigest()
                if p['capture'] else None) for p in plans]
            if valid:
                item['env_only_varies']=plans[0]['capture']['records'] != plans[1]['capture']['records']
                item['fixed_wrapper_identical']=plans[2]['capture']['records'] == plans[3]['capture']['records']
            save(a.out/'PRIVATE_RESULT.json',result)
            print(json.dumps(dict(done=sum('plans' in r for r in result['rows']),total=len(selected))),flush=True)
        paired.check_resource(a.resource_check,a.kit)
        assert sha(a.data)==DATA_SHA
        result.update(complete=True,cohort_sha256=sha(a.out/'COHORT.json'))
    except BaseException as e:
        result['error']=type(e).__name__+': '+str(e); raise
    finally:
        result['elapsed_s']=time.monotonic()-start
        save(a.out/'PRIVATE_RESULT.json',result)
        public={k:v for k,v in result.items() if k!='rows'}
        rr=result['rows']
        public['counts']=dict(runners_with_rng=sum(bool(r['rng_sites']) for r in rr),
            dynamic_eligible=sum(r['dynamic_eligible'] for r in rr),
            capture_valid=sum(r.get('capture_valid',False) for r in rr),
            env_only_varies=sum(r.get('env_only_varies',False) for r in rr),
            fixed_wrapper_identical=sum(r.get('fixed_wrapper_identical',False) for r in rr))
        public['blocked_calls']=dict(Counter(x for r in rr if r['rng_sites'] for x in r['unsafe']))
        public['private_result_sha256']=sha(a.out/'PRIVATE_RESULT.json')
        save(a.out/'PUBLIC_RESULT.json',public)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--child',action='store_true')
    p.add_argument('--profile');p.add_argument('--case',type=Path)
    for n in ['data','out','site','paired','kit','resource-check','previous']:p.add_argument('--'+n,type=Path)
    a=p.parse_args()
    if a.child: sys.exit(child(a))
    run(a)
