"""Frozen diagnostic-feedback comparison; run only through the AMD resource guard."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import urllib.request

from mcp_client import StdioClient

MODEL = "Qwen3.6-27B-Q4_K_M"
ENDPOINT = "http://127.0.0.1:8000/v1"
COMMON = ("Review the candidate against the full specification. Correct functional errors with "
          "a focused edit, preserve the interface and required timing, and add no unsupported "
          "reset or initialization. If it already meets the specification, return it unchanged. "
          "Return only one complete synthesizable TopModule, without explanations or a testbench.")
SYSTEM = "You review synthesizable RTL. Use the supplied public specification as the authority."


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unpack(raw):
    return raw.get("structuredContent") or json.loads(raw["content"][0]["text"])


def main():
    ap=argparse.ArgumentParser()
    for name in ("root", "kit", "resource-check"):
        ap.add_argument("--"+name,type=Path,required=True)
    args=ap.parse_args();root=args.root.resolve();kit=args.kit.resolve()
    if ctypes.CDLL(None, use_errno=True).prctl(36,1,0,0,0)!=0:
        raise OSError("owned descendant subreaper unavailable")
    spec=read(root/"RUN_SPEC.json");out=root/"results";out.mkdir(exist_ok=False)
    for f,h in spec["source_hashes"].items():assert sha(root/f)==h,f
    assert sha(root/"official_eval.py")==spec["judge_adapter_sha256"]
    assert sha(root/"vivado-mcp-server")==spec["binary_sha256"]
    paired=load("repair_owned_adapter",root/"owned_adapter.py")
    paired.REPO=root;paired.INHERITED_ORACLE=root/"probe_runner.py"
    baseline=load("repair_fixed_extract",root/"baseline_extract.py")
    evaluator=load("repair_fixed_official",root/"official_eval.py")
    evaluator.ROOT=kit;evaluator.OFFICIAL=kit/"official_reference"
    assert evaluator.verify_upstream()==spec["official_commit"]
    paired.check_resource(args.resource_check,kit,first=True)
    started=time.monotonic()
    report=dict(schema="ross_diagnostic_repair_pilot_v1",complete=False,verified=False,
        attempts=0,responses=0,retries=0,controls={},originals={},rows=[],mcp_tool_calls=0,
        closed_sessions=[],model=MODEL,run_spec_sha256=sha(root/"RUN_SPEC.json"),new_score=False,
        full_skill_model_execution=False,formal_runtime_integrated=False)
    save(out/"summary.json",report)

    def frozen():
        assert time.monotonic()-started<spec["max_stage_elapsed_s"]
        for f,h in spec["source_hashes"].items():assert sha(root/f)==h,f
        paired.check_resource(args.resource_check,kit)

    def probe(task,source,destination):
        frozen()
        r=paired.oracle(dict(task=task,checks=spec["tasks"][task]["checks"],tb="inputs/"+task+"/tb.sv"),source,destination)
        if r["status"]=="environment_error":raise RuntimeError("XSim environment failure: "+task)
        return r

    def grade(task,source,destination):
        frozen();destination.mkdir(parents=True,exist_ok=False)
        r=evaluator.judge_sample(kit/"bench/tasks_veval"/task,source,destination,destination/"verdict.json",120)
        if r.get("tool_error") or r.get("suspected_silent_degradation"):
            raise RuntimeError("official environment failure: "+task)
        return r

    client=None;session=None
    def tool(name,arguments):
        report["mcp_tool_calls"]+=1
        raw=client.tool(name,arguments,timeout=180)
        save(out/"mcp"/("%03d_%s.json"%(report["mcp_tool_calls"],name)),raw)
        data=unpack(raw)
        assert data.get("success") is not False and data.get("status") not in ("error","failed"),data
        return data

    def execute(command):
        r=tool("vivado_execute",dict(session_id=session,command=command,mode="proxy",verbosity="full",capture_log=True))
        assert r.get("exit_code") in (None,0) and r.get("status")!="running",r
        return r

    try:
        for task,contract in spec["tasks"].items():
            d=root/"inputs"/task
            controls={n:probe(task,d/(n+".sv"),out/"controls"/task/n) for n in ("positive","negative")}
            assert controls["positive"]["status"]=="pass" and controls["negative"]["failure_kind"]=="semantic_mismatch",controls
            report["controls"][task]=controls
        (out/"mcp").mkdir()
        client=StdioClient([str(root/"vivado-mcp-server"),"--stdio","--state-dir="+str(out/"mcp/state"),"--vivado-path=/workspace/AMD/2026.1/Vivado/bin/vivado","--enable-lsf=false","--enable-ssh=false","--disable-telemetry","--disable-otel","--max-sessions=1","--limit-ai-output=false"],out/"mcp",os.environ.copy(),out/"mcp/rpc.jsonl",out/"mcp/stderr.log")
        client.request("initialize",dict(protocolVersion="2025-11-25",capabilities={},clientInfo=dict(name="ross-diagnostic-repair-pilot",version="0.1")))
        client.notify("notifications/initialized")
        for task,contract in spec["tasks"].items():
            frozen();d=root/"inputs"/task;work=out/"mcp"/task;work.mkdir()
            start=tool("vivado_start",dict(working_dir=str(work),session_type="general",gui_mode=False,display_mode="none",external=False))
            session=start["session_id"]
            assert Path(start["log_file"]).resolve().is_relative_to(work)
            version=execute('puts "PROBE_VERSION:[version -short]"');assert "PROBE_VERSION:2026.1" in version["output"]
            execute('create_project diagnostic {'+str(work/"project")+'} -part '+spec["part"])
            execute('add_files {'+str(d/"candidate.sv")+'}; add_files -fileset sim_1 {'+str(d/"tb.sv")+'}; set_property top R2Probe [get_filesets sim_1]; set_property target_simulator XSim [current_project]; set_property xsim.simulate.runtime {} [get_filesets sim_1]; update_compile_order -fileset sources_1; update_compile_order -fileset sim_1')
            execute('launch_simulation -simset sim_1 -mode behavioral')
            runtime=execute('run 100 us')
            execute('close_sim')
            logs=list(work.rglob("simulate.log"));assert len(logs)==1
            text=logs[0].read_text(encoding="utf-8",errors="replace")
            found=re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$',text,re.M)
            assert len(found)==1 and found[0][:2]==(task,str(contract["checks"])),found
            mismatch=int(found[0][2]);assert 0<=mismatch<=contract["checks"]
            first=[x for x in text.splitlines() if x.startswith("FIRST_MISMATCH")]
            if contract["role"]=="development_error":assert mismatch>0 and len(first)==1
            else:assert mismatch==0 and not first
            feedback="Public-specification self-check, XSim 2026.1. Completed checks=%d mismatches=%d.\n"%(contract["checks"],mismatch)
            feedback+=(first[0]+"\nTime unit in the diagnostic is ps.\n") if first else "No mismatch in this bounded self-check.\n"
            feedback+="This self-check is derived from the supplied public specification. It is not an official or hidden test and does not prove correctness beyond its exercised cases."
            (d/"feedback_observed.txt").write_text(feedback,encoding="utf-8")
            # Runtime evidence is separate from the frozen input/expected oracle.
            tool("vivado_stop",dict(session_id=session,close_vivado=True));report["closed_sessions"].append(session);session=None
            official=grade(task,d/"candidate.sv",out/"official_originals"/task)
            assert (official["level"]==3)==(contract["role"]=="correct_guard"),official
            report["originals"][task]=dict(checks=contract["checks"],mismatches=mismatch,first_mismatch=first[0] if first else None,feedback=feedback,transcript_path=str(logs[0].relative_to(root)),transcript_sha256=sha(logs[0]),run_tcl_exit_code=runtime.get("exit_code"),official=official)
            save(out/"summary.json",report);print(json.dumps(dict(phase="original_verified",task=task,mismatches=mismatch,official_level=official["level"])),flush=True)
        client.close();report["mcp_server_exit_code"]=client.proc.returncode;client=None
        assert report["mcp_server_exit_code"]==0
        save(out/"controls_verified.json",dict(controls=report["controls"],originals=report["originals"],model_calls=0))
        for task,contract in spec["tasks"].items():
            prompt=(root/"inputs"/task/"prompt.txt").read_text(encoding="utf-8")
            candidate=(root/"inputs"/task/"candidate.sv").read_text(encoding="utf-8")
            for label in spec["order"]:
                frozen();paired.model_idle(ENDPOINT,MODEL)
                assert report["attempts"]<spec["model_call_budget"]
                row_out=out/"generated"/task/label;row_out.mkdir(parents=True)
                user="Specification:\n"+prompt+"\nCandidate:\n"+candidate+"\n\n"+COMMON
                if label.startswith("D"):user+="\n\nObserved diagnostic:\n"+report["originals"][task]["feedback"]
                payload=dict(model=MODEL,temperature=0,top_p=1,max_tokens=spec["max_tokens"],messages=[dict(role="system",content=SYSTEM),dict(role="user",content=user)])
                body=json.dumps(payload,ensure_ascii=False).encode("utf-8");(row_out/"request.json").write_bytes(body)
                row=dict(task=task,label=label,role=contract["role"],request_sha256=sha(row_out/"request.json"),response_received=False)
                report["rows"].append(row);report["attempts"]+=1;save(out/"summary.json",report)
                tick=time.monotonic()
                request=urllib.request.Request(ENDPOINT+"/chat/completions",data=body,headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(request,timeout=spec["request_timeout_s"]) as response:raw=response.read()
                (row_out/"response.json").write_bytes(raw);response=json.loads(raw);choice=response["choices"][0]
                row.update(response_received=True,request_elapsed_s=time.monotonic()-tick,response_sha256=sha(row_out/"response.json"),usage=response.get("usage"),finish_reason=choice.get("finish_reason"),cache_or_timings={k:v for k,v in response.items() if "cache" in k.lower() or k=="timings"} or "unknown")
                report["responses"]+=1;content=choice["message"].get("content")
                if choice.get("finish_reason")!="stop" or not isinstance(content,str) or not content.strip():raise RuntimeError("truncated/empty response; stop without retry")
                (row_out/"answer.txt").write_text(content,encoding="utf-8")
                solution=row_out/"solution.v";solution.write_text(baseline.extract(content,"rtl"),encoding="utf-8")
                row.update(solution_path=str(solution.relative_to(root)),solution_sha256=sha(solution),source_changed=sha(solution)!=sha(root/"inputs"/task/"candidate.sv"))
                save(row_out/"row.json",row);save(out/"summary.json",report)
                print(json.dumps(dict(phase="generated",count=report["responses"],task=task,label=label,elapsed_s=row["request_elapsed_s"])),flush=True)
        save(out/"generation_complete.json",dict(rows=report["rows"],grading_started=False))
        for row in report["rows"]:
            task=row["task"];solution=root/row["solution_path"]
            row["probe"]=probe(task,solution,out/"generated_probes"/task/row["label"])
            if not row["source_changed"]:
                row["official"]=report["originals"][task]["official"];row["official_original_result_reused_identical_bytes"]=True
            else:row["official"]=grade(task,solution,out/"official_generated"/task/row["label"])
            save(out/"summary.json",report)
            print(json.dumps(dict(phase="graded",task=task,label=row["label"],probe=row["probe"]["status"],official_level=row["official"]["level"])),flush=True)
        report["complete"]=True
        report["verified"]=report["attempts"]==report["responses"]==spec["model_call_budget"]
    except BaseException as e:
        report["error"]=type(e).__name__+": "+str(e)
    finally:
        if client:
            if session:
                try:tool("vivado_stop",dict(session_id=session,close_vivado=True));report["closed_sessions"].append(session)
                except BaseException as e:report["stop_error"]=str(e)
            client.close();report["mcp_server_exit_code"]=client.proc.returncode
        report["elapsed_s"]=time.monotonic()-started
        report["assets_unchanged"]=all(sha(root/f)==h for f,h in spec["source_hashes"].items())
        report["verified"]=bool(report["verified"] and report["assets_unchanged"] and not report.get("stop_error"))
        report["arms"]={}
        for arm in ("C","D"):
            rows=[x for x in report["rows"] if x["label"].startswith(arm)]
            report["arms"][arm]=dict(rows=len(rows),graded=sum("official" in x for x in rows),repairs=sum(x["role"]=="development_error" and x.get("official",{}).get("level")==3 for x in rows),guard_regressions=sum(x["role"]=="correct_guard" and "official" in x and x["official"]["level"]<3 for x in rows),request_elapsed_s=sum(x.get("request_elapsed_s",0) for x in rows))
        save(out/"summary.json",report)
    print(json.dumps({k:report.get(k) for k in ("complete","verified","attempts","responses","arms","error")}),flush=True)
    return 0 if report["verified"] else 1


if __name__=="__main__":raise SystemExit(main())
