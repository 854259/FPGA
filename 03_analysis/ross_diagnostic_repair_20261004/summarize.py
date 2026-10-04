"""Verify all saved requests, tool evidence, and grades without new model calls."""
import hashlib
import json
from pathlib import Path
import re

from repair_pilot import COMMON, SYSTEM, unpack
import baseline_extract as baseline

ROOT=Path(__file__).resolve().parent
RAW=ROOT/"raw_evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    archive=read(ROOT/"ARCHIVE.json")
    assert sha(ROOT/"evidence.zip")==archive["sha256"]
    manifest=read(RAW/"MANIFEST.json")
    for row in manifest["files"]:
        p=(RAW/row["path"]).resolve();assert p.is_relative_to(RAW.resolve())
        assert p.stat().st_size==row["bytes"] and sha(p)==row["sha256"],row["path"]
    spec=read(ROOT/"RUN_SPEC.json")
    assert (ROOT/"RUN_SPEC.json").read_bytes()==(RAW/"RUN_SPEC.json").read_bytes()
    assert (ROOT/"RUN_SPEC.initial.json").read_bytes()==(RAW/"RUN_SPEC.initial.json").read_bytes()
    for f,h in spec["source_hashes"].items():assert sha(ROOT/f)==sha(RAW/f)==h,f
    assert sha(ROOT/"official_eval.py")==sha(RAW/"official_eval.py")==spec["judge_adapter_sha256"]
    assert sha(RAW/"guard_wrapper.py")==spec["resource_guard_sha256"]
    assert (ROOT/"owned_adapter.py").read_bytes()==(ROOT/"paired_checkpoint.py").read_bytes()
    old=read(RAW/"pre_model_failure_results/summary.json");oldguard=read(RAW/"guard-v2/status.json")
    assert old["attempts"]==old["responses"]==old["mcp_tool_calls"]==0
    assert "paired_checkpoint.py" in old["error"] and not oldguard["passed"]
    for g in (oldguard,read(RAW/"guard-v3/status.json")):
        assert g["complete"] and g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
        assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    guard=read(RAW/"guard-v3/status.json")
    summary=read(RAW/"results/summary.json")
    assert summary["complete"] and summary["verified"] and guard["passed"]
    assert summary["attempts"]==summary["responses"]==spec["model_call_budget"]==16
    assert summary["assets_unchanged"] and summary["retries"]==0 and summary["mcp_server_exit_code"]==0
    assert summary["run_spec_sha256"]==sha(ROOT/"RUN_SPEC.json")
    rpc=[json.loads(x) for x in (RAW/"results/mcp/rpc.jsonl").read_text(encoding="utf-8").splitlines()]
    calls=[x for x in rpc if x["direction"]=="client" and x["message"].get("method")=="tools/call"]
    assert len(calls)==summary["mcp_tool_calls"]==32
    stops=[x["message"]["params"]["arguments"]["session_id"] for x in calls if x["message"]["params"]["name"]=="vivado_stop"]
    assert len(stops)==len(set(stops))==4 and stops==summary["closed_sessions"]
    server_by_id={x["message"]["id"]:x for x in rpc if x["direction"]=="server" and "id" in x["message"]}
    diagnostic_elapsed={}
    for index,task in enumerate(spec["tasks"]):
        group=calls[index*8:(index+1)*8]
        assert group[0]["message"]["params"]["name"]=="vivado_start"
        assert group[-1]["message"]["params"]["name"]=="vivado_stop"
        actual_start=unpack(server_by_id[group[0]["message"]["id"]]["message"]["result"])
        assert actual_start["session_id"]==stops[index]
        response=server_by_id[group[-1]["message"]["id"]]
        assert unpack(response["message"]["result"])["status"]=="success"
        diagnostic_elapsed[task]=response["ts"]-group[0]["ts"]
    for task,contract in spec["tasks"].items():
        controls=summary["controls"][task]
        for name,row in controls.items():
            probe=read(RAW/"results/controls"/task/name/"result.json")
            assert probe["checks"]==contract["checks"] and probe["inputs_unchanged"]
            assert probe["solution_sha256"]==sha(ROOT/"inputs"/task/(name+".sv"))
            assert probe["tb_sha256"]==sha(ROOT/"inputs"/task/"tb.sv")
            assert probe["status"]==("pass" if name=="positive" else "fail")
            if name=="negative":assert probe["failure_kind"]=="semantic_mismatch"
        original=summary["originals"][task];p=RAW/original["transcript_path"]
        assert sha(p)==original["transcript_sha256"]
        text=p.read_text(encoding="utf-8")
        assert re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$',text,re.M)==[(task,str(contract["checks"]),str(original["mismatches"]))]
        if original["first_mismatch"]:assert original["first_mismatch"] in text
        assert (original["mismatches"]==0)==(contract["role"]=="correct_guard")
        assert (original["official"]["level"]==3)==(contract["role"]=="correct_guard")
    output_rows=[];response_ids=[]
    for row in summary["rows"]:
        task,label=row["task"],row["label"];folder=RAW/"results/generated"/task/label
        assert sha(folder/"request.json")==row["request_sha256"] and sha(folder/"response.json")==row["response_sha256"]
        payload=read(folder/"request.json")
        expected="Specification:\n"+(ROOT/"inputs"/task/"prompt.txt").read_text(encoding="utf-8")+"\nCandidate:\n"+(ROOT/"inputs"/task/"candidate.sv").read_text(encoding="utf-8")+"\n\n"+COMMON
        if label.startswith("D"):expected+="\n\nObserved diagnostic:\n"+summary["originals"][task]["feedback"]
        assert payload["messages"]==[dict(role="system",content=SYSTEM),dict(role="user",content=expected)]
        assert payload["model"]==summary["model"] and payload["temperature"]==0 and payload["top_p"]==1 and payload["max_tokens"]==spec["max_tokens"]
        response=read(folder/"response.json");choice=response["choices"][0]
        response_ids.append(response["id"])
        assert choice["finish_reason"]==row["finish_reason"]=="stop" and row["response_received"]
        solution=RAW/row["solution_path"];assert sha(solution)==row["solution_sha256"]
        assert solution.read_bytes()==baseline.extract(choice["message"]["content"],"rtl").encode("utf-8")
        probe=read(RAW/"results/generated_probes"/task/label/"result.json")
        assert probe["solution_sha256"]==sha(solution) and probe["tb_sha256"]==sha(ROOT/"inputs"/task/"tb.sv")
        assert probe["inputs_unchanged"] and probe["status"]==row["probe"]["status"]
        verdict=row["official"]
        assert not verdict.get("tool_error") and not verdict.get("suspected_silent_degradation")
        if row.get("official_original_result_reused_identical_bytes"):
            assert sha(solution)==sha(ROOT/"inputs"/task/"candidate.sv")
            actual=read(RAW/"results/official_originals"/task/"verdict.json")
        else:actual=read(RAW/"results/official_generated"/task/label/"verdict.json")
        assert actual["level"]==verdict["level"]
        output_rows.append({k:row[k] for k in ("task","label","role","request_sha256","response_sha256","solution_sha256","source_changed","usage","finish_reason","request_elapsed_s")}|{"probe_status":probe["status"],"probe_failure_kind":probe["failure_kind"],"probe_checks":probe["checks"],"probe_mismatches":probe["mismatches"],"official_level":verdict["level"]})
    assert [(x["task"],x["label"]) for x in output_rows]==[(task,label) for task in spec["tasks"] for label in spec["order"]]
    assert len(set(response_ids))==16 and all(response_ids)
    arms={}
    for arm in ("C","D"):
        group=[x for x in output_rows if x["label"].startswith(arm)]
        arms[arm]=dict(rows=len(group),error_reviews=sum(x["role"]=="development_error" for x in group),repairs=sum(x["role"]=="development_error" and x["official_level"]==3 for x in group),guard_reviews=sum(x["role"]=="correct_guard" for x in group),guard_regressions=sum(x["role"]=="correct_guard" and x["official_level"]<3 for x in group),request_elapsed_s=sum(x["request_elapsed_s"] for x in group))
        assert arms[arm]["repairs"]==summary["arms"][arm]["repairs"] and arms[arm]["guard_regressions"]==summary["arms"][arm]["guard_regressions"]
    conflicts=[dict(task=x["task"],label=x["label"],probe_status=x["probe_status"],official_level=x["official_level"]) for x in output_rows if x["official_level"]==3 and x["probe_status"]!="pass"]
    qualifies=arms["D"]["repairs"]>arms["C"]["repairs"] and arms["D"]["guard_regressions"]==0 and not conflicts
    result=dict(schema="ross_diagnostic_repair_audit_v1",status="complete_verified",qualifies_for_independent_validation=qualifies,formal_runtime_integrated=False,new_score=False,full_skill_model_execution=False,model=summary["model"],attempts=16,responses=16,retries=0,mcp_tool_calls=32,mcp_sessions_closed=4,elapsed_s=summary["elapsed_s"],arms=arms,rows=output_rows,original_diagnostics={t:{k:r[k] for k in ("checks","mismatches","first_mismatch","run_tcl_exit_code","transcript_sha256")} for t,r in summary["originals"].items()},mcp_diagnostic_elapsed_s_by_task=diagnostic_elapsed,mcp_diagnostic_elapsed_s=sum(diagnostic_elapsed.values()),production_end_to_end_benefit_measured=False,manual_testbench_creation_cost_measured=False,guard={k:guard[k] for k in ("started_at_utc","finished_at_utc","elapsed_s","stage_rc","model_unchanged","protected_files_unchanged","own_slot_released","model_idle_after")},owned_cleanup_verified=True,remaining_owned_processes=0,evidence={"archive_sha256":archive["sha256"],"manifest_files":len(manifest["files"]),"all_hashes_verified":True,"all_requests_exactly_reconstructed":True,"all_extractions_and_grades_verified":True},postflight=read(RAW/"postflight.json"),pre_model_failures=[read(RAW/"launch_failure.json"),dict(reason=old["error"],model_calls=0,mcp_calls=0,owned_cleanup_verified=True,source_or_test_inputs_changed=False,adjustment="Add byte-identical canonical filename alias; preserve initial spec and failed evidence")],limits=spec["limits"])
    result["official_pass_selfcheck_conflicts"]=conflicts
    result["unique_response_ids_verified"]=16
    (ROOT/"RESULTS.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(verified=True,arms=arms,qualifies_for_independent_validation=qualifies,manifest_files=len(manifest["files"]))))


if __name__=="__main__":main()
