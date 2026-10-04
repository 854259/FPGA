"""Test the documented XSim verdict gates on a small prompt-derived contract."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from mcp_client import StdioClient


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def save(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")


def unpack(raw):
    if isinstance(raw.get("structuredContent"),dict):
        return raw["structuredContent"]
    return json.loads(raw["content"][0]["text"])


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--resource-check",type=Path,required=True)
    args=ap.parse_args()
    root=args.root.resolve()
    spec=json.loads((root/"RUN_SPEC.json").read_text())
    check=json.loads(args.resource_check.read_text())
    assert check["resource_idle"] and check["model_pid"]==2013333
    for f,h in spec["source_hashes"].items(): assert sha(root/f)==h,f
    binary=root/"vivado-mcp-server"
    assert sha(binary)==spec["binary_sha256"]
    out=root/"results"
    out.mkdir(exist_ok=False)
    env=os.environ.copy()
    env["LD_LIBRARY_PATH"]="/workspace/team/udev-stub"+(":"+env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["NO_PROXY"]=env["no_proxy"]="127.0.0.1,localhost,::1"
    command=[str(binary),"--stdio","--state-dir="+str(out/"state"),"--vivado-path=/workspace/AMD/2026.1/Vivado/bin/vivado","--enable-lsf=false","--enable-ssh=false","--disable-telemetry","--disable-otel","--max-sessions=1","--limit-ai-output=false"]
    client=None
    session=None
    calls=0
    tick=time.monotonic()
    result=dict(complete=False,passed=False,model_calls=0,rows=[],closed_sessions=[],full_skill_model_execution=False)

    def tool(name,arguments):
        nonlocal calls
        calls+=1
        raw=client.tool(name,arguments,timeout=180)
        save(out/("%02d_%s.json"%(calls,name)),raw)
        data=unpack(raw)
        if data.get("status") in ["error","failed"] or data.get("success") is False: raise RuntimeError(str(data)[:1500])
        return data

    def execute(command):
        data=tool("vivado_execute",dict(session_id=session,command=command,mode="proxy",verbosity="full",capture_log=True))
        if data.get("status")=="running":raise RuntimeError("Unexpected handoff in small bounded probe")
        if data.get("exit_code") not in [None,0]:raise RuntimeError(str(data)[:2000])
        return data

    try:
        client=StdioClient(command,out,env,out/"rpc.jsonl",out/"stderr.log")
        client.request("initialize",dict(protocolVersion="2025-11-25",capabilities={},clientInfo=dict(name="ross-simulation-gate-probe",version="0.1")))
        client.notify("notifications/initialized")
        for case in spec["cases"]:
            directory=out/case["name"]
            directory.mkdir()
            start=tool("vivado_start",dict(working_dir=str(directory),session_type="general",gui_mode=False,display_mode="none",external=False))
            session=start["session_id"]
            actual_log=Path(start["log_file"]).resolve()
            assert actual_log.is_relative_to(directory) and actual_log.is_file()
            execute('puts "PROBE_VERSION:[version -short]"')
            execute('create_project sim_probe {'+str(directory/"project")+'} -part '+spec["part"])
            execute('add_files {'+str(root/case["source"])+"}; add_files -fileset sim_1 {"+str(root/"inputs/tb.sv")+'}; set_property top tb [get_filesets sim_1]; set_property target_simulator XSim [current_project]; set_property xsim.simulate.runtime {} [get_filesets sim_1]; update_compile_order -fileset sources_1; update_compile_order -fileset sim_1')
            config=execute('puts "PROBE_SIM:[get_property target_simulator [current_project]]"; puts "PROBE_TOP:[get_property TOP [get_filesets sim_1]]"')
            assert "PROBE_SIM:XSim" in config["output"] and "PROBE_TOP:tb" in config["output"]
            launch=execute('launch_simulation -simset sim_1 -mode behavioral')
            execute('open_vcd {'+str(directory/"trace.vcd")+'}; log_vcd [get_objects {/tb/a /tb/b /tb/sum /tb/expected /tb/checks}]')
            runtime=execute('run 20 ns')
            execute('flush_vcd; close_vcd')
            logs=list(directory.rglob("simulate.log"))
            # The generated directory/log name is discovered, not presumed.
            if not logs: logs=list(directory.rglob("xsim.log"))
            assert len(logs)==1, [str(p) for p in logs]
            text=logs[0].read_text(errors="replace")
            pass_markers=re.findall(r'^TEST_PASS checks=(\d+)\s*$',text,re.M)
            fail_lines=[line for line in text.splitlines() if "TEST_FAIL" in line or line.startswith("Fatal:")]
            vcd=directory/"trace.vcd"
            assert vcd.is_file() and vcd.stat().st_size>0
            vcd_text=vcd.read_text()
            assert "$enddefinitions" in vcd_text and "a " in vcd_text and "sum " in vcd_text
            verdict="PASS" if pass_markers==["5"] and not fail_lines else "FAIL" if fail_lines and not pass_markers else "INCONCLUSIVE"
            row=dict(case=case["name"],expected_verdict=case["expected_verdict"],verdict=verdict,launch_tcl_exit_code=launch.get("exit_code"),run_tcl_exit_code=runtime.get("exit_code"),pass_markers=pass_markers,first_failure=fail_lines[0] if fail_lines else None,transcript_path=str(logs[0].relative_to(root)),transcript_sha256=sha(logs[0]),vcd_sha256=sha(vcd),vcd_bytes=vcd.stat().st_size,vcd_header_verified=True,source_sha256=sha(root/case["source"]))
            assert verdict==case["expected_verdict"],row
            result["rows"].append(row)
            save(out/"summary.json",result)
            execute("close_sim")
            tool("vivado_stop",dict(session_id=session,close_vivado=True))
            result["closed_sessions"].append(session)
            session=None
            print(json.dumps(row),flush=True)
        result["passed"]=True
    except BaseException as e:
        result["error"]=type(e).__name__+": "+str(e)
    finally:
        if client and session:
            try:
                tool("vivado_stop",dict(session_id=session,close_vivado=True))
                result["closed_sessions"].append(session)
            except BaseException as e:result["stop_error"]=str(e);result["passed"]=False
        if client:
            client.close()
            result["server_exit_code"]=client.proc.returncode
        result.update(complete=True,elapsed_s=time.monotonic()-tick,tool_calls=calls)
        save(out/"summary.json",result)
    print(json.dumps(result),flush=True)
    return 0 if result["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
