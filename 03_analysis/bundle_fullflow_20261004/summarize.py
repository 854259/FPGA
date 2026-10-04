"""Reconstruct full worker replay identity, requests, extraction, grades and cost."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"
sys.path.insert(0, str(ROOT))
from extract_bundle import extract_bundle
from guarded_bundle import decide


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def main():
    archive = read(ROOT / "ARCHIVE.json")
    assert sha(ROOT / "evidence.zip") == archive["sha256"]
    manifest = read(RAW / "MANIFEST.json")
    for row in manifest["files"]:
        p = (RAW / row["path"]).resolve()
        assert p.is_relative_to(RAW.resolve()) and sha(p) == row["sha256"]
        assert p.stat().st_size == row["bytes"]
    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for n, h in spec["source_hashes"].items():
        assert sha(ROOT / n) == sha(RAW / n) == h, n
    for n, h in spec["dependency_hashes"].items():
        assert sha(RAW / "dependency_snapshot" / n) == h
    assert sha(ROOT / "package/agent/runtime.py") == "22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7"
    g, s = read(RAW / "guard/status.json"), read(RAW / "results/summary.json")
    assert g["complete"] and g["passed"] and g["stage_rc"] == 0
    assert g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
    assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    assert g["model_idle_after"]["processing_slots"] == 0
    assert s["complete"] and s["verified"] and s["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    baseline = load("flow_audit_baseline", ROOT / "package/baseline.py")
    lexical = load("flow_audit_lexical", ROOT / "lexical_mask.py")
    runtime = load("flow_audit_runtime", ROOT / "package/agent/runtime.py")
    skill = (ROOT / "package/skill/rtl-generation/SKILL.md").read_text(encoding="utf-8")
    repair = (ROOT / "package/skill/rtl-feedback-repair/SKILL.md").read_text(encoding="utf-8")
    count, live_count, gate_count, gate_elapsed = 0, 0, 0, 0.0
    live_ids, first_requests, rows = [], {}, []
    live_contents, live_payloads = {}, {}

    def stage_check(stage, folder):
        log = folder / Path(stage["log"]).name
        assert sha(log) == stage["log_sha256"] and log.stat().st_size == stage["log_bytes"]
        assert not stage["timeout"] and not stage["launch_error"] and not stage["remaining_live_group"]

    def probe_check(p, folder, source, task):
        nonlocal count
        result, receipt = read(folder / "result.json"), read(folder / "adapter_receipt.json")
        assert receipt == p and all(receipt[k] == v for k, v in result.items())
        assert p["inherited_result_sha256"] == sha(folder / "result.json")
        assert p["inherited_runner_sha256"] == spec["dependency_hashes"]["probe_runner.py"]
        assert p["oracle_adapter_sha256"] == spec["dependency_hashes"]["paired_checkpoint.py"]
        assert p["solution_sha256"] == sha(source) == sha(folder / "dut.sv")
        assert p["tb_sha256"] == sha(ROOT / "inputs" / task / "tb.sv") == sha(folder / "tb.sv")
        assert p["inputs_unchanged"] and p["status"] in ("pass", "fail")
        for stage in p["stages"]:
            stage_check(stage, folder)
        if p["checks"] is not None:
            assert p["checks"] == spec["checks"][task]
            markers = re.findall(r"^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$",
                (folder / "xsim.log").read_text(encoding="utf-8"), re.M)
            assert markers == [(task, str(p["checks"]), str(p["mismatches"]))]
        if p["status"] == "pass":
            assert p["mismatches"] == 0 and p["checks"] == spec["checks"][task]
        count += 1

    for task, controls in s["controls"].items():
        for name, p in controls.items():
            probe_check(p, RAW / "results/controls" / task / name,
                        ROOT / "inputs" / task / (name + ".sv"), task)
            assert p["status"] == ("pass" if name == "positive" else "fail")
            if name == "negative":
                assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0
    assert read(RAW / "results/workers_complete.json")["grading_started"] is False
    assert [(r["task"], r["arm"]) for r in s["rows"]] == [tuple(x) for x in spec["order"]]
    for row in s["rows"]:
        task, arm = row["task"], row["arm"]
        folder = RAW / "results/workers" / task / arm
        worker = read(folder / "worker_result.json")
        assert worker == row["worker"] and worker["complete"] and worker["arm"] == arm
        stage_check(row["supervisor"], folder.parent)
        assert row["supervisor"]["returncode"] == 0
        assert sha(folder / "solution.v") == row["solution_sha256"]
        assert (folder / "prompt_only/prompt.txt").read_bytes() == (ROOT / "inputs" / task / "prompt.txt").read_bytes()
        assert [p.name for p in (folder / "prompt_only").iterdir()] == ["prompt.txt"]
        events = [json.loads(x) for x in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        assert not any(e.get("error") for e in events)
        meta = [e for e in events if e["tool"] == "agent_meta"]
        assert len(meta) == 1 and meta[0]["repairs"] == 1
        assert meta[0]["skill_sha256"] == hashlib.sha256(skill.encode()).hexdigest()
        assert meta[0]["repair_skill_sha256"] == hashlib.sha256(repair.encode()).hexdigest()
        journal, extraction = read(folder / "requests.json"), read(folder / "extraction.json")
        assert worker["extraction"] == extraction
        assert len(journal) == len(extraction) == worker["requests"]
        assert worker["replayed_requests"] == 1 and worker["actual_model_requests"] == len(journal) - 1
        llms = [e for e in events if e["tool"] == "llm"]
        starts = [e for e in events if e["tool"] == "llm_start"]
        assert [e["round"] for e in llms] == [e["round"] for e in starts] == list(range(len(journal)))
        codes, live_elapsed = [], 0.0
        for index, entry in enumerate(journal):
            rq = folder / "requests" / str(index)
            payload, response = read(rq / "request.json"), read(rq / "response.json")
            assert entry["index"] == index and entry["replayed"] == (index == 0) and entry["response_received"]
            assert payload["model"] == spec["model"] and payload["temperature"] == 0
            assert payload["top_p"] == 1 and payload["max_tokens"] == 8192
            assert payload["messages"][0] == dict(role="system", content=skill + ("\n" + repair if index else ""))
            prompt = (ROOT / "inputs" / task / "prompt.txt").read_text(encoding="utf-8")
            if index == 0:
                assert payload["messages"][1] == dict(role="user", content=prompt)
                assert (rq / "response.json").read_bytes() == (ROOT / "inputs" / task / "initial_response.json").read_bytes()
                if task in first_requests:
                    assert payload == first_requests[task]
                else:
                    first_requests[task] = payload
            else:
                # Find the original worker's last diagnostic before round1.
                before = events[:events.index(starts[index])]
                diagnostics = [e for e in before if e["tool"] in ("check_source", "check_submodules", "lint")]
                assert diagnostics
                expected = prompt + "\nPrevious candidate:\n" + codes[index - 1] + "\nCandidate diagnostics:\n" + diagnostics[-1]["excerpt"]
                assert payload["messages"][1] == dict(role="user", content=expected)
                live_count += 1
                live_ids.append(response.get("id"))
                live_payloads[task, arm] = payload
                live_contents[task, arm] = response["choices"][0]["message"]["content"]
                live_elapsed += entry["elapsed_s"]
            choice = response["choices"][0]
            assert choice["finish_reason"] == entry["finish_reason"] == llms[index]["finish"] == "stop"
            assert response.get("id") == entry["response_id"]
            usage = response.get("usage") or {}
            assert llms[index]["tokens_in"] == usage.get("prompt_tokens")
            assert llms[index]["tokens_out"] == usage.get("completion_tokens")
            text = choice["message"]["content"]
            if arm == "A":
                code, receipt = baseline.extract(text, "rtl"), dict(decision="original_baseline")
            else:
                recorded = extraction[index].get("stages", [])
                gate_folder = folder / ("candidate_gate_" + str(index))
                b, _ = extract_bundle(text, baseline, lexical._strip_noncode)
                for stage in recorded:
                    stage_check(stage, gate_folder)
                gate_count += len(recorded)
                gate_elapsed += sum(x["elapsed_s"] for x in recorded)

                class Replay:
                    cursor = 0

                    def owned_command(self, argv, cwd, log, seconds):
                        result = dict(recorded[self.cursor])
                        self.cursor += 1
                        assert argv[0].replace("\\", "/") == result["argv"][0]
                        assert argv[1:] == result["argv"][1:] and seconds == 60
                        assert (Path(cwd) / "dut.sv").read_text(encoding="utf-8") == b
                        Path(log).write_bytes((gate_folder / Path(result["log"]).name).read_bytes())
                        result.pop("name")
                        result.pop("argv")
                        return result

                replay = Replay()
                with tempfile.TemporaryDirectory() as temporary:
                    code, receipt = decide(text, baseline, lexical._strip_noncode, replay,
                        Path(temporary) / "gate", "/workspace/AMD/2026.1/Vivado/bin")
                for stage in receipt.get("stages", []):
                    stage["argv"][0] = stage["argv"][0].replace("\\", "/")
                assert replay.cursor == len(recorded)
            assert receipt == extraction[index]
            assert (folder / ("extracted_" + str(index) + ".sv")).read_text(encoding="utf-8") == code
            codes.append(code)
        expected_final = codes[-1]
        fixes = [e for e in events if e["tool"] == "declaration_fix"]
        if fixes:
            assert len(fixes) == 1 and fixes[0]["rc"] == 0
            lint = [e for e in events if e["tool"] == "lint"][-1]
            expected_final = runtime.repair_ansi_declarations(expected_final, lint["excerpt"])
        assert (folder / "solution.v").read_text(encoding="utf-8") == expected_final
        probe_check(row["probe"], RAW / "results/probes" / task / arm, folder / "solution.v", task)
        rows.append(dict(task=task, arm=arm, status=row["probe"]["status"],
            failure_kind=row["probe"]["failure_kind"], checks=row["probe"]["checks"],
            mismatches=row["probe"]["mismatches"], actual_model_requests=worker["actual_model_requests"],
            replayed_requests=1, worker_elapsed_s=worker["elapsed_s"], model_request_elapsed_s=live_elapsed,
            final_sha256=row["solution_sha256"], extraction_decisions=[x["decision"] for x in extraction]))
    assert count == s["actual_probes"] == 12
    assert live_count == s["actual_model_requests"] <= spec["max_actual_model_requests"]
    assert all(live_ids) and len(live_ids) == len(set(live_ids))
    assert s["replayed_requests"] == 6
    totals = {}
    for arm in ("A", "C"):
        subset = [r for r in rows if r["arm"] == arm]
        totals[arm] = dict(passes=sum(r["status"] == "pass" for r in subset),
            actual_model_requests=sum(r["actual_model_requests"] for r in subset),
            worker_elapsed_s=sum(r["worker_elapsed_s"] for r in subset),
            model_request_elapsed_s=sum(r["model_request_elapsed_s"] for r in subset))
    by = {(r["task"], r["arm"]):r for r in rows}
    regressions = sum(by[t, "A"]["status"] == "pass" and by[t, "C"]["status"] == "fail" for t in spec["checks"])
    fixes = sum(by[t, "A"]["status"] == "fail" and by[t, "C"]["status"] == "pass" for t in spec["checks"])
    equal_quality_cost_gain = totals["C"]["passes"] == totals["A"]["passes"] and totals["C"]["actual_model_requests"] < totals["A"]["actual_model_requests"] and totals["C"]["worker_elapsed_s"] < totals["A"]["worker_elapsed_s"]
    accepted = regressions == 0 and (totals["C"]["passes"] > totals["A"]["passes"] or equal_quality_cost_gain)
    result = dict(schema="bundle_fullflow_audit_v1", status="complete_verified", groups=totals,
        regressions=regressions, fixes=fixes, acceptance_met=accepted, adoption=False, new_score=False,
        actual_model_requests=live_count, replayed_initial_responses=6, unique_initial_responses=3,
        live_unique_answer_texts=len(set(live_contents.values())),
        live_request_pairs_identical=[t for t in spec["checks"] if (t, "A") in live_payloads and (t, "C") in live_payloads and live_payloads[t, "A"] == live_payloads[t, "C"]],
        live_response_content_pairs_identical=[t for t in spec["checks"] if (t, "A") in live_contents and (t, "C") in live_contents and live_contents[t, "A"] == live_contents[t, "C"]],
        original_final_correct_guard_count=totals["A"]["passes"],
        actual_probes=count, controls_valid=6, candidate_gate_commands=gate_count,
        candidate_gate_elapsed_s=gate_elapsed, synthesis_calls=0, rows=rows, elapsed_s=s["elapsed_s"],
        independent_natural_validation=False, production_initial_generation_measured=False,
        guard={k:g[k] for k in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "own_slot_released", "model_idle_after")},
        evidence=dict(sha256=archive["sha256"], files=len(manifest["files"]), all_hashes_verified=True),
        postflight=read(RAW / "postflight.json"), limits=spec["limits"])
    (ROOT / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k:result[k] for k in ("status", "groups", "fixes", "regressions", "acceptance_met", "actual_model_requests", "evidence")}))


if __name__ == "__main__":
    main()
