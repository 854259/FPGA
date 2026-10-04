"""Recompute same-response extraction audit from immutable private evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def load(name, p):
    spec = importlib.util.spec_from_file_location(name, p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    archive = read(ROOT / "ARCHIVE.json")
    assert sha(ROOT / "evidence.zip") == archive["sha256"]
    manifest = read(RAW / "MANIFEST.json")
    for row in manifest["files"]:
        p = (RAW / row["path"]).resolve()
        assert p.is_relative_to(RAW.resolve())
        assert sha(p) == row["sha256"] and p.stat().st_size == row["bytes"]
    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == sha(RAW / name) == digest, name
    for name, digest in spec["dependency_hashes"].items():
        assert sha(RAW / "dependency_snapshot" / name) == digest
    assert sha(ROOT.parent / "ross_diagnostic_repair_20261004/baseline_extract.py") == spec["dependency_hashes"]["baseline_extract.py"]
    assert sha(ROOT.parent / "natural_coverage_20261004/signedness_selector.py") == sha(ROOT / "lexical_mask.py")
    local_tests = (ROOT / "LOCAL_TESTS.txt").read_text(encoding="utf-8")
    assert "Ran 19 tests" in local_tests and local_tests.rstrip().endswith("OK")
    baseline = load("bundle_audit_baseline", RAW / "dependency_snapshot/baseline_extract.py")
    lexical = load("bundle_audit_lexical", RAW / "lexical_mask.py")
    bundle = load("bundle_audit_extractor", RAW / "extract_bundle.py")
    g = read(RAW / "guard/status.json")
    s = read(RAW / "results/summary.json")
    assert g["complete"] and g["passed"] and g["stage_rc"] == 0
    assert g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
    assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    assert sha(RAW / "guard_wrapper.py") == spec["resource_guard_sha256"]
    assert s["complete"] and s["verified"] and s["attempts"] == s["responses"] == spec["model_call_budget"] == 8
    assert s["retries"] == 0 and s["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    preflight = read(RAW / "results/preflight_verified.json")
    assert preflight["model_calls"] == 0 and preflight["controls"] == s["controls"]
    assert preflight["format_controls"] == s["format_controls"]
    contracts = {c["task"]: c for c in spec["contracts"]}
    counts = dict(probes=0, synthesis=0, synthesis_reuses=0)

    def probe(folder, source, task, summary):
        p = read(folder / "result.json")
        receipt = read(folder / "adapter_receipt.json")
        assert summary == receipt and all(receipt[k] == v for k, v in p.items())
        assert receipt["inherited_result_sha256"] == sha(folder / "result.json")
        assert receipt["inherited_runner_sha256"] == spec["dependency_hashes"]["probe_runner.py"]
        assert receipt["oracle_adapter_sha256"] == spec["dependency_hashes"]["paired_checkpoint.py"]
        assert p["solution_sha256"] == sha(source) == sha(folder / "dut.sv")
        assert p["tb_sha256"] == sha(ROOT / "inputs" / task / "tb.sv") == sha(folder / "tb.sv")
        assert p["inputs_unchanged"] and p["status"] in ("pass", "fail")
        for stage in p["stages"]:
            log = folder / Path(stage["log"]).name
            assert sha(log) == stage["log_sha256"] and log.stat().st_size == stage["log_bytes"]
            assert not stage["remaining_live_group"] and not stage["timeout"] and not stage["launch_error"]
        if p["checks"] is not None:
            assert p["checks"] == contracts[task]["checks"]
            markers = re.findall(r"^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$", (folder / "xsim.log").read_text(encoding="utf-8"), re.M)
            assert markers == [(task, str(p["checks"]), str(p["mismatches"]))]
        if p["status"] == "pass":
            assert p["checks"] == contracts[task]["checks"] and p["mismatches"] == 0
        counts["probes"] += 1
        return p

    def synthesis(folder, source, result):
        assert result["returncode"] == 0 and not result["remaining_live_group"]
        assert not result["timeout"] and not result["launch_error"]
        assert sha(folder / "dut.sv") == sha(source)
        assert sha(folder / "synth.log") == result["log_sha256"]
        assert (folder / "synth.log").stat().st_size == result["log_bytes"]
        text = (folder / "synth.log").read_text(encoding="utf-8")
        assert len(re.findall(r"^BUNDLE_SYNTHESIS_PASS\s*$", text, re.M)) == 1
        assert not re.search(r"^BUNDLE_SYNTHESIS_FAIL\b", text, re.M)
        counts["synthesis"] += 1

    for task in contracts:
        for name in ("positive", "negative"):
            p = probe(RAW / "results/controls" / task / name, ROOT / "inputs" / task / (name + ".sv"), task, s["controls"][task][name])
            assert p["checks"] == contracts[task]["checks"]
            assert p["status"] == ("pass" if name == "positive" else "fail")
            if name == "negative":
                assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0

    def extraction(answer, folder, receipt_name):
        a = baseline.extract(answer, "rtl")
        b, receipt = bundle.extract_bundle(answer, baseline, lexical._strip_noncode)
        assert (folder / "A.sv").read_bytes() == a.encode()
        assert (folder / "B.sv").read_bytes() == b.encode()
        assert read(folder / receipt_name) == receipt
        return receipt

    format_rows = []
    for case in spec["format_controls"]:
        name = case["id"]
        folder = RAW / "results/format_sources" / name
        receipt = extraction((ROOT / case["reply"]).read_text(encoding="utf-8"), folder, "receipt.json")
        record = s["format_controls"][name]
        assert receipt == record["receipt"]
        for arm in ("A", "B"):
            p = probe(RAW / "results/format_probes" / name / arm, folder / (arm + ".sv"), "adder_8bit", record["probes"][arm])
            assert p["status"] == case["expected_" + arm]
            if arm == "B" and case.get("expected_B_failure_kind"):
                assert p["failure_kind"] == case["expected_B_failure_kind"]
        if record["probes"]["B"]["status"] == "pass":
            synthesis(RAW / "results/format_synthesis" / name, folder / "B.sv", record["B_synthesis"])
        format_rows.append(dict(id=name, A=record["probes"]["A"]["status"], B=record["probes"]["B"]["status"], changed=receipt["changed"]))
    generation = read(RAW / "results/generation_complete.json")
    assert generation["grading_started"] is False and len(generation["rows"]) == 8
    assert all("grades" not in row for row in generation["rows"])
    events = [json.loads(line) for line in (RAW / "guard/stage.log").read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    phases = [event.get("phase") for event in events if event.get("phase")]
    assert phases == ["preflight_verified"] + ["generated"] * 8 + ["graded"] * 8
    assert [(r["task"], r["trial"]) for r in s["rows"]] == [tuple(x) for x in spec["generation_order"]]
    ids, rows, answer_hashes, diagnostic_changes = set(), [], set(), []
    for i, row in enumerate(s["rows"]):
        assert {k: v for k, v in row.items() if k != "grades"} == generation["rows"][i]
        task, trial = row["task"], str(row["trial"])
        folder = RAW / "results/generated" / task / trial
        payload = dict(model=spec["model"], temperature=0, top_p=1, max_tokens=spec["max_tokens"], messages=[dict(role="system", content=baseline.SYS["rtl"]), dict(role="user", content=(ROOT / "inputs" / task / "prompt.txt").read_text(encoding="utf-8"))])
        assert read(folder / "request.json") == payload and sha(folder / "request.json") == row["request_sha256"]
        response = read(folder / "response.json")
        assert sha(folder / "response.json") == row["response_sha256"]
        assert response["id"] == row["response_id"] and response["id"] not in ids
        ids.add(response["id"])
        assert row["response_received"] and row["usage"] == response["usage"]
        choice = response["choices"][0]
        assert choice["finish_reason"] == row["finish_reason"] == "stop"
        answer = choice["message"]["content"]
        assert (folder / "answer.txt").read_bytes() == answer.encode()
        answer_hashes.add(sha(folder / "answer.txt"))
        receipt = extraction(answer, folder, "bundle_receipt.json")
        assert receipt == row["bundle_receipt"] and receipt["changed"] == row["bundle_changed"]
        for arm in ("A", "B"):
            assert sha(folder / (arm + ".sv")) == row[arm + "_sha256"]
            grade = row["grades"][arm]
            p = probe(RAW / "results/generated_probes" / task / trial / arm, folder / (arm + ".sv"), task, grade["probe"])
            if p["status"] == "pass":
                if grade.get("synthesis_reused_identical_bytes"):
                    assert arm == "B" and not receipt["changed"] and sha(folder / "A.sv") == sha(folder / "B.sv")
                    assert grade["synthesis"] == row["grades"]["A"]["synthesis"]
                    counts["synthesis_reuses"] += 1
                else:
                    synthesis(RAW / "results/generated_synthesis" / task / trial / arm, folder / (arm + ".sv"), grade["synthesis"])
        rows.append(dict(task=task, trial=int(trial), A=row["grades"]["A"]["probe"]["status"], B=row["grades"]["B"]["probe"]["status"], A_failure=row["grades"]["A"]["probe"]["failure_kind"], B_failure=row["grades"]["B"]["probe"]["failure_kind"], changed=receipt["changed"], reason=receipt["reason"], modules=receipt["modules"], A_sha256=row["A_sha256"], B_sha256=row["B_sha256"], request_elapsed_s=row["request_elapsed_s"]))
        if task == "adder_8bit":
            assert receipt["changed"] and receipt["modules"] == ["TopModule", "full_adder"]
            assert row["grades"]["A"]["probe"]["failure_kind"] == row["grades"]["B"]["probe"]["failure_kind"] == "xelab_failed"
            logs = {arm: RAW / "results/generated_probes" / task / trial / arm / "xelab.log" for arm in ("A", "B")}
            assert "Module <full_adder> not found" in logs["A"].read_text(encoding="utf-8")
            assert "index 8 into 'carry' is out of bounds" in logs["B"].read_text(encoding="utf-8")
            assert "logic [7:0] carry;" in answer and "carry[8]" in answer
            diagnostic_changes.append(dict(task=task, trial=int(trial), A="missing_full_adder", B="carry_index_8_out_of_bounds", A_log_sha256=sha(logs["A"]), B_log_sha256=sha(logs["B"]), simulation_reached=False))
    assert counts["probes"] == 32
    fixes = sum(r["A"] == "fail" and r["B"] == "pass" for r in rows)
    regressions = sum(r["A"] == "pass" and r["B"] == "fail" for r in rows)
    postflight = read(RAW / "postflight.json")
    assert g["model_idle_after"]["health_status"] == "ok" and g["model_idle_after"]["processing_slots"] == 0
    assert postflight["model_health"]["status"] == "ok" and not postflight["own_slot_exists"]
    if postflight["slot_exists"]:
        assert postflight["slot_owner"] and postflight["slot_owner"] != "fpga_owner_module_bundle_20261004"
    collection = read(RAW / "collection_failure.json")
    assert sha(RAW / "collect_evidence.initial.py") == collection["first_collector_sha256"]
    assert collection["model_calls"] == collection["eda_calls"] == 0 and not collection["run_inputs_or_results_changed"] and not collection["foreign_slot_modified"]
    result = dict(schema="module_bundle_same_response_audit_v1", status="complete_verified", model_requests=8, complete_responses=8, retries=0, paired_generated_probes=16, A_passes=sum(r["A"] == "pass" for r in rows), B_passes=sum(r["B"] == "pass" for r in rows), fixes=fixes, regressions=regressions, changed_responses=sum(r["changed"] for r in rows), acceptance_met=fixes > 0 and regressions == 0, adoption=False, new_score=False, controls_valid=8, format_controls=format_rows, counts=counts, rows=rows, elapsed_s=s["elapsed_s"], model_request_elapsed_s=sum(r["request_elapsed_s"] for r in rows), guard={k: g[k] for k in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "own_slot_released", "model_idle_after")}, owned_cleanup_verified=True, remaining_owned_processes=0, evidence=dict(archive_sha256=archive["sha256"], manifest_files=len(manifest["files"]), all_hashes_verified=True), postflight=postflight, branch=read(RAW / "launch.json")["branch"], limits=spec["limits"])
    result.update(unique_answer_texts=len(answer_hashes), unique_A_B_source_pairs=len({(r["A_sha256"], r["B_sha256"]) for r in rows}), diagnostic_changes=diagnostic_changes, archive_collection_retry=collection)
    (ROOT / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("status", "A_passes", "B_passes", "fixes", "regressions", "changed_responses", "acceptance_met", "counts", "evidence")}))


if __name__ == "__main__":
    main()
