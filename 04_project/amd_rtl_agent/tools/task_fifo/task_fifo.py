"""Linux whole-task FIFO admission; existing model and per-stage guards stay put.

Only jobs registered here share this reservation. It deliberately does not
rewrite slot.sh, seize legacy locks, kill processes, or restart the model.
"""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

DONE = {"completed", "cancelled_before_start", "failed_released_after_inspection"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def registry(root):
    root = Path(root)
    (root / "tickets").mkdir(parents=True, exist_ok=True)
    with (root / "registry.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
        fcntl.flock(lock, fcntl.LOCK_UN)


def ticket_path(root, number):
    return Path(root) / "tickets" / ("%08d.json" % number)


def identity(pid):
    try:
        base = Path("/proc") / str(pid)
        fields = (base / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        return dict(pid=pid, starttime=fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


def entries(root):
    return [read(path) for path in sorted((Path(root) / "tickets").glob("*.json"))]


def head(root):
    return next((item for item in entries(root) if item["state"] not in DONE), None)


def register(root, task_name, command, cwd, completion, owner_prefix, adopted=None):
    with registry(root):
        if adopted is not None and head(root) is not None:
            raise RuntimeError("An already-running job can be adopted only into an empty FIFO")
        counter = Path(root) / "counter.json"
        number = (read(counter)["last_issued"] if counter.exists() else 0) + 1
        save(counter, dict(last_issued=number))
        item = dict(schema="whole_task_fifo_v1", ticket=number, task_name=task_name,
                    accepted_at_utc=now(), state="queued", command=command, cwd=str(cwd),
                    completion_json=str(completion), slot_owner_prefix=owner_prefix,
                    adopted_process=adopted)
        save(ticket_path(root, number), item)
    return item


def completion_ok(item):
    path = Path(item["completion_json"])
    if not path.is_file():
        return False
    data = read(path)
    return data.get("complete") is True and data.get("passed", True) is True and data.get("valid", True) is True


def probe(item):
    """Read-only admission/retirement check; no cancellation or lock mutation."""
    model = identity(2013333)
    if model is None:
        return False
    executable = Path(os.readlink("/proc/2013333/exe")).name
    if "llama-server" not in executable:
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:8000/health", timeout=5) as response:
            health = json.load(response)
        with opener.open("http://127.0.0.1:8000/slots", timeout=5) as response:
            slots = json.load(response)
    except (OSError, ValueError):
        return False
    if health.get("status") != "ok" or not isinstance(slots, list) or not slots:
        return False
    if any(slot.get("is_processing") is not False for slot in slots):
        return False
    for directory in Path("/proc").glob("[0-9]*"):
        try:
            name = (directory / "comm").read_text().strip()
            state = (directory / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            continue
        if state not in ("Z", "X") and name in {"xvlog", "xelab", "xsim", "xsimk", "vivado"}:
            return False
    slot = Path("/workspace/team/SLOT.lock")
    try:
        owner = slot.read_text().splitlines()[0]
    except FileNotFoundError:
        owner = None
    # Before starting, legacy resource use gets to finish. After our completion,
    # any still-present resource lock also delays FIFO retirement conservatively.
    return owner is None


def execute(root, number, check=probe, poll_s=2, lifetime_s=86400):
    path = ticket_path(root, number)
    deadline = time.monotonic() + lifetime_s
    item = read(path)
    process = None
    try:
        if item["state"] != "queued":
            raise RuntimeError("Ticket is not awaiting its first execution; no automatic rerun")
        while True:
            with registry(root):
                item = read(path)
                if item["state"] == "cancelled_before_start":
                    return
                first = head(root)
                admitted = first is not None and first["ticket"] == number
            if admitted and (item["adopted_process"] is not None or check(item)):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("FIFO wait lifetime expired; retained for inspection")
            time.sleep(poll_s)
        if item["adopted_process"] is None and Path(item["completion_json"]).exists():
            raise RuntimeError("Use a fresh completion receipt for a newly submitted task")
        with registry(root):
            item = read(path)
            if item["state"] == "cancelled_before_start":
                return
            assert head(root)["ticket"] == number
            item.update(state="adopted_running" if item["adopted_process"] else "running",
                        started_at_utc=now(), runner=identity(os.getpid()),
                        task_fifo_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            save(path, item)
        if item["adopted_process"] is not None:
            target = item["adopted_process"]
            while identity(target["pid"]) == target:
                time.sleep(poll_s)
            returncode = None
        else:
            log = Path(root) / ("task_%08d.log" % number)
            with log.open("xb") as stream:
                process = subprocess.Popen(item["command"], cwd=item["cwd"], stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with registry(root):
                    item = read(path)
                    item["child"] = identity(process.pid)
                    save(path, item)
                returncode = process.wait()
        if returncode not in (None, 0) or not completion_ok(item):
            raise RuntimeError("Task failed or completion receipt is not verified; FIFO head retained")
        retirement_deadline = time.monotonic() + 300
        while not check(item):
            if time.monotonic() >= retirement_deadline:
                raise RuntimeError("Shared model/slot not idle after completion; FIFO head retained")
            time.sleep(poll_s)
        with registry(root):
            item = read(path)
            item.update(state="completed", finished_at_utc=now(), returncode=returncode,
                        completion_sha256=hashlib.sha256(Path(item["completion_json"]).read_bytes()).hexdigest())
            save(path, item)
    except BaseException as error:
        with registry(root):
            item = read(path)
            if item["state"] not in DONE:
                item.update(state="held_for_inspection", error=(type(error).__name__ + ": " + str(error))[:1000])
                save(path, item)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/workspace/team/task_fifo"))
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("submit", "adopt"):
        command = sub.add_parser(action)
        command.add_argument("--task-name", required=True)
        command.add_argument("--cwd", type=Path, required=True)
        command.add_argument("--completion-json", type=Path, required=True)
        command.add_argument("--slot-owner-prefix", required=True)
        if action == "adopt":
            command.add_argument("--pid", type=int, required=True)
        else:
            command.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    worker = sub.add_parser("_run")
    worker.add_argument("--ticket", type=int, required=True)
    cancel = sub.add_parser("cancel-queued")
    cancel.add_argument("--ticket", type=int, required=True)
    release = sub.add_parser("release-held")
    release.add_argument("--ticket", type=int, required=True)
    release.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.action == "status":
        with registry(args.root):
            print(json.dumps([dict(ticket=x["ticket"], task_name=x["task_name"], state=x["state"],
                                  accepted_at_utc=x["accepted_at_utc"], error=x.get("error")) for x in entries(args.root)], ensure_ascii=False))
        return
    if args.action == "cancel-queued":
        with registry(args.root):
            path = ticket_path(args.root, args.ticket)
            item = read(path)
            if item["state"] != "queued":
                raise RuntimeError("Only a task that has not started can be cancelled; no process killing")
            item.update(state="cancelled_before_start", cancelled_at_utc=now())
            save(path, item)
        return
    if args.action == "release-held":
        with registry(args.root):
            path = ticket_path(args.root, args.ticket)
            item = read(path)
            targets = [item.get("child"), item.get("adopted_process")]
            if item["state"] != "held_for_inspection" or any(target and identity(target["pid"]) == target for target in targets):
                raise RuntimeError("Held ticket still has a live task; do not stop it")
            if not args.reason.strip() or not probe(item):
                raise RuntimeError("Inspection reason and idle model/tools/resource slot required")
            item.update(state="failed_released_after_inspection", released_at_utc=now(), inspection_reason=args.reason)
            save(path, item)
        return
    if args.action == "_run":
        execute(args.root, args.ticket)
        return
    adopted = identity(args.pid) if args.action == "adopt" else None
    if args.action == "adopt" and adopted is None:
        raise RuntimeError("Adopted PID is not a live process")
    command = args.command if args.action == "submit" else []
    if command and command[0] == "--":
        command = command[1:]
    if args.action == "submit" and not command:
        raise ValueError("A command is required")
    if not args.cwd.is_dir() or not args.slot_owner_prefix:
        raise ValueError("Existing working directory and explicit slot owner prefix required")
    item = register(args.root, args.task_name, command, args.cwd.resolve(), args.completion_json.resolve(), args.slot_owner_prefix, adopted)
    argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--root", str(args.root.resolve()), "_run", "--ticket", str(item["ticket"])]
    with (args.root / ("runner_%08d.log" % item["ticket"])).open("xb") as log:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print(json.dumps(dict(ticket=item["ticket"], task_name=item["task_name"], monitor_pid=process.pid, accepted_at_utc=item["accepted_at_utc"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
