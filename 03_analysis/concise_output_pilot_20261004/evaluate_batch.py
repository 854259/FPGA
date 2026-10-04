"""Isolated twelve-task original vs concise-output pilot with cooperative admission.

No shared deployment/model mutation. Each sample acquires both existing locks,
publishes a receipt, and releases them before the next sample. The worker sees
prompt/interface only; references and tests enter only the external judge.
"""
import argparse
import ctypes
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import urllib.request

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen(validate_inputs=True):
    spec = read(ROOT / "RUN_SPEC.json")
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == digest, name
    for name, digest in spec["dependency_hashes"].items():
        assert sha(Path(spec["dependencies_cloud"]) / name) == digest, name
    kit = Path(spec["kit"])
    assert len(spec["task_ids"]) == 12 and len(set(spec["task_ids"])) == 12
    if validate_inputs:
        manifest = read(ROOT / "INPUT_MANIFEST.json")
        assert manifest["task_ids"] == spec["task_ids"]
        for name, digest in manifest["input_sha256"].items():
            assert sha(kit / "bench/tasks_veval" / name) == digest, name
        for name, digest in manifest["official_sha256"].items():
            assert sha(kit / "official_reference" / name) == digest, name
    return spec, kit


def owned():
    spec = read(ROOT / "RUN_SPEC.json")
    return load("full_owned", Path(spec["dependencies_cloud"]) / "paired_checkpoint.py")


