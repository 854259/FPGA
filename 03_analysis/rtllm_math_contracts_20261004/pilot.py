"""Run frozen controls and archived candidates under the owned resource guard."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import time


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")


def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def main():
    ap=argparse.ArgumentParser()
    for name in ("root","kit","resource-check"):ap.add_argument("--"+name,type=Path,required=True)
    args=ap.parse_args();root=args.root.resolve();spec=json.loads((root/"RUN_SPEC.json").read_text())
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    deps=Path(spec["dependencies_cloud"])
    for name,h in spec["dependency_hashes"].items():assert sha(deps/name)==h
    paired=load("owned_math_probe",deps/"paired_checkpoint.py");paired.REPO=root;paired.INHERITED_ORACLE=deps/"probe_runner.py"
    paired.check_resource(args.resource_check,args.kit,first=True)
    out=root/"results";out.mkdir(exist_ok=False);start=time.monotonic()
    report=dict(complete=False,verified=False,controls={},candidates={},synthesis={},model_calls=0,run_spec_sha256=sha(root/"RUN_SPEC.json"))
    def gate():
        assert time.monotonic()-start<spec["timeout_s"]
        for name,h in spec["source_hashes"].items():assert sha(root/name)==h,name
        for name,h in spec["dependency_hashes"].items():assert sha(deps/name)==h,name
        assert sha(root/"RUN_SPEC.json")==report["run_spec_sha256"]
        paired.check_resource(args.resource_check,args.kit)
    try:
        for contract in spec["contracts"]:
            task=contract["task"];folder=root/"inputs"/task;test=dict(task=task,checks=contract["checks"],tb="inputs/"+task+"/tb.sv")
            controls={}
            for name in ("positive","negative"):
                gate();controls[name]=paired.oracle(test,folder/(name+".sv"),out/"controls"/task/name)
                assert controls[name]["checks"]==contract["checks"]
                assert controls[name]["status"]==("pass" if name=="positive" else "fail")
                if name=="negative":assert controls[name]["failure_kind"]=="semantic_mismatch"
            report["controls"][task]=controls
            gate();synth=out/"synthesis"/task;synth.mkdir(parents=True)
            (synth/"dut.sv").write_bytes((folder/"positive.sv").read_bytes())
            (synth/"run.tcl").write_text('if {[catch {read_verilog -sv dut.sv; synth_design -top TopModule -part '+spec["part"]+'} err]} {puts "CONTRACT_SYNTHESIS_FAIL: $err"; exit 1}\nputs "CONTRACT_SYNTHESIS_PASS"\nexit 0\n')
            command=["/workspace/AMD/2026.1/Vivado/bin/vivado","-mode","batch","-source","run.tcl","-nolog","-nojournal"]
            result=paired.owned_command(command,synth,synth/"synth.log",90)
            assert result["returncode"]==0 and not result["remaining_live_group"]
            assert "CONTRACT_SYNTHESIS_PASS" in (synth/"synth.log").read_text()
            report["synthesis"][task]=result
            report["candidates"][task]={}
            for side in ("agent","baseline"):
                gate();r=paired.oracle(test,folder/(side+".sv"),out/"candidates"/task/side)
                assert r["status"]!="environment_error"
                report["candidates"][task][side]=r
            save(out/"summary.json",report)
            print(json.dumps(dict(task=task,controls_valid=True,positive_synthesized=True,candidates={s:r["status"] for s,r in report["candidates"][task].items()})),flush=True)
        gate();report["complete"]=report["verified"]=True
    except BaseException as e:report["error"]=type(e).__name__+": "+str(e)
    finally:
        report["elapsed_s"]=time.monotonic()-start;save(out/"summary.json",report)
    print(json.dumps({k:report.get(k) for k in ("complete","verified","error","elapsed_s")}),flush=True)
    return 0 if report["verified"] else 1


if __name__=="__main__":raise SystemExit(main())
