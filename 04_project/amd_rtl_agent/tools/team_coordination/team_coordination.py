"""Owned progress cards and revision-bound reviews; no model/tool execution."""
import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

SCHEMA = "team_coordination_v1"
RUN_SCHEMAS = {"phaseP_stability156x5_v1", "semantic_edge_guidance_pilot_v1",
               "compile_diag_priority_pilot_v1", "phase_full156_v1"}
STATUSES = {"investigate", "prepared", "queued", "running", "completed_pending_audit",
            "verified_bounded", "rejected", "blocked", "unknown"}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("Invalid namespace or notice identifier")
    return value


def inside(base, path):
    base, path = Path(base).resolve(), Path(path).resolve()
    if path == base or not path.is_relative_to(base):
        raise ValueError("Path outside owned namespace")
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


@contextmanager
def owned_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "coordination.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def validate(plan, owner, runs_base):
    if plan["owner"] != name(owner):
        raise ValueError("Plan owner differs from publishing owner")
    timestamp(plan["authored_at_utc"])
    for field in ("branch", "commit", "summary", "next_step"):
        if not isinstance(plan[field], str) or not plan[field]:
            raise ValueError("Missing plan text: " + field)
    for field in ("changed_files", "issues", "notices", "runs"):
        if not isinstance(plan[field], list):
            raise ValueError("Missing plan list: " + field)
    if any(not isinstance(item, str) for item in plan["changed_files"]):
        raise ValueError("Changed files must be text paths")
    for issue in plan["issues"]:
        if issue["status"] not in STATUSES or not all(isinstance(issue[k], str) and issue[k] for k in ("issue_key", "experiment_key")):
            raise ValueError("Invalid issue identity/status")
        if any(not isinstance(issue[k], list) or any(not isinstance(v, str) for v in issue[k]) for k in ("evidence", "limits")):
            raise ValueError("Evidence and limits must be lists")
        if issue["status"] == "verified_bounded" and (not issue["evidence"] or not issue["limits"]):
            raise ValueError("Verified issue requires evidence and scope limits")
    notices = [name(n["id"]) for n in plan["notices"]]
    if len(notices) != len(set(notices)) or any(not isinstance(n["revision"], str) or not n["revision"] or not isinstance(n["text"], str) or not n["text"] for n in plan["notices"]):
        raise ValueError("Invalid notice revision/identity")
    owned_runs = inside(runs_base, Path(runs_base) / owner)
    for run in plan["runs"]:
        inside(owned_runs, run["root"])
        if type(run["ticket"]) is not int or run["ticket"] < 1 or type(run["expected_samples"]) is not int or run["expected_samples"] < 1:
            raise ValueError("Invalid run ticket/count")
        if not re.fullmatch(r"[0-9a-f]{64}", run["spec_sha256"]):
            raise ValueError("Invalid frozen specification digest")


def observe_run(run, tickets_base):
    result = dict(run, status="unknown", completed_samples=None, observation_error=None)
    try:
        ticket = read(Path(tickets_base) / ("%08d.json" % run["ticket"]))
        if ticket["schema"] != "whole_task_fifo_v1" or ticket["ticket"] != run["ticket"] or Path(ticket["cwd"]).resolve() != Path(run["root"]).resolve():
            raise ValueError("Ticket identity or owned run mismatch")
        result["ticket_state"] = ticket["state"]
        root = Path(run["root"])
        if hashlib.sha256((root / "RUN_SPEC.json").read_bytes()).hexdigest() != run["spec_sha256"]:
            raise ValueError("Frozen specification mismatch")
        summary = read(root / "results/summary.json")
        if summary["schema"] not in RUN_SCHEMAS or summary["spec_sha256"] != run["spec_sha256"] or not isinstance(summary["rows"], list):
            raise ValueError("Unknown or unbound run summary")
        if type(summary["complete"]) is not bool or type(summary["passed"]) is not bool or len(summary["rows"]) > run["expected_samples"]:
            raise ValueError("Invalid completion/count")
        result["completed_samples"] = len(summary["rows"])
        result["status"] = "failed" if summary.get("error") or summary["complete"] and not summary["passed"] else "completed_pending_audit" if summary["complete"] and len(summary["rows"]) == run["expected_samples"] else "running" if not summary["complete"] else "unknown"
        result["stage_error"] = summary.get("error")
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["observation_error"] = type(error).__name__ + ": " + str(error)
    if result.get("ticket_state") in {"held_for_inspection", "failed_released_after_inspection"}:
        result["status"] = "failed"
    return result


