"""Audit real MCP evidence; preserve admission/runner failures separately."""
import hashlib
import json
from pathlib import Path

from diagnostics import inspect_report

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean_guard(guard):
    return dict(complete=guard["complete"], passed=guard["passed"],
                model_unchanged=guard["model_unchanged"], protected_files_unchanged=guard["protected_files_unchanged"],
                own_slot_released=guard["own_slot_released"], owned_cleanup_verified=guard["owned_cleanup"]["verified"],
                remaining_owned_processes=len(guard["owned_cleanup"]["remaining"]),
                started_at_utc=guard.get("started_at_utc"), finished_at_utc=guard["finished_at_utc"])


def main():
    raw = ROOT / "mcp_raw_evidence"
    for filename, item in read(raw / "EVIDENCE_MANIFEST.json").items():
        path = (raw / filename).resolve()
        assert path.is_relative_to(raw.resolve()) and path.stat().st_size == item["bytes"]
        assert sha(path) == item["sha256"]
    spec = read(ROOT / "MCP_SPEC.json")
    assert sha(raw / "live_source_v3/MCP_SPEC.json") == sha(ROOT / "MCP_SPEC.json")
    for filename, digest in spec["source_hashes"].items():
        assert sha(ROOT / filename) == sha(raw / "live_source_v3" / filename) == digest
    handshake = read(raw / "handshake/summary.json")
    assert handshake["complete"] and handshake["passed"] and handshake["server_exit_code"] == 0
    assert handshake["initialization"]["serverInfo"]["version"] == "2026.9.1"
    original = read(raw / "live_source_v3/live/summary.json")
    assert original["complete"] and original["passed"] and original["version_verified"]
    assert original["server_exit_code"] == 0 and original["own_session_absent_after_stop"]
    assert len(original["rows"]) == len(spec["runs"])
    rows = []
    for run, row in zip(spec["runs"], original["rows"]):
        assert run["case"] == row["case"] and run["mode"] == row["mode"]
        directory = raw / "live_source_v3/live/work" / (row["case"] + "__" + row["mode"])
        assert sha(directory / "candidate.sv") == row["source_sha256"] == spec["inputs"][row["case"]]["sha256"]
        assert sha(directory / "diagnostic.log") == row["log_sha256"]
        assert row["tool_execution_valid"]
        assert not any("overwriting previous definition" in x for x in row["messages"])
        row = dict(row)
        if run["mode"] == "lint":
            assert sha(directory / "linter.csv") == row["report_sha256"]
            row["report_inspection"] = inspect_report((directory / "linter.csv").read_text(encoding="utf-8"),row["linter_counts"][0])
            assert row["report_inspection"]["verified"]
        rows.append(row)
    guards = [read(raw / p / "status.json") for p in ["guard-handshake", "guard-live-v1-retry", "guard-live-v2-retry", "guard-live-v3"]]
    guard_sha = sha(raw / "resource_guard.py")
    assert guard_sha == "59c4212cb77971406255690c0efab0593cb5c100b21cf9d22622a9917be5e66d"
    for guard in guards:
        assert all(guard[k] for k in ["complete", "model_unchanged", "protected_files_unchanged", "own_slot_released"])
        assert guard["owned_cleanup"]["verified"] and not guard["owned_cleanup"]["remaining"]
    assert guards[0]["passed"] and not guards[1]["passed"] and guards[2]["passed"] and guards[3]["passed"]
    admission = read(raw / "guard-live-v1/status.json")
    assert admission["complete"] and not admission["passed"] and "slot occupied" in admission["error"]
    assert "stage_pid" not in admission and admission["own_slot_released"] is None
    second_admission = read(raw / "guard-live-v2/status.json")
    assert second_admission["complete"] and not second_admission["passed"] and "slot occupied" in second_admission["error"]
    assert "stage_pid" not in second_admission and second_admission["own_slot_released"] is None
    failed = read(raw / "live_source_v1/live/summary.json")
    assert failed["complete"] and not failed["passed"] and not failed["rows"]
    assert failed["own_session_absent_after_stop"] and "FileNotFoundError" in failed["error"]
    assert sha(raw / "live_source_v1/MCP_SPEC.json") == spec["previous_attempt"]["spec_sha256"]
    oldspec = read(raw / "live_source_v1/MCP_SPEC.json")
    for filename,digest in oldspec["source_hashes"].items():
        assert sha(raw / "live_source_v1" / filename) == digest
    hot_spec = read(raw / "live_source_v2/MCP_SPEC.json")
    assert sha(raw / "live_source_v2/MCP_SPEC.json") == spec["previous_hot_session"]["spec_sha256"]
    for filename, digest in hot_spec["source_hashes"].items():
        assert sha(raw / "live_source_v2" / filename) == digest
    hot = read(raw / "live_source_v2/live/summary.json")
    assert hot["complete"] and hot["passed"] and hot["own_session_absent_after_stop"]
    assert any("overwriting previous definition" in x for row in hot["rows"] for x in row["messages"])
    transcript = [json.loads(x) for x in (raw / "live_source_v3/live/rpc.jsonl").read_text(encoding="utf-8").splitlines()]
    calls = [x["message"] for x in transcript if x["direction"]=="client" and x["message"].get("method")=="tools/call"]
    assert len(calls)==original["tool_calls"]
    starts=[x for x in calls if x["params"]["name"]=="vivado_start"]
    stops=[x for x in calls if x["params"]["name"]=="vivado_stop"]
    assert len(starts)==len(stops)==spec["sessions_started"]==4
    stopped_ids = [x["params"]["arguments"]["session_id"] for x in stops]
    assert len(set(stopped_ids))==4 and set(stopped_ids)==set(original["closed_session_ids"])
    assert all(x["params"]["arguments"]["close_vivado"] is True for x in stops)
    assert not any(x["params"]["name"] in ["vivado_cleanup","vivado_connect","vivado_lsf","vivado_ssh"] for x in calls)
    assert not any(x["message"].get("method")=="sampling/createMessage" for x in transcript)
    positive = [x for x in rows if x["mode"]=="lint" and spec["inputs"][x["case"]]["role"]=="diagnostic_positive"]
    negative = [x for x in rows if x["mode"]=="lint" and spec["inputs"][x["case"]]["role"]=="diagnostic_negative"]
    engine_verified = len(positive)>=2 and all(x["linter_counts"][0]>0 for x in positive) and bool(negative) and all(x["linter_counts"]==[0] for x in negative)
    post = read(raw / "postflight.json")
    assert post["model_health"]["status"]=="ok" and post["processing_slots"]==0 and not post["slot_exists"]
    assert post["model_identity_unchanged"] and post["protected_files_unchanged"]
    result = dict(schema="ross_mcp_evidence_v1",date="2026-10-04",complete=True,
                  binary=read(ROOT / "BINARY.json"),spec_sha256=sha(ROOT / "MCP_SPEC.json"),
                  evidence_zip_sha256=sha(ROOT / "mcp_evidence.zip"),
                  cloud_root="/workspace/team/runs/fpga_owner/ross_mcp_20261004_v1",
                  transport_verified=True,session_execution_verified=True,actual_vivado_version="2026.1",part=spec["part"],
                  model_calls=0,new_score=False,functional_repair_measured=False,formal_runtime_integrated=False,
                  successful_stage_tool_calls=original["tool_calls"],successful_stage_elapsed_s=original["elapsed_s"],
                  successful_stage_sessions_started=len(starts),successful_stage_sessions_closed=len(stops),
                  session_start_elapsed_s=original["start_elapsed_s"],
                  successful_stage_lint_calls=len(positive)+len(negative),successful_stage_synthesis_calls=1,
                  diagnostic_engine_verified=engine_verified,rows=rows,
                  handshake=dict(server_version="2026.9.1",protocol_version=handshake["initialization"]["protocolVersion"],tool_names=handshake["tool_names"]),
                  guards=[clean_guard(g) for g in guards],
                  resource_guard_source=dict(commit="bde08582f99d70dc16581afe837e9457a1a92e64",path="03_analysis/selective_runtime_integration_20261003/resource_guard.py",sha256=guard_sha),
                  all_mcp_stages=dict(tool_calls=failed["tool_calls"]+hot["tool_calls"]+original["tool_calls"],vivado_sessions_started=6,vivado_sessions_closed=6,lint_calls=6,synthesis_calls=2,model_calls=0),
                  failed_attempts=[dict(type="admission_refused",stage_started=False,error=admission["error"],other_slot_preserved=True),
                                   dict(type="runner_log_path_error",stage_started=True,vivado_start_succeeded=True,lint_calls=0,error=failed["error"],cleanup=clean_guard(guards[1])),
                                   dict(type="second_admission_refused",stage_started=False,error=second_admission["error"],other_slot_preserved=True)],
                  exploratory_hot_session=dict(tool_calls=hot["tool_calls"],elapsed_s=hot["elapsed_s"],lint_counts=[x["linter_counts"] for x in hot["rows"] if x["mode"]=="lint"],source_isolation_verified=False,limitation=spec["previous_hot_session"]["limitation"],all_owned_sessions_closed=True),
                  state_directory_limitation=spec["limits"][0],postflight=post,
                  decision="MCP connection is available for isolated development; automated lint repair remains disabled until diagnostic calibration and repair controls pass",
                  remaining=["Resolve lint-positive controls on this installed Vivado build without fabricating findings","Audit binary redistribution terms and offline container reproducibility before final inclusion","Measure local-model tool selection, bounded repair benefit and total cost on independent guards"])
    (ROOT / "MCP_RESULTS.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ["transport_verified","session_execution_verified","diagnostic_engine_verified","successful_stage_tool_calls","successful_stage_elapsed_s"]}))


if __name__ == "__main__":
    main()
