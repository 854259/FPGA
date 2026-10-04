"""AMD real-tool controls for missing-executable judge admission (zero model)."""
import argparse
import ctypes
import json
import os
import shutil
import sys
import time
from pathlib import Path
from pilot import REPO, load, save, sha
from elaboration_batch import OLD


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((Path(__file__).parent/'CONTINUATION_SPEC.json').read_text())
    protected={a.kit/p:h for p,h in spec['kit_hashes'].items()}
    case=next(x for x in json.loads((Path(__file__).parent/'ELABORATION_SPEC.json').read_text())['captured'] if x['label']=='correct8')
    src=Path(case['root'])/'original/solution.v'
    assert sha(src)==case['files']['original/solution.v'] and all(sha(p)==h for p,h in protected.items())
    assert sha(OLD/'taskset_manifest.json')==spec['input_manifest_sha256']
    m=json.loads((OLD/'taskset_manifest.json').read_text())['task_sha256']
    assert all(sha(OLD/'tasks_verified'/p)==h for p,h in m.items())
    paired=load('admission_owned',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    paired.check_resource(a.resource_check,a.kit,first=True)
    fixed=load('isolated_fixed_judge',REPO/'04_project/amd_rtl_agent/official_eval.py')
    fixed.OFFICIAL=a.kit/'official_reference';assert fixed.verify_upstream()==spec['upstream_commit']
    a.out.mkdir(parents=True,exist_ok=False);task=a.out/'judge_task';shutil.copytree(OLD/'tasks_verified'/case['task'],task)
    solution=a.out/'positive.v';shutil.copyfile(src,solution)
    syntax=a.out/'syntax.v';syntax.write_text('module TopModule(input a, output y); assign y = ; endmodule\n')
    report=dict(complete=False,valid=False,model_calls=0,full_round_complete=False,rows=[],error=None,
                original_evaluator_sha256=sha(a.kit/'official_eval.py'),isolated_evaluator_sha256=sha(REPO/'04_project/amd_rtl_agent/official_eval.py'))
    initial_path=os.environ['PATH'];real_which=fixed.shutil.which;tick=time.monotonic()
    try:
        for label,late in [('missing_preflight',False),('missing_after_preflight_injection',True)]:
            os.environ['PATH']='/usr/bin:/bin'
            assert all(real_which(n) is None for n in ['xvlog','xelab','xsim','vivado'])
            # Fault injection simulates a successful availability check followed by
            # an actual missing-executable launch in the unmodified pinned judge.
            if late:fixed.shutil.which=lambda name:str(Path(os.environ['VIVADO_BIN'])/name)
            dest=a.out/label;dest.mkdir();blocked=False;error=None
            try:fixed.judge_sample(task,solution,dest,dest/'verdict.json',60)
            except RuntimeError as exc:blocked=True;error=str(exc)
            finally:fixed.shutil.which=real_which
            assert blocked,error
            if late:
                receipt=json.loads((dest/'judge_receipt.json').read_text())
                assert any('tool launch failed' in s for s in receipt['errors'])
                assert '可执行文件不存在' in (dest/'judge_work_logs/w_judge.log').read_text()
            else:assert 'executable unavailable on PATH' in error and not (dest/'verdict.json').exists()
            report['rows'].append(dict(name=label,blocked_as_environment=True,error=error,model_calls=0))
        os.environ['PATH']=os.environ['VIVADO_BIN']+os.pathsep+initial_path
        for label,path,expected in [('real_positive',solution,3),('real_syntax_error',syntax,0)]:
            dest=a.out/label;dest.mkdir();v=fixed.judge_sample(task,path,dest,dest/'verdict.json',90)
            assert v['level']==expected and not v.get('tool_error') and not v.get('suspected_silent_degradation'),v
            report['rows'].append(dict(name=label,level=v['level'],tool_error=v.get('tool_error'),verdict=v))
        assert all(sha(p)==h for p,h in protected.items()) and sha(solution)==case['files']['original/solution.v']
        paired.check_resource(a.resource_check,a.kit)
        report.update(complete=True,valid=True,formal_evaluator_unchanged=True,decision='retain isolated evidence guard; no solver quality claim')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        os.environ['PATH']=initial_path;fixed.shutil.which=real_which
        report['elapsed_s']=time.monotonic()-tick;save(a.out/'summary.json',report)
    print(json.dumps({k:report[k] for k in ['complete','valid','model_calls','elapsed_s','decision']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('kit','out','resource-check'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