def worker(args):
    spec, kit = frozen(validate_inputs=False)
    paired = owned()

    def admission():
        record = read(args.resource_check)
        assert record["schema_version"] == 1 and record["resource_idle"] is True
        slot = Path(record["slot_lock_path"])
        assert sha(slot) == record["slot_lock_sha256"]
        assert slot.read_text().splitlines()[0] == record["slot_owner"]
        assert paired.model_identity(record["model_pid"]) == record["model_identity"]

    admission()
    runtime = load("full_original_runtime", ROOT / "package/agent/runtime.py")
    original_skills = runtime.skill_texts()
    if args.arm == "C":
        concise_skill = (ROOT / "CONCISE_GENERATION.md").read_text(encoding="utf-8")
        runtime.skill_texts = lambda: (concise_skill, original_skills[1])
    lexical = load("full_lexical", ROOT / "lexical_mask.py")
    candidate = load("full_guarded_bundle", ROOT / "guarded_bundle.py")
    import baseline
    original_extract = baseline.extract
    baseline_only = types.SimpleNamespace(extract=original_extract)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = out / "work"
    work.mkdir()
    prompt_only = out / "prompt_only"
    prompt_only.mkdir()
    task = kit / "bench/tasks_veval" / args.task
    for name in ("prompt.txt", "interface.txt"):
        if (task / name).is_file():
            (prompt_only / name).write_bytes((task / name).read_bytes())
    (out / "solution.v").write_text("", encoding="utf-8")
    (out / "trace.jsonl").write_text("", encoding="utf-8")
    requests, extraction, lint = [], [], []
    save(out / "requests.json", requests)
    save(out / "extraction.json", extraction)
    save(out / "lint_journal.json", lint)
    original_open = urllib.request.urlopen
    original_run = subprocess.run

    def journal_open(request, *positional, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if not url.endswith("/chat/completions"):
            return original_open(request, *positional, **kwargs)
        assert url == "http://127.0.0.1:8000/v1/chat/completions"
        assert isinstance(request, urllib.request.Request) and request.get_method() == "POST"
        index = len(requests)
        assert index < 2
        payload = json.loads(request.data)
        expected_system = runtime.skill_texts()[0] + ("\n" + runtime.skill_texts()[1] if index else "")
        assert payload["messages"][0] == dict(role="system", content=expected_system)
        assert payload["model"] == spec["model"] and payload["temperature"] == 0
        assert payload["top_p"] == 1 and payload["max_tokens"] == 8192
        folder = out / "requests" / str(index)
        folder.mkdir(parents=True)
        save(folder / "request.json", payload)
        entry = dict(index=index, replayed=False, response_received=False,
                     request_sha256=sha(folder / "request.json"))
        requests.append(entry)
        save(out / "requests.json", requests)
        admission()
        paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
        started = time.monotonic()
        try:
            with original_open(request, *positional, **kwargs) as response:
                raw = response.read()
        except Exception as error:
            entry.update(error=type(error).__name__, elapsed_s=time.monotonic() - started)
            save(out / "requests.json", requests)
            raise RuntimeError("Actual model request failed; do not resample") from error
        (folder / "response.json").write_bytes(raw)
        response = json.loads(raw)
        choice = response["choices"][0]
        entry.update(response_received=True, elapsed_s=time.monotonic() - started,
                     response_id=response.get("id"), finish_reason=choice.get("finish_reason"),
                     response_sha256=sha(folder / "response.json"))
        save(out / "requests.json", requests)
        return io.BytesIO(raw)

    def extraction_hook(text, track):
        assert track == "rtl"
        code, receipt = original_extract(text, track), dict(decision="original_baseline")
        path = out / ("extracted_" + str(len(extraction)) + ".sv")
        path.write_text(code, encoding="utf-8", newline="\n")
        receipt["extracted_sha256"] = sha(path)
        extraction.append(receipt)
        save(out / "extraction.json", extraction)
        return code

    def observed_run(*positional, **kwargs):
        argv = positional[0] if positional else kwargs.get("args")
        if not isinstance(argv, list) or Path(argv[0]).name != "xvlog":
            return original_run(*positional, **kwargs)
        assert len(argv) == 3 and argv[1] == "--sv"
        source = Path(argv[2])
        folder = out / "lint_journal" / str(len(lint))
        folder.mkdir(parents=True)
        (folder / "source_before.sv").write_bytes(source.read_bytes())
        started = time.monotonic()
        result = original_run(*positional, **kwargs)
        (folder / "source_after.sv").write_bytes(source.read_bytes())
        (folder / "stdout.log").write_text(result.stdout, encoding="utf-8", newline="\n")
        receipt = dict(argv=argv, cwd=str(kwargs["cwd"]), returncode=result.returncode,
            elapsed_s=time.monotonic() - started, source_before_sha256=sha(folder / "source_before.sv"),
            source_after_sha256=sha(folder / "source_after.sv"), stdout_sha256=sha(folder / "stdout.log"))
        save(folder / "receipt.json", receipt)
        lint.append(receipt)
        save(out / "lint_journal.json", lint)
        return result

    urllib.request.urlopen = journal_open
    baseline.extract = extraction_hook
    subprocess.run = observed_run
    os.chdir(work)
    started = time.monotonic()
    runtime.worker(prompt_only, out)
    events = [json.loads(line) for line in (out / "trace.jsonl").read_text().splitlines()]
    assert requests and len(requests) == len(extraction)
    assert all(row["response_received"] for row in requests)
    assert not any(event.get("error") for event in events)
    save(out / "worker_result.json", dict(complete=True, task=args.task, arm=args.arm,
        elapsed_s=time.monotonic() - started, actual_model_requests=len(requests),
        solution_sha256=sha(out / "solution.v"), extraction=extraction,
        original_lint_calls=len(lint)))


def judge(args):
    spec, kit = frozen()
    evaluator = load("full_external_evaluator", ROOT / "official_eval_guarded.py")
    evaluator.OFFICIAL = kit / "official_reference"
    task = kit / "bench/tasks_veval" / args.task
    args.out.mkdir(parents=True, exist_ok=False)
    verdict = evaluator.judge_sample(task, args.solution, args.out,
                                    args.out / "verdict.json", spec["judge_timeout_s"])
    assert not verdict.get("tool_error"), verdict
    assert verdict["task_id"] == args.task and verdict["judge_evidence_complete"]
    save(args.out / "bound_verdict.json", dict(solution_sha256=sha(args.solution),
         verdict_sha256=sha(args.out / "verdict.json"), verdict=verdict))


def run_judge(paired, args, solution, out):
    command = [sys.executable, "-B", str(ROOT / "evaluate_batch.py"), "judge",
               "--task", args.task, "--solution", str(solution), "--out", str(out)]
    result = paired.owned_command(command, ROOT, out.parent / (out.name + ".log"), 360)
    save(out.parent / (out.name + "_command.json"), result)
    assert not result["timeout"] and not result["launch_error"] and result["returncode"] == 0, result
    return read(out / "bound_verdict.json")


def stage(args):
    spec, kit = frozen()
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    paired = owned()
    paired.check_resource(args.resource_check, kit, first=True)
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    if args.arm == "controls":
        task = kit / "bench/tasks_veval" / args.task
        positive = args.out / "positive.sv"
        positive.write_bytes((task / "reference/solution.sv").read_bytes())
        negative = args.out / "negative.sv"
        negative.write_text("module TopModule(output zero); assign zero = ; endmodule\n", encoding="utf-8")
        good = run_judge(paired, args, positive, args.out / "positive")
        bad = run_judge(paired, args, negative, args.out / "negative")
        assert good["verdict"]["level"] == 3 and bad["verdict"]["level"] == 0
        row = dict(complete=True, valid=True, controls_valid=2, actual_model_requests=0)
    else:
        paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
        worker_out = args.out / "worker"
        command = [sys.executable, "-B", str(ROOT / "evaluate_batch.py"), "worker",
            "--task", args.task, "--arm", args.arm, "--out", str(worker_out),
            "--resource-check", str(args.resource_check)]
        result = paired.owned_command(command, ROOT, args.out / "worker.log", spec["solve_deadline_s"])
        save(args.out / "worker_command.json", result)
        assert not result["launch_error"] and not result["remaining_live_group"]
        assert result["timeout"] or result["returncode"] == 0, result
        # A solver deadline is a measured budget failure; never kill the shared
        # model to cancel inference. Drain this owned request before proceeding.
        if result["timeout"]:
            deadline = time.monotonic() + 120
            while True:
                try:
                    paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(2)
        bound = run_judge(paired, args, worker_out / "solution.v", args.out / "judge")
        requests = read(worker_out / "requests.json")
        extraction = read(worker_out / "extraction.json")
        row = dict(complete=True, valid=True, task=args.task, arm=args.arm,
            solve_elapsed_s=result["elapsed_s"], solve_deadline_reached=result["timeout"],
            actual_model_requests=len(requests), received_model_responses=sum(x["response_received"] for x in requests),
            solution_sha256=bound["solution_sha256"], verdict_sha256=bound["verdict_sha256"],
            verdict=bound["verdict"], extraction=extraction)
    paired.check_resource(args.resource_check, kit)
    paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
    row["stage_elapsed_s"] = time.monotonic() - started
    save(args.out / "row.json", row)


def queue(args):
    spec, kit = frozen()
    status_path = ROOT / "queue_status.json"
    assert not status_path.exists(), "No resuming/resampling partial experiments silently"
    status = dict(schema="concise_output_pilot_queue_v1", complete=False, state="starting",
        started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), pid=os.getpid(),
        expected_samples=24, completed_samples=0, source_spec_sha256=sha(ROOT / "RUN_SPEC.json"))
    save(status_path, status)
    schedule = [("Prob001_zero", "controls")]
    for index, task in enumerate(spec["task_ids"]):
        schedule.extend((task, arm) for arm in (("A", "C") if index % 2 == 0 else ("C", "A")))
    queue_deadline = time.monotonic() + spec["queue_deadline_s"]
    try:
        for index, (task, arm) in enumerate(schedule):
            while True:
                if (ROOT / "STOP_AFTER_CURRENT").exists():
                    raise RuntimeError("Boundary stop requested; completed samples preserved")
                if time.monotonic() >= queue_deadline:
                    raise TimeoutError("Queue lifetime exhausted; preserve incomplete run")
                slot = Path("/workspace/team/SLOT.lock")
                if slot.exists():
                    status.update(state="waiting_for_teammate", current_task=task, current_arm=arm)
                    save(status_path, status)
                    time.sleep(15)
                    continue
                attempt = ROOT / "admission" / (str(index) + "_" + str(time.time_ns()))
                attempt.parent.mkdir(parents=True, exist_ok=True)
                out = ROOT / "samples" / arm / task
                owner = "fpga_owner_concise_output_" + str(index)
                command = ["/usr/bin/flock", "-n", "/workspace/team/.gpu.lock", sys.executable,
                    "-B", str(ROOT / "guard_wrapper.py"), "--kit", str(kit),
                    "--model-pid", str(spec["model_pid"]), "--model-name", spec["model"],
                    "--owner", owner, "--guard-out", str(attempt),
                    "--slot-minutes", "20", "--stage-timeout-s", "900", "--",
                    sys.executable, "-B", str(ROOT / "evaluate_batch.py"), "stage",
                    "--task", task, "--arm", arm, "--out", str(out),
                    "--resource-check", "{resource_check}"]
                status.update(state="running", current_task=task, current_arm=arm, current_guard=str(attempt))
                save(status_path, status)
                with attempt.with_suffix(".launcher.log").open("xb") as log:
                    proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                    status["current_guard_pid"] = proc.pid
                    save(status_path, status)
                    result = proc.wait()
                guard_path = attempt / "status.json"
                if not guard_path.exists():
                    assert result == 1 and not out.exists(), "Unexpected flock/launcher failure"
                    time.sleep(15)
                    continue
                guard = read(guard_path)
                if guard.get("stage_pid") is None and not out.exists():
                    reason = guard.get("error", "")
                    if "shared slot occupied" in reason or "shared evaluation/tools still active" in reason or "model slots are busy" in reason:
                        status.update(state="waiting_for_teammate", last_admission_error=reason)
                        save(status_path, status)
                        time.sleep(15)
                        continue
                assert result == 0 and guard["complete"] and guard["passed"] and guard["own_slot_released"], guard
                row = read(out / "row.json")
                assert row["complete"] and row["valid"]
                row["guard_directory"] = str(attempt)
                row["guard_status_sha256"] = sha(guard_path)
                save(out / "accepted_row.json", row)
                status["completed_samples"] += int(arm != "controls")
                status.update(state="between_samples", last_finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                save(status_path, status)
                # Release both locks and leave teammates an admission interval.
                time.sleep(5)
                break
        assert status["completed_samples"] == 24
        status.update(complete=True, state="complete", finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as error:
        status.update(state="stopped_with_evidence", error=(type(error).__name__ + ": " + str(error))[:1500])
        raise
    finally:
        save(status_path, status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("worker", "judge", "stage", "queue"))
    parser.add_argument("--task")
    parser.add_argument("--arm", choices=("A", "C", "controls"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--solution", type=Path)
    parser.add_argument("--resource-check", type=Path)
    arguments = parser.parse_args()
    globals()[arguments.phase](arguments)
