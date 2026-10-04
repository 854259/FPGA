"""Offline reconstruction of actual-agent generation and paired worker evidence.

No model or EDA invocation: candidate gates are replayed from archived receipts.
Acceptance admits further validation only; a single timing observation is not a
latency claim or a deployment decision.
"""
import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"
sys.path.insert(0, str(ROOT))
from extract_bundle import extract_bundle
from guarded_bundle import decide


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def nonnegative(value):
    assert type(value) in (int, float) and math.isfinite(value) and value >= 0
    return value


def utc(value):
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    return parsed.astimezone(datetime.timezone.utc)


def normalized(value):
    return str(value).replace("\\", "/")


def main():
    archive = read(ROOT / "ARCHIVE.json")
    assert sha(ROOT / "evidence.zip") == archive["sha256"]
    assert (ROOT / "evidence.zip").stat().st_size == archive["bytes"]
    manifest = read(RAW / "MANIFEST.json")
    paths = [row["path"] for row in manifest["files"]]
    assert len(paths) == len(set(paths)) == archive["files"]
    # Bind extracted evidence to the actual ZIP as well as its manifest.
    with zipfile.ZipFile(ROOT / "evidence.zip") as bundle:
        assert len(bundle.namelist()) == len(set(bundle.namelist()))
        assert set(bundle.namelist()) == set(paths) | {"MANIFEST.json"}
        assert bundle.read("MANIFEST.json") == (RAW / "MANIFEST.json").read_bytes()
        for row in manifest["files"]:
            path = (RAW / row["path"]).resolve()
            assert path.is_relative_to(RAW.resolve())
            assert sha(path) == row["sha256"] and path.stat().st_size == row["bytes"]
            assert bundle.read(row["path"]) == path.read_bytes()

    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == sha(RAW / name) == digest, name
    for name, digest in spec["dependency_hashes"].items():
        assert sha(RAW / "dependency_snapshot" / name) == digest
    assert sha(ROOT / "package/agent/runtime.py") == "22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7"
    assert spec["max_initial_requests"] == 3
    assert spec["max_repair_requests"] == 6 and spec["max_actual_model_requests"] == 9
    assert spec["retries"] == 0
    tasks = list(spec["checks"])
    assert set(tasks) == {"adder_8bit", "adder_16bit", "adder_32bit"}
    assert len(spec["generation_order"]) == len(set(spec["generation_order"])) == 3
    assert set(spec["generation_order"]) == set(tasks)
    order = [tuple(row) for row in spec["order"]]
    assert len(order) == 6 and set(order) == {(task, arm) for task in tasks for arm in ("A", "C")}

    guard = read(RAW / "guard/status.json")
    summary = read(RAW / "results/summary.json")
    assert guard["complete"] and guard["passed"] and guard["stage_rc"] == 0
    assert guard["model_unchanged"] and guard["protected_files_unchanged"] and guard["own_slot_released"]
    assert guard["owned_cleanup"]["verified"] and not guard["owned_cleanup"]["remaining"]
    assert guard["model_idle_after"]["processing_slots"] == 0
    assert summary["complete"] and summary["verified"] and not summary.get("error")
    assert summary["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    assert summary["initial_attempts"] == summary["initial_received"] == 3
    assert [row["task"] for row in summary["initial_rows"]] == spec["generation_order"]
    assert [(row["task"], row["arm"]) for row in summary["rows"]] == order

    baseline = load("producer_audit_baseline", ROOT / "package/baseline.py")
    lexical = load("producer_audit_lexical", ROOT / "lexical_mask.py")
    runtime = load("producer_audit_runtime", ROOT / "package/agent/runtime.py")
    skill, repair = runtime.skill_texts()
    assert skill == (ROOT / "package/skill/rtl-generation/SKILL.md").read_text(encoding="utf-8")
    assert repair == (ROOT / "package/skill/rtl-feedback-repair/SKILL.md").read_text(encoding="utf-8")
    old_rows = read(ROOT / "OLD_CONTENT_IDENTITIES.json")["rows"]
    assert old_rows and all(re.fullmatch(r"[0-9a-f]{64}", row["content_sha256"]) for row in old_rows)

    def expected_request(prompt, later=False):
        return dict(model=spec["model"], messages=[dict(role="system", content=skill + ("\n" + repair if later else "")),
            dict(role="user", content=prompt)], temperature=0.0, top_p=1.0, max_tokens=8192)

    def check_request(payload, expected):
        assert payload == expected, "Request contains changed or additional fields/messages"
        assert type(payload["temperature"]) is float and type(payload["top_p"]) is float
        assert type(payload["max_tokens"]) is int
        assert len(payload["messages"]) == 2

    def choice_check(response):
        assert len(response["choices"]) == 1
        choice = response["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["role"] == "assistant"
        assert isinstance(choice["message"]["content"], str) and choice["message"]["content"]
        assert isinstance(response.get("id"), str) and response["id"]
        return choice

    initial, request_ids = {}, []
    for row in summary["initial_rows"]:
        task = row["task"]
        folder = RAW / "results/initial_generation" / task
        payload, response = read(folder / "request.json"), read(folder / "response.json")
        check_request(payload, expected_request((ROOT / "inputs" / task / "prompt.txt").read_text(encoding="utf-8")))
        choice = choice_check(response)
        assert row["response_received"] and row["finish_reason"] == choice["finish_reason"]
        assert row["request_sha256"] == sha(folder / "request.json")
        assert row["response_sha256"] == sha(folder / "response.json")
        assert row["response_id"] == response["id"] and row["usage"] == response.get("usage")
        elapsed = nonnegative(row["elapsed_s"])
        content_digest = text_sha(choice["message"]["content"])
        initial[task] = dict(request=payload, response=response, folder=folder, elapsed_s=elapsed,
            content_sha256=content_digest,
            seen_content_records=[old for old in old_rows if old["content_sha256"] == content_digest],
            seen_same_task_records=[old for old in old_rows if old["task"] == task and old["content_sha256"] == content_digest])
        request_ids.append(response["id"])

    probe_count = 0
    gate_count = 0
    gate_elapsed = 0.0
    lint_count = 0
    lint_elapsed = 0.0
    live_count = 0
    live_contents, live_payloads = {}, {}
    rows = []

    def stage_check(stage, folder):
        log = folder / Path(stage["log"]).name
        assert sha(log) == stage["log_sha256"] and log.stat().st_size == stage["log_bytes"]
        assert not stage["timeout"] and not stage["launch_error"] and not stage["remaining_live_group"]
        nonnegative(stage["elapsed_s"])

    def probe_check(probe, folder, source, task):
        nonlocal probe_count
        result, receipt = read(folder / "result.json"), read(folder / "adapter_receipt.json")
        assert receipt == probe and all(receipt[key] == value for key, value in result.items())
        assert probe["inherited_result_sha256"] == sha(folder / "result.json")
        assert probe["inherited_runner_sha256"] == spec["dependency_hashes"]["probe_runner.py"]
        assert probe["oracle_adapter_sha256"] == spec["dependency_hashes"]["paired_checkpoint.py"]
        assert probe["solution_sha256"] == sha(source) == sha(folder / "dut.sv")
        assert probe["tb_sha256"] == sha(ROOT / "inputs" / task / "tb.sv") == sha(folder / "tb.sv")
        assert probe["inputs_unchanged"] and probe["status"] in ("pass", "fail")
        for stage in probe["stages"]:
            stage_check(stage, folder)
        if probe["checks"] is not None:
            assert probe["checks"] == spec["checks"][task]
            markers = re.findall(r"^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$",
                (folder / "xsim.log").read_text(encoding="utf-8"), re.M)
            assert markers == [(task, str(probe["checks"]), str(probe["mismatches"]))]
        if probe["status"] == "pass":
            assert probe["mismatches"] == 0 and probe["checks"] == spec["checks"][task]
        probe_count += 1

    assert list(summary["controls"]) == tasks
    for task, controls in summary["controls"].items():
        assert set(controls) == {"positive", "negative"}
        for name, probe in controls.items():
            probe_check(probe, RAW / "results/controls" / task / name, ROOT / "inputs" / task / (name + ".sv"), task)
            assert probe["status"] == ("pass" if name == "positive" else "fail")
            if name == "negative":
                assert probe["failure_kind"] == "semantic_mismatch" and probe["mismatches"] > 0
    assert read(RAW / "results/controls_verified.json") == summary["controls"]
    generation_complete = read(RAW / "results/initial_generation_complete.json")
    assert generation_complete == dict(rows=summary["initial_rows"], workers_started=False, grading_started=False)
    workers_complete = read(RAW / "results/workers_complete.json")
    assert workers_complete == dict(grading_started=False, rows=[{key:value for key,value in row.items() if key != "probe"} for row in summary["rows"]])

    for row in summary["rows"]:
        task, arm = row["task"], row["arm"]
        folder = RAW / "results/workers" / task / arm
        worker = read(folder / "worker_result.json")
        assert worker == row["worker"] and worker["complete"] and worker["arm"] == arm
        stage_check(row["supervisor"], folder.parent)
        assert row["supervisor"]["returncode"] == 0
        worker_elapsed = nonnegative(worker["elapsed_s"])
        supervisor_elapsed = nonnegative(row["supervisor"]["elapsed_s"])
        assert supervisor_elapsed + 0.001 >= worker_elapsed
        assert sha(folder / "solution.v") == row["solution_sha256"]
        assert (folder / "prompt_only/prompt.txt").read_bytes() == (ROOT / "inputs" / task / "prompt.txt").read_bytes()
        assert sorted(path.name for path in (folder / "prompt_only").iterdir()) == ["prompt.txt"]
        events = [json.loads(line) for line in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        assert not any(event.get("error") for event in events)
        meta = [event for event in events if event["tool"] == "agent_meta"]
        assert len(meta) == 1 and meta[0]["repairs"] == 1
        assert meta[0]["skill_sha256"] == text_sha(skill) and meta[0]["repair_skill_sha256"] == text_sha(repair)
        journal, extraction = read(folder / "requests.json"), read(folder / "extraction.json")
        assert worker["extraction"] == extraction
        assert 1 <= len(journal) == len(extraction) == worker["requests"] <= 2
        assert worker["replayed_requests"] == 1 and worker["actual_model_requests"] == len(journal) - 1
        llms = [event for event in events if event["tool"] == "llm"]
        starts = [event for event in events if event["tool"] == "llm_start"]
        assert [event["round"] for event in llms] == [event["round"] for event in starts] == list(range(len(journal)))
        codes, live_elapsed = [], 0.0
        for index, entry in enumerate(journal):
            request_folder = folder / "requests" / str(index)
            payload, response = read(request_folder / "request.json"), read(request_folder / "response.json")
            assert entry["index"] == index and entry["replayed"] == (index == 0) and entry["response_received"]
            prompt = (ROOT / "inputs" / task / "prompt.txt").read_text(encoding="utf-8")
            if index == 0:
                check_request(payload, expected_request(prompt))
                assert payload == initial[task]["request"]
                assert (request_folder / "request.json").read_bytes() == (initial[task]["folder"] / "request.json").read_bytes()
                assert (request_folder / "response.json").read_bytes() == (initial[task]["folder"] / "response.json").read_bytes()
            else:
                before = events[:events.index(starts[index])]
                diagnostics = [event for event in before if event["tool"] in ("check_source", "check_submodules", "lint")]
                assert diagnostics and diagnostics[-1]["rc"] != 0
                if diagnostics[-1]["tool"] == "check_submodules":
                    missing = runtime.undefined_submodules(codes[index - 1])
                    assert missing and diagnostics[-1]["excerpt"] == "The design instantiates module(s) that this file never defines: " + ", ".join(missing) + "."
                elif diagnostics[-1]["tool"] == "check_source":
                    previous = codes[index - 1]
                    if re.search(r"`include|\$(?:readmem\w*|fopen|system)\b", previous):
                        expected_feedback = "Return a self-contained module without file access or include directives."
                    else:
                        assert not re.search(r"\bmodule\s+TopModule\b", previous) or "endmodule" not in previous
                        expected_feedback = "Return a complete TopModule ending in endmodule."
                    assert diagnostics[-1]["excerpt"] == expected_feedback
                user = prompt + "\nPrevious candidate:\n" + codes[index - 1] + "\nCandidate diagnostics:\n" + diagnostics[-1]["excerpt"]
                check_request(payload, expected_request(user, later=True))
                live_count += 1
                request_ids.append(response.get("id"))
                live_payloads[task, arm] = payload
                live_contents[task, arm] = response["choices"][0]["message"]["content"]
                live_elapsed += nonnegative(entry["elapsed_s"])
            choice = choice_check(response)
            assert choice["finish_reason"] == entry["finish_reason"] == llms[index]["finish"] == "stop"
            assert response["id"] == entry["response_id"]
            usage = response.get("usage") or {}
            assert llms[index]["tokens_in"] == usage.get("prompt_tokens") and llms[index]["tokens_out"] == usage.get("completion_tokens")
            nonnegative(entry["elapsed_s"])
            text = choice["message"]["content"]
            if arm == "A":
                code, receipt = baseline.extract(text, "rtl"), dict(decision="original_baseline")
            else:
                recorded = extraction[index].get("stages", [])
                gate_folder = folder / ("candidate_gate_" + str(index))
                proposed, _ = extract_bundle(text, baseline, lexical._strip_noncode)
                for stage in recorded:
                    stage_check(stage, gate_folder)
                if recorded:
                    assert (gate_folder / "dut.sv").read_bytes() == proposed.encode("utf-8")
                gate_count += len(recorded)
                gate_elapsed += sum(stage["elapsed_s"] for stage in recorded)

                class Replay:
                    cursor = 0

                    def owned_command(self, argv, cwd, log, seconds):
                        result = dict(recorded[self.cursor])
                        self.cursor += 1
                        assert normalized(argv[0]) == normalized(result["argv"][0])
                        assert argv[1:] == result["argv"][1:] and seconds == 60
                        # The temporary replay is created on the audit host;
                        # Windows write_text may translate its line endings.
                        # Archived Linux DUT bytes were checked separately.
                        assert (Path(cwd) / "dut.sv").read_text(encoding="utf-8") == proposed
                        Path(log).write_bytes((gate_folder / Path(result["log"]).name).read_bytes())
                        result.pop("name")
                        result.pop("argv")
                        return result

                replay = Replay()
                with tempfile.TemporaryDirectory() as temporary:
                    code, receipt = decide(text, baseline, lexical._strip_noncode, replay,
                        Path(temporary) / "gate", "/workspace/AMD/2026.1/Vivado/bin")
                for stage in receipt.get("stages", []):
                    stage["argv"][0] = normalized(stage["argv"][0])
                assert replay.cursor == len(recorded)
            assert receipt == extraction[index]
            assert (folder / ("extracted_" + str(index) + ".sv")).read_bytes() == code.encode("utf-8")
            codes.append(code)

        # Every original xvlog call is now independently bound to its source,
        # actual stdout and rc, including a possible ANSI declaration recompile.
        lint_journal = read(folder / "lint_journal.json")
        assert worker["ordinary_lint_commands"] == len(lint_journal)
        if (folder / "lint_journal").exists():
            assert {path.name for path in (folder / "lint_journal").iterdir()} == {str(number) for number in range(len(lint_journal))}
        else:
            assert not lint_journal
        lint_starts = [event for event in events if event["tool"] == "lint_start"]
        lint_events = [event for event in events if event["tool"] == "lint"]
        fix_events = [event for event in events if event["tool"] == "declaration_fix"]
        assert len(fix_events) <= 1
        assert [event["round"] for event in lint_starts] == [event["round"] for event in lint_events]
        by_round = {}
        for number, item in enumerate(lint_journal):
            journal_folder = folder / "lint_journal" / str(number)
            receipt = read(journal_folder / "receipt.json")
            assert item == receipt
            round_number = receipt["round"]
            assert type(round_number) is int and 0 <= round_number < len(codes)
            assert sha(journal_folder / "source_before.sv") == receipt["source_sha256_before"]
            assert sha(journal_folder / "source_after.sv") == receipt["source_sha256_after"]
            assert receipt["source_sha256_before"] == receipt["source_sha256_after"]
            assert sha(journal_folder / "stdout.log") == receipt["stdout_sha256"]
            cwd = normalized(receipt["cwd"])
            assert PurePosixPath(cwd).parts[-6:] == ("results", "workers", task, arm, "work", "compile-" + str(round_number))
            assert [normalized(arg) for arg in receipt["argv"]] == ["/workspace/AMD/2026.1/Vivado/bin/xvlog", "--sv", cwd + "/candidate.sv"]
            assert type(receipt["returncode"]) is int
            nonnegative(receipt["elapsed_s"])
            by_round.setdefault(round_number, []).append((receipt, journal_folder))
            lint_count += 1
            lint_elapsed += receipt["elapsed_s"]
        assert list(by_round) == [event["round"] for event in lint_starts]
        expected_final = codes[-1]
        observed_fix_rounds = []
        for event in lint_events:
            round_number = event["round"]
            entries = by_round[round_number]
            assert 1 <= len(entries) <= 2
            first, first_folder = entries[0]
            assert (first_folder / "source_before.sv").read_bytes() == codes[round_number].encode("utf-8")
            stdout = (first_folder / "stdout.log").read_text(encoding="utf-8")
            lines = [line for line in stdout.splitlines() if re.search("ERROR|WARNING|FATAL", line)]
            feedback = "\n".join(lines)[:2048] or stdout[-2048:]
            assert event["rc"] == first["returncode"] and event["excerpt"] == feedback
            final_compile_source = codes[round_number]
            if len(entries) == 2:
                assert first["returncode"] != 0
                patched = runtime.repair_ansi_declarations(codes[round_number], feedback)
                assert patched
                second, second_folder = entries[1]
                assert (second_folder / "source_before.sv").read_bytes() == patched.encode("utf-8")
                final_compile_source = patched
                if second["returncode"] == 0:
                    observed_fix_rounds.append(round_number)
                    assert round_number == len(codes) - 1
                    expected_final = patched
            assert (folder / "work" / ("compile-" + str(round_number)) / "candidate.sv").read_bytes() == final_compile_source.encode("utf-8")
        assert [event["round"] for event in fix_events] == observed_fix_rounds
        assert all(event["rc"] == 0 for event in fix_events)
        assert (folder / "solution.v").read_bytes() == expected_final.encode("utf-8")
        assert live_elapsed <= worker_elapsed + 0.001
        probe_check(row["probe"], RAW / "results/probes" / task / arm, folder / "solution.v", task)
        rows.append(dict(task=task, arm=arm, status=row["probe"]["status"],
            failure_kind=row["probe"]["failure_kind"], checks=row["probe"]["checks"], mismatches=row["probe"]["mismatches"],
            actual_repair_requests=worker["actual_model_requests"], actual_model_requests=worker["actual_model_requests"],
            replayed_requests=1, worker_elapsed_s=worker_elapsed, supervisor_elapsed_s=supervisor_elapsed,
            repair_request_elapsed_s=live_elapsed, model_request_elapsed_s=live_elapsed,
            initial_generation_elapsed_s=initial[task]["elapsed_s"], final_sha256=row["solution_sha256"],
            extraction_decisions=[item["decision"] for item in extraction],
            candidate_gate_entered=any(item.get("compile_required") for item in extraction),
            candidate_accepted=any(item["decision"] == "candidate_accepted" for item in extraction)))

    assert probe_count == summary["actual_probes"] == 12
    assert live_count == summary["actual_repair_requests"] <= spec["max_repair_requests"]
    assert summary["actual_model_requests"] == 3 + live_count <= spec["max_actual_model_requests"]
    assert summary["replayed_requests"] == 6
    assert all(request_ids) and len(request_ids) == len(set(request_ids)) == summary["actual_model_requests"]

    # Require the complete protocol sequence, not merely a saved boolean.
    phase = [json.loads(line) for line in (RAW / "results/phase_events.jsonl").read_text(encoding="utf-8").splitlines()]
    expected_phase = [("stage_start", None, None), ("controls_verified", None, None)]
    for task in spec["generation_order"]:
        expected_phase.extend([("initial_request_start", task, None), ("initial_response_received", task, None)])
    expected_phase.append(("initial_generation_complete", None, None))
    for task, arm in order:
        expected_phase.extend([("worker_start", task, arm), ("worker_complete", task, arm)])
    expected_phase.append(("workers_complete", None, None))
    for task, arm in order:
        expected_phase.extend([("grade_start", task, arm), ("graded", task, arm)])
    expected_phase.append(("stage_finish", None, None))
    assert [(event["kind"], event.get("task"), event.get("arm")) for event in phase] == expected_phase
    elapsed_values = [nonnegative(event["elapsed_s"]) for event in phase]
    assert elapsed_values == sorted(elapsed_values)
    assert all(utc(guard["started_at_utc"]) <= utc(event["utc"]) <= utc(guard["finished_at_utc"]) for event in phase)
    worker_sources = {(row["task"], row["arm"]):row for row in summary["rows"]}
    phase_starts = {}
    for event in phase:
        kind = event["kind"]
        task, arm = event.get("task"), event.get("arm")
        if kind == "stage_start":
            assert event["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
        elif kind == "controls_verified":
            assert event["controls_sha256"] == sha(RAW / "results/controls_verified.json")
        elif kind in ("initial_request_start", "initial_response_received"):
            assert event["request_sha256"] == sha(initial[task]["folder"] / "request.json")
            if kind == "initial_request_start":
                phase_starts[kind, task] = event["elapsed_s"]
            if kind == "initial_response_received":
                assert event["response_sha256"] == sha(initial[task]["folder"] / "response.json")
                assert initial[task]["elapsed_s"] <= event["elapsed_s"] - phase_starts["initial_request_start", task] + 0.001
        elif kind == "initial_generation_complete":
            assert event["manifest_sha256"] == sha(RAW / "results/initial_generation_complete.json")
        elif kind in ("worker_complete", "grade_start"):
            assert event["solution_sha256"] == worker_sources[task, arm]["solution_sha256"]
            if kind == "worker_complete":
                assert event["worker_result_sha256"] == sha(RAW / "results/workers" / task / arm / "worker_result.json")
                assert worker_sources[task, arm]["supervisor"]["elapsed_s"] <= event["elapsed_s"] - phase_starts["worker_start", task, arm] + 0.001
        elif kind == "worker_start":
            phase_starts[kind, task, arm] = event["elapsed_s"]
        elif kind == "workers_complete":
            assert event["manifest_sha256"] == sha(RAW / "results/workers_complete.json")
        elif kind == "graded":
            assert event["receipt_sha256"] == sha(RAW / "results/probes" / task / arm / "adapter_receipt.json")
        elif kind == "stage_finish":
            assert event["complete"] and event["verified"]
            assert event["summary_sha256"] == sha(RAW / "results/summary.json")
            assert event["elapsed_s"] >= summary["elapsed_s"]

    shared_generation_elapsed = sum(item["elapsed_s"] for item in initial.values())
    assert shared_generation_elapsed + sum(row["supervisor_elapsed_s"] for row in rows) <= nonnegative(summary["elapsed_s"]) + 0.01
    totals = {}
    for arm in ("A", "C"):
        subset = [row for row in rows if row["arm"] == arm]
        repair_count = sum(row["actual_repair_requests"] for row in subset)
        worker_seconds = sum(row["worker_elapsed_s"] for row in subset)
        supervisor_seconds = sum(row["supervisor_elapsed_s"] for row in subset)
        totals[arm] = dict(passes=sum(row["status"] == "pass" for row in subset),
            actual_repair_requests=repair_count, actual_model_requests=repair_count,
            initial_requests_for_one_production_run=3, production_model_requests=3 + repair_count,
            worker_elapsed_s=worker_seconds, supervisor_elapsed_s=supervisor_seconds,
            repair_request_elapsed_s=sum(row["repair_request_elapsed_s"] for row in subset),
            shared_initial_generation_elapsed_s=shared_generation_elapsed,
            production_elapsed_estimate_s=shared_generation_elapsed + worker_seconds,
            production_supervisor_elapsed_estimate_s=shared_generation_elapsed + supervisor_seconds)
    by = {(row["task"], row["arm"]):row for row in rows}
    regressions = sum(by[task, "A"]["status"] == "pass" and by[task, "C"]["status"] == "fail" for task in tasks)
    fixes = sum(by[task, "A"]["status"] == "fail" and by[task, "C"]["status"] == "pass" for task in tasks)
    correct_tasks = [task for task in tasks if by[task, "A"]["status"] == "pass"]
    correct_accepted = [task for task in correct_tasks if by[task, "C"]["candidate_accepted"]]
    correct_gate_entered = [task for task in correct_tasks if by[task, "C"]["candidate_gate_entered"]]
    correct_final_changed = [task for task in correct_tasks if by[task, "A"]["final_sha256"] != by[task, "C"]["final_sha256"]]
    equal_quality_call_gain = totals["C"]["passes"] == totals["A"]["passes"] and totals["C"]["actual_repair_requests"] < totals["A"]["actual_repair_requests"]
    accepted = regressions == 0 and (totals["C"]["passes"] > totals["A"]["passes"] or equal_quality_call_gain)
    postflight = read(RAW / "postflight.json")
    assert postflight["model_health"]["status"] == "ok" and not postflight["own_slot_exists"]
    assert postflight["instance_shutdown_or_model_restart"] is False
    result = dict(schema="bundle_producer_audit_v1", status="complete_verified", groups=totals,
        regressions=regressions, fixes=fixes, acceptance_met=accepted, adoption=False, new_score=False,
        acceptance_scope="Further validation only; no timing-only acceptance, adoption, score or independent-task claim.",
        actual_initial_requests=3, actual_repair_requests=live_count, actual_model_requests=3 + live_count,
        replayed_initial_responses=6, unique_initial_response_ids=3,
        unique_initial_answer_texts=len({item["content_sha256"] for item in initial.values()}),
        initial_content_seen_before_count=sum(bool(item["seen_content_records"]) for item in initial.values()),
        initial_content_seen_same_task_count=sum(bool(item["seen_same_task_records"]) for item in initial.values()),
        initial_rows=[dict(task=task, response_id=initial[task]["response"]["id"],
            response_sha256=sha(initial[task]["folder"] / "response.json"), content_sha256=initial[task]["content_sha256"],
            elapsed_s=initial[task]["elapsed_s"], seen_content_records=initial[task]["seen_content_records"],
            seen_same_task_records=initial[task]["seen_same_task_records"]) for task in spec["generation_order"]],
        live_unique_answer_texts=len(set(live_contents.values())),
        live_request_pairs_identical=[task for task in tasks if (task, "A") in live_payloads and (task, "C") in live_payloads and live_payloads[task, "A"] == live_payloads[task, "C"]],
        live_response_content_pairs_identical=[task for task in tasks if (task, "A") in live_contents and (task, "C") in live_contents and live_contents[task, "A"] == live_contents[task, "C"]],
        original_final_correct_guard_count=len(correct_tasks),
        original_final_correct_C_gate_entered_count=len(correct_gate_entered),
        original_final_correct_C_accepted_change_count=len(correct_accepted),
        original_final_correct_final_source_changed_count=len(correct_final_changed),
        original_final_correct_C_no_accepted_change_count=len(correct_tasks) - len(correct_accepted),
        correct_guard_tasks=dict(original=correct_tasks, C_gate_entered=correct_gate_entered,
            C_accepted_change=correct_accepted, final_source_changed=correct_final_changed),
        actual_probes=probe_count, controls_valid=6, candidate_gate_commands=gate_count,
        candidate_gate_elapsed_s=gate_elapsed, original_lint_calls=lint_count,
        original_lint_elapsed_s=lint_elapsed, synthesis_calls=0, rows=rows,
        elapsed_s=summary["elapsed_s"], shared_initial_generation_elapsed_s=shared_generation_elapsed,
        phase_event_count=len(phase), phase_sequence_and_hashes_verified=True,
        full_requests_and_runtime_lint_evidence_verified=True,
        independent_natural_validation=False, production_initial_generation_measured=True,
        production_initial_generation_scope="Exact original runtime generation-skill request schema dispatched once per known development task; worker first requests and full response bytes match. Production HTTP solve/lock transport is not measured.",
        timing_scope="Observed single-run generation/repair/worker/supervisor costs include adapter and diagnostic journaling overhead; repair request journals include admission/idle checks. Production estimates add shared initial generation once per arm, retain replay overhead, and exclude HTTP solve transport. Cache/order effects are uncontrolled; elapsed time is observational only.",
        guard={key:guard[key] for key in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "own_slot_released", "model_idle_after")},
        evidence=dict(sha256=archive["sha256"], files=len(manifest["files"]), all_hashes_verified=True,
                      zip_members_bound_to_extracted_evidence=True), postflight=postflight, limits=spec["limits"])
    (ROOT / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key:result[key] for key in ("status", "groups", "fixes", "regressions", "acceptance_met", "actual_model_requests", "evidence")}))


if __name__ == "__main__":
    main()
