"""Grade every available response of a stopped pilot; never regenerate."""
import argparse
import ctypes
import json
from pathlib import Path

from timing_pilot import JUDGE_SHA, PAIR_SHA, load, save, sha
from complete_module_extract import extract_complete


def main():
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError("cannot enable owned descendant reaping")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "inputs", "kit", "resource-check", "original", "out", "judge-adapter", "prior-audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    inputs, out, kit = args.inputs.resolve(), args.out.resolve(), args.kit.resolve()
    original_path = args.original / "summary.json"
    original = json.loads(original_path.read_text(encoding="utf-8"))
    if original["complete"] or original["client_attempts"] != 13 or original["responses_received"] != 12 or original.get("error") != "TimeoutError: timed out":
        raise RuntimeError("this audit admits only the preserved single stopped pilot")
    pair_path = args.source / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py"
    if sha(pair_path) != PAIR_SHA or sha(args.judge_adapter) != JUDGE_SHA:
        raise RuntimeError("evaluation adapter changed")
    paired = load("timing_partial_oracle", pair_path)
    paired.frozen()
    paired.check_resource(args.resource_check, kit, first=True)
    for path, digest in original["snapshot_before"].items():
        if sha(path) != digest:
            raise RuntimeError("original frozen input changed: " + path)
    rows = [dict(row) for row in original["rows"] if row.get("response_received") and "solution_sha256" in row]
    expected = {"Prob045_edgedetect2", "Prob054_edgedetect", "Prob129_ece241_2013_q8"}
    if len(rows) != 12 or {row["task"] for row in rows} != expected:
        raise RuntimeError("completed subset changed")
    for task in expected:
        if {row["label"] for row in rows if row["task"] == task} != {"C0", "C1", "D0", "D1"} or not original["controls"][task]["valid"]:
            raise RuntimeError("subset labels or controls invalid")
    assets = dict(original["snapshot_before"])
    assets.update({str(original_path): sha(original_path), str(Path(__file__)): sha(__file__),
                   str(Path(__file__).with_name("complete_module_extract.py")): sha(Path(__file__).with_name("complete_module_extract.py"))})
    prior_path = args.prior_audit / "summary.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    if prior.get("error") != "RuntimeError: official environment/tool failure: Prob129_ece241_2013_q8":
        raise RuntimeError("unexpected environment recovery source")
    assets[str(prior_path)] = sha(prior_path)
    for row in rows:
        folder = Path(row["solution"]).parent
        for filename, key in (("request.json", "request_sha256"), ("response.json", "response_sha256"), ("solution.v", "solution_sha256")):
            if sha(folder / filename) != row[key]:
                raise RuntimeError("available response changed")
            assets[str(folder / filename)] = row[key]
        assets[str(folder / "answer.txt")] = sha(folder / "answer.txt")
    out.mkdir(parents=True, exist_ok=False)
    report = dict(schema="interrupted_timing_pilot_offline_audit_v1", complete=False, verified=False,
                  original_pilot_complete=False, eligible_for_original_pilot_acceptance=False,
                  real_model_calls=0, additional_generation=0, original_summary_sha256=sha(original_path),
                  snapshot_before=assets, originals={}, rows=rows, missing_moore_guard=True,
                  deployment_approved=False, limits=["all 12 available outputs before timeout; not the planned 16-response pilot",
                                                    "two known development errors and one known Mealy guard only",
                                                    "no complete-pilot, independent generalization, release or end-to-end claim"])
    evaluator = load("timing_partial_official", args.judge_adapter)
    evaluator.ROOT, evaluator.OFFICIAL = kit, kit / "official_reference"
    report["official_commit"] = evaluator.verify_upstream()
    baseline = load("timing_extraction_baseline", paired.PACKAGE / "baseline.py")
    lexer = load("timing_extraction_lexer", paired.PACKAGE / "agent/signedness_selector.py")
    # Freeze all alternate extractions before grading. Never choose by an oracle outcome.
    for row in rows:
        answer = Path(row["solution"]).with_name("answer.txt").read_text(encoding="utf-8")
        alternative, transformation = extract_complete(answer, baseline, lexer._strip_noncode)
        if transformation["original_sha256"] != row["solution_sha256"]:
            raise RuntimeError("baseline extraction cannot be reproduced")
        destination = out / "extracted" / row["task"] / row["label"] / "solution.v"
        destination.parent.mkdir(parents=True)
        destination.write_text(alternative, encoding="utf-8", newline="\n")
        row.update(extraction=transformation, extracted_solution=str(destination))
    report["extraction"] = dict(policy="only one complete fenced TopModule; ambiguous answers preserve official extraction",
                                 model_calls=0, frozen_before_grading=True, changed=sum(row["extraction"]["changed"] for row in rows))
    save(out / "extractions_frozen.json", report)

    def frozen():
        if any(sha(path) != digest for path, digest in assets.items()):
            raise RuntimeError("frozen inputs changed")
        paired.check_resource(args.resource_check, kit)

    def official(task, solution, destination):
        frozen()
        destination.mkdir(parents=True)
        verdict = evaluator.judge_sample(kit / "bench/tasks_veval" / task, solution, destination, destination / "verdict.json", 120)
        if verdict.get("tool_error") or verdict.get("suspected_silent_degradation"):
            raise RuntimeError("official environment/tool failure: " + task)
        return verdict

    try:
        for task in sorted(expected):
            wanted = 3 if task == "Prob129_ece241_2013_q8" else 1
            if task in prior["originals"]:
                result = dict(prior["originals"][task])
                if not result.get("judge_evidence_complete") or result.get("tool_error"):
                    raise RuntimeError("invalid prior original evidence")
                result["prior_valid_verdict_reused"] = True
            else:
                result = official(task, inputs / task / "candidate.sv", out / "official_originals" / task)
            if result["level"] != wanted:
                raise RuntimeError("original role contradicted")
            report["originals"][task] = result
        for row in rows:
            frozen()
            contract = json.loads((inputs / row["task"] / "contract.json").read_text(encoding="utf-8"))
            task = dict(task=row["task"], checks=contract["checks"], tb=str(inputs / row["task"] / "tb.sv"))
            row["probe"] = paired.oracle(task, Path(row["solution"]), out / "probes" / row["task"] / row["label"])
            if row["probe"]["status"] == "environment_error":
                raise RuntimeError("probe environment failure")
            row["official"] = official(row["task"], Path(row["solution"]), out / "official_generated" / row["task"] / row["label"])
            if row["extraction"]["changed"]:
                row["extracted_probe"] = paired.oracle(task, Path(row["extracted_solution"]), out / "extracted_probes" / row["task"] / row["label"])
                if row["extracted_probe"]["status"] == "environment_error":
                    raise RuntimeError("extracted probe environment failure")
                row["extracted_official"] = official(row["task"], Path(row["extracted_solution"]), out / "official_extracted" / row["task"] / row["label"])
            else:
                row.update(extracted_probe=row["probe"], extracted_official=row["official"], byte_identical_result_reused=True)
            print(json.dumps(dict(task=row["task"], label=row["label"], probe=row["probe"]["status"], official=row["official"]["level"])), flush=True)
        report["complete"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    report["snapshot_after"] = {path: sha(path) for path in assets}
    report["inputs_unchanged"] = assets == report["snapshot_after"]
    report["verified"] = report["complete"] and report["inputs_unchanged"]
    report["arms"] = {}
    for arm in ("C", "D"):
        group = [row for row in rows if row["label"].startswith(arm)]
        report["arms"][arm] = dict(rows=len(group), repairs=sum(row.get("official", {}).get("level") == 3 and row["role"] == "development_error" for row in group),
            guard_regressions=sum(row.get("official", {}).get("level", 3) < 3 and row["role"] == "correct_guard" for row in group),
            probe_passes=sum(row.get("probe", {}).get("status") == "pass" for row in group),
            request_elapsed_s=sum(row["request_elapsed_s"] for row in group))
    report["extraction"].update(
        official_repairs=sum(row.get("extracted_official", {}).get("level") == 3 and row.get("official", {}).get("level") != 3 for row in rows),
        official_regressions=sum(row.get("extracted_official", {}).get("level", 3) < row.get("official", {}).get("level", 0) for row in rows))
    save(out / "summary.json", report)
    print(json.dumps({key: report.get(key) for key in ("complete", "verified", "arms", "error")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
