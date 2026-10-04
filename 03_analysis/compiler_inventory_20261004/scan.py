"""Offline cross-task context inventory; all detections are unconfirmed hints."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

from literal_bounds import inspect

ROOT = Path(__file__).resolve().parent


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
    spec, arc = read(ROOT / "RUN_SPEC.json"), read(ROOT / "ARCHIVE.json")
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == digest, name
    assert sha(ROOT / "corpus.zip") == spec["corpus_archive_sha256"]
    assert sha(ROOT / "metadata.zip") == arc["sha256"]
    raw, corpus = ROOT / "raw_evidence", ROOT / "corpus"
    for row in read(raw / "MANIFEST.json")["files"]:
        p = (raw / row["path"]).resolve()
        assert p.is_relative_to(raw.resolve()) and sha(p) == row["sha256"] and p.stat().st_size == row["bytes"]
    assert (raw / "RUN_SPEC.json").read_bytes() == (ROOT / "RUN_SPEC.json").read_bytes()
    pairs = read(corpus / "PAIR_MANIFEST.json")
    assert sha(corpus / "PAIR_MANIFEST.json") == spec["pair_manifest_sha256"]
    collection = read(raw / "COLLECTION.json")
    assert collection["model_calls"] == collection["eda_calls"] == 0 and collection["archived_source_unchanged"]
    metadata = {(r["dataset"], r["side"], r["task"]): r for r in collection["rows"]}
    lexical, runtime = load("inventory_lexical", ROOT / "lexical_mask.py"), load("inventory_runtime", ROOT / "runtime_snapshot.py")
    rows = []
    for pair in pairs["pairs"]:
        key = tuple(pair[k] for k in ("dataset", "side", "task"))
        context = metadata[key]
        assert context["source_sha256"] == pair["source_sha256"] and context["prompt_sha256"] == pair["prompt_sha256"]
        source, prompt = corpus / pair["source"], corpus / pair["prompt"]
        assert sha(source) == pair["source_sha256"] and sha(prompt) == pair["prompt_sha256"]
        before = sha(source)
        text = source.read_text(encoding="utf-8")
        bounds = inspect(text, lexical._strip_noncode)
        assert bounds == inspect(text, lexical._strip_noncode)
        missing = runtime.undefined_submodules(text)
        assert missing == runtime.undefined_submodules(text) and sha(source) == before
        folder = raw / context["metadata"]
        verdict = read(folder / "verdict.json")
        assert verdict["task_id"] == pair["task"]
        ds = raw / "metadata" / pair["dataset"]
        assert sha(ds / "experiment.json") == pairs["datasets"][pair["dataset"]]["experiment_sha256"]
        summary = read(ds / "graded_summary.json")
        taskrow = next(t for t in summary["modes"][pair["side"]]["per_task"] if t["task_id"] == pair["task"])
        if taskrow["scored_samples"]:
            assert taskrow["levels"] == [verdict["level"]]
        traces = []
        if (folder / "trace.jsonl").exists():
            traces = [json.loads(line) for line in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        last_lint = next((t for t in reversed(traces) if t.get("tool") == "lint"), None)
        nonempty_logs = sum(r["bytes"] > 0 for r in context["judge_logs"])
        rows.append({k: pair[k] for k in ("dataset", "side", "task", "prompt_sha256", "source_sha256")} | dict(bounds=bounds, runtime_missing_modules=missing, historical_level=verdict.get("level"), historical_tool_error=verdict.get("tool_error"), historical_compile=verdict.get("stages", {}).get("compile"), judge_log_count=len(context["judge_logs"]), nonempty_judge_logs=nonempty_logs, last_lint_rc=last_lint.get("rc") if last_lint else None, trace_candidate_hash_bound=False, known_development_task=pair["task"] in spec["known_development_tasks"]))
    assert len(rows) == len(metadata) == spec["expected_records"]
    flagged = [r for r in rows if r["bounds"]["hints"] or r["runtime_missing_modules"]]
    gaps = [r for r in rows if r["side"] == "agent" and r["historical_level"] == 0 and not r["historical_tool_error"] and r["last_lint_rc"] == 0 and not r["runtime_missing_modules"]]
    bounds_rows = [r for r in rows if r["bounds"]["hints"]]
    compact = lambda r: {k: r[k] for k in ("dataset", "side", "task", "source_sha256", "historical_level", "last_lint_rc", "known_development_task")} | dict(hints=r["bounds"]["hints"], missing_modules=r["runtime_missing_modules"])
    result = dict(schema="compiler_source_context_inventory_v1", status="complete_verified_readonly_inventory", records=len(rows), unique_prompt_source_pairs=len({(r["prompt_sha256"], r["source_sha256"]) for r in rows}), bounds_hint_records=len(bounds_rows), bounds_hint_tasks=sorted({r["task"] for r in bounds_rows}), independent_bounds_hint_tasks=sorted({r["task"] for r in bounds_rows if not r["known_development_task"]}), missing_module_hint_records=sum(bool(r["runtime_missing_modules"]) for r in rows), missing_module_hint_tasks=sorted({r["task"] for r in rows if r["runtime_missing_modules"]}), flagged_records=len(flagged), bounds_scan_statuses=dict(Counter(r["bounds"]["status"] for r in rows)), numeric_internal_declarations=sum(r["bounds"]["declarations"] for r in rows), skipped_scopes=sum(r["bounds"]["skipped_scopes"] for r in rows), historical_agent_compile_gap_records=len(gaps), historical_agent_compile_gap_tasks=sorted({r["task"] for r in gaps}), judge_log_files=sum(r["judge_log_count"] for r in rows), nonempty_judge_log_files=sum(r["nonempty_judge_logs"] for r in rows), hint_rows=[compact(r) for r in flagged], compile_gap_rows=[compact(r) for r in gaps], model_calls=0, eda_calls=0, new_compiler_diagnostics_confirmed=0, new_functional_verdicts=0, adoption=False, new_score=False, runtime_sha256=sha(ROOT / "runtime_snapshot.py"), corpus_archive_sha256=sha(ROOT / "corpus.zip"), metadata_archive_sha256=sha(ROOT / "metadata.zip"), limits=spec["limits"])
    (ROOT / "raw_evidence/SCAN.json").write_text(json.dumps(dict(rows=rows, result=result), indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("status", "records", "unique_prompt_source_pairs", "bounds_hint_records", "bounds_hint_tasks", "independent_bounds_hint_tasks", "missing_module_hint_records", "historical_agent_compile_gap_records", "historical_agent_compile_gap_tasks", "nonempty_judge_log_files")}))


if __name__ == "__main__":
    main()
