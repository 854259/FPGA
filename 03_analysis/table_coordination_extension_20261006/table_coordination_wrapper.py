"""Private draft: extend a pinned coordination module at runtime; no run execution."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

BASE_SHA256 = "71c6c8490c201a37ded586d2c3a898d3651b2aec917babaf8ef8b062a5449b30"
TABLE_SCHEMA = "table_synthesis_pilot_v1"
FROZEN_SCHEMA = "table_synthesis_pilot_frozen_v1"
PROGRESS_SCHEMA = "table_synthesis_progress_observation_v1"
TERMINAL_TICKETS = {"completed", "held_for_inspection",
                    "failed_released_after_inspection", "cancelled_before_start"}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def table_details(summary, spec, run):
    """Observe stage reports only; zero-call provenance belongs to the auditor."""
    tasks = spec["task_ids"]
    if (spec["schema"] != FROZEN_SCHEMA or spec["expected_samples"] != 28
            or run["expected_samples"] != 28 or spec["arms"] != ["C", "P"]
            or len(tasks) != 14 or len(set(tasks)) != 14
            or any(not isinstance(task, str) or not task for task in tasks)):
        raise ValueError("Table observer requires the frozen 14-task/28-output scope")
    expected = [(task, arm) for i, task in enumerate(tasks)
                for arm in (["C", "P"] if i % 2 == 0 else ["P", "C"])]
    rows = summary["rows"]
    if [(row["task"], row["arm"]) for row in rows] != expected[:len(rows)]:
        raise ValueError("Table rows do not match the frozen stage order")
    total = summary["actual_model_requests"]
    if type(total) is not int or not 0 <= total <= 56:
        raise ValueError("Invalid reported actual model call count")
    calls = {"C": 0, "P": 0}
    routes = {arm: {"model": 0, "mechanical_table": 0} for arm in calls}
    for row in rows:
        count, arm, route = row["actual_model_requests"], row["arm"], row["generation_route"]
        if type(count) is not int:
            raise ValueError("Row call count must be an integer")
        if route == "mechanical_table":
            if arm != "P" or count != 0:
                raise ValueError("Mechanical stage rows require P and zero reported calls")
        elif route == "model":
            if not 1 <= count <= 2:
                raise ValueError("Model stage rows require one or two reported calls")
        else:
            raise ValueError("Unknown table generation route")
        calls[arm] += count
        routes[arm][route] += 1
    completed_calls = sum(calls.values())
    if completed_calls > total:
        raise ValueError("Completed row calls exceed the recorded stage count")
    if summary["complete"] and summary["passed"] and not summary.get("error"):
        if len(rows) != 28 or completed_calls != total:
            raise ValueError("Successful stage needs all 28 outputs and exact call accounting")
    return dict(actual_model_requests=total, completed_row_model_requests=completed_calls,
                unrepresented_model_requests=total-completed_calls,
                completed_row_requests_by_arm=calls, completed_row_generation_routes=routes,
                model_call_evidence="stage_reported_not_audited")


def extend_tool(original_path):
    """Load the exact old file without rewriting it or changing ACK/card schemas."""
    original_path = Path(original_path).resolve()
    if sha_bytes(original_path.read_bytes()) != BASE_SHA256:
        raise ValueError("Pinned team_coordination.py SHA256 mismatch")
    module_spec = importlib.util.spec_from_file_location("_table_coordination_base", original_path)
    tool = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(tool)
    tool.RUN_SCHEMAS = set(tool.RUN_SCHEMAS) | {TABLE_SCHEMA}
    original_observe, original_publish = tool.observe_run, tool.publish

    def observe_run(run, tickets_base):
        observed = original_observe(run, tickets_base)
        root = Path(run["root"])
        try:
            spec_bytes = (root/"RUN_SPEC.json").read_bytes()
            if sha_bytes(spec_bytes) != run["spec_sha256"]:
                return observed
            spec = json.loads(spec_bytes)
            if spec.get("schema") != FROZEN_SCHEMA:
                return observed
        except (OSError, ValueError, KeyError, TypeError):
            return observed
        terminal = (observed.get("ticket_state") in TERMINAL_TICKETS
                    or observed["status"] in {"failed", "completed_pending_audit"})
        state = "terminal" if terminal else "running" if observed["status"] == "running" else \
                "pending" if observed.get("ticket_state") == "queued" else "unknown"
        observed.update(progress_schema=PROGRESS_SCHEMA, execution_state=state,
                        quality_conclusion="pending_terminal_audit" if terminal else "pending",
                        terminal_quality_result_observed=False,
                        actual_model_requests=None, completed_row_model_requests=None,
                        unrepresented_model_requests=None,
                        model_call_evidence="unavailable",
                        progress_observer_base_sha256=BASE_SHA256,
                        progress_observer_sha256=sha_bytes(Path(__file__).read_bytes()))
        if observed["observation_error"] is not None:
            return observed
        try:
            summary_bytes = (root/"results/summary.json").read_bytes()
            summary = json.loads(summary_bytes)
            if (summary["schema"] != TABLE_SCHEMA or summary["spec_sha256"] != run["spec_sha256"]
                    or type(summary["complete"]) is not bool or type(summary["passed"]) is not bool
                    or not isinstance(summary["rows"], list)
                    or len(summary["rows"]) != observed["completed_samples"]
                    or summary.get("error") != observed.get("stage_error")):
                raise ValueError("Table summary changed or lost its frozen binding")
            expected_status = ("failed" if summary.get("error") or summary["complete"] and not summary["passed"]
                               else "completed_pending_audit" if summary["complete"] and len(summary["rows"]) == 28
                               else "running" if not summary["complete"] else "unknown")
            if observed.get("ticket_state") not in {"held_for_inspection", "failed_released_after_inspection"} \
                    and expected_status != observed["status"]:
                raise ValueError("Table completion changed during observation")
            observed.update(table_details(summary, spec, run),
                            observed_summary_sha256=sha_bytes(summary_bytes))
        except (OSError, ValueError, KeyError, TypeError) as error:
            observed.update(status="unknown" if not terminal else observed["status"],
                            observation_error=type(error).__name__+": "+str(error))
        return observed

    def publish(plan, owner, ledger_base, runs_base, tickets_base, observed_at=None, watcher=None):
        card = original_publish(plan, owner, ledger_base, runs_base, tickets_base, observed_at, watcher)
        table_runs = [run for run in card["runs"] if run.get("progress_schema") == PROGRESS_SCHEMA]
        if table_runs:
            lines = ["# 表格生成测试观察", "", "仅显示阶段记录；调用数未经终态原始档案审计。",
                     "28 行指两臂输出数，机械生成不计模型调用。质量结论仍等待终态审计。",
                     "现有提醒 revision 与待确认记录沿用；观察器不会代队友确认。", ""]
            for run in table_runs:
                lines += [f"- FIFO {run['ticket']}：{run['completed_samples']}/28 输出；执行 {run['execution_state']}；质量 {run['quality_conclusion']}",
                          f"  阶段记录的实际模型调用：{run['actual_model_requests']}；完成行调用：{run['completed_row_model_requests']}；尚未归入完成行：{run['unrepresented_model_requests']}"]
                if run.get("completed_row_requests_by_arm") is not None:
                    lines += ["  完成行两臂调用："+json.dumps(run["completed_row_requests_by_arm"], ensure_ascii=False)]
                if run["observation_error"]:
                    lines += ["  观察错误："+run["observation_error"]]
            owned = tool.inside(ledger_base, Path(ledger_base)/owner)
            with tool.owned_lock(owned):
                tool.write(tool.inside(owned, owned/"TABLE_PROGRESS.md"), "\n".join(lines)+"\n")
        return card

    tool.observe_run, tool.publish = observe_run, publish
    return tool


def main(argv=None):
    # Explicit original location keeps this draft portable without editing it.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--base-tool", required=True, type=Path)
    args, forwarded = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    tool = extend_tool(args.base_tool)
    previous = sys.argv
    try:
        sys.argv = [previous[0], *forwarded]
        return tool.main()
    finally:
        sys.argv = previous


if __name__ == "__main__":
    main()
