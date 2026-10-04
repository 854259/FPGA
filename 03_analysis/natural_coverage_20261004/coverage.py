"""Freeze natural archived prompt/source pairs and audit unchanged B2 coverage."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--collect", action="store_true")
    args = ap.parse_args()
    root = args.root.resolve()
    spec = read(root / "RUN_SPEC.json")
    for name, digest in spec["source_hashes"].items():
        assert sha(root / name) == digest, name
    selector = load("frozen_selector", root / "signedness_selector.py")
    patcher = load("frozen_b2", root / "signed_shift_patch.py")
    manifest = root / "PAIR_MANIFEST.json"
    if args.collect:
        assert not manifest.exists()
        pairs, dataset_receipts = [], {}
        for dataset in spec["datasets"]:
            archive, tasks = Path(dataset["archive"]), Path(dataset["tasks"])
            experiment = archive / "experiment.json"
            meta = read(experiment)
            assert meta["complete"] and meta["samples"] == 1
            assert len(meta["task_ids"]) == dataset["expected_tasks"]
            dataset_receipts[dataset["id"]] = dict(experiment_path=str(experiment), experiment_sha256=sha(experiment))
            for side in ("agent", "baseline"):
                for task in sorted(meta["task_ids"]):
                    prompt = tasks / task / "prompt.txt"
                    source = archive / side / task / "s0/solution.v"
                    assert source.is_file() and sha(prompt) == meta["input_sha256"][task + "/prompt.txt"]
                    folder = root / "inputs" / dataset["id"] / side / task
                    folder.mkdir(parents=True, exist_ok=False)
                    shutil.copyfile(prompt, folder / "prompt.txt")
                    shutil.copyfile(source, folder / "candidate.sv")
                    pairs.append(dict(dataset=dataset["id"], side=side, task=task,
                        original_prompt=str(prompt), original_source=str(source),
                        prompt=str((folder / "prompt.txt").relative_to(root)), source=str((folder / "candidate.sv").relative_to(root)),
                        prompt_sha256=sha(prompt), source_sha256=sha(source)))
        save(manifest, dict(pairs=pairs, datasets=dataset_receipts, model_calls=0, eda_calls=0))
    frozen = read(manifest)
    rows = []
    for pair in frozen["pairs"]:
        prompt, source = root / pair["prompt"], root / pair["source"]
        assert sha(prompt) == pair["prompt_sha256"] and sha(source) == pair["source_sha256"]
        p, s = prompt.read_text(encoding="utf-8"), source.read_text(encoding="utf-8")
        updated, receipt = patcher.patch(p, s, selector)
        duplicate, duplicate_receipt = patcher.patch(p, s, selector)
        again, again_receipt = patcher.patch(p, updated, selector)
        assert updated == duplicate and receipt == duplicate_receipt and again == updated
        assert receipt["changed"] == (updated != s)
        rows.append({k: pair[k] for k in ("dataset", "side", "task", "prompt_sha256", "source_sha256")} |
            dict(decision=receipt["selection"]["decision"], reason=receipt["reason"], changed=receipt["changed"],
                output_sha256=hashlib.sha256(updated.encode()).hexdigest(),
                known_development_task=pair["task"] in spec["known_development_tasks"], receipt=receipt))
    total_expected = sum(x["expected_tasks"] * 2 for x in spec["datasets"])
    assert len(rows) == total_expected
    changed = [x for x in rows if x["changed"]]
    result = dict(schema="b2_natural_archive_coverage_v1", status="complete_verified",
        rows=len(rows), unique_prompt_source_pairs=len({(x["prompt_sha256"], x["source_sha256"]) for x in rows}),
        unique_task_identities=len({(next(d["family"] for d in spec["datasets"] if d["id"] == x["dataset"]), x["task"]) for x in rows}),
        changed=len(changed), changed_tasks=sorted({x["task"] for x in changed}),
        independent_task_changes=[x for x in changed if not x["known_development_task"]],
        datasets={d["id"]: dict(rows=sum(x["dataset"] == d["id"] for x in rows),
            changed=sum(x["dataset"] == d["id"] and x["changed"] for x in rows),
            decisions=dict(Counter(x["decision"] for x in rows if x["dataset"] == d["id"]))) for d in spec["datasets"]},
        model_calls=0, eda_calls=0, functional_validation=False, new_score=False,
        repeat_and_idempotence_verified=True, pair_manifest_sha256=sha(manifest), run_spec_sha256=sha(root / "RUN_SPEC.json"),
        rows_detail=rows, limits=spec["limits"])
    output = root / "COVERAGE.json"
    if output.exists():
        assert read(output) == result
    else:
        save(output, result)
    if args.collect:
        for pair in frozen["pairs"]:
            assert sha(Path(pair["original_prompt"])) == pair["prompt_sha256"]
            assert sha(Path(pair["original_source"])) == pair["source_sha256"]
        with zipfile.ZipFile(root / "evidence.zip", "x", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix != ".zip" and "__pycache__" not in p.parts:
                    z.write(p, str(p.relative_to(root)))
    print(json.dumps({k: result[k] for k in ("status", "rows", "unique_prompt_source_pairs", "unique_task_identities", "changed", "changed_tasks", "independent_task_changes", "datasets")}))
    if args.collect:
        print(json.dumps(dict(archive_sha256=sha(root / "evidence.zip"), bytes=(root / "evidence.zip").stat().st_size)))


if __name__ == "__main__":
    main()
