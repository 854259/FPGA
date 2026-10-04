"""AMD-only natural candidate applicability audit, with zero generation/EDA."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
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
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def run(args):
    if sys.platform != "linux":
        raise RuntimeError("execute only on authorized AMD")
    spec = json.loads((HERE / "REPLAY_SPEC.json").read_text())
    selector_path = REPO / "04_project/amd_rtl_agent/bench/signedness_selector.py"
    patch_path = REPO / "03_analysis/semantic_repair_20261004/signed_shift_patch.py"
    if sha(selector_path) != spec["selector_sha256"] or sha(patch_path) != spec["patch_sha256"]:
        raise RuntimeError("frozen selector/patch mismatch")
    paired = load("replay_resource_checks", REPO / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    paired.check_resource(args.resource_check, args.kit, first=True)
    args.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    report = dict(complete=False, valid=False, new_model_calls=0, eda_calls=0,
                  patch_sha256=sha(patch_path), selector_sha256=sha(selector_path),
                  runner_sha256=sha(__file__), spec_sha256=sha(HERE / "REPLAY_SPEC.json"),
                  rows=[], datasets={}, error=None)
    try:
        inputs, frozen = [], {}
        for dataset in spec["datasets"]:
            archive, tasks = Path(dataset["archive"]), Path(dataset["tasks"])
            experiment = archive / "experiment.json"
            if sha(experiment) != dataset["experiment_sha256"]:
                raise RuntimeError("archive identity mismatch: " + dataset["id"])
            exp = json.loads(experiment.read_text())
            ids = sorted(exp["task_ids"])
            if len(ids) != dataset["task_count"] or len(set(ids)) != len(ids):
                raise RuntimeError("task count/uniqueness mismatch")
            frozen[str(experiment)] = sha(experiment)
            for mode in spec["modes"]:
                if sorted(p.name for p in (archive / mode).iterdir() if p.is_dir()) != ids:
                    raise RuntimeError("candidate task set mismatch")
                for task in ids:
                    prompt_path = tasks / task / "prompt.txt"
                    prompt_bytes = prompt_path.read_bytes()
                    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
                    if exp["input_sha256"][task + "/prompt.txt"] != prompt_hash:
                        raise RuntimeError("prompt changed since generation: " + task)
                    frozen[str(prompt_path)] = prompt_hash
                    for sample in spec["samples"]:
                        source_path = archive / mode / task / sample / "solution.v"
                        raw = source_path.read_bytes()
                        source_hash = hashlib.sha256(raw).hexdigest()
                        frozen[str(source_path)] = source_hash
                        row_id = ".".join((dataset["id"], mode, task, sample))
                        folder = args.out / "private_inputs" / row_id
                        folder.mkdir(parents=True)
                        (folder / "before.sv").write_bytes(raw)
                        (folder / "prompt.txt").write_bytes(prompt_bytes)
                        inputs.append(dict(id=row_id, dataset=dataset["id"], mode=mode, task=task,
                            sample=sample, before_sha256=source_hash, prompt_sha256=prompt_hash,
                            known_development_task=task in spec["known_patch_development_tasks"]))
            if sum(r["dataset"] == dataset["id"] for r in inputs) != dataset["candidate_count"]:
                raise RuntimeError("candidate denominator mismatch")
        # All input identities are saved before any transformation or outcome inspection.
        save(args.out / "inputs_frozen.json", dict(inputs=inputs, source_hashes=frozen))
        selector = load("replay_selector", selector_path)
        patcher = load("replay_patch", patch_path)
        for item in inputs:
            folder = args.out / "private_inputs" / item["id"]
            original = (folder / "before.sv").read_bytes()
            source = original.decode("utf-8")
            prompt = (folder / "prompt.txt").read_bytes().decode("utf-8")
            started = time.perf_counter()
            after, receipt = patcher.patch(prompt, source, selector)
            transform_s = time.perf_counter() - started
            repeated, repeated_receipt = patcher.patch(prompt, source, selector)
            again, again_receipt = patcher.patch(prompt, after, selector)
            encoded = after.encode("utf-8")
            row = dict(item, changed=receipt["changed"], reason=receipt["reason"],
                selection=receipt["selection"], after_sha256=hashlib.sha256(encoded).hexdigest(),
                transform_s=transform_s, byte_identical=encoded == original,
                repeat_identical=after == repeated and receipt == repeated_receipt,
                idempotent=again == after and not again_receipt["changed"])
            if not row["repeat_identical"] or not row["idempotent"] or row["changed"] == row["byte_identical"]:
                raise RuntimeError("transformation invariant failed: " + item["id"])
            (folder / "after.sv").write_bytes(encoded)
            report["rows"].append(row)
        if any(sha(path) != digest for path, digest in frozen.items()):
            raise RuntimeError("archive changed during replay")
        paired.check_resource(args.resource_check, args.kit)
        for dataset in spec["datasets"]:
            rows = [r for r in report["rows"] if r["dataset"] == dataset["id"]]
            report["datasets"][dataset["id"]] = dict(candidates=len(rows),
                tasks=dataset["task_count"], changed=sum(r["changed"] for r in rows),
                byte_identical=sum(r["byte_identical"] for r in rows),
                selection_counts=dict(Counter(r["selection"]["decision"] for r in rows)),
                reasons=dict(Counter(r["reason"] for r in rows)),
                transform_s=sum(r["transform_s"] for r in rows))
        report["changed_candidates"] = [r["id"] for r in report["rows"] if r["changed"]]
        report["independent_task_changes"] = [r["id"] for r in report["rows"] if r["changed"] and not r["known_development_task"]]
        report["decision"] = ("freeze_changed_nondevelopment_candidates_for_semantic_evaluation"
            if report["independent_task_changes"] else "no_independent_natural_benefit_established_do_not_expand_or_deploy")
        report.update(complete=True, valid=True, inputs_unchanged=True)
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        report["elapsed_s"] = time.monotonic() - tick
        save(args.out / "summary.json", report)
        print(json.dumps({k:v for k,v in report.items() if k != "rows"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args())
