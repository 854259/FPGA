"""Bounded timing-contract pilot: 16 direct reviews, then offline grading."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import urllib.request

MODEL = "Qwen3.6-27B-Q4_K_M"
ENDPOINT = "http://127.0.0.1:8000/v1"
COMMON = ("Review the candidate against the specification. Correct any functional errors, "
          "preserve the given interface and requirements, and return only one complete TopModule. "
          "If the candidate already meets the specification, return it unchanged.")
TIMING = ("Verify the required output timing before editing. For each output distinguish live "
          "combinational or Mealy behavior, a Moore decode of registered state, and a pulse held "
          "for a complete clock cycle. If the specification requires a pulse in the cycle following "
          "a sampled condition, compute it from pre-edge state and the sampled input and retain it "
          "through that cycle. Preserve explicitly required Mealy behavior and Moore output latency. "
          "Trace consecutive active edges and input changes between edges to check early clearing "
          "and an extra cycle of delay. Add no reset or initialization absent from the specification.")
PAIR_SHA = "78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c"
JUDGE_SHA = "53d1d4ff661ca6c3e27bc1d20a2328815dc39e281abc3a93757099b6e60bf797"
BASELINE_SHA = "537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51"
FEEDBACK_SHA = "aee81f188b3717ce10dc72efd11b01f009acc0d27211e7dcd4ce02cbf0802f74"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main():
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError("cannot enable owned descendant reaping")
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "inputs", "kit", "resource-check", "out", "judge-adapter"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    repo, inputs, out, kit = (args.source.resolve(), args.inputs.resolve(), args.out.resolve(), args.kit.resolve())
    pair_path = repo / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py"
    if sha(pair_path) != PAIR_SHA or sha(args.judge_adapter) != JUDGE_SHA:
        raise RuntimeError("evaluation adapter identity changed")
    paired = load("timing_owned_oracle", pair_path)
    paired.frozen()
    baseline_path = paired.PACKAGE / "baseline.py"
    feedback_path = paired.PACKAGE / "skill/rtl-feedback-repair/SKILL.md"
    if sha(baseline_path) != BASELINE_SHA or sha(feedback_path) != FEEDBACK_SHA:
        raise RuntimeError("fixed extraction or feedback skill changed")
    baseline = load("timing_fixed_extractor", baseline_path)
    evaluator = load("timing_official_adapter", args.judge_adapter)
    evaluator.ROOT, evaluator.OFFICIAL = kit, kit / "official_reference"
    official_commit = evaluator.verify_upstream()
    manifest = json.loads((inputs / "manifest.json").read_text())
    if len(manifest["tasks"]) != 4 or manifest["real_model_call_budget"] != 16 or manifest["order"] != ["D0", "C0", "C1", "D1"]:
        raise RuntimeError("preregistered design changed")
    for rel, digest in manifest["files"].items():
        if sha(inputs / rel) != digest:
            raise RuntimeError("input changed: " + rel)
    paths = [inputs / rel for rel in manifest["files"]] + [inputs / "manifest.json", Path(__file__),
             pair_path, args.judge_adapter, baseline_path, feedback_path]
    snapshot = {str(path): sha(path) for path in paths}
    resource = paired.check_resource(args.resource_check, kit, first=True)
    if resource["model_name"] != MODEL or resource["llm_base_url"] != ENDPOINT:
        raise RuntimeError("model identity or endpoint changed")
    out.mkdir(parents=True, exist_ok=False)
    report = dict(schema="timing_contract_review_pilot_v1", complete=False, verified=False,
                  model=MODEL, model_call_budget=16, client_attempts=0, responses_received=0,
                  new_initial_generations=0, retries=0, snapshot_before=snapshot,
                  manifest_sha256=sha(inputs / "manifest.json"), official_commit=official_commit,
                  common_instruction=COMMON, timing_instruction=TIMING, controls={}, originals={}, rows=[],
                  runtime_integrated=False, deployment_approved=False, limits=manifest["limits"])

    def frozen():
        if {str(path): sha(path) for path in paths} != snapshot:
            raise RuntimeError("frozen assets changed")
        paired.check_resource(args.resource_check, kit)

    tasks = {task: json.loads((inputs / task / "contract.json").read_text()) for task in manifest["tasks"]}

    def probe(task, solution, destination):
        frozen()
        contract = dict(task=task, checks=tasks[task]["checks"], tb=str(inputs / task / "tb.sv"))
        result = paired.oracle(contract, solution, destination)
        if result["status"] == "environment_error":
            raise RuntimeError("probe environment failure: " + task)
        return result

    try:
        # Verify prompt-derived controls and checkpoint roles before using the shared model.
        for task in manifest["tasks"]:
            controls = {name: probe(task, inputs / task / (name + ".sv"), out / "controls" / task / name)
                        for name in ("positive", "negative")}
            controls["valid"] = controls["positive"]["status"] == "pass" and controls["negative"]["failure_kind"] == "semantic_mismatch"
            report["controls"][task] = controls
            if not controls["valid"]:
                raise RuntimeError("oracle controls failed; no model calls admitted: " + task)
            original = probe(task, inputs / task / "candidate.sv", out / "original_probes" / task)
            wanted = "fail" if tasks[task]["role"] == "development_error" else "pass"
            original["role_verified"] = original["status"] == wanted and (wanted == "pass" or original["failure_kind"] == "semantic_mismatch")
            report["originals"][task] = {"probe": original}
            if not original["role_verified"]:
                raise RuntimeError("checkpoint role contradicted: " + task)
        save(out / "controls_verified.json", dict(controls=report["controls"], originals=report["originals"], model_calls=0))
        skill = feedback_path.read_text(encoding="utf-8")
        for task in manifest["tasks"]:
            prompt = (inputs / task / "prompt.txt").read_text(encoding="utf-8")
            candidate = (inputs / task / "candidate.sv").read_bytes().decode("utf-8")
            for label in manifest["order"]:
                frozen()
                paired.model_idle(ENDPOINT, MODEL)
                row_out = out / "generated" / task / label
                row_out.mkdir(parents=True)
                instruction = COMMON + ("\n\n" + TIMING if label.startswith("D") else "")
                payload = dict(model=MODEL, temperature=0, top_p=1, max_tokens=8192,
                    messages=[dict(role="system", content="You review synthesizable RTL. Return a complete module only.\n\n" + skill),
                              dict(role="user", content="Specification:\n" + prompt + "\nCandidate:\n" + candidate + "\n\n" + instruction)])
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                (row_out / "request.json").write_bytes(body)
                row = dict(task=task, label=label, role=tasks[task]["role"], request_sha256=sha(row_out / "request.json"),
                           client_attempts=1, response_received=False, solution=str(row_out / "solution.v"))
                report["rows"].append(row)
                report["client_attempts"] += 1
                started = time.monotonic()
                request = urllib.request.Request(ENDPOINT + "/chat/completions", data=body, headers={"Content-Type": "application/json"})
                # Exactly one request; failures and truncation stop the pilot without resampling.
                with urllib.request.urlopen(request, timeout=120) as response:
                    raw = response.read()
                (row_out / "response.json").write_bytes(raw)
                response = json.loads(raw)
                row.update(response_received=True, request_elapsed_s=time.monotonic() - started,
                           response_sha256=sha(row_out / "response.json"), usage=response.get("usage"),
                           cache_or_timings={key: value for key, value in response.items() if "cache" in key.lower() or key == "timings"} or "unknown")
                report["responses_received"] += 1
                choice = response["choices"][0]
                row["finish_reason"] = choice.get("finish_reason")
                content = choice["message"].get("content")
                if row["finish_reason"] != "stop" or not isinstance(content, str) or not content.strip():
                    raise RuntimeError("truncated/empty response; no retry: " + task + " " + label)
                (row_out / "answer.txt").write_text(content, encoding="utf-8", newline="\n")
                Path(row["solution"]).write_text(baseline.extract(content, "rtl"), encoding="utf-8", newline="\n")
                row.update(solution_sha256=sha(row["solution"]), source_changed=Path(row["solution"]).read_bytes() != candidate.encode("utf-8"))
                save(row_out / "row.json", row)
                print(json.dumps(dict(generated=len(report["rows"]), task=task, label=label, elapsed_s=round(row["request_elapsed_s"], 2))), flush=True)
        save(out / "generation_complete.json", dict(rows=report["rows"], actual_generated_grading_started=False))
        for task in manifest["tasks"]:
            destination = out / "official_originals" / task
            destination.mkdir(parents=True)
            verdict = evaluator.judge_sample(kit / "bench/tasks_veval" / task, inputs / task / "candidate.sv", destination, destination / "verdict.json", 120)
            if verdict.get("tool_error") or verdict.get("suspected_silent_degradation"):
                raise RuntimeError("official original environment/tool failure: " + task)
            report["originals"][task]["official"] = verdict
            wanted = 1 if tasks[task]["role"] == "development_error" else 3
            if verdict["level"] != wanted:
                raise RuntimeError("official original grade contradicted: " + task)
        for row in report["rows"]:
            row["probe"] = probe(row["task"], Path(row["solution"]), out / "generated_probes" / row["task"] / row["label"])
            destination = out / "official_generated" / row["task"] / row["label"]
            destination.mkdir(parents=True)
            row["official"] = evaluator.judge_sample(kit / "bench/tasks_veval" / row["task"], Path(row["solution"]), destination, destination / "verdict.json", 120)
            if row["official"].get("tool_error") or row["official"].get("suspected_silent_degradation"):
                raise RuntimeError("official generated environment/tool failure: " + row["task"] + " " + row["label"])
        report["complete"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    report["snapshot_after"] = {str(path): sha(path) for path in paths}
    report["inputs_unchanged"] = report["snapshot_after"] == snapshot
    report["verified"] = report["complete"] and report["inputs_unchanged"] and report["client_attempts"] == 16 and report["responses_received"] == 16
    report["arms"] = {}
    for arm in ("C", "D"):
        rows = [row for row in report["rows"] if row["label"].startswith(arm)]
        report["arms"][arm] = dict(rows=len(rows), repairs=sum(row.get("official", {}).get("level") == 3 and row["role"] == "development_error" for row in rows),
            guard_regressions=sum(row.get("official", {}).get("level", 3) < 3 and row["role"] == "correct_guard" for row in rows),
            probe_passes=sum(row.get("probe", {}).get("status") == "pass" for row in rows),
            request_elapsed_s=sum(row.get("request_elapsed_s", 0) for row in rows))
    save(out / "summary.json", report)
    print(json.dumps({key: report.get(key) for key in ("complete", "verified", "client_attempts", "responses_received", "arms", "error")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
