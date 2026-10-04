"""Audit downloaded evidence; does not connect to cloud, model, or Vivado."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"
ARCHIVE_SHA = "1a35e0fcd70f7c9c846f7ec80db0cb3abf234d17647be4de10fd2a9be05cee18"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(data):
    return data.get("structuredContent") or json.loads(data["content"][0]["text"])


def main():
    assert sha(ROOT / "evidence.zip") == ARCHIVE_SHA
    manifest = read(RAW / "MANIFEST.json")
    for row in manifest["files"]:
        p = (RAW / row["path"]).resolve()
        assert p.is_relative_to(RAW.resolve())
        assert p.stat().st_size == row["bytes"] and sha(p) == row["sha256"]
    spec = read(ROOT / "RUN_SPEC.json")
    assert (ROOT / "RUN_SPEC.json").read_bytes() == (RAW / "RUN_SPEC.json").read_bytes()
    for f, h in spec["source_hashes"].items():
        assert sha(ROOT / f) == h and sha(RAW / f) == h
    assert sha(RAW / "resource_guard_executed.py") == spec["resource_guard_sha256"]
    sources = read(ROOT / "SOURCES.json")
    assert (ROOT / "SOURCES.json").read_bytes() == (RAW / "SOURCES.json").read_bytes()
    for f, row in sources["files"].items():
        p = ROOT.parent / "ross_probe_20261004" / "expert_sources" / f.replace("\\", "/")
        assert p.stat().st_size == row["bytes"] and sha(p) == row["sha256"]
    summary = read(RAW / "results/summary.json")
    guard = read(RAW / "guard/status.json")
    assert summary["complete"] and summary["passed"] and summary["model_calls"] == 0
    assert summary["server_exit_code"] == 0 and not summary["full_skill_model_execution"]
    for k in ("complete", "passed", "model_unchanged", "protected_files_unchanged", "own_slot_released"):
        assert guard[k]
    assert guard["owned_cleanup"]["verified"] and not guard["owned_cleanup"]["remaining"]
    rpc = [json.loads(line) for line in (RAW / "results/rpc.jsonl").read_text(encoding="utf-8").splitlines()]
    requests = [r["message"] for r in rpc if r["direction"] == "client" and r["message"].get("method") == "tools/call"]
    assert len(requests) == summary["tool_calls"] == 22
    starts = [r for r in requests if r["params"]["name"] == "vivado_start"]
    stops = [r["params"]["arguments"]["session_id"] for r in requests if r["params"]["name"] == "vivado_stop"]
    assert len(starts) == 2 and stops == summary["closed_sessions"] and len(set(stops)) == 2
    actual_starts = [unpack(read(RAW / "results" / f)) for f in ("01_vivado_start.json", "12_vivado_start.json")]
    assert [r["session_id"] for r in actual_starts] == stops
    for f in ("02_vivado_execute.json", "13_vivado_execute.json"):
        assert unpack(read(RAW / "results" / f))["output"] == "PROBE_VERSION:2026.1"
    transcript_snapshots = []
    for row in summary["rows"]:
        p = RAW / row["transcript_path"]
        # close_sim appends memory/CPU statistics after the runner's observation.
        # Preserve its original hash and prove the exact observed prefix survives.
        data = p.read_bytes()
        offsets = [0]
        for line in data.splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        matching = [n for n in offsets if hashlib.sha256(data[:n]).hexdigest() == row["transcript_sha256"]]
        assert len(matching) == 1
        suffix = data[matching[0]:].decode("utf-8")
        assert suffix.startswith("INFO: xsimkernel Simulation Memory Usage:")
        assert "TEST_FAIL" not in suffix and "TEST_PASS" not in suffix
        transcript_snapshots.append({"case": row["case"], "observed_prefix_bytes": matching[0], "observed_prefix_sha256": row["transcript_sha256"], "final_file_bytes": len(data), "final_file_sha256": sha(p), "appended_at_close": "xsimkernel memory/CPU usage statistics"})
        text = p.read_text(encoding="utf-8")
        vcd = RAW / "results" / row["case"] / "trace.vcd"
        assert sha(vcd) == row["vcd_sha256"] and vcd.stat().st_size == row["vcd_bytes"]
        assert "$enddefinitions" in vcd.read_text(encoding="utf-8")
        assert row["verdict"] == row["expected_verdict"]
        assert row["launch_tcl_exit_code"] == row["run_tcl_exit_code"] == 0
        if row["case"] == "correct":
            assert "TEST_PASS checks=5" in text and "TEST_FAIL" not in text
        else:
            assert "TEST_FAIL time=1000 a=1 b=1 expected=2 observed=0" in text
            assert "TEST_PASS" not in text and "Fatal:" in text
    result = {
        "schema": "ross_expert_assessment_v1", "status": "isolated_xsim_verdict_gates_verified",
        "upstream_commit": sources["upstream_commit"], "frozen_spec": "RUN_SPEC.json",
        "cloud_root": manifest["root"], "simulation_probe": summary,
        "transcript_snapshot_audit": transcript_snapshots,
        "guard": {k: guard[k] for k in ("started_at_utc", "finished_at_utc", "elapsed_s", "stage_rc", "model_unchanged", "protected_files_unchanged", "model_idle_after", "own_slot_released")},
        "owned_cleanup_verified": True, "remaining_owned_processes": 0,
        "postflight": read(RAW / "postflight.json"),
        "evidence": {"archive_sha256": ARCHIVE_SHA, "manifest_files": len(manifest["files"]), "hashes_verified": True, "expert_sources_verified": len(sources["files"])},
        "assessment": {
            "rtl_simulation": {"priority": "high", "observed_use": "Complete transcript plus explicit PASS/check-count gates distinguish correct and faulty RTL despite Tcl return code zero", "model_repair_benefit_measured": False},
            "knowledge_base": {"priority": "selective_document_lookup", "runtime_tested": False, "deployed": False, "doc_search_is_separate_mcp": True, "official_local_stack": ["Weaviate", "llama.cpp embedding", "amd-doc-search MCP"], "official_document_download_gb": [3.1, 4.4], "contest_offline_compatibility_verified": False},
            "timing_methodology": {"priority": "later_if_constraints_or_timing_needed", "runtime_tested": False, "functional_spec_equivalence": False},
            "ip_hls_hardware_vitis_ai": {"priority": "low_for_current_rtl_track", "runtime_tested": False}
        },
        "formal_runtime_integrated": False, "formal_package_changed": False, "new_score": False,
        "limitations": spec["limits"] + ["Hand-adapted official workflow; no full model-selected skill execution", "Two synthetic candidates for one tiny contract, not independent competition problems", "Existing project already has verdict gates; no comparative detection or score gain established", "No candidate repair, KB retrieval, timing-methodology execution, or KB latency/resource measurement"]
    }
    (ROOT / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "manifest_files": len(manifest["files"]), "tool_calls": len(requests), "sessions_closed": len(stops), "model_calls": 0}))


if __name__ == "__main__":
    main()
