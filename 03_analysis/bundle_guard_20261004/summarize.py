"""Offline byte, gate and functional receipt reconstruction; no EDA/model."""
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
from guarded_bundle import decide
from extract_bundle import extract_bundle


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
        assert sha(RAW / "dependency_snapshot" / n) == h, n
    g, s = read(RAW / "guard/status.json"), read(RAW / "results/summary.json")
    assert g["complete"] and g["passed"] and g["stage_rc"] == 0
    assert g["model_unchanged"] and g["protected_files_unchanged"] and g["own_slot_released"]
    assert g["owned_cleanup"]["verified"] and not g["owned_cleanup"]["remaining"]
    assert g["model_idle_after"]["processing_slots"] == 0
    assert s["complete"] and s["verified"] and s["expectations_met"]
    assert s["model_calls"] == spec["model_calls"] == 0
    assert s["run_spec_sha256"] == sha(ROOT / "RUN_SPEC.json")
    baseline = load("guard_audit_baseline", RAW / "dependency_snapshot/baseline_extract.py")
    lexical = load("guard_audit_lexical", RAW / "lexical_mask.py")
    probe_count, gate_count = 0, 0

    def stage_check(stage, folder):
        log = folder / Path(stage["log"]).name
        assert sha(log) == stage["log_sha256"] and log.stat().st_size == stage["log_bytes"]
        assert not stage["timeout"] and not stage["launch_error"] and not stage["remaining_live_group"]

    def probe_check(p, folder, source, task):
        nonlocal probe_count
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
        probe_count += 1

    for task, controls in s["controls"].items():
        for name, p in controls.items():
            probe_check(p, RAW / "results/controls" / task / name,
                        ROOT / "inputs" / task / (name + ".sv"), task)
            assert p["status"] == ("pass" if name == "positive" else "fail")
            if name == "negative":
                assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0

    rows = []
    assert len(s["rows"]) == len(spec["cases"]) == 12
    for row, case in zip(s["rows"], spec["cases"]):
        assert row["id"] == case["id"] and row["kind"] == case["kind"] and row["task"] == case["task"]
        folder = RAW / "results/sources" / case["id"]
        text = (ROOT / case["answer"]).read_text(encoding="utf-8")
        a = baseline.extract(text, "rtl")
        b, raw = extract_bundle(text, baseline, lexical._strip_noncode)
        assert raw == row["raw"]
        assert (folder / "A.sv").read_text(encoding="utf-8") == a
        assert (folder / "B.sv").read_text(encoding="utf-8") == b
        gate_folder = RAW / "results/candidate_gates" / case["id"]
        recorded = row["guarded"].get("stages", [])
        for stage in recorded:
            stage_check(stage, gate_folder)
        gate_count += len(recorded)

        class Replay:
            index = 0

            def owned_command(self, argv, cwd, log, seconds):
                result = dict(recorded[self.index])
                self.index += 1
                assert argv[0].replace("\\", "/") == result["argv"][0]
                assert argv[1:] == result["argv"][1:] and seconds == 60
                assert (Path(cwd) / "dut.sv").read_text(encoding="utf-8") == b
                Path(log).write_bytes((gate_folder / Path(result["log"]).name).read_bytes())
                result.pop("name")
                result.pop("argv")
                return result

        replay = Replay()
        with tempfile.TemporaryDirectory() as temporary:
            c, reconstructed = decide(text, baseline, lexical._strip_noncode, replay,
                                      Path(temporary) / "gate", "/workspace/AMD/2026.1/Vivado/bin")
        for stage in reconstructed.get("stages", []):
            stage["argv"][0] = stage["argv"][0].replace("\\", "/")
        assert replay.index == len(recorded) and reconstructed == row["guarded"]
        assert reconstructed["decision"] == case["C_decision"]
        assert (folder / "C.sv").read_text(encoding="utf-8") == c
        assert read(folder / "receipt.json") == dict(raw=raw, guarded=reconstructed)
        for arm in ("A", "B", "C"):
            assert sha(folder / (arm + ".sv")) == row[arm + "_sha256"]
            p = row["probes"][arm]
            probe_check(p, RAW / "results/probes" / case["id"] / arm, folder / (arm + ".sv"), case["task"])
            assert p["status"] == case["expected"][arm]
        rows.append(dict(id=case["id"], task=case["task"], kind=case["kind"],
                         **{arm: row["probes"][arm]["status"] for arm in ("A", "B", "C")},
                         decision=reconstructed["decision"],
                         **{arm + "_mismatches": row["probes"][arm]["mismatches"] for arm in ("A", "B", "C")},
                         A_B_changed=a != b, A_C_changed=a != c,
                         gate_commands=len(recorded)))
    assert probe_count == s["actual_probes"] == 42 and gate_count == s["gate_commands"]
    groups = {}
    for kind in ("constructed_development", "known_natural_development_replay"):
        subset = [r for r in rows if r["kind"] == kind]
        groups[kind] = dict(count=len(subset),
            passes={arm: sum(r[arm] == "pass" for r in subset) for arm in ("A", "B", "C")},
            B_regressions=sum(r["A"] == "pass" and r["B"] == "fail" for r in subset),
            C_regressions=sum(r["A"] == "pass" and r["C"] == "fail" for r in subset),
            original_passes_with_raw_changes=sum(r["A"] == "pass" and r["A_B_changed"] for r in subset))
    result = dict(schema="bundle_guard_audit_v1", status="complete_verified", model_calls=0,
        controls_valid=6, actual_probes=probe_count, candidate_gate_commands=gate_count,
        synthesis_calls=0, groups=groups, rows=rows, elapsed_s=s["elapsed_s"],
        candidate_gate_elapsed_s=sum(x["elapsed_s"] for row in s["rows"] for x in row["guarded"].get("stages", [])),
        guard={k:g[k] for k in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "own_slot_released", "model_idle_after")},
        evidence=dict(sha256=archive["sha256"], manifest_files=len(manifest["files"]), all_hashes_verified=True),
        postflight=read(RAW / "postflight.json"), adoption=False, new_score=False,
        independent_natural_correct_guard_count=0,
        full_flow_or_cost_benefit_verified=False, limits=spec["limits"])
    (ROOT / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8", newline="\n")
    print(json.dumps({k:result[k] for k in ("status", "groups", "actual_probes", "candidate_gate_commands", "evidence")}))


if __name__ == "__main__":
    main()
