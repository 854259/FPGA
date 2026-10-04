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
        assert p.is_relative_to(RAW.resolve()) and sha(p) == row["sha256"] and p.stat().st_size == row["bytes"]
    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == sha(RAW / name) == digest, name
    for name, digest in spec["dependency_hashes"].items():
        assert sha(RAW / "dependency_snapshot" / name) == digest
    assert sha(ROOT / "extract_bundle.py") == spec["extractor_sha256"] == "8a7ab290e1e15d4248fd166b9c587b5fea7fb2958265853aeffe50e335de6414"
    baseline = load("helper_audit_baseline", RAW / "dependency_snapshot/baseline_extract.py")
    lexical = load("helper_audit_lexical", RAW / "lexical_mask.py")
    bundle = load("helper_audit_extractor", RAW / "extract_bundle.py")
    g, s = read(RAW / "guard/status.json"), read(RAW / "results/summary.json")
    assert g["complete"] and g["passed"] and g["stage_rc"] == 0
    assert g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
    assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    assert g["model_idle_after"]["health_status"] == "ok" and g["model_idle_after"]["processing_slots"] == 0
    assert sha(RAW / "guard_wrapper.py") == spec["resource_guard_sha256"]
    assert s["complete"] and s["verified"] and s["attempts"] == s["responses"] == spec["model_call_budget"] == 3
    assert s["retries"] == 0 and s["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    pre = read(RAW / "results/preflight_verified.json")
    assert pre["model_calls"] == 0
    for k in ("controls", "control_synthesis", "format_controls"):
        assert pre[k] == s[k]
    contracts = {c["task"]: c for c in spec["contracts"]}
    counts = dict(probes=0, synthesis=0, synthesis_reuses=0, format_positive_probe_reuses=3)

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
        assert len(re.findall(r"^HELPER_SYNTHESIS_PASS\s*$", text, re.M)) == 1
        assert not re.search(r"^HELPER_SYNTHESIS_FAIL\b", text, re.M)
        counts["synthesis"] += 1

    for task, contract in contracts.items():
        inputs = ROOT / "inputs" / task
        provenance = spec["prompt_provenance"][task]
        original = (inputs / "prompt.original.txt").read_bytes()
        assert sha(inputs / "prompt.original.txt") == provenance["original_prompt_sha256"]
        assert sha(inputs / "prompt.txt") == provenance["corrected_prompt_sha256"]
        text = original.decode()
        pat = re.compile(r"(?m)^Module name:[ \t]*(?:\r?\n[ \t]*)?(TopModule|adder_16bit|adder_32bit)[ \t]*(?:\r?\n|$)")
        matches = list(pat.finditer(text))
        if task == "barrel_shifter":
            assert len(matches) == 1 and (inputs / "prompt.txt").read_bytes() == original
        else:
            assert len(matches) == 2
            corrected = text[:matches[0].start()] + "Module name: TopModule\n" + text[matches[0].end():matches[1].start()] + text[matches[1].end():]
            assert (inputs / "prompt.txt").read_bytes() == corrected.encode()
        for name in ["positive"] + contract["negative_controls"]:
            p = probe(RAW / "results/controls" / task / name, inputs / (name + ".sv"), task, s["controls"][task][name])
            assert p["checks"] == contract["checks"] and p["status"] == ("pass" if name == "positive" else "fail")
            if name != "positive":
                assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0
        synthesis(RAW / "results/control_synthesis" / task, inputs / "positive.sv", s["control_synthesis"][task])
        folder = RAW / "results/format_sources" / task
        text = (inputs / "positive.sv").read_text(encoding="utf-8")
        a = baseline.extract(text, "rtl")
        b, receipt = bundle.extract_bundle(text, baseline, lexical._strip_noncode)
        assert (folder / "A.sv").read_bytes() == a.encode()
        assert (folder / "B.sv").read_bytes() == b.encode() == (inputs / "positive.sv").read_bytes()
        record = s["format_controls"][task]
        assert read(folder / "receipt.json") == record["receipt"] == receipt and receipt["changed"]
        assert record["B_reused_positive_exact_bytes"] and record["B"] == s["controls"][task]["positive"]
        assert record["B_synthesis"] == s["control_synthesis"][task]
        p = probe(RAW / "results/format_probes" / task / "A", folder / "A.sv", task, record["A"])
        assert p["status"] == "fail"
    generation = read(RAW / "results/generation_complete.json")
    assert generation["grading_started"] is False and len(generation["rows"]) == 3
    assert all("grades" not in row for row in generation["rows"])
    events = [json.loads(line) for line in (RAW / "guard/stage.log").read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    assert [e.get("phase") for e in events if e.get("phase")] == ["preflight_verified"] + ["generated"] * 3 + ["graded"] * 3
    assert [(r["task"], r["trial"]) for r in s["rows"]] == [tuple(x) for x in spec["generation_order"]]
    ids, rows, answers = set(), [], set()
    for i, row in enumerate(s["rows"]):
        assert {k:v for k,v in row.items() if k != "grades"} == generation["rows"][i]
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
        answers.add(sha(folder / "answer.txt"))
        a = baseline.extract(answer, "rtl")
        b, receipt = bundle.extract_bundle(answer, baseline, lexical._strip_noncode)
        assert (folder / "A.sv").read_bytes() == a.encode() and (folder / "B.sv").read_bytes() == b.encode()
        assert read(folder / "bundle_receipt.json") == row["bundle_receipt"] == receipt and receipt["changed"] == row["bundle_changed"]
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
        rows.append(dict(task=task, trial=int(trial), A=row["grades"]["A"]["probe"]["status"], B=row["grades"]["B"]["probe"]["status"], A_failure=row["grades"]["A"]["probe"]["failure_kind"], B_failure=row["grades"]["B"]["probe"]["failure_kind"], checks=contracts[task]["checks"], full_input_domain_exhaustive=contracts[task]["domain"]["full_input_domain_exhaustive"], changed=receipt["changed"], reason=receipt["reason"], modules=receipt["modules"], A_sha256=row["A_sha256"], B_sha256=row["B_sha256"], request_elapsed_s=row["request_elapsed_s"]))
    assert counts["probes"] == 18
    for row in rows:
        original = next(r for r in s["rows"] if r["task"] == row["task"])
        for arm in ("A", "B"):
            p = original["grades"][arm]["probe"]
            row[arm + "_checks"] = p["checks"]
            row[arm + "_mismatches"] = p["mismatches"]
        folder = RAW / "results/generated_probes" / row["task"] / str(row["trial"]) / "B"
        row["B_bounds_warning_count"] = sum(len(re.findall(r"^WARNING:.*out of bounds.*$", p.read_text(encoding="utf-8"), re.M)) for p in folder.glob("*.log"))
    fixes = sum(r["A"] == "fail" and r["B"] == "pass" for r in rows)
    regressions = sum(r["A"] == "pass" and r["B"] == "fail" for r in rows)
    postflight = read(RAW / "postflight.json")
    assert postflight["model_health"]["status"] == "ok" and not postflight["own_slot_exists"]
    result = dict(schema="helper_three_contract_audit_v1", status="complete_verified", model_requests=3, complete_responses=3, retries=0, paired_generated_probes=6, A_passes=sum(r["A"] == "pass" for r in rows), B_passes=sum(r["B"] == "pass" for r in rows), fixes=fixes, regressions=regressions, changed_responses=sum(r["changed"] for r in rows), acceptance_met=fixes>0 and regressions==0, adoption=False, new_score=False, controls_valid=9, positive_synthesized=3, constructed_format_controls=3, unique_answer_texts=len(answers), counts=counts, rows=rows, domains={c["task"]:c["domain"] for c in spec["contracts"]}, elapsed_s=s["elapsed_s"], model_request_elapsed_s=sum(r["request_elapsed_s"] for r in rows), guard={k:g[k] for k in ("started_at_utc","finished_at_utc","elapsed_s","stage_rc","model_unchanged","protected_files_unchanged","own_slot_released","model_idle_after")}, owned_cleanup_verified=True, remaining_owned_processes=0, evidence=dict(archive_sha256=archive["sha256"],manifest_files=len(manifest["files"]),all_hashes_verified=True), postflight=postflight, branch=read(RAW / "launch.json")["branch"], limits=spec["limits"])
    result.update(natural_A_pass_guard_count=sum(r["A"]=="pass" for r in rows), zero_regressions_does_not_validate_correct_candidate_protection=True)
    (ROOT / "RESULTS.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({k:result[k] for k in ("status","A_passes","B_passes","fixes","regressions","changed_responses","acceptance_met","counts","evidence")}))


if __name__ == "__main__":
    main()
