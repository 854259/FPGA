"""Offline evidence audit. A partial snapshot never produces a full-set score."""
import argparse
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import types
import zipfile

SPEC_SHA = "200ec12684229812029466ae5ffd1c63f461b9afa494a51e389d6377ee710e0b"
COEFF = {0: 0., 1: .2, 2: .7, 3: 1.}


def check(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unpack(archive, root):
    root = Path(root).resolve()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        check(len(names) == len(set(names)), "Duplicate archive names")
        check(len(names) <= 100000, "Archive member limit")
        for info in bundle.infolist():
            parts = PurePosixPath(info.filename)
            check(not parts.is_absolute() and ".." not in parts.parts and "\\" not in info.filename
                  and ":" not in info.filename and not info.is_dir(), "Unsafe archive name")
            check(info.file_size <= 50 * 1024 * 1024, "Archive file limit")
        check(sum(info.file_size for info in bundle.infolist()) <= 1024**3, "Archive total limit")
        manifest = json.loads(bundle.read("ARCHIVE_MANIFEST.json"))
        check(set(names) == set(manifest["files"]) | {"ARCHIVE_MANIFEST.json"}, "Archive inventory mismatch")
        for name, expected in manifest["files"].items():
            raw = bundle.read(name)
            check(digest(raw) == expected, "Archive checksum mismatch: " + name)
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (root / "ARCHIVE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def command(receipt, log, allow_timeout=False):
    check(not receipt["launch_error"] and not receipt["remaining_live_group"], "Owned command cleanup/launch")
    check(allow_timeout or not receipt["timeout"], "Unexpected command timeout")
    check(sha(log) == receipt["log_sha256"] and log.stat().st_size == receipt["log_bytes"], "Command log binding")
    if not receipt["timeout"]:
        check(receipt["returncode"] == 0, "Owned command exit")
    return receipt


def guard(root, row, spec, manifest):
    run = root / "run"
    cloud = PurePosixPath(manifest["run_root"])
    original = PurePosixPath(row["guard_directory"])
    check(original.is_relative_to(cloud / "admission"), "Guard escapes run admission")
    folder = run / original.relative_to(cloud).as_posix()
    path = folder / "status.json"
    check(sha(path) == row["guard_status_sha256"], "Guard status binding")
    status = read(path)
    for key in ("complete", "passed", "model_unchanged", "protected_files_unchanged", "own_slot_released"):
        check(status.get(key) is True, "Guard check: " + key)
    check(status["stage_rc"] == 0 and not status["model_managed"] and not status["instance_managed"], "Guard ownership")
    check(status["owned_cleanup"]["verified"] and not status["owned_cleanup"]["remaining"], "Guard cleanup")
    check(status["model_idle_after"]["processing_slots"] == 0
          and status["model_idle_after"]["model_pid_owns_port"], "Guard model retirement")
    resource = read(folder / "resource_check.json")
    check(resource["resource_idle"] is True and resource["model_pid"] == spec["model_pid"]
          and resource["model_name"] == spec["model"], "Resource admission")
    check(resource["model_identity"]["pid"] == spec["model_pid"]
          and resource["model_identity"]["starttime"] == resource["model_starttime"], "Model identity")
    inputs = read(run / "INPUT_MANIFEST.json")
    check(resource["protected"]["tasks"] == inputs["input_sha256"], "Resource task fingerprints")
    check(resource["protected"]["official"] == inputs["official_sha256"], "Resource official fingerprints")
    return status, resource


def judge(folder, solution, task):
    bound = read(folder / "bound_verdict.json")
    verdict = read(folder / "verdict.json")
    receipt = read(folder / "judge_receipt.json")
    evidence = folder / "judge_work_logs"
    check(receipt["judge_rc"] == 0 and receipt["errors"] == [] and receipt["scratch_retained"] is None,
          "Judge adapter/cleanup error")
    for name, identity in receipt["evidence"].items():
        path = evidence / name
        check(sha(path) == identity["sha256"] and path.stat().st_size == identity["bytes"], "Judge evidence: " + name)
    raw = read(evidence / "adapter_verdict.json")
    check(all(verdict.get(k) == value for k, value in raw.items()), "Official verdict changed")
    check(bound["verdict"] == verdict and bound["verdict_sha256"] == sha(folder / "verdict.json")
          and bound["solution_sha256"] == sha(solution), "Judge binding")
    level = verdict["level"]
    check(type(level) is int and level in COEFF and verdict["coefficient"] == COEFF[level]
          and verdict["task_id"] == task and not verdict.get("tool_error")
          and verdict["judge_evidence_complete"], "Official verdict identity")
    stages = verdict.get("stages") or {}
    check(bool(stages.get("compile")) == (level >= 1)
          and bool(stages.get("simulate")) == (level >= 2)
          and bool(stages.get("synth")) == (level >= 3), "Verdict stage/level mismatch")
    if solution.read_text(encoding="utf-8").strip():
        # Pinned judge.py reads UTF-8 with replacement and universal newlines,
        # then writes the resulting text on Linux; CRLF references become LF.
        normalized = solution.read_text(encoding="utf-8", errors="replace").encode("utf-8")
        check(sha(evidence / "dut.sv") == digest(normalized), "Judge evaluated different source")
        check((evidence / "w_judge.log").stat().st_size > 0, "Missing native judge log")
    kept = [name for name in receipt["evidence"] if name not in
            ("adapter.stdout.log", "adapter.stderr.log", "adapter_verdict.json")]
    check(verdict["judge_evidence"] == kept, "Judge evidence list")
    check(verdict["judge_log_bytes"] == sum(receipt["evidence"][name]["bytes"] for name in kept if name.endswith(".log")),
          "Judge byte count")
    return verdict


def replay_extract(worker, arm, index, reply, baseline, runtime, candidate, lexical):
    path = worker / ("extracted_" + str(index) + ".sv")
    stored = read(worker / "extraction.json")[index]
    if arm == "A":
        code = baseline.extract(reply, "rtl")
        expected = dict(decision="original_baseline")
    else:
        gate = worker / ("candidate_gate_" + str(index))
        stages = copy.deepcopy(stored.get("stages", []))
        used = []

        def recorded(argv, cwd, log, seconds):
            check(len(used) < len(stages), "Unexpected extraction tool")
            item = stages[len(used)]
            name = Path(argv[0]).name
            check(item["name"] == name and item["argv"] == argv and seconds == 60, "Gate command/budget mismatch")
            check(Path(cwd, "dut.sv").read_text(encoding="utf-8") == (gate / "dut.sv").read_text(encoding="utf-8"),
                  "Gate compiled different proposal")
            raw = (gate / (name + ".log")).read_bytes()
            check(digest(raw) == item["log_sha256"] and len(raw) == item["log_bytes"], "Gate log checksum")
            Path(log).write_bytes(raw)
            used.append(name)
            return item

        tool_bin = str(PurePosixPath(stages[0]["argv"][0]).parent) if stages else "/unused"
        with tempfile.TemporaryDirectory(prefix="offline-gate-") as temporary:
            code, expected = candidate.decide(reply, types.SimpleNamespace(extract=baseline.extract),
                lexical._strip_noncode, types.SimpleNamespace(owned_command=recorded),
                Path(temporary) / "gate", tool_bin)
        check(len(used) == len(stages), "Unreplayed gate stage")
    expected["extracted_sha256"] = digest(code.encode("utf-8"))
    check(expected == stored and sha(path) == expected["extracted_sha256"], "Extraction decision/source mismatch")
    return code, stored


def sample(root, arm, task, spec, manifest, modules):
    run = root / "run"
    folder = run / "samples" / arm / task
    row = read(folder / "accepted_row.json")
    base = read(folder / "row.json")
    check({k: v for k, v in row.items() if k not in ("guard_directory", "guard_status_sha256")} == base,
          "Accepted row differs from stage result")
    check(row["complete"] and row["valid"] and row["task"] == task and row["arm"] == arm, "Sample identity")
    g, resource = guard(root, row, spec, manifest)
    worker = folder / "worker"
    cmd = command(read(folder / "worker_command.json"), folder / "worker.log", allow_timeout=True)
    check(row["solve_elapsed_s"] == cmd["elapsed_s"] and row["solve_deadline_reached"] == cmd["timeout"],
          "Solve budget receipt mismatch")
    solution = worker / "solution.v"
    check(sha(solution) == row["solution_sha256"], "Final source mismatch")
    verdict = judge(folder / "judge", solution, task)
    check(row["verdict"] == verdict and row["verdict_sha256"] == sha(folder / "judge/verdict.json"), "Row verdict mismatch")
    command(read(folder / "judge_command.json"), folder / "judge.log")
    baseline, runtime, candidate, lexical = modules
    prompt_dir = worker / "prompt_only"
    allowed = {"prompt.txt", "interface.txt"}
    check(set(p.name for p in prompt_dir.iterdir()).issubset(allowed), "Worker input boundary")
    kit_task = root / "kit/bench/tasks_veval" / task
    for path in prompt_dir.iterdir():
        check(sha(path) == sha(kit_task / path.name), "Worker prompt copy")
    prompt = (prompt_dir / "prompt.txt").read_text(encoding="utf-8")
    interface = prompt_dir / "interface.txt"
    if interface.is_file() and interface.read_text(encoding="utf-8").strip():
        prompt += "\n\nInterface:\n" + interface.read_text(encoding="utf-8")
    skills = [(run / "package/skill" / name / "SKILL.md").read_text(encoding="utf-8")
              for name in ("rtl-generation", "rtl-feedback-repair")]
    requests = read(worker / "requests.json")
    extraction = read(worker / "extraction.json")
    trace = [json.loads(line) for line in (worker / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    check(1 <= len(requests) <= 2 and row["actual_model_requests"] == len(requests), "Request budget/count")
    check(row["received_model_responses"] == sum(x["response_received"] for x in requests), "Response count")
    check(not any(e.get("error") for e in trace), "Worker trace error")
    check(trace[0]["tool"] == "agent_meta" and trace[0]["repairs"] == 1
          and trace[0]["skill_sha256"] == digest(skills[0].encode())
          and trace[0]["repair_skill_sha256"] == digest(skills[1].encode()), "Trace skill identity")
    starts = [e for e in trace if e["tool"] == "llm_start"]
    check([e["round"] for e in starts] == list(range(len(requests))), "Request trace order")
    previous, feedback = "", ""
    received = 0
    first_payload_sha = first_reply_sha = first_response_sha = None
    for index, entry in enumerate(requests):
        check(entry["index"] == index and entry["replayed"] is False, "Request journal identity")
        req_folder = worker / "requests" / str(index)
        payload = read(req_folder / "request.json")
        check(sha(req_folder / "request.json") == entry["request_sha256"], "Request payload checksum")
        user = prompt if index == 0 else prompt + "\nPrevious candidate:\n" + previous + "\nCandidate diagnostics:\n" + feedback
        expected = dict(model=spec["model"], messages=[
            dict(role="system", content=skills[0] + ("\n" + skills[1] if index else "")),
            dict(role="user", content=user)], temperature=0., top_p=1., max_tokens=8192)
        check(payload == expected, "Model message/input or setting mismatch")
        if index == 0:
            first_payload_sha = entry["request_sha256"]
        if not entry["response_received"]:
            check(cmd["timeout"] and index == len(requests) - 1, "Unconfirmed request without hard deadline")
            continue
        received += 1
        response = read(req_folder / "response.json")
        check(sha(req_folder / "response.json") == entry["response_sha256"], "Model response checksum")
        choice = response["choices"][0]
        check(choice.get("finish_reason") == entry["finish_reason"]
              and response.get("id") == entry["response_id"], "Response metadata")
        reply = choice["message"].get("content") or ""
        if index == 0:
            first_reply_sha, first_response_sha = digest(reply.encode()), entry["response_sha256"]
        llm = [e for e in trace if e["tool"] == "llm" and e["round"] == index]
        usage = response.get("usage") or {}
        check(len(llm) == 1 and llm[0]["finish"] == choice.get("finish_reason")
              and llm[0]["tokens_in"] == usage.get("prompt_tokens")
              and llm[0]["tokens_out"] == usage.get("completion_tokens"), "LLM trace metadata")
        if index < len(extraction):
            previous, _ = replay_extract(worker, arm, index, reply, baseline, runtime, candidate, lexical)
        else:
            check(cmd["timeout"], "Missing extraction outside deadline")
        round_events = [e for e in trace if starts[index]["ts"] <= e["ts"]
                        and (index + 1 == len(starts) or e["ts"] < starts[index + 1]["ts"])]
        diagnostics = [e for e in round_events if e["tool"] in ("check_source", "check_submodules", "lint")]
        feedback = diagnostics[-1]["excerpt"] if diagnostics else ""
    check(len(extraction) <= received, "More extractions than responses")
    check(row["extraction"] == extraction, "Row extraction mismatch")
    lint = read(worker / "lint_journal.json")
    by_round = {}
    for index, item in enumerate(lint):
        directory = worker / "lint_journal" / str(index)
        check(read(directory / "receipt.json") == item, "Lint journal receipt mismatch")
        for name, field in (("source_before.sv", "source_before_sha256"), ("source_after.sv", "source_after_sha256"),
                            ("stdout.log", "stdout_sha256")):
            check(sha(directory / name) == item[field], "Lint source/log checksum")
        check(item["source_before_sha256"] == item["source_after_sha256"], "Compiler modified source")
        check(len(item["argv"]) == 3 and PurePosixPath(item["argv"][0]).name == "xvlog"
              and item["argv"][1] == "--sv", "Native lint command")
        round_number = int(PurePosixPath(item["cwd"]).name.removeprefix("compile-"))
        group = by_round.setdefault(round_number, [])
        source = (directory / "source_before.sv").read_text(encoding="utf-8")
        if not group:
            check(sha(directory / "source_before.sv") == sha(worker / ("extracted_" + str(round_number) + ".sv")),
                  "Native lint did not compile extracted source")
            stdout = (directory / "stdout.log").read_text(encoding="utf-8")
            lines = [line for line in stdout.splitlines() if re.search("ERROR|WARNING|FATAL", line)]
            excerpt = "\n".join(lines)[:2048] or stdout[-2048:]
            events = [e for e in trace if e["tool"] == "lint" and e["round"] == round_number]
            check(len(events) == 1 and events[0]["rc"] == item["returncode"] and events[0]["excerpt"] == excerpt,
                  "Native lint trace mismatch")
            group.append((source, excerpt, item))
        else:
            check(len(group) == 1 and group[0][2]["returncode"] != 0, "Unexpected declaration repair compile")
            patched = runtime.repair_ansi_declarations(group[0][0], group[0][1])
            check(source == patched, "Declaration patch source mismatch")
            group.append((source, "", item))
    fixes = [e for e in trace if e["tool"] == "declaration_fix"]
    if fixes:
        check(len(fixes) == 1 and fixes[0]["rc"] == 0, "Declaration fix trace")
        group = by_round[fixes[0]["round"]]
        check(len(group) == 2 and group[-1][2]["returncode"] == 0
              and solution.read_text(encoding="utf-8") == group[-1][0], "Unverified final declaration patch")
    elif extraction:
        check(sha(solution) == extraction[-1]["extracted_sha256"], "Final source not last extraction")
    else:
        check(cmd["timeout"] and not solution.read_bytes(), "No extraction but nonempty final source")
    if not cmd["timeout"]:
        result = read(worker / "worker_result.json")
        check(result["complete"] and result["task"] == task and result["arm"] == arm
              and result["solution_sha256"] == sha(solution)
              and result["actual_model_requests"] == len(requests)
              and result["extraction"] == extraction and result["original_lint_calls"] == len(lint), "Worker result")
    return dict(task=task, arm=arm, level=verdict["level"], coefficient=verdict["coefficient"],
        request_attempts=len(requests), confirmed_responses=received, unconfirmed_attempts=len(requests)-received,
        solve_elapsed_s=row["solve_elapsed_s"], judge_elapsed_s=verdict["elapsed_s"],
        guard_elapsed_s=g["elapsed_s"], deadline=row["solve_deadline_reached"],
        changed_extractions=sum(e.get("decision") == "candidate_accepted" for e in extraction),
        decisions=[e["decision"] for e in extraction], solution_sha256=sha(solution),
        first_request_sha256=first_payload_sha, first_reply_content_sha256=first_reply_sha,
        first_raw_response_sha256=first_response_sha, model_identity=resource["model_identity"],
        verdict=verdict)


def summarize(root, manifest):
    run = root / "run"
    check(sha(run / "RUN_SPEC.json") == SPEC_SHA == manifest["source_spec_sha256"], "Frozen spec checksum")
    spec = read(run / "RUN_SPEC.json")
    check(len(spec["task_ids"]) == 156 and len(set(spec["task_ids"])) == 156, "Frozen task count")
    for name, expected in spec["source_hashes"].items():
        check(sha(run / name) == expected, "Frozen source: " + name)
    for name, expected in spec["dependency_hashes"].items():
        check(sha(root / "dependencies" / name) == expected, "Frozen dependency")
    inputs = read(run / "INPUT_MANIFEST.json")
    check(inputs["task_ids"] == spec["task_ids"], "Input task list")
    for kind, folder in (("input_sha256", root / "kit/bench/tasks_veval"), ("official_sha256", root / "kit/official_reference")):
        for name, expected in inputs[kind].items():
            check(sha(folder / name) == expected, "Input/official checksum")
    status = read(run / "queue_status.json")
    n = manifest["completed_samples"]
    check(n == status["completed_samples"] and 0 <= n <= 312, "Snapshot count")
    check(manifest["run_complete_at_capture"] == status["complete"], "Snapshot completion flag")
    check(not status["complete"] or (n == 312 and status["state"] == "complete"), "Premature completion flag")
    schedule = []
    for index, task in enumerate(spec["task_ids"]):
        schedule.extend((arm, task) for arm in (("A", "C") if index % 2 == 0 else ("C", "A")))
    expected = [("controls", spec["preflight_task"])] + schedule[:n]
    check([tuple(x) for x in manifest["accepted_schedule"]] == expected, "Snapshot schedule")
    actual = {(p.parent.parent.name, p.parent.name) for p in (run / "samples").glob("*/*/accepted_row.json")}
    check(actual == set(expected), "Accepted sample inventory")
    control = run / "samples/controls" / spec["preflight_task"]
    control_row = read(control / "accepted_row.json")
    check(sha(control / "positive.sv") == sha(root / "kit/bench/tasks_veval" / spec["preflight_task"] / "reference/solution.sv"),
          "Positive control source changed")
    check(control_row["complete"] and control_row["valid"] and control_row["controls_valid"] == 2
          and control_row["actual_model_requests"] == 0, "Control receipt")
    guard(root, control_row, spec, manifest)
    for name, level in (("positive", 3), ("negative", 0)):
        verdict = judge(control / name, control / (name + ".sv"), spec["preflight_task"])
        check(verdict["level"] == level, "Control level")
        command(read(control / (name + "_command.json")), control / (name + ".log"))
    old_path = list(sys.path)
    sys.path.insert(0, str(run))
    try:
        baseline = load("offline_full_baseline", run / "package/baseline.py")
        runtime = load("offline_full_runtime", run / "package/agent/runtime.py")
        candidate = load("offline_full_candidate", run / "guarded_bundle.py")
        lexical = load("offline_full_lexical", run / "lexical_mask.py")
        rows = [sample(root, arm, task, spec, manifest, (baseline, runtime, candidate, lexical))
                for arm, task in schedule[:n]]
    finally:
        sys.path[:] = old_path
    check(len({json.dumps(row["model_identity"], sort_keys=True) for row in rows}) <= 1, "Model changed between samples")
    a = {row["task"]: row for row in rows if row["arm"] == "A"}
    c = {row["task"]: row for row in rows if row["arm"] == "C"}
    pairs = []
    for task in sorted(a.keys() & c.keys()):
        aa, cc = a[task], c[task]
        pairs.append(dict(task=task, A_level=aa["level"], C_level=cc["level"],
            same_first_request=aa["first_request_sha256"] == cc["first_request_sha256"],
            same_first_reply_content=aa["first_reply_content_sha256"] is not None
                and aa["first_reply_content_sha256"] == cc["first_reply_content_sha256"],
            same_first_raw_response=aa["first_raw_response_sha256"] is not None
                and aa["first_raw_response_sha256"] == cc["first_raw_response_sha256"],
            C_accepted_helper=bool(cc["changed_extractions"]), A_requests=aa["request_attempts"],
            C_requests=cc["request_attempts"],
            original_repair_bypass_signal=bool(cc["changed_extractions"] and aa["request_attempts"] > cc["request_attempts"]),
            A_L3_C_regression=aa["level"] == 3 and cc["level"] < 3))
    complete = status["complete"] is True and status["state"] == "complete" and n == 312
    scores = None
    if complete:
        score = load("offline_pinned_score", root / "kit/official_reference/selftest/score.py")
        scores = {arm: score.summarize({task: [items[task]["verdict"]] for task in spec["task_ids"]})
                  for arm, items in (("A", a), ("C", c))}
        check(all(s["tasks"] == s["scored_tasks"] == 156 and s["tool_errors"] == 0 for s in scores.values()),
              "Official score denominator")
    totals = {arm: dict(samples=sum(row["arm"] == arm for row in rows),
        request_attempts=sum(row["request_attempts"] for row in rows if row["arm"] == arm),
        confirmed_responses=sum(row["confirmed_responses"] for row in rows if row["arm"] == arm),
        unconfirmed_attempts=sum(row["unconfirmed_attempts"] for row in rows if row["arm"] == arm),
        deadlines=sum(row["deadline"] for row in rows if row["arm"] == arm),
        solve_s=sum(row["solve_elapsed_s"] for row in rows if row["arm"] == arm),
        judge_s=sum(row["judge_elapsed_s"] for row in rows if row["arm"] == arm))
        for arm in ("A", "C")}
    decision = "incomplete_no_full_score_or_adoption"
    if complete:
        improvement = scores["C"]["set_score"] > scores["A"]["set_score"]
        equal_fewer = scores["C"]["set_score"] == scores["A"]["set_score"] and (
            totals["C"]["confirmed_responses"] < totals["A"]["confirmed_responses"])
        unknown = any(totals[arm]["unconfirmed_attempts"] for arm in totals)
        clean = not any(pair["A_L3_C_regression"] for pair in pairs)
        decision = ("retain_for_further_validation_not_deploy" if clean and not unknown and (improvement or equal_fewer)
                    else "do_not_promote_current_candidate")
    public_rows = [{k: v for k, v in row.items() if k not in ("verdict", "model_identity")} for row in rows]
    return dict(schema="full156_offline_audit_v1", evidence_valid=True, full_round_complete=complete,
        snapshot_samples=n, source_spec_sha256=SPEC_SHA, scores=scores, totals=totals,
        paired_tasks=len(pairs), pairs=pairs, rows=public_rows, decision=decision,
        deployment_changed=False, new_official_baseline=False, model_calls=0, eda_calls=0,
        limitations=["Known public regression, not unseen-task validation",
            "A/C fresh generation differences may include inference variation",
            "Unconfirmed timeout journal entries are not certified actual POST counts",
            "One sample per arm, not five-sample stability",
            "External official solve ingress/exclusive timing/32GB final delivery not certified"])


def audit_archive(archive, output):
    output = Path(output)
    check(not output.exists(), "Use fresh audit output directory")
    with tempfile.TemporaryDirectory(prefix="full156-evidence-") as temporary:
        root = Path(temporary)
        manifest = unpack(archive, root)
        result = summarize(root, manifest)
    result["archive_sha256"] = sha(archive)
    result["auditor_sha256"] = sha(Path(__file__))
    output.mkdir(parents=True)
    (output / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ("task", "A_level", "C_level", "same_first_request", "same_first_reply_content",
              "same_first_raw_response", "C_accepted_helper", "A_requests", "C_requests",
              "original_repair_bypass_signal", "A_L3_C_regression")
    with (output / "pairs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["pairs"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit_archive(args.archive, args.out)
    print(json.dumps({key: result[key] for key in ("evidence_valid", "full_round_complete",
          "snapshot_samples", "scores", "totals", "decision", "archive_sha256")}))