def publish(plan, owner, ledger_base, runs_base, tickets_base, observed_at=None, watcher=None):
    validate(plan, owner, runs_base)
    root = inside(ledger_base, Path(ledger_base) / owner)
    card = dict(plan, schema=SCHEMA, observed_at_utc=observed_at or utc(), developer_activity="unknown", watcher=watcher,
                runs=[observe_run(run, tickets_base) for run in plan["runs"]])
    current = ["# 当前工作", "", "作者：" + owner, "计划写于：" + plan["authored_at_utc"],
               "现场观察：" + card["observed_at_utc"], "此时间仅表示观察，开发者是否活跃未知。", "分支/提交：" + plan["branch"] + " / " + plan["commit"],
               "", plan["summary"], "", "下一步：" + plan["next_step"], "", "修改文件：" + ", ".join(plan["changed_files"])]
    for run in card["runs"]:
        current += ["", f"- FIFO {run['ticket']}：{run['status']}；{run['completed_samples']}/{run['expected_samples']}；票状态 {run.get('ticket_state', 'unknown')}"]
        if run["observation_error"] or run.get("stage_error"):
            current += ["  观察/运行错误：" + str(run["observation_error"] or run["stage_error"])]
    problems = ["# 问题登记", "", "未审计完成不表示已验证；过期卡不表示可接管。", ""]
    for issue in plan["issues"]:
        problems += [f"- {issue['issue_key']} | {issue['experiment_key']} | {issue['status']}",
                     "  证据：" + "; ".join(issue["evidence"]), "  边界：" + "; ".join(issue["limits"])]
    notices = ["# 待阅读与确认", "", "确认须由接收方在自己的命名空间记录当前 revision。", ""]
    for notice in plan["notices"]:
        notices += [f"- {notice['id']} / {notice['revision']}：{notice['text']}"]
    with owned_lock(root):
        for filename, lines in (("CURRENT_WORK.md", current), ("PROBLEMS.md", problems), ("REVIEW_REQUIRED.md", notices)):
            write(inside(root, root / filename), "\n".join(lines) + "\n")
        write(inside(root, root / "COORDINATION.json"), card)
    return card


def ack(owner, author, notice_id, revision, ledger_base):
    name(owner); name(author); name(notice_id)
    if owner == author:
        raise ValueError("Reviewer must differ from notice author")
    author_root = inside(ledger_base, Path(ledger_base) / author)
    card_path = inside(author_root, author_root / "COORDINATION.json")
    card = read(card_path)
    notice = next((n for n in card["notices"] if n["id"] == notice_id), None)
    if card["schema"] != SCHEMA or card["owner"] != author or not notice or notice["revision"] != revision:
        raise ValueError("Notice revision does not match author's current card")
    root = inside(ledger_base, Path(ledger_base) / owner)
    receipt = dict(schema="team_review_v1", owner=owner, author=author, notice_id=notice_id,
                   revision=revision, reviewed_at_utc=utc())
    with owned_lock(root):
        write(inside(root, root / "reviews" / author / (notice_id + ".json")), receipt)
    return receipt


