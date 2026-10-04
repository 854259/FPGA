"""Read-only observation of owned full-evaluation evidence into a shared ledger.

No model/tool calls. Does not alter experiment sources or other authors' logs.
"""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import time


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append(root, kind, event_id, summary, data):
    assert kind in ("calls", "changes", "conclusions")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (kind + ".jsonl")
    with (root / "ledger.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        if not any(entry["event_id"] == event_id for entry in entries):
            event = dict(schema="team_activity_v1", event_id=event_id, kind=kind,
                         observed_at_utc=now(), summary=summary, data=data)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                stream.flush()
        fcntl.flock(lock, fcntl.LOCK_UN)


def sync(run_root, ledger_root):
    run_root, ledger_root = Path(run_root), Path(ledger_root)
    status = read(run_root / "queue_status.json")
    calls = 0
    existing = {}
    for kind in ("calls", "conclusions"):
        path = ledger_root / (kind + ".jsonl")
        existing[kind] = {json.loads(line)["event_id"] for line in path.read_text(encoding="utf-8").splitlines()} if path.exists() else set()
    for arm in ("A", "C"):
        for path in sorted((run_root / "samples" / arm).glob("*/worker/requests.json")):
            task = path.parent.parent.name
            for entry in read(path):
                if not entry["response_received"]:
                    continue
                folder = path.parent / "requests" / str(entry["index"])
                payload = read(folder / "response.json")
                request = read(folder / "request.json")
                usage = payload.get("usage") or {}
                data = dict(task=task, arm=arm, round=entry["index"], model=request["model"],
                    elapsed_s=entry["elapsed_s"], finish_reason=entry["finish_reason"],
                    tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"),
                    response_sha256=entry["response_sha256"], evidence_path=str(folder),
                    timestamp_scope="Observation time; original request/response remain in private evidence")
                event_id = f"full156:{task}:{arm}:{entry['index']}:{entry['response_sha256']}"
                if event_id not in existing["calls"]:
                    append(ledger_root, "calls", event_id,
                           f"{task} / {arm} / {'首生成' if entry['index'] == 0 else '普通复查'}已收到回复", data)
                    existing["calls"].add(event_id)
                calls += 1
    rows = []
    for arm in ("A", "C"):
        for path in sorted((run_root / "samples" / arm).glob("*/accepted_row.json")):
            row = read(path)
            assert row["complete"] and row["valid"]
            rows.append(row)
            event_id = f"sample:{row['task']}:{arm}:{row['solution_sha256']}"
            if event_id not in existing["conclusions"]:
                append(ledger_root, "conclusions", event_id,
                       f"逐样本结果：{row['task']} / {arm} / L{row['verdict']['level']}，尚非全量结论",
                       dict(scope="one sample in ongoing known-public regression", task=row["task"], arm=arm,
                        level=row["verdict"]["level"], model_requests=row["actual_model_requests"],
                        solve_elapsed_s=row["solve_elapsed_s"], solution_sha256=row["solution_sha256"],
                        evidence_path=str(path), full_round_audited=False))
                existing["conclusions"].add(event_id)
    queue = Path("/workspace/team/task_fifo/tickets")
    tickets = []
    if queue.is_dir():
        for path in sorted(queue.glob("*.json")):
            item = read(path)
            tickets.append(dict(ticket=item["ticket"], task=item["task_name"], state=item["state"]))
    ledger_root.mkdir(parents=True, exist_ok=True)
    snapshot = dict(schema="team_activity_snapshot_v1", observed_at_utc=now(), run_root=str(run_root),
        experiment="full156_bundle_20261004", state=status["state"], complete=status["complete"],
        completed_samples=status["completed_samples"], expected_samples=312, calls_received=calls,
        current_task=status.get("current_task"), current_arm=status.get("current_arm"), fifo=tickets,
        source_spec_sha256=status["source_spec_sha256"], final_score_audited=False)
    temporary = ledger_root / "SNAPSHOT.json.pending"
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger_root / "SNAPSHOT.json")
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    text = f"# 当前测试与修改台账\n\n更新时间：{timestamp}（北京时间）\n\n"
    text += "正在测试：全部156道公开VerilogEval题，A原较好版本与C辅助模块保护版本各1次真实求解。每题300秒，0补抽；参考／测试台只在外部判定侧使用。当前为已知公开题回归，不是未见题盲测。\n\n"
    text += f"状态：{status['state']}；已完成 **{status['completed_samples']}/312** 个样本，已收到 **{calls}** 次模型回复。当前：{status.get('current_task')} / {status.get('current_arm')}。\n\n"
    text += "整轮结束后仍需离线审计才能发布新全量分；这里的逐题等级仅为进度证据。共享模型／正式部署未因台账改动；旧0.7667分只作历史记录。\n\n"
    text += "| FIFO票号 | 整轮任务 | 状态 |\n|---|---|---|\n"
    for item in tickets:
        text += f"| {item['ticket']} | {item['task']} | {item['state']} |\n"
    text += "\n调用记录：calls.jsonl（仅元数据，不含模型正文／参考答案）。修改记录：changes.jsonl。测试结果与范围：conclusions.jsonl。原始证据目录：" + str(run_root) + "。\n\n"
    path = ledger_root / "changes.jsonl"
    if path.exists():
        text += "最近修改：\n\n"
        for item in [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()][-5:]:
            text += "- " + item["summary"] + "\n"
    temporary = ledger_root / "STATUS.md.pending"
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(ledger_root / "STATUS.md")
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    observe = sub.add_parser("observe")
    observe.add_argument("--run-root", type=Path, required=True)
    observe.add_argument("--once", action="store_true")
    note = sub.add_parser("append")
    note.add_argument("--kind", choices=("calls", "changes", "conclusions"), required=True)
    note.add_argument("--event-id", required=True)
    note.add_argument("--summary", required=True)
    note.add_argument("--data-json", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "append":
        append(args.ledger_root, args.kind, args.event_id, args.summary, read(args.data_json))
        return
    while True:
        snapshot = sync(args.run_root, args.ledger_root)
        if args.once or snapshot["complete"] or snapshot["state"] == "stopped_with_evidence":
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
