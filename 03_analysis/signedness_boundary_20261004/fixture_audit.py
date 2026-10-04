"""AMD-only isolated fixture-port audit. No model calls or original edits."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run(args):
    if sys.platform != "linux" or ctypes.CDLL(None, use_errno=True).prctl(36,1,0,0,0):
        raise RuntimeError("AMD Linux owned-child subreaper required")
    spec = json.loads((HERE / "FIXTURE_SPEC.json").read_text())
    task = args.kit / "bench/tasks_veval" / spec["task"]
    archive = Path(spec["archive"])
    originals = {str(task/p):h for p,h in spec["task_hashes"].items()}
    originals.update({str(archive/m/spec["task"]/'s0/solution.v'):h for m,h in spec["candidate_hashes"].items()})
    originals[str(args.kit/'official_eval.py')] = spec['adapter_sha256']
    if any(sha(p) != h for p,h in originals.items()):
        raise RuntimeError("frozen evidence changed before audit")
    paired = load("fixture_owned_resources", REPO / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    paired.check_resource(args.resource_check,args.kit,first=True)
    evaluator = load("fixture_official_adapter",args.kit/'official_eval.py')
    upstream = evaluator.verify_upstream()
    if upstream != spec["upstream_commit"]:
        raise RuntimeError("official source changed")
    args.out.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    report=dict(schema="isolated_fixture_port_audit_E1",complete=False,valid=False,model_calls=0,
                task=spec['task'],original_hashes=originals,upstream_commit=upstream,rows={},error=None,
                formal_inputs_modified=False,new_full_score=False)
    try:
        old=args.out/'original_task';fixed=args.out/'corrected_task'
        shutil.copytree(task,old);shutil.copytree(task,fixed)
        old_tb=(old/'tb.sv').read_bytes();text=old_tb.decode('utf-8')
        if text.count('.Y2(') != 2 or text.count('.Y4(') != 2:
            raise RuntimeError("unexpected port binding pattern")
        updated=text.replace('.Y2(','.Y1(').replace('.Y4(','.Y3(')
        (fixed/'tb.sv').write_bytes(updated.encode('utf-8'))
        if updated.replace('.Y1(','.Y2(').replace('.Y3(','.Y4(') != text:
            raise RuntimeError("nonlocal fixture edit")
        for name in spec['task_hashes']:
            if name != 'tb.sv' and sha(old/name) != sha(fixed/name):
                raise RuntimeError("unexpected copied task change")
        negative=(fixed/'reference/solution.sv').read_text()
        negative,n=re.subn(r'(assign\s+Y1\s*=\s*)([^;]+)(;)',lambda m:m[1]+'~('+m[2]+')'+m[3],negative)
        if n != 1:
            raise RuntimeError("negative control output assignment not unique")
        neg=args.out/'negative_control.sv';neg.write_text(negative)
        sources={'old_reference':old/'reference/solution.sv','corrected_reference':fixed/'reference/solution.sv',
                 'negative_control':neg,'archived_agent':archive/'agent'/spec['task']/'s0/solution.v',
                 'archived_baseline':archive/'baseline'/spec['task']/'s0/solution.v'}
        copied={str(p.relative_to(args.out)):sha(p) for folder in (old,fixed) for p in folder.rglob('*') if p.is_file()}
        save(args.out/'inputs_frozen.json',dict(original=originals,copied=copied,negative_sha256=sha(neg),spec_sha256=sha(HERE/'FIXTURE_SPEC.json')))
        for name in spec['order']:
            paired.check_resource(args.resource_check,args.kit)
            if any(sha(p) != h for p,h in originals.items()):
                raise RuntimeError("original evidence changed")
            destination=args.out/'grades'/name;destination.mkdir(parents=True)
            verdict=evaluator.judge_sample(old if name=='old_reference' else fixed,sources[name],destination,destination/'verdict.json',90)
            report['rows'][name]=verdict
            if verdict.get('tool_error'):
                raise RuntimeError("judge environment/tool error: "+str(verdict['tool_error']))
            if name=='old_reference':
                log=(destination/'judge_work_logs/w_judge.log').read_text(errors='replace')
                evidence=[line for line in log.splitlines() if re.search(r'(port.*(?:Y2|Y4)|(?:Y2|Y4).*port)',line,re.I)]
                report['old_port_diagnostics']=evidence
                if verdict['level']!=0 or not evidence:
                    raise RuntimeError("old binding failure not reproduced with diagnostics")
            if name=='corrected_reference' and verdict['level']!=3:
                raise RuntimeError("corrected positive control failed")
            if name=='negative_control' and (verdict['level']!=1 or not verdict['stages']['compile'] or verdict['stages']['simulate']):
                raise RuntimeError("negative control did not expose semantic mismatch")
            print(json.dumps({'row':name,'level':verdict['level'],'tool_error':verdict.get('tool_error'),'elapsed_s':verdict.get('elapsed_s')}),flush=True)
        if any(sha(p)!=h for p,h in originals.items()) or any(sha(args.out/p)!=h for p,h in copied.items()):
            raise RuntimeError("frozen inputs changed during audit")
        paired.check_resource(args.resource_check,args.kit)
        report.update(complete=True,valid=True,inputs_unchanged=True,corrected_tb_sha256=sha(fixed/'tb.sv'),
            decision='retain_isolated_port_contract_correction_not_model_or_algorithm_gain')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        report['elapsed_s']=time.monotonic()-start
        save(args.out/'summary.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--kit',type=Path,required=True)
    parser.add_argument('--resource-check',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args())
