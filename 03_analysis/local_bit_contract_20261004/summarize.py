"""Audit the frozen three-arm evidence without new model or EDA calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from feedback import messages
from pilot import COMMON, SYSTEM

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    archive = read(ROOT / "ARCHIVE.json")
    assert sha(ROOT / "evidence.zip") == archive["sha256"]
    manifest = read(RAW / "MANIFEST.json")
    for row in manifest["files"]:
        p = (RAW / row["path"]).resolve()
        assert p.is_relative_to(RAW.resolve())
        assert p.stat().st_size == row["bytes"] and sha(p) == row["sha256"], row["path"]
    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for f, h in spec["source_hashes"].items():
        assert sha(ROOT / f) == sha(RAW / f) == h, f
    dependency = ROOT.parent / "ross_diagnostic_repair_20261004"
    for f, h in spec["dependency_hashes"].items():
        assert sha(dependency / f) == sha(RAW / "dependency_snapshot" / f) == h, f
    assert sha(RAW / "guard_wrapper.py") == spec["resource_guard_sha256"]
    module_spec = importlib.util.spec_from_file_location("frozen_baseline", dependency / "baseline_extract.py")
    baseline = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(baseline)
    guard = read(RAW / "guard/status.json")
    summary = read(RAW / "results/summary.json")
    launch = read(RAW / "launch.json")
    assert launch["run_spec_sha256"] == summary["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    assert guard["complete"] and guard["passed"] and guard["stage_rc"] == 0
    assert guard["model_unchanged"] and guard["protected_files_unchanged"] and guard["own_slot_released"]
    assert guard["owned_cleanup"]["verified"] and not guard["owned_cleanup"]["remaining"]
    assert guard["model_idle_after"]["processing_slots"] == 0
    assert summary["complete"] and summary["verified"] and summary["assets_unchanged"]
    assert summary["attempts"] == summary["responses"] == spec["model_call_budget"] == 18
    assert summary["retries"] == 0 and summary["model"] == spec["model_alias"]
    assert read(RAW / "results/preflight_verified.json")["model_calls"] == 0
    generation = read(RAW / "results/generation_complete.json")
    assert generation["grading_started"] is False and len(generation["rows"]) == 18
    assert all("official" not in row and "probe" not in row for row in generation["rows"])
    events = [json.loads(line) for line in (RAW / "guard/stage.log").read_text(encoding="utf-8").splitlines() if line.startswith('{')]
    phases = [x.get("phase") for x in events if x.get("phase")]
    assert phases == ["original_verified"] * 3 + ["generated"] * 18 + ["graded"] * 18
    subjects = {x["id"]: x for x in spec["subjects"]}
    task = spec["task"]
    tb_sha = sha(ROOT / "inputs" / task / "tb.sv")

    def audit_probe(folder, source):
        probe = read(folder / "result.json")
        receipt = read(folder / "adapter_receipt.json")
        assert receipt["inherited_result_sha256"] == sha(folder / "result.json")
        assert receipt["oracle_adapter_sha256"] == spec["dependency_hashes"]["paired_checkpoint.py"]
        assert receipt["inherited_runner_sha256"] == spec["dependency_hashes"]["probe_runner.py"]
        assert all(receipt[k] == v for k, v in probe.items())
        assert probe["solution_sha256"] == sha(source) and probe["tb_sha256"] == tb_sha
        assert probe["runner_sha256"] == spec["dependency_hashes"]["probe_runner.py"]
        assert probe["inputs_unchanged"] and probe["status"] != "environment_error"
        for stage in probe["stages"]:
            log = folder / Path(stage["log"]).name
            assert sha(log) == stage["log_sha256"] and log.stat().st_size == stage["log_bytes"]
            assert not stage["remaining_live_group"]
        return probe

    def audit_grade(folder, source):
        verdict = read(folder / "verdict.json")
        receipt = read(folder / "judge_receipt.json")
        assert not receipt["errors"] and receipt["judge_rc"] == 0
        assert not verdict.get("tool_error") and not verdict.get("suspected_silent_degradation")
        evidence = folder / "judge_work_logs"
        assert verdict["judge_evidence_complete"] and sha(evidence / "dut.sv") == sha(source)
        for name, row in receipt["evidence"].items():
            p = evidence / name
            assert sha(p) == row["sha256"] and p.stat().st_size == row["bytes"], name
        return verdict

    for name in ("positive", "negative"):
        p = audit_probe(RAW / "results/controls" / name, ROOT / "inputs" / task / (name + ".sv"))
        assert p["checks"] == spec["checks"]
        assert p["status"] == ("pass" if name == "positive" else "fail")
        if name == "negative":
            assert p["failure_kind"] == "semantic_mismatch"
    diagnostics = {}
    for subject, contract in subjects.items():
        source = ROOT / contract["source"]
        folder = RAW / "results/original_probes" / subject
        p = audit_probe(folder, source)
        assert p["checks"] == spec["checks"] and p["mismatches"] == contract["expected_mismatches"]
        transcript = (folder / "xsim.log").read_text(encoding="utf-8")
        assert re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$', transcript, re.M) == [(task, str(spec["checks"]), str(p["mismatches"]))]
        first = [x for x in transcript.splitlines() if x.startswith("FIRST_MISMATCH")]
        assert len(first) == (1 if contract["role"] == "development_error" else 0)
        feedback = messages(p["checks"], p["mismatches"], first[0] if first else None)
        assert feedback == summary["originals"][subject]["feedback"]
        if first:
            n = feedback["normalized"]
            assert n["round_trip_verified"] and n["time_ps"] == 5000 and n["time_ns"] == "5"
            assert n["previous_set_bits"] == [0] and n["data_set_bits"] == []
            assert n["load"] == n["bit"] == n["expected"] == 0 and n["observed"] == 1
        official = audit_grade(RAW / "results/official_originals" / subject, source)
        assert official == summary["originals"][subject]["official"]
        assert (official["level"] == 3) == (contract["role"] == "correct_guard")
        diagnostics[subject] = dict(checks=p["checks"], mismatches=p["mismatches"], official_level=official["level"], first_mismatch=first[0] if first else None)
    rows, response_ids = [], []
    for row in summary["rows"]:
        subject, label = row["subject"], row["label"]
        source = ROOT / subjects[subject]["source"]
        folder = RAW / "results/generated" / subject / label
        assert sha(folder / "request.json") == row["request_sha256"]
        assert sha(folder / "response.json") == row["response_sha256"]
        payload = read(folder / "request.json")
        user = "Specification:\n" + (ROOT / "inputs" / task / "prompt.txt").read_text(encoding="utf-8") + "\nCandidate:\n" + source.read_text(encoding="utf-8") + "\n\n" + COMMON + "\n\nObserved diagnostic:\n" + summary["originals"][subject]["feedback"][label[0]]
        assert payload == dict(model=spec["model_alias"], temperature=0, top_p=1, max_tokens=spec["max_tokens"], messages=[dict(role="system", content=SYSTEM), dict(role="user", content=user)])
        response = read(folder / "response.json")
        response_ids.append(response["id"])
        choice = response["choices"][0]
        assert row["response_received"] and choice["finish_reason"] == row["finish_reason"] == "stop"
        solution = RAW / row["solution_path"]
        assert sha(solution) == row["solution_sha256"]
        assert solution.read_bytes() == baseline.extract(choice["message"]["content"], "rtl").encode("utf-8")
        assert row["source_changed"] == (sha(solution) != sha(source))
        probe = audit_probe(RAW / "results/generated_probes" / subject / label, solution)
        if row.get("official_original_reused_identical_bytes"):
            assert sha(solution) == sha(source)
            official = audit_grade(RAW / "results/official_originals" / subject, solution)
        else:
            official = audit_grade(RAW / "results/official_generated" / subject / label, solution)
        assert official == row["official"] and probe["status"] == row["probe"]["status"]
        rows.append({k: row[k] for k in ("subject", "role", "label", "request_sha256", "response_sha256", "solution_sha256", "source_changed", "usage", "finish_reason", "request_elapsed_s")} | dict(probe_status=probe["status"], probe_failure_kind=probe["failure_kind"], probe_checks=probe["checks"], probe_mismatches=probe["mismatches"], official_level=official["level"]))
    assert [(x["subject"], x["label"]) for x in rows] == [(x, label) for x in subjects for label in spec["order"]]
    assert len(response_ids) == len(set(response_ids)) == 18 and all(response_ids)
    arms = {}
    for arm in ("A", "B", "C"):
        group = [x for x in rows if x["label"].startswith(arm)]
        arms[arm] = dict(rows=len(group), error_reviews=sum(x["role"] == "development_error" for x in group), repairs=sum(x["role"] == "development_error" and x["official_level"] == 3 for x in group), guard_reviews=sum(x["role"] == "correct_guard" for x in group), guard_regressions=sum(x["role"] == "correct_guard" and x["official_level"] < 3 for x in group), request_elapsed_s=sum(x["request_elapsed_s"] for x in group), byte_identical=sum(not x["source_changed"] for x in group))
        assert arms[arm]["rows"] == 6 and arms[arm]["error_reviews"] == 2 and arms[arm]["guard_reviews"] == 4
        assert all(arms[arm][k] == summary["arms"][arm][k] for k in ("rows", "repairs", "guard_regressions", "request_elapsed_s"))
    conflicts = [dict(subject=x["subject"], label=x["label"], probe_status=x["probe_status"], official_level=x["official_level"]) for x in rows if (x["official_level"] == 3) != (x["probe_status"] == "pass")]
    qualify = [arm for arm in ("B", "C") if arms[arm]["repairs"] > arms["A"]["repairs"] and arms[arm]["guard_regressions"] == 0 and not conflicts]
    postflight = read(RAW / "postflight.json")
    assert postflight["model_health"]["status"] == "ok" and postflight["processing_slots"] == 0 and not postflight["slot_exists"]
    result = dict(schema="local_bit_contract_audit_v1", status="complete_verified", qualifies_for_independent_validation=bool(qualify), qualifying_arms=qualify, formal_runtime_integrated=False, new_score=False, full_skill_model_execution=False, model=summary["model"], attempts=18, responses=18, retries=0, mcp_sessions=0, elapsed_s=summary["elapsed_s"], arms=arms, rows=rows, original_diagnostics=diagnostics, official_selfcheck_conflicts=conflicts, production_end_to_end_benefit_measured=False, manual_testbench_creation_cost_measured=False, guard={k: guard[k] for k in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "own_slot_released", "model_idle_after")}, owned_cleanup_verified=True, remaining_owned_processes=0, evidence=dict(archive_sha256=archive["sha256"], manifest_files=len(manifest["files"]), all_hashes_verified=True, all_requests_exactly_reconstructed=True, all_extractions_and_grades_verified=True, unique_response_ids=18), postflight=postflight, limits=spec["limits"])
    (ROOT / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(verified=True, arms=arms, qualifying_arms=qualify, conflicts=conflicts, manifest_files=len(manifest["files"]))))


if __name__ == "__main__":
    main()
