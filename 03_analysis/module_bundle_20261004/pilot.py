"""Frozen same-response extraction comparison; owned guard and no retries."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import urllib.request

from extract_bundle import extract_bundle


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, data):
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load(name, p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def main():
    ap=argparse.ArgumentParser()
    for n in ("root","kit","resource-check"):ap.add_argument("--"+n,type=Path,required=True)
    args=ap.parse_args();root=args.root.resolve();spec=read(root/"RUN_SPEC.json")
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    deps=Path(spec["dependencies_cloud"])
    paired=load("bundle_owned",deps/"paired_checkpoint.py");paired.REPO=root;paired.INHERITED_ORACLE=deps/"probe_runner.py"
    baseline=load("bundle_baseline",deps/"baseline_extract.py")
    lexical=load("bundle_lexical",root/"lexical_mask.py")
    paired.check_resource(args.resource_check,args.kit,first=True)
    out=root/"results";out.mkdir(exist_ok=False);start=time.monotonic();spec_hash=sha(root/"RUN_SPEC.json")
    report=dict(schema="module_bundle_pilot_v1",complete=False,verified=False,attempts=0,responses=0,retries=0,
        controls={},format_controls={},rows=[],run_spec_sha256=spec_hash)
    save(out/"summary.json",report)
    def gate():
        assert time.monotonic()-start<spec["stage_timeout_s"]
        assert sha(root/"RUN_SPEC.json")==spec_hash
        for name,h in spec["source_hashes"].items():assert sha(root/name)==h,name
        for name,h in spec["dependency_hashes"].items():assert sha(deps/name)==h,name
        paired.check_resource(args.resource_check,args.kit)
    def probe(contract,source,folder):
        gate();r=paired.oracle(dict(task=contract["task"],checks=contract["checks"],tb="inputs/"+contract["task"]+"/tb.sv"),source,folder)
        if r["status"]=="environment_error":raise RuntimeError("Probe environment error")
        return r
    def synth(source,folder):
        gate();folder.mkdir(parents=True,exist_ok=False);(folder/"dut.sv").write_bytes(source.read_bytes())
        (folder/"run.tcl").write_text('if {[catch {read_verilog -sv dut.sv; synth_design -top TopModule -part '+spec["part"]+'} err]} {puts "BUNDLE_SYNTHESIS_FAIL: $err"; exit 1}\nputs "BUNDLE_SYNTHESIS_PASS"\nexit 0\n')
        r=paired.owned_command(["/workspace/AMD/2026.1/Vivado/bin/vivado","-mode","batch","-source","run.tcl","-nolog","-nojournal"],folder,folder/"synth.log",90)
        text=(folder/"synth.log").read_text();assert r["returncode"]==0 and not r["remaining_live_group"]
        assert "\nBUNDLE_SYNTHESIS_PASS\n" in text
        return r
    try:
        for contract in spec["contracts"]:
            controls={}
            for name in ("positive","negative"):
                controls[name]=probe(contract,root/"inputs"/contract["task"]/(name+".sv"),out/"controls"/contract["task"]/name)
                assert controls[name]["checks"]==contract["checks"]
                assert controls[name]["status"]==("pass" if name=="positive" else "fail")
                if name=="negative":assert controls[name]["failure_kind"]=="semantic_mismatch"
            report["controls"][contract["task"]]=controls
        adder=next(c for c in spec["contracts"] if c["task"]=="adder_8bit")
        for case in spec["format_controls"]:
            text=(root/case["reply"]).read_text();a=baseline.extract(text,"rtl");b,receipt=extract_bundle(text,baseline,lexical._strip_noncode)
            folder=out/"format_sources"/case["id"];folder.mkdir(parents=True)
            (folder/"A.sv").write_text(a);(folder/"B.sv").write_text(b);save(folder/"receipt.json",receipt)
            results={arm:probe(adder,folder/(arm+".sv"),out/"format_probes"/case["id"]/arm) for arm in ("A","B")}
            assert results["A"]["status"]==case["expected_A"] and results["B"]["status"]==case["expected_B"]
            if case.get("expected_B_failure_kind"):assert results["B"]["failure_kind"]==case["expected_B_failure_kind"]
            record=dict(receipt=receipt,probes=results)
            if results["B"]["status"]=="pass":record["B_synthesis"]=synth(folder/"B.sv",out/"format_synthesis"/case["id"])
            report["format_controls"][case["id"]]=record
        save(out/"preflight_verified.json",dict(controls=report["controls"],format_controls=report["format_controls"],model_calls=0))
        save(out/"summary.json",report);print(json.dumps(dict(phase="preflight_verified",model_calls=0)),flush=True)
        for task,trial in spec["generation_order"]:
            gate();paired.model_idle("http://127.0.0.1:8000/v1",spec["model"])
            folder=out/"generated"/task/str(trial);folder.mkdir(parents=True)
            payload=dict(model=spec["model"],temperature=0,top_p=1,max_tokens=spec["max_tokens"],messages=[dict(role="system",content=baseline.SYS["rtl"]),dict(role="user",content=(root/"inputs"/task/"prompt.txt").read_text())])
            save(folder/"request.json",payload);row=dict(task=task,trial=trial,request_sha256=sha(folder/"request.json"),response_received=False)
            report["rows"].append(row);report["attempts"]+=1;assert report["attempts"]<=spec["model_call_budget"]
            save(out/"summary.json",report);tick=time.monotonic()
            req=urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=spec["request_timeout_s"]) as response:raw=response.read()
            (folder/"response.json").write_bytes(raw);d=json.loads(raw);choice=d["choices"][0]
            row.update(response_received=True,response_sha256=sha(folder/"response.json"),response_id=d.get("id"),usage=d.get("usage"),finish_reason=choice.get("finish_reason"),request_elapsed_s=time.monotonic()-tick)
            report["responses"]+=1;content=choice["message"].get("content")
            assert choice.get("finish_reason")=="stop" and isinstance(content,str) and content.strip(),"Incomplete response: stop without retry"
            (folder/"answer.txt").write_text(content);a=baseline.extract(content,"rtl");b,receipt=extract_bundle(content,baseline,lexical._strip_noncode)
            (folder/"A.sv").write_text(a);(folder/"B.sv").write_text(b);save(folder/"bundle_receipt.json",receipt)
            row.update(A_sha256=sha(folder/"A.sv"),B_sha256=sha(folder/"B.sv"),bundle_changed=a!=b,bundle_receipt=receipt)
            save(out/"summary.json",report);print(json.dumps(dict(phase="generated",count=report["responses"],task=task,trial=trial)),flush=True)
        save(out/"generation_complete.json",dict(rows=report["rows"],grading_started=False))
        contracts={c["task"]:c for c in spec["contracts"]}
        for row in report["rows"]:
            folder=out/"generated"/row["task"]/str(row["trial"]);row["grades"]={}
            for arm in ("A","B"):
                p=probe(contracts[row["task"]],folder/(arm+".sv"),out/"generated_probes"/row["task"]/str(row["trial"])/arm)
                result=dict(probe=p)
                if p["status"]=="pass":
                    if arm=="B" and not row["bundle_changed"]:
                        result.update(synthesis=row["grades"]["A"]["synthesis"],synthesis_reused_identical_bytes=True)
                    else:result["synthesis"]=synth(folder/(arm+".sv"),out/"generated_synthesis"/row["task"]/str(row["trial"])/arm)
                row["grades"][arm]=result
            save(out/"summary.json",report);print(json.dumps(dict(phase="graded",task=row["task"],trial=row["trial"],A=row["grades"]["A"]["probe"]["status"],B=row["grades"]["B"]["probe"]["status"])),flush=True)
        gate();report["complete"]=True;report["verified"]=report["attempts"]==report["responses"]==spec["model_call_budget"]
    except BaseException as e:report["error"]=type(e).__name__+": "+str(e)
    finally:
        report["elapsed_s"]=time.monotonic()-start;save(out/"summary.json",report)
    print(json.dumps({k:report.get(k) for k in ("complete","verified","attempts","responses","error","elapsed_s")}),flush=True)
    return 0 if report["verified"] else 1


if __name__=="__main__":raise SystemExit(main())
