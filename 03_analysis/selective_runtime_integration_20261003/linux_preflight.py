#!/usr/bin/env python3
"""AMD-only Linux preflight for the frozen 773d4ce prototype.

UNRUN on delivery. Run through resource_guard.py on the authorised AMD host.
This uses a private loopback responder, real Vivado, and copied packages. It
does not launch/stop the shared model or change the submission/baseline.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPT = Path(__file__).resolve()
PACKAGE = HERE / "package"
INPUT = REPO / "03_analysis/r2_signedness_20261003/input/Prob115_shift18"
PROBES = REPO / "03_analysis/r2_signedness_20261003/probes"
FROZEN_RUNTIME = "318672f841430a864cd99fae4de712942258d0dcda7a1ad6b0567c71610f52c8"
BUDGET = {"llm_cap_s": 20, "compile_cap_s": 5, "cleanup_reserve_s": 6,
          "admission_s": 31}
REVIEW_ENV = ("RTL_REVIEW_LLM_CAP_S", "RTL_REVIEW_COMPILE_CAP_S",
              "RTL_REVIEW_CLEANUP_RESERVE_S", "RTL_REVIEW_SOCKET_CAP_S")
OWNED_ROOTS = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def append(path, value):
    raw = (json.dumps(value, ensure_ascii=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()] if Path(path).exists() else []


def unchanged(files):
    try:
        return all(sha(REPO / name) == digest for name, digest in files.items())
    except OSError:
        return False


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return {"pid": int(pid), "starttime": fields[19], "pgid": int(fields[2]),
                "ppid": int(fields[1]), "state": fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def status(record):
    current = identity(record["pid"])
    if not current:
        return {**record, "observed_state": "absent"}
    if current["starttime"] != record["starttime"]:
        return {**record, "observed_state": "identity_reused"}
    return {**record, "observed_state": current["state"], "current_pgid": current["pgid"]}


def group_records(pgid):
    # Observation only. A group is recorded only after our own Popen created it.
    return [row for path in Path("/proc").glob("[0-9]*")
            if (row := identity(int(path.name))) and row["pgid"] == pgid]


def unique_records(rows):
    return list({(row["pid"], row["starttime"]): row for row in rows if row}.values())


def reap_owned(records):
    # The harness is a subreaper. Never wait/kill a shared or unrecorded process.
    for row in records:
        current = identity(row["pid"])
        if current and current["starttime"] == row["starttime"] and current["state"] == "Z":
            try:
                os.waitpid(row["pid"], os.WNOHANG)
            except ChildProcessError:
                pass


def settle(records, seconds=5):
    deadline = time.monotonic() + seconds
    while True:
        reap_owned(records)
        states = [status(row) for row in records]
        if all(row["observed_state"] in ("absent", "identity_reused") for row in states):
            return states
        if time.monotonic() >= deadline:
            return states
        time.sleep(.025)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def environment(values):
    before = dict(os.environ)
    try:
        for name in REVIEW_ENV:
            os.environ.pop(name, None)  # Exercise the actual 20/5/6 defaults.
        os.environ.update({key: str(value) for key, value in values.items()})
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def source_checks():
    manifest = json.loads((HERE / "source_manifest.json").read_text())
    assets = {name: row["sha256"] for name, row in manifest["files"].items()
              if "/selective_runtime_integration_20261003/package/" in name
              or "/r2_signedness_20261003/input/Prob115_shift18/" in name}
    if sha(PACKAGE / "agent/runtime.py") != FROZEN_RUNTIME:
        raise ValueError("frozen runtime SHA-256 mismatch")
    for name, digest in assets.items():
        if sha(REPO / name) != digest:
            raise ValueError("source manifest mismatch: " + name)
    formal = REPO / "04_project/amd_rtl_agent/submission"
    protected = {str(path.relative_to(REPO)): sha(path) for path in formal.rglob("*")
                 if path.is_file() and "__pycache__" not in path.parts}
    return assets, protected


def check_resources(path):
    value = json.loads(Path(path).read_text())
    stamp = datetime.fromisoformat(value["checked_at_utc"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if (value.get("schema_version") != 1 or value.get("host") != socket.gethostname()
            or value.get("resource_idle") is not True or not 0 <= age <= 120):
        raise ValueError("resource check must be host-matched and <=120 seconds old")
    lock = Path(value["slot_lock_path"])
    owner = str(value["slot_owner"])
    if not owner or sha(lock) != value["slot_lock_sha256"]:
        raise ValueError("resource slot identity changed")
    # Supports the existing slot's text owner record as well as a JSON record.
    if lock.read_text().splitlines()[0] != owner:
        raise ValueError("resource slot owner mismatch")
    model = identity(int(value["model_pid"]))
    if not model or model["state"] in ("Z", "X") or model["starttime"] != str(value["model_starttime"]):
        raise ValueError("shared model identity changed")
    for group in ("baseline_hashes", "official_hashes"):
        if not value.get(group):
            raise ValueError("missing protected hashes: " + group)
        for name, digest in value[group].items():
            source = Path(name) if Path(name).is_absolute() else REPO / name
            if sha(source) != digest:
                raise ValueError("resource-check protected source mismatch: " + name)
    return value


class FakeModel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with self.server.fixture_lock:
            index = len(self.server.received)
            self.server.received.append(request)
            reply = self.server.replies[index] if index < len(self.server.replies) else {"status": 500}
        if self.server.stop_fixture.wait(reply.get("delay_s", 0)):
            return
        payload = {"model": "private-preflight-responder", "choices": [{"finish_reason": "stop",
                   "message": {"content": reply.get("source", "")}}],
                   "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        raw = json.dumps(payload).encode()
        self.send_response(reply.get("status", 200))
        self.send_header("Content-Length", str(len(raw)))
        try:
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextmanager
def fake_model():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    server.daemon_threads = False
    server.fixture_lock = threading.Lock()
    server.stop_fixture = threading.Event()
    server.received, server.replies = [], []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.stop_fixture.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def real_tool(argv):
    evidence = Path(os.environ["PREFLIGHT_TOOL_DIR"])
    folder = evidence / (str(time.time_ns()) + "-" + str(os.getpid()))
    folder.mkdir()
    source = Path(argv[-1])
    shutil.copyfile(source, folder / "candidate.sv")
    command = [str(Path(os.environ["PREFLIGHT_REAL_BIN"]) / "xvlog"), *argv]
    started = time.monotonic()
    begin = {"event": "start", "identity": identity(os.getpid()), "argv": command,
             "cwd": str(Path.cwd()), "original_source_path": str(source), "source_path": str(folder / "candidate.sv"),
             "source_sha256": sha(source), "saved_source": str(folder / "candidate.sv")}
    append(evidence / "tools.jsonl", begin)
    with (folder / "xvlog.log").open("xb") as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        append(evidence / "tools.jsonl", {**begin, "event": "compiler_child", "identity": identity(proc.pid)})
        proc.wait()
    append(evidence / "tools.jsonl", {**begin, "event": "end", "rc": proc.returncode,
           "elapsed_s": time.monotonic() - started, "log": str(folder / "xvlog.log"),
           "log_sha256": sha(folder / "xvlog.log")})
    sys.stdout.buffer.write((folder / "xvlog.log").read_bytes())
    return proc.returncode


def make_tools(out, real_bin):
    tools, logs = out / "bin", out / "tool_logs"
    tools.mkdir()
    logs.mkdir()
    wrapper = tools / "xvlog"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                       shlex.quote(str(SCRIPT)) + " _real-tool -- \"$@\"\n")
    wrapper.chmod(0o700)
    return {"VIVADO_BIN": tools, "PREFLIGHT_REAL_BIN": real_bin, "PREFLIGHT_TOOL_DIR": logs,
            "PATH": str(tools) + os.pathsep + str(real_bin) + os.pathsep + os.environ.get("PATH", "")}


def copy_package(out, forced=False):
    dest = out / ("forced_package" if forced else "package")
    shutil.copytree(PACKAGE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if forced:
        selector = dest / "agent/signedness_selector.py"
        shutil.copyfile(selector, selector.with_name("fixture_original_selector.py"))
        selector.write_text("# Test fixture only: deliberately force a correct candidate into review.\n"
                            "from fixture_original_selector import _strip_noncode\n"
                            "def analyze(prompt, source):\n"
                            "    return {'decision': 'review', 'reasons': ['forced_correct_test_fixture_only'], 'findings': []}\n")
    if sha(dest / "agent/runtime.py") != FROZEN_RUNTIME:
        raise ValueError("copied runtime SHA mismatch")
    return dest


def run_case(package, server, out, case_id, initial, revised, seconds, expected,
             review="checklist", delay_s=0):
    case = out / case_id
    case.mkdir()
    task = case / "task"
    task.mkdir()
    shutil.copyfile(INPUT / "prompt.txt", task / "prompt.txt")
    (case / "original.sv").write_text(initial)
    if revised is not None:
        (case / "offered_review.sv").write_text(revised)
    with server.fixture_lock:
        server.received = []
        server.replies = [{"source": initial}] + ([{"source": revised, "delay_s": delay_s}] if revised is not None else [])
    runtime = load("preflight_" + case_id, package / "agent/runtime.py")
    original_popen, original_stop = runtime.subprocess.Popen, runtime.stop_tree
    identities, stops = [], []
    owned_groups = []
    monitor_stop = threading.Event()
    tool_record_path = Path(os.environ["PREFLIGHT_TOOL_DIR"]) / "tools.jsonl"
    tool_offset = len(read_rows(tool_record_path))

    def monitor():
        while not monitor_stop.wait(.01):
            for pgid in list(owned_groups):
                identities.extend(group_records(pgid))

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()

    def record_popen(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        row = identity(proc.pid)
        if row:
            identities.append(row)
            if kwargs.get("start_new_session") and row["pgid"] == proc.pid:
                owned_groups.append(proc.pid)
                OWNED_ROOTS[proc.pid] = proc
        return proc

    def record_stop(proc):
        members = group_records(proc.pid)
        identities.extend(members)
        before = [status(row) for row in unique_records(identities)]
        original_stop(proc)
        stops.append({"before": before, "after": [status(row) for row in unique_records(identities)]})

    started = time.monotonic()
    job_completed = False
    try:
        runtime.subprocess.Popen, runtime.stop_tree = record_popen, record_stop
        with environment({"RTL_REVIEW_MODE": review}):
            solution, raw_trace = runtime.run_job("agent", task, case / "run", seconds)
            job_completed = True
    finally:
        runtime.subprocess.Popen, runtime.stop_tree = original_popen, original_stop
        monitor_stop.set()
        monitor_thread.join(timeout=5)
        if job_completed:
            for pgid in owned_groups:
                OWNED_ROOTS.pop(pgid, None)  # run_job's own finally already stopped it.
    elapsed = time.monotonic() - started
    events = [json.loads(line) for line in raw_trace.splitlines()]
    with server.fixture_lock:
        requests = list(server.received)
    json_write(case / "requests.json", requests)
    commit = next((row for row in events if row["tool"] == "review_commit"), {})
    actual = case / "run/solution.v"
    checks = {"expected_source": solution == expected["source"],
              "request_count": len(requests) == expected["calls"],
              "expected_commit": commit.get("status") == expected["status"],
              "expected_reason": commit.get("reason") in expected["reasons"],
              "worker_done": bool(events and events[-1]["tool"] == "worker_done"),
              "default_budget": all(next((row for row in events if row["tool"] == "review_meta"), {}).get(key) == value
                                    for key, value in BUDGET.items() if key != "admission_s")}
    if expected.get("declaration_fix"):
        checks["declaration_fix"] = any(row["tool"] == "declaration_fix" for row in events)
    tool_records = read_rows(tool_record_path)[tool_offset:]
    identities.extend(row["identity"] for row in tool_records if row.get("identity"))
    states = settle(unique_records(identities))
    checks["owned_processes_gone"] = all(row["observed_state"] in ("absent", "identity_reused") for row in states)
    row = {"case_id": case_id, "passed": all(checks.values()), "checks": checks,
           "seconds": seconds, "elapsed_s": elapsed, "solution_sha256": sha(actual),
           "solution": str(actual), "original_sha256": text_sha(initial), "original_path": str(case / "original.sv"),
           "offered_sha256": text_sha(revised) if revised is not None else None,
           "offered_path": str(case / "offered_review.sv") if revised is not None else None,
           "requests_received": len(requests), "extra_calls_received": max(0, len(requests) - 1),
           "calls_attempted": sum(event["tool"] in ("llm_start", "review_llm_start") for event in events),
           "review_commit": commit, "events": events, "outer_cleanup": stops,
           "owned_final_states": states, "tool_records": tool_records,
           "requests_path": str(case / "requests.json"),
           "requests_sha256": sha(case / "requests.json"),
           "trace_path": str(case / "run/trace.jsonl"), "trace_sha256": sha(case / "run/trace.jsonl"),
           "worker_log_path": str(case / "run/worker.log"), "worker_log_sha256": sha(case / "run/worker.log")}
    json_write(case / "receipt.json", row)
    return row


def sleeper(record, role):
    append(record, {**identity(os.getpid()), "role": role})
    time.sleep(30)


def slow_tool(topology, record):
    append(record, {**identity(os.getpid()), "role": "tool_parent", "topology": topology})

    def spawn():
        child = subprocess.Popen([sys.executable, str(SCRIPT), "_sleeper", str(record), "tool_child"])
        append(record, {**identity(child.pid), "role": "child_created", "spawn_thread": threading.get_native_id()})
        if topology == "other_thread":
            time.sleep(30)  # Keep the spawning thread alive through inner cleanup.

    if topology == "other_thread":
        thread = threading.Thread(target=spawn)
        thread.start()
        thread.join()
    else:
        spawn()
    if topology == "parent_fast_exit":
        return 0
    time.sleep(30)
    return 0


def stage_worker(package, out, topology):
    runtime = load("owned_stage_runtime", package / "agent/runtime.py")
    record = out / "identities.jsonl"
    append(record, {**identity(os.getpid()), "role": "fixture_worker"})
    started = time.monotonic()
    result = runtime._bounded_command([sys.executable, str(SCRIPT), "_slow-tool", topology, str(record)],
                                     out, out / "tool.log", .35, 6)
    rows = unique_records(read_rows(record))
    json_write(out / "inner.tmp.json", {"stage": result, "identities": rows,
               "inner_snapshot": [status(row) for row in rows], "elapsed_s": time.monotonic() - started})
    os.replace(out / "inner.tmp.json", out / "inner.json")
    # Keep this owned group observable until the parent applies runtime.stop_tree.
    time.sleep(30)
    return 0


def process_case(package, out, topology):
    folder = out / ("process_" + topology)
    folder.mkdir()
    runtime = load("outer_" + topology, package / "agent/runtime.py")
    started = time.monotonic()
    inner, error = {}, None
    with (folder / "worker.log").open("xb") as log:
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "_stage-worker", str(package), str(folder), topology],
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        owned_worker = identity(proc.pid)
        OWNED_ROOTS[proc.pid] = proc
        rows = unique_records([owned_worker])
        try:
            deadline = time.monotonic() + 12
            while not (folder / "inner.json").exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(.025)
            inner = json.loads((folder / "inner.json").read_text()) if (folder / "inner.json").exists() else {}
            recorded = read_rows(folder / "identities.jsonl")
            members = group_records(proc.pid)
            rows = unique_records([owned_worker, *recorded, *members])
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
        finally:
            try:
                rows = unique_records([*rows, *read_rows(folder / "identities.jsonl"), *group_records(proc.pid)])
            except (OSError, ValueError) as exc:
                error = type(exc).__name__ + ": " + str(exc)
            outer_before = [status(row) for row in rows]
            runtime.stop_tree(proc)  # Only the session established by this Popen.
            OWNED_ROOTS.pop(proc.pid, None)
    outer_immediate = [status(row) for row in rows]
    final = settle(rows)
    gone = all(row["observed_state"] in ("absent", "identity_reused") for row in final)
    children = [row for row in rows if row.get("role") in ("tool_child", "child_created")]
    checks = {"inner_recorded": bool(inner), "owned_child_recorded": bool(children),
              "outer_group_cleanup": gone, "no_fixture_error": error is None,
              "expected_timeout": inner.get("stage", {}).get("timeout") == (topology != "parent_fast_exit")}
    result = {"topology": topology, "passed": all(checks.values()), "checks": checks,
              "helper_scope": "actual _bounded_command plus actual stop_tree in an owned fixture session",
              "run_job_scope": False, "all_identities": rows, "inner": inner,
              "outer_before": outer_before, "outer_immediate": outer_immediate,
              "outer_snapshot": final, "outer_alive": [row for row in final if row["observed_state"] not in ("absent", "identity_reused")],
              "error": error, "elapsed_s": time.monotonic() - started,
              "inner_live": [row for row in inner.get("inner_snapshot", [])
                             if row["observed_state"] not in ("absent", "identity_reused", "Z")],
              "tool_log_path": str(folder / "tool.log"),
              "tool_log_sha256": sha(folder / "tool.log") if (folder / "tool.log").exists() else None}
    json_write(folder / "receipt.json", result)
    return result


def version_evidence(real_bin, out):
    command = [str(real_bin / "vivado"), "-version"]
    started = time.monotonic()
    with (out / "vivado_version.log").open("xb") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=30)
    version = (out / "vivado_version.log").read_text(errors="replace")
    if result.returncode or "2026.1" not in version:
        raise ValueError("Vivado 2026.1 identity was not confirmed")
    return {"argv": command, "rc": result.returncode, "elapsed_s": time.monotonic() - started,
            "log": str(out / "vivado_version.log"), "log_sha256": sha(out / "vivado_version.log"), "bin": str(real_bin),
            "tool_executable_hashes": {str(real_bin / name): sha(real_bin / name)
                                       for name in ("vivado", "xvlog", "xelab", "xsim")}}


def engineering(args, package, server, out):
    original = (INPUT / "candidate.sv").read_text()
    fixed = original.replace("q_reg >>>", "$signed(q_reg) >>>")
    syntax_error = fixed.replace("q_reg <= data;", "q_reg <= ;")
    declaration = original.replace("    reg [63:0] q_reg;", "").replace("q_reg", "q").replace("    assign q = q;", "")
    declared = declaration.replace("output [63:0] q", "output reg [63:0] q")
    declared_fixed = declared.replace("q >>>", "$signed(q) >>>")
    def expected(source, calls, state, reasons, **extra):
        return dict(source=source, calls=calls, status=state, reasons=reasons, **extra)
    matrix = [
        ("correct_review", original, fixed, args.seconds, expected(fixed, 2, "accepted", ["static_and_compile_gates_only"]), 0),
        ("syntax_rejected", original, syntax_error, args.seconds, expected(original, 2, "rejected", ["compile_failed"]), 0),
        ("budget_below_31", original, fixed, 30, expected(original, 1, "bypassed", ["time_budget"]), 0),
        ("budget_exact_31", original, fixed, 31, expected(original, 1, "bypassed", ["time_budget"]), 0),
        ("review_client_timeout", original, fixed, args.seconds, expected(original, 2, "rejected", ["client_timeout", "llm_error"]), 22),
        ("declaration_repair_exit", declaration, declared_fixed, args.seconds,
         expected(declared_fixed, 2, "accepted", ["static_and_compile_gates_only"], declaration_fix=True), 0),
    ]
    cases = [run_case(package, server, out, name, initial, revised, seconds, want, delay_s=delay)
             for name, initial, revised, seconds, want, delay in matrix]
    processes = [process_case(package, out, topology)
                 for topology in ("live_parent_child", "parent_fast_exit", "other_thread")]
    cases.append(run_case(package, server, out, "last_normal_request", fixed, None, args.seconds,
                          expected(fixed, 1, "bypassed", ["selection_skip"])))
    return {"cases": cases, "process_cases": processes,
            "passed": all(row["passed"] for row in cases + processes),
            "cleanup_verified": all(row["checks"]["owned_processes_gone"] for row in cases)
                                and all(row["checks"]["outer_group_cleanup"] for row in processes),
            "review_compile_stage_elapsed_s": [event["sec"] for row in cases for event in row["events"]
                                               if event["tool"] == "review_validate" and "sec" in event],
            "model_budget_conclusion": "real model response time UNTESTED; private responder only",
            "http_contract": "UNTESTED: run_job interface only; no /v1/solve claim"}


def functional(args, package, server, out):
    prior = json.loads(args.engineering_report.read_text())
    frozen_sources = source_checks()[0]
    if not (prior.get("schema") == "selective_runtime_linux_preflight_v1" and prior.get("phase") == "engineering"
            and all(prior.get(key) is True for key in ("complete", "passed", "real_compiler", "linux",
                                                       "protected_files_unchanged", "cleanup_verified"))
            and prior.get("source_runtime_sha256") == FROZEN_RUNTIME and prior.get("default_review_budget") == BUDGET
            and prior.get("package_files") == {name: digest for name, digest in frozen_sources.items() if "/package/" in name}
            and prior.get("input_files") == {name: digest for name, digest in frozen_sources.items() if "/package/" not in name}):
        raise ValueError("functional stage requires a completed, passing frozen Linux engineering report")
    original = (INPUT / "candidate.sv").read_text().replace("q_reg >>>", "$signed(q_reg) >>>")
    wrong = original.replace("$signed(q_reg) >>>", "q_reg >>")
    controls = out / "functional_controls"
    controls.mkdir()
    (controls / "positive.sv").write_text(original)
    (controls / "negative.sv").write_text(wrong)
    runner = load("frozen_r2_probe", PROBES / "probe_runner.py")
    oracle_assets_before = runner.frozen_assets()
    results = {name: runner.probe_candidate("Prob115_shift18", path, out / ("oracle_" + name))
               for name, path in {"original": controls / "positive.sv", "candidate": controls / "negative.sv"}.items()}
    valid = (results["original"]["status"] == "pass" and results["original"]["mismatches"] == 0
             and results["candidate"]["status"] == "fail" and results["candidate"]["failure_kind"] == "semantic_mismatch"
             and results["candidate"]["mismatches"] > 0)
    if not valid:
        raise ValueError("offline positive/negative controls failed before any model request")
    normal = run_case(package, server, out, "normal_correct_bypass", original, None, args.seconds,
                      dict(source=original, calls=1, status="bypassed", reasons=["selection_skip"]))
    forced = copy_package(out, forced=True)
    row = run_case(forced, server, out, "forced_correct_review", original, wrong, args.seconds,
                   dict(source=wrong, calls=2, status="accepted", reasons=["static_and_compile_gates_only"]))
    # Controls were validated independently; only the completed return is graded now.
    results["final"] = runner.probe_candidate("Prob115_shift18", Path(row["solution"]), out / "oracle_final")
    oracle_unchanged = (oracle_assets_before == runner.frozen_assets() and all(
        result.get("inputs_unchanged") is True
        and result["runner_sha256"] == oracle_assets_before["probe_runner.py"]
        and result["tb_sha256"] == oracle_assets_before["Prob115_shift18/tb.sv"]
        for result in results.values()))
    regressed = (valid and row["review_commit"].get("status") == "accepted"
                 and results["final"]["status"] == "fail" and results["final"]["failure_kind"] == "semantic_mismatch")
    return {"passed": normal["passed"] and row["passed"] and regressed and oracle_unchanged,
            "status": "functional_regression_detected" if regressed else "negative_control_inconclusive",
            "regression_protection": False if regressed else "unverified", "deployment_blocked": True,
            "real_oracle": True, "fake_model": True, "normal_bypass": normal, "forced_review": row,
            "cases": [normal, row],
            "oracle_results": results, "oracle_asset_hashes": oracle_assets_before,
            "oracle_assets_unchanged": oracle_unchanged, "expected_outcome_met": regressed and oracle_unchanged,
            "engineering_report_path": str(args.engineering_report), "engineering_report_sha256": sha(args.engineering_report),
            "forced_selector_sha256": sha(forced / "agent/signedness_selector.py"),
            "forced_fixture_only": True, "corrected_runtime_modified": False,
            "cleanup_verified": normal["checks"]["owned_processes_gone"] and row["checks"]["owned_processes_gone"]}


def main():
    if sys.platform != "linux":
        raise SystemExit("Linux required; no other platform is an approved execution target")
    sys.dont_write_bytecode = True
    if len(sys.argv) > 1 and sys.argv[1].startswith("_"):
        action, argv = sys.argv[1], sys.argv[2:]
        if action == "_real-tool":
            return real_tool(argv[1:] if argv and argv[0] == "--" else argv)
        if action == "_sleeper":
            sleeper(Path(argv[0]), argv[1])
            return 0
        if action == "_slow-tool":
            return slow_tool(argv[0], Path(argv[1]))
        if action == "_stage-worker":
            return stage_worker(Path(argv[0]), Path(argv[1]), argv[2])
        raise SystemExit("unknown internal fixture command")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("engineering", "functional"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vivado-bin", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    parser.add_argument("--engineering-report", type=Path)
    parser.add_argument("--seconds", type=float, default=90)
    args = parser.parse_args()
    if args.seconds < 40 or not args.seconds < 3600:
        parser.error("--seconds must be finite and in [40, 3600)")
    if args.phase == "functional" and args.engineering_report is None:
        parser.error("functional requires --engineering-report")
    if args.out.exists():
        parser.error("output exists: choose a new immutable experiment directory")
    args.vivado_bin = args.vivado_bin.resolve()
    if args.engineering_report:
        args.engineering_report = args.engineering_report.resolve()
    for name in ("vivado", "xvlog", "xelab", "xsim"):
        if not (args.vivado_bin / name).is_file():
            parser.error("real Vivado tool missing: " + name)
    assets, protected = source_checks()
    resources = check_resources(args.resource_check)
    # Adopt/reap only this harness's orphan fixture descendants, not system children.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise SystemExit("owned-process subreaper setup failed")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    package = copy_package(out)
    summary = {"schema": "selective_runtime_linux_preflight_v1" if args.phase == "engineering" else "selective_runtime_forced_correct_v1",
               "schema_version": 1, "phase": args.phase, "complete": False, "passed": False,
               "linux": True, "real_compiler": True, "fake_model": True,
               "source_runtime_sha256": FROZEN_RUNTIME, "source_runtime_path": str(PACKAGE / "agent/runtime.py"),
               "package_files": {name: digest for name, digest in assets.items() if "/package/" in name},
               "input_files": {name: digest for name, digest in assets.items() if "/package/" not in name},
               "source_manifest_path": str(HERE / "source_manifest.json"), "source_manifest_sha256": sha(HERE / "source_manifest.json"),
               "script_path": str(SCRIPT), "script_sha256": sha(SCRIPT),
               "resource_check_path": str(args.resource_check.resolve()), "resource_check_sha256": sha(args.resource_check), "host": resources["host"],
               "default_review_budget": BUDGET, "uncovered": ["shared model latency/cancellation", "/v1/solve HTTP contract",
                 "real Vivado child topology", "detached process groups", "atomic write/replace interrupt injection", "full156 quality"]}
    started = time.monotonic()
    def cancelled(signum, frame):
        raise SystemExit(128 + signum)
    previous_signals = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        summary["vivado"] = version_evidence(args.vivado_bin, out)
        tools = make_tools(out, args.vivado_bin)
        with fake_model() as server, environment({**tools,
              "LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
              "MODEL_NAME": "private-preflight-responder", "RTL_PROFILE": "development",
              "RTL_REPAIRS": "1", "RTL_TEMPERATURE": "0", "RTL_MAX_TOKENS": "8192",
              "EDA_TMP": out / "scratch"}):
            summary.update(engineering(args, package, server, out) if args.phase == "engineering"
                           else functional(args, package, server, out))
        summary["fake_service_closed"] = True
        summary["complete"] = True
    except Exception as exc:
        summary.update(error=type(exc).__name__ + ": " + str(exc), passed=False)
    finally:
        for sig in previous_signals:
            signal.signal(sig, signal.SIG_IGN)
        cleanup_runtime = load("final_owned_cleanup", package / "agent/runtime.py")
        for proc in list(OWNED_ROOTS.values()):
            cleanup_runtime.stop_tree(proc)
            OWNED_ROOTS.pop(proc.pid, None)
        summary["elapsed_s"] = time.monotonic() - started
        summary["protected_files_unchanged"] = unchanged(protected)
        summary["source_files_unchanged"] = unchanged(assets)
        model = identity(int(resources["model_pid"]))
        summary["shared_model_identity_unchanged"] = bool(model and model["state"] not in ("Z", "X")
                                                          and model["starttime"] == str(resources["model_starttime"]))
        summary["tool_records"] = read_rows(out / "tool_logs/tools.jsonl")
        summary["tool_records_path"] = str(out / "tool_logs/tools.jsonl")
        summary["tool_records_sha256"] = sha(out / "tool_logs/tools.jsonl") if (out / "tool_logs/tools.jsonl").exists() else None
        summary["passed"] = bool(summary["passed"] and summary["protected_files_unchanged"]
                                  and summary["source_files_unchanged"] and summary["shared_model_identity_unchanged"]
                                  and summary.get("cleanup_verified"))
        json_write(out / "summary.json", summary)
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
    print(json.dumps({"phase": args.phase, "complete": summary["complete"], "passed": summary["passed"],
                      "status": summary.get("status"), "summary": str(out / "summary.json")}, ensure_ascii=False))
    return 0 if summary["complete"] and summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