def check(ledger_base, now_at=None):
    moment = timestamp(now_at or utc())
    cards, errors, directions, reviews, unregistered, member_names = [], [], {}, [], [], []
    for folder in sorted(Path(ledger_base).iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        try:
            member_names.append(name(folder.name))
            card = read(inside(folder, folder / "COORDINATION.json"))
            if card["schema"] != SCHEMA or card["owner"] != folder.name:
                raise ValueError("Invalid card owner/schema")
            age = (moment - timestamp(card["observed_at_utc"])).total_seconds()
            freshness = "unknown" if age < 0 else "stale" if age > 900 else "fresh"
            cards.append(dict(owner=card["owner"], freshness=freshness, age_s=age, card=card))
            for issue in card["issues"]:
                directions.setdefault(issue["issue_key"], []).append(dict(owner=card["owner"],
                    experiment_key=issue["experiment_key"], status=issue["status"], freshness=freshness,
                    verified=issue["status"] == "verified_bounded" and freshness == "fresh" and bool(issue["evidence"]) and bool(issue["limits"])))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(dict(owner=folder.name, freshness="unknown", error=str(error)))
    for entry in cards:
        author = entry["owner"]
        for notice in entry["card"]["notices"]:
            if len(member_names) == 1:
                unregistered.append(dict(author=author, notice_id=notice["id"], revision=notice["revision"], status="no_registered_reviewers"))
            for reviewer in [owner for owner in member_names if owner != author]:
                confirmed = False
                try:
                    reviewer_root = inside(ledger_base, Path(ledger_base) / reviewer)
                    r = read(inside(reviewer_root, reviewer_root / "reviews" / author / (name(notice["id"]) + ".json")))
                    confirmed = r["schema"] == "team_review_v1" and r["owner"] == reviewer and r["author"] == author and r["notice_id"] == notice["id"] and r["revision"] == notice["revision"]
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                reviews.append(dict(author=author, reviewer=reviewer, notice_id=notice["id"],
                                    revision=notice["revision"], acknowledged=confirmed))
    return dict(observed_at_utc=moment.isoformat(), members=cards, unknown_members=errors,
                repeated_directions={k: v for k, v in directions.items() if len({e['owner'] for e in v}) > 1},
                reviews=reviews, unregistered_reviews=unregistered, stale_ownership_released=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("publish", "watch", "ack", "check"))
    parser.add_argument("--ledger-root", type=Path, default=Path("/workspace/team/activity"))
    parser.add_argument("--runs-root", type=Path, default=Path("/workspace/team/runs"))
    parser.add_argument("--tickets-root", type=Path, default=Path("/workspace/team/task_fifo/tickets"))
    parser.add_argument("--stop-ticket", type=int)
    parser.add_argument("--max-watch-seconds", type=int, default=50400)
    for option in ("owner", "plan", "author", "notice-id", "revision"):
        parser.add_argument("--" + option)
    args = parser.parse_args()
    if args.action == "check":
        result = check(args.ledger_root)
    elif args.action == "ack":
        result = ack(args.owner, args.author, args.notice_id, args.revision, args.ledger_root)
    else:
        plan = read(args.plan)
        plan.setdefault("authored_at_utc", utc())
        if not 0 < args.max_watch_seconds <= 50400 or args.action == "watch" and args.stop_ticket not in [r["ticket"] for r in plan["runs"]]:
            raise ValueError("Watch requires an owned stop-ticket and maximum duration <=14h")
        started = time.monotonic()
        watcher = dict(mode=args.action, pid=os.getpid(), stopped=False, stop_ticket=args.stop_ticket, maximum_seconds=args.max_watch_seconds)
        while True:
            updated = read(args.plan)
            updated.setdefault("authored_at_utc", plan["authored_at_utc"])
            plan = updated
            result = publish(plan, args.owner, args.ledger_root, args.runs_root, args.tickets_root, watcher=watcher)
            if args.action == "publish":
                break
            terminal = next(r for r in result["runs"] if r["ticket"] == args.stop_ticket)
            remaining = args.max_watch_seconds - (time.monotonic() - started)
            if terminal.get("ticket_state") in {"completed", "held_for_inspection", "failed_released_after_inspection", "cancelled_before_start"} or terminal["status"] in {"failed", "completed_pending_audit"} or remaining <= 0:
                watcher.update(stopped=True, stop_reason="owned_run_terminal" if remaining > 0 else "maximum_duration")
                result = publish(plan, args.owner, args.ledger_root, args.runs_root, args.tickets_root, watcher=watcher)
                break
            time.sleep(min(60, remaining))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
