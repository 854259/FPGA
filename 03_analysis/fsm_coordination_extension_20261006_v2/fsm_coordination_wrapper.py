"""AMD-only execution: extend pinned table/base observers; never start a run.

FSM counts are stage-reported observations, not original-archive audit proof.
The legacy table/80/83 cards and manual revision ACK API remain delegated.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

BASE_SHA256 = "71c6c8490c201a37ded586d2c3a898d3651b2aec917babaf8ef8b062a5449b30"
TABLE_WRAPPER_SHA256 = "012370da40913ba32b26fc129e03dd524a419d803f7b43e02b88bc72ae6775db"
FROZEN_SCHEMA = "fsm_native_calibration_frozen_v2"
SUMMARY_SCHEMA = "fsm_native_calibration_measurement_v2"
CASE_SCHEMA = "fsm_native_calibration_case_plan_v2"
PROGRESS_SCHEMA = "fsm_native_calibration_progress_observation_v2"
PLANNED = dict(semantic_variants=24, transport_variants=10, eda_failure_variants=2,
               supervisor_probes=2, total_controls=38, native_variants=36,
               native_commands=105, owned_supervisor_commands=2,
               semantic_observations=2160, transport_observations=850,
               full_trace_observations=3010)
NATIVE_BY_TOOL = dict(xvlog=36, xelab=35, xsim=34)
TERMINAL_TICKETS = {"completed", "held_for_inspection", "failed_released_after_inspection", "cancelled_before_start"}
FAILED_TICKETS = {"held_for_inspection", "failed_released_after_inspection"}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(path):
    data = Path(path).read_bytes()
    return data, json.loads(data)


def count(value, ceiling, field):
    require(type(value) is int and 0 <= value <= ceiling, "Invalid reported "+field)
    return value


def frozen_plan(spec, run, plan_bytes, plan):
    require(spec["schema"] == FROZEN_SCHEMA and spec["planned"] == PLANNED
            and type(spec["model_requests_max"]) is int and spec["model_requests_max"] == 0
            and spec["expected_native_by_tool"] == NATIVE_BY_TOOL and run["expected_samples"] == 38,
            "FSM observer requires frozen38/105/2/0model scope")
    require(Path(spec["cloud_root"]).resolve() == Path(run["root"]).resolve(), "Frozen FSM root differs from owned run")
    require(sha(plan_bytes) == spec["source_hashes"]["CASE_PLAN.json"]
            and plan["schema"] == CASE_SCHEMA and plan["planned"] == PLANNED
            and plan["expected_native_by_tool"] == NATIVE_BY_TOOL,
            "FSM case plan lost its frozen source binding")
    rows = plan["rows"]
    require(type(rows) is list and len(rows) == 38, "Exactly38 planned control rows")
    require([row["index"] for row in rows] == list(range(38))
            and all(type(row["index"]) is int and type(row["label"]) is str
                    and re.fullmatch(r"[A-Za-z0-9_-]+", row["label"]) for row in rows)
            and len({row["label"] for row in rows}) == 38, "Unique ordered control identities")
    semantic = {"producer_positive", "sentinel_positive", "semantic_negative"}
    kinds = [row["kind"] for row in rows]
    require(sum(k in semantic for k in kinds) == 24 and kinds.count("producer_positive") == 2
            and kinds.count("sentinel_positive") == 2 and kinds.count("semantic_negative") == 20
            and kinds.count("transport_refusal") == 10 and kinds.count("eda_failure") == 2
            and kinds.count("supervisor_probe") == 2, "Fixed calibration kinds")
    for row in rows:
        tools = row["expected_native_tools"]
        require(type(tools) is list and tools in (["xvlog", "xelab", "xsim"], ["xvlog"], ["xvlog", "xelab"], []),
                "Known native command sequence")
        require((row["kind"] == "supervisor_probe") == (tools == []), "Supervisor/native counter separation")
        require(row["kind"] == "eda_failure" or tools == [] or tools == ["xvlog", "xelab", "xsim"],
                "Only EDA sentinels may have partial tool sequences")
    commands = [tool for row in rows for tool in (row["expected_native_tools"] or ["owned_supervisor"])]
    require(len(commands) == 107 and {tool: commands.count(tool) for tool in NATIVE_BY_TOOL} == NATIVE_BY_TOOL
            and commands.count("owned_supervisor") == 2, "Fixed105 native plus2 owned probes")
    return rows, commands


def row_prefix(rows, planned):
    require(type(rows) is list and len(rows) <= 38, "Reported control row count")
    actual = [(r["index"], r["label"], r["kind"]) for r in rows]
    expected = [(r["index"], r["label"], r["kind"]) for r in planned[:len(rows)]]
    require(actual == expected and all(type(row["index"]) is int for row in rows), "Control rows are not frozen-order prefix")
    for row in rows:
        require(row.get("error") is None or type(row["error"]) is str, "Reported row error type")
    return len(rows)


def counters(report, planned_commands):
    require(type(report["model_calls"]) is int and report["model_calls"] == 0,
            "Calibration has zero reported model calls")
    attempted = count(report["attempted_owned_commands"], 107, "owned attempts")
    confirmed = count(report["confirmed_owned_commands"], 107, "owned confirmations")
    pending = count(report["unconfirmed_owned_attempts"], 107, "unconfirmed attempts")
    require(confirmed <= attempted and pending == attempted-confirmed, "Owned attempt/confirmation accounting")
    native = report["actual_native_by_tool"]
    require(type(native) is dict and set(native) == set(NATIVE_BY_TOOL), "Exact native tool counter keys")
    for tool, maximum in NATIVE_BY_TOOL.items():
        count(native[tool], maximum, tool+" calls")
    native_total = count(report["actual_native_commands"], 105, "native total")
    probes = count(report["actual_owned_supervisor_commands"], 2, "owned supervisor probes")
    require(native_total == sum(native.values()) and confirmed == native_total+probes, "Native and probe count separation")
    expected = planned_commands[:confirmed]
    require(native == {tool: expected.count(tool) for tool in NATIVE_BY_TOOL}
            and probes == expected.count("owned_supervisor"), "Reported commands are not the frozen-order prefix")
    require(type(report["inventory_errors"]) is list and all(type(x) is str for x in report["inventory_errors"]), "Inventory error metadata")
    return dict(actual_model_requests=0, actual_native_by_tool=native, actual_native_commands=native_total,
                actual_owned_supervisor_commands=probes, attempted_owned_commands=attempted,
                confirmed_owned_commands=confirmed, unconfirmed_owned_attempts=pending,
                reported_inventory_errors=report["inventory_errors"], count_evidence="stage_reported_not_audited")


def observe_fsm(run, tickets_base, spec_bytes, spec, tool):
    root = Path(run["root"])
    result = dict(run, status="unknown", completed_samples=None, observation_error=None,
                  progress_schema=PROGRESS_SCHEMA, execution_state="unknown", quality_conclusion="pending",
                  native_qualification="pending", terminal_quality_result_observed=False,
                  actual_model_requests=None, actual_native_by_tool=None, actual_native_commands=None,
                  actual_owned_supervisor_commands=None, attempted_owned_commands=None,
                  confirmed_owned_commands=None, unconfirmed_owned_attempts=None,
                  count_evidence="unavailable", reported_stage_native_qualified=None,
                  reported_stage_evidence_complete=None, progress_observer_base_sha256=BASE_SHA256,
                  progress_observer_table_sha256=TABLE_WRAPPER_SHA256,
                  progress_observer_sha256=sha(Path(__file__).read_bytes()))
    terminal = False
    try:
        ticket_bytes, ticket = snapshot(Path(tickets_base)/("%08d.json" % run["ticket"]))
        require(type(run["ticket"]) is int and run["ticket"] > 0 and ticket["schema"] == "whole_task_fifo_v1"
                and type(ticket["ticket"]) is int and ticket["ticket"] == run["ticket"]
                and Path(ticket["cwd"]).resolve() == root.resolve(), "Ticket identity or owned run mismatch")
        result["ticket_state"] = ticket["state"]
        terminal = ticket["state"] in TERMINAL_TICKETS
        plan_bytes, plan = snapshot(root/"CASE_PLAN.json")
        planned, planned_commands = frozen_plan(spec, run, plan_bytes, plan)
        rows, snapshots = [], []
        summary_path = root/"results/summary.json"
        if summary_path.is_file():
            summary_bytes, summary = snapshot(summary_path)
            require(summary["schema"] == SUMMARY_SCHEMA and summary["spec_sha256"] == run["spec_sha256"]
                    and summary["planned"] == PLANNED and all(type(summary[k]) is bool for k in
                    ("complete", "evidence_complete", "native_qualified"))
                    and (summary.get("error") is None or type(summary["error"]) is str), "Unbound FSM terminal summary")
            rows = summary["rows"]
            completed = row_prefix(rows, planned)
            details = counters(summary, planned_commands)
            if summary["complete"]:
                require(completed == 38 and details["actual_native_commands"] == 105
                        and details["actual_owned_supervisor_commands"] == 2 and details["unconfirmed_owned_attempts"] == 0
                        and not details["reported_inventory_errors"] and summary.get("error") is None
                        and summary["guard_receipts"] == 216, "Complete calibration needs exact38/105/2/216 accounting")
            require(not summary["native_qualified"] or summary["complete"] and summary["evidence_complete"],
                    "Reported qualification lacks reported complete evidence")
            result.update(details, completed_samples=completed, stage_error=summary.get("error"),
                          reported_stage_native_qualified=summary["native_qualified"],
                          reported_stage_evidence_complete=summary["evidence_complete"],
                          observed_summary_sha256=sha(summary_bytes))
            result["status"] = ("failed" if summary.get("error") or summary["complete"] and not summary["native_qualified"]
                                else "completed_pending_audit" if summary["complete"] else "running")
            terminal = terminal or result["status"] in {"failed", "completed_pending_audit"}
            snapshots.append((summary_path, summary_bytes))
        else:
            row_paths = list((root/"results").glob("*/ROW.json")) if (root/"results").exists() else []
            allowed = {row["label"]: row for row in planned}
            require(all(path.parent.name in allowed for path in row_paths), "Unknown reported control row directory")
            found = {path.parent.name: path for path in row_paths}
            for item in planned:
                path = found.get(item["label"])
                if path is None:
                    break
                raw, row = snapshot(path); snapshots.append((path, raw)); rows.append(row)
            require(len(rows) == len(found), "Live control rows are not a contiguous frozen prefix")
            completed = row_prefix(rows, planned)
            result["completed_samples"] = completed
            progress_root = root/"results/progress"
            files = sorted(progress_root.glob("*.json")) if progress_root.exists() else []
            if files:
                require([path.name for path in files] == [str(i).zfill(4)+".json" for i in range(len(files))]
                        and len(files) <= 107, "Unknown/repeated/noncontiguous progress snapshots")
                raw, progress = snapshot(files[-1]); snapshots.append((files[-1], raw))
                require(progress["schema"] == "fsm_native_progress_v2" and progress["label"] in allowed,
                        "Unknown live FSM progress identity")
                details = counters(progress, planned_commands)
                progress_rows = count(progress["completed_rows"], 38, "progress completed rows")
                require(progress_rows <= completed <= progress_rows+1
                        and allowed[progress["label"]]["index"] == progress_rows
                        and progress["confirmed_owned_commands"] == len(files), "Live row/progress snapshots changed or disagree")
                result.update(details, observed_progress_sha256=sha(raw))
            row_error = next((row["error"] for row in rows if row.get("error")), None)
            result["status"] = "failed" if row_error else "running" if files or rows or ticket["state"] == "running" else "unknown"
            if row_error:
                result["stage_error"] = row_error; terminal = True
        if ticket["state"] in FAILED_TICKETS:
            result["status"] = "failed"
        require((root/"RUN_SPEC.json").read_bytes() == spec_bytes
                and (root/"CASE_PLAN.json").read_bytes() == plan_bytes
                and (Path(tickets_base)/("%08d.json" % run["ticket"])).read_bytes() == ticket_bytes
                and all(path.read_bytes() == data for path, data in snapshots), "FSM snapshot changed during observation")
        state = "terminal" if terminal else "running" if result["status"] == "running" else "pending" if ticket["state"] == "queued" else "unknown"
        result.update(execution_state=state, quality_conclusion="pending_terminal_audit" if terminal else "pending",
                      native_qualification="pending_terminal_audit" if terminal else "pending")
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(status="failed" if result.get("ticket_state") in FAILED_TICKETS else "unknown",
                      observation_error=type(error).__name__+": "+str(error),
                      execution_state="terminal" if terminal else "unknown",
                      quality_conclusion="pending_terminal_audit" if terminal else "pending",
                      native_qualification="pending_terminal_audit" if terminal else "pending",
                      actual_model_requests=None, actual_native_by_tool=None, actual_native_commands=None,
                      actual_owned_supervisor_commands=None, attempted_owned_commands=None,
                      confirmed_owned_commands=None, unconfirmed_owned_attempts=None, completed_samples=None,
                      reported_stage_native_qualified=None, reported_stage_evidence_complete=None,
                      count_evidence="unavailable")
        for field in ("observed_summary_sha256", "observed_progress_sha256", "reported_inventory_errors"):
            result.pop(field, None)
    return result


def extend_tool(table_wrapper_path, original_path):
    """Reuse two exact sealed modules; neither disk file or legacy schema changes."""
    path = Path(table_wrapper_path).resolve()
    require(sha(path.read_bytes()) == TABLE_WRAPPER_SHA256, "Pinned table wrapper SHA256 mismatch")
    require(sha(Path(original_path).read_bytes()) == BASE_SHA256, "Pinned base tool SHA256 mismatch")
    loader = importlib.util.spec_from_file_location("_fsm_pinned_table_wrapper", path)
    table = importlib.util.module_from_spec(loader); loader.loader.exec_module(table)
    tool = table.extend_tool(original_path)
    tool.RUN_SCHEMAS = set(tool.RUN_SCHEMAS) | {SUMMARY_SCHEMA}
    original_observe, original_publish = tool.observe_run, tool.publish

    def observe_run(run, tickets_base):
        try:
            spec_bytes, spec = snapshot(Path(run["root"])/"RUN_SPEC.json")
            if sha(spec_bytes) == run["spec_sha256"] and spec.get("schema") == FROZEN_SCHEMA:
                return observe_fsm(run, tickets_base, spec_bytes, spec, tool)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return original_observe(run, tickets_base)

    def publish(plan, owner, ledger_base, runs_base, tickets_base, observed_at=None, watcher=None):
        card = original_publish(plan, owner, ledger_base, runs_base, tickets_base, observed_at, watcher)
        fsm_runs = [run for run in card["runs"] if run.get("progress_schema") == PROGRESS_SCHEMA]
        if fsm_runs:
            lines = ["# FSM 原生校准观察", "", "控制行、原生调用和监督探针分别计数；均为阶段记录，尚未经原档案审计。",
                     "38项控制；105次原生工具调用；另有2次监督探针；模型计划调用为0。",
                     "原生合格与成绩结论等待终态原档案审计，summary声明不会自动成为最终结论。",
                     "提醒沿用原revision；观察器不会代队友确认或自动采用质量结论。", ""]
            for run in fsm_runs:
                lines += [f"- FIFO {run['ticket']}：{run['completed_samples']}/38 控制行；执行 {run['execution_state']}；原生资格 {run['native_qualification']}",
                          f"  阶段记录：native {run['actual_native_commands']}/105；owned supervisor {run['actual_owned_supervisor_commands']}/2；模型 {run['actual_model_requests']}",
                          "  原生工具计数："+json.dumps(run["actual_native_by_tool"], ensure_ascii=False),
                          f"  未确认owned尝试：{run['unconfirmed_owned_attempts']}；计数证据 {run['count_evidence']}"]
                if run["observation_error"]:
                    lines.append("  观察错误："+run["observation_error"])
            owned = tool.inside(ledger_base, Path(ledger_base)/owner)
            with tool.owned_lock(owned):
                tool.write(tool.inside(owned, owned/"FSM_NATIVE_PROGRESS.md"), "\n".join(lines)+"\n")
        return card

    tool.observe_run, tool.publish = observe_run, publish
    return tool


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--table-wrapper", required=True, type=Path)
    parser.add_argument("--base-tool", required=True, type=Path)
    args, forwarded = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    tool = extend_tool(args.table_wrapper, args.base_tool)
    previous = sys.argv
    try:
        sys.argv = [previous[0], *forwarded]
        return tool.main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    main()
