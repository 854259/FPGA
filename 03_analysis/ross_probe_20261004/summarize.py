"""Audit downloaded evidence and produce a public, reproducible research summary."""
import hashlib
import json
from pathlib import Path

from diagnostics import analyze, calibration, inspect_report

ROOT = Path(__file__).resolve().parent
CLOUD = "/workspace/team/runs/fpga_owner/ross_probe_20261004_v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    raw = ROOT / "raw_evidence"
    summary = json.loads((raw / "summary.json").read_text())
    spec = json.loads((ROOT / "RUN_SPEC.json").read_text())
    assert summary["complete"] and summary["tool_execution_valid"] and summary["inputs_unchanged"]
    assert sha(raw / "RUN_SPEC.json") == sha(ROOT / "RUN_SPEC.json")
    assert sha(raw / "run_probe.py") == spec["runner_sha256"] == sha(ROOT / "run_probe.py")
    assert sha(raw / "resource_guard.py") == spec["resource_guard_sha256"]
    for name, data in spec["inputs"].items():
        assert sha(ROOT / data["file"]) == sha(raw / data["file"]) == data["sha256"]
    rows = []
    for original in summary["rows"]:
        row = dict(original)
        run_id = row["case"] + "__" + row["configuration"] + "__" + row["mode"]
        directory = raw / "results" / run_id
        for filename, key in [("stdout.log", "log_sha256"), ("probe.tcl", "tcl_sha256"), ("candidate.sv", "run_source_sha256")]:
            assert sha(directory / filename) == row[key]
        assert row["source_sha256"] == row["run_source_sha256"]
        if row["mode"] == "lint":
            assert sha(directory / "linter.csv") == row["report_sha256"]
            inspection = inspect_report((directory / "linter.csv").read_text(), row["linter_counts"][0])
            row.update(report_parse_verified=inspection["verified"], report_format=inspection["format"], report_inspection=inspection)
        rows.append(row)
    caps = {config: calibration(rows, config) for config in spec["configurations"]}
    for row in rows:
        run_id = row["case"] + "__" + row["configuration"] + "__" + row["mode"]
        directory = raw / "results" / run_id
        row["diagnostics"] = analyze(row, (directory / "stdout.log").read_bytes(),
                                     (directory / "candidate.sv").read_bytes(),
                                     CLOUD + "/results/" + run_id + "/candidate.sv", caps[row["configuration"]])
    guard = json.loads((raw / "guard/status.json").read_text())
    assert all(guard[k] for k in ["complete", "passed", "model_unchanged", "protected_files_unchanged", "own_slot_released"])
    assert guard["owned_cleanup"]["verified"]
    post = json.loads((raw / "postflight.json").read_text())
    assert not post["slot_exists"] and post["model_health"]["status"] == "ok" and post["processing_slots"] == 0
    lint = [x for x in rows if x["mode"] == "lint"]
    results = dict(schema="ross_diagnostic_research_v1", date="2026-10-04", complete=True,
                   scope=spec["scope"], upstream_commit=spec["upstream_commit"], cloud_root=CLOUD,
                   evidence_zip_sha256=sha(ROOT / "evidence.zip"), spec_sha256=sha(ROOT / "RUN_SPEC.json"),
                   model_calls=0, real_lint_calls=len(lint), real_synthesis_calls=1,
                   lint_average_s=sum(x["elapsed_s"] for x in lint)/len(lint),
                   calibrations=caps, diagnostic_engine_verified=all(x["verified"] for x in caps.values()),
                   report_format_effect="Default report is an ASCII table despite .csv extension; the official option changes it to an empty headerless CSV at zero count, but both fault controls still produce zero lint counts",
                   rows=rows, resource_guard={k:v for k,v in guard.items() if k!="owned_cleanup"},
                   owned_cleanup=dict(verified=True, remaining=[], recorded_process_count=len(guard["owned_cleanup"]["recorded"])),
                   postflight=post, limits=spec["limitations"],
                   integration_decision="Do not enable automated ROSS lint repair; retain ordinary diagnostics as factual evidence for later isolated repair studies",
                   integration_state=dict(is_historical_stage_snapshot=True, later_mcp_results="MCP_RESULTS.json",
                                          formal_package_changed=False, mcp_installed=False, mcp_invoked=False,
                                          functional_repair_measured=False, new_score=False,
                                          download_dependency="At this earlier direct-command stage the Linux binary had not been supplied; later real MCP evidence is separate in MCP_RESULTS.json"))
    (ROOT / "RESULTS.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(lint_calls=len(lint), average_s=results["lint_average_s"],
                         engine_verified=results["diagnostic_engine_verified"],
                         unique_messages=[(x["case"],x["configuration"],x["mode"],x["diagnostics"]["unique_messages"]) for x in rows])))


if __name__ == "__main__":
    main()
