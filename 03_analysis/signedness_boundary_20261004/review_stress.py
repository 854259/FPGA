"""Bounded AMD O/C/D correct-candidate stress study; isolated runtime only."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run(args):
    if sys.platform != "linux" or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):
        raise RuntimeError("authorized AMD Linux subreaper required")
    spec = json.loads((HERE / "STRESS_SPEC.json").read_text())
    for name, digest in spec["files"].items():
        if sha(REPO / name) != digest:
            raise RuntimeError("frozen file mismatch: " + name)
    paired = load("stress_pair", REPO / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    boundary = load("stress_materials", HERE / "boundary_validation.py")
    paired.check_resource(args.resource_check, args.kit, first=True)
    package = REPO / "03_analysis/selective_runtime_integration_20261003/package"
    sys.path.insert(0, str(package / "agent"))
    import signedness_selector
    original_analyze = signedness_selector.analyze
    runtime = load("stress_runtime", package / "agent/runtime.py")
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(schema="correct_review_stress_d1", complete=False, valid=False,
                  model_calls=0, responses=0, retries=0, rows=[], controls={}, originals={},
                  runtime_integrated=False, deployment_approved=False, error=None,
                  spec_sha256=sha(HERE / "STRESS_SPEC.json"), source_hashes=spec["files"],
                  previously_observed_other_round_calls=18, new_call_limit=4)
    try:
        case = next(c for c in json.loads((HERE / "cases.json").read_text())["cases"] if c["id"] == "compensated_add9")
        family, tb, positive, negative = boundary.materials(case)
        folder = args.out / "inputs/compensated_add9"
        folder.mkdir(parents=True)
        for name, data in (("candidate.sv",case["source"]),("prompt.txt",case["prompt"]),("tb.sv",tb),("positive.sv",positive),("negative.sv",negative)):
            (folder / name).write_text(data, encoding="utf-8")
        subjects = {"compensated_add9":dict(folder=folder, task=family, checks=48, forced=False)}
        other = REPO / "03_analysis/r2_selectivity_20261003/guards/Prob085_shift4"
        subjects["Prob085_shift4"] = dict(folder=other, task="Prob085_shift4", checks=209, forced=True)
        frozen = {str(p):sha(p) for s in subjects.values() for p in s["folder"].iterdir() if p.is_file()}
        save(args.out / "inputs_frozen.json", dict(files=frozen, runtime_sha256=sha(package / "agent/runtime.py")))

        def probe(subject, path, destination):
            result = paired.oracle(dict(task=subject["task"], checks=subject["checks"], tb=str(subject["folder"] / "tb.sv")), path, destination)
            if result["status"] == "environment_error":
                raise RuntimeError("EDA environment error")
            return result

        for name, subject in subjects.items():
            controls = {kind:probe(subject, subject["folder"]/(kind+".sv"), args.out/"controls"/name/kind) for kind in ("positive","negative")}
            controls["valid"] = controls["positive"]["status"] == "pass" and controls["negative"]["status"] == "fail" and controls["negative"]["failure_kind"] == "semantic_mismatch"
            report["controls"][name] = controls
            if not controls["valid"]:
                raise RuntimeError("invalid oracle controls")
            result = probe(subject, subject["folder"] / "candidate.sv", args.out / "originals" / name)
            report["originals"][name] = result
            if result["status"] != "pass":
                raise RuntimeError("correct guard role not verified: " + name)
        save(args.out / "controls_verified.json", dict(controls=report["controls"], originals=report["originals"], model_calls=0))
        skill, repair_skill = runtime.skill_texts()
        for name, label in spec["order"]:
            paired.check_resource(args.resource_check, args.kit)
            if any(sha(p) != h for p,h in frozen.items()) or any(sha(REPO/p) != h for p,h in spec["files"].items()):
                raise RuntimeError("frozen inputs changed")
            if time.monotonic() - started > 720 or report["model_calls"] >= 4:
                raise RuntimeError("global time or call budget exhausted")
            paired.model_idle("http://127.0.0.1:8000/v1", "Qwen3.6-27B-Q4_K_M")
            subject = subjects[name]
            source = (subject["folder"] / "candidate.sv").read_text()
            prompt = (subject["folder"] / "prompt.txt").read_text()
            normal = original_analyze(prompt, source)
            if (not subject["forced"] and normal["decision"] != "review") or (subject["forced"] and normal["decision"] == "review"):
                raise RuntimeError("normal/forced selection role changed")
            def forced_analyze(p, s):
                actual = original_analyze(p, s)
                return dict(actual, decision="review", reason="isolated_forced_correct_guard_stress", forced=True, normal_decision=actual["decision"])
            signedness_selector.analyze = forced_analyze if subject["forced"] else original_analyze
            os.environ.update(LLM_BASE_URL="http://127.0.0.1:8000/v1", MODEL_NAME="Qwen3.6-27B-Q4_K_M", RTL_PROFILE="submission", RTL_REVIEW_MODE="control" if label == "C" else "checklist", RTL_REVIEW_LLM_CAP_S="20", RTL_REVIEW_COMPILE_CAP_S="5", RTL_REVIEW_CLEANUP_RESERVE_S="6", RTL_REVIEW_SOCKET_CAP_S="20", RTL_TEMPERATURE="0", RTL_MAX_TOKENS="8192")
            row_dir = args.out / "review" / name / label
            row_dir.mkdir(parents=True)
            runtime.write(row_dir / "solution.v", source)
            runtime.write(row_dir / "trace.jsonl", "")
            tick = time.monotonic()
            try:
                runtime.finish_compiled(prompt, source, row_dir, 0, 1, "Qwen3.6-27B-Q4_K_M", skill, repair_skill, tick + 60, 0)
            finally:
                signedness_selector.analyze = original_analyze
            elapsed = time.monotonic() - tick
            events = [json.loads(line) for line in (row_dir / "trace.jsonl").read_text().splitlines()]
            attempts = sum(e["tool"] == "review_llm_start" for e in events)
            report["model_calls"] += attempts
            response_path = row_dir / "review/response.json"
            response = json.loads(response_path.read_text()) if response_path.exists() else {}
            received = isinstance(response.get("payload"), dict)
            report["responses"] += int(received)
            commit = next((e for e in reversed(events) if e["tool"] == "review_commit"), {})
            row = dict(subject=name, arm=label, forced=subject["forced"], normal_selection=normal,
                       attempts=attempts, response_received=received, elapsed_s=elapsed, commit=commit,
                       original_sha256=sha(subject["folder"] / "candidate.sv"), final_sha256=sha(row_dir / "solution.v"))
            report["rows"].append(row)
            save(row_dir / "generation_receipt.json", row)
            paired.model_idle("http://127.0.0.1:8000/v1", "Qwen3.6-27B-Q4_K_M")
            if attempts != 1 or not received:
                raise RuntimeError("incomplete review request; stop without retry")
            candidate = row_dir / "review/candidate.sv"
            if candidate.is_file():
                row["candidate_sha256"] = sha(candidate)
                row["candidate_probe"] = probe(subject, candidate, args.out / "grades" / name / label / "candidate")
            final = row_dir / "solution.v"
            if row["final_sha256"] == row["original_sha256"]:
                row["final_probe"] = report["originals"][name]
                row["final_reuses_original_receipt"] = True
            elif candidate.is_file() and sha(final) == sha(candidate):
                row["final_probe"] = row["candidate_probe"]
                row["final_reuses_candidate_receipt"] = True
            else:
                row["final_probe"] = probe(subject, final, args.out / "grades" / name / label / "final")
            row.update(regression=row["final_probe"]["status"] != "pass", repair=False,
                       byte_identical=row["original_sha256"] == row["final_sha256"])
            save(row_dir / "graded_receipt.json", row)
            print(json.dumps({k:row[k] for k in ("subject","arm","forced","attempts","elapsed_s","regression","byte_identical")}), flush=True)
        report["arms"] = {label:dict(rows=sum(r["arm"]==label for r in report["rows"]),
            repairs=0, regressions=sum(r["regression"] for r in report["rows"] if r["arm"]==label),
            byte_identical=sum(r["byte_identical"] for r in report["rows"] if r["arm"]==label),
            review_elapsed_s=sum(r["elapsed_s"] for r in report["rows"] if r["arm"]==label)) for label in ("C","D")}
        paired.check_resource(args.resource_check, args.kit)
        if any(sha(p) != h for p,h in frozen.items()) or any(sha(REPO/p) != h for p,h in spec["files"].items()):
            raise RuntimeError("source/input changes after review")
        report.update(complete=True, valid=True, inputs_unchanged=True,
                      decision="reject_review_adoption" if any(r["regression"] for r in report["rows"]) else "bounded_guards_passed_no_new_repair_benefit_no_deployment")
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        signedness_selector.analyze = original_analyze
        report["elapsed_s"] = time.monotonic() - started
        save(args.out / "summary.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
