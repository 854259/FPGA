"""Copy archived metadata only; no model, EDA, locks or shared-file writes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    root = ap.parse_args().root.resolve()
    spec = json.loads((root / "RUN_SPEC.json").read_text())
    assert sha(root / "collect_metadata.py") == spec["source_hashes"]["collect_metadata.py"]
    out = root / "metadata"
    out.mkdir(exist_ok=False)
    rows, receipts = [], {}
    for dataset in spec["datasets"]:
        archive, tasks = Path(dataset["archive"]), Path(dataset["tasks"])
        frozen = out / dataset["id"]
        frozen.mkdir()
        exp, summary = archive / "experiment.json", archive / "graded_summary.json"
        meta = json.loads(exp.read_text())
        assert meta["complete"] and meta["samples"] == 1 and len(meta["task_ids"]) == dataset["expected_tasks"]
        shutil.copyfile(exp, frozen / "experiment.json")
        shutil.copyfile(summary, frozen / "graded_summary.json")
        receipts[dataset["id"]] = dict(experiment_sha256=sha(exp), summary_sha256=sha(summary))
        for side in ("agent", "baseline"):
            for task in sorted(meta["task_ids"]):
                sample = archive / side / task / "s0"
                source, prompt = sample / "solution.v", tasks / task / "prompt.txt"
                sh, ph = sha(source), sha(prompt)
                assert ph == meta["input_sha256"][task + "/prompt.txt"]
                dest = frozen / side / task
                dest.mkdir(parents=True)
                verdict = archive / "results" / (side + "." + task + ".s0.json")
                shutil.copyfile(verdict, dest / "verdict.json")
                trace = sample / "trace.jsonl"
                if trace.is_file():
                    shutil.copyfile(trace, dest / "trace.jsonl")
                logs = []
                for i, log in enumerate(sorted((sample / "judge_logs").glob("*.log"))):
                    assert not log.is_symlink()
                    target = dest / ("judge_" + str(i) + ".log")
                    shutil.copyfile(log, target)
                    logs.append(dict(original=str(log), copy=target.relative_to(root).as_posix(), bytes=target.stat().st_size, sha256=sha(target)))
                assert sha(source) == sh and sha(prompt) == ph
                rows.append(dict(dataset=dataset["id"], side=side, task=task, source_sha256=sh, prompt_sha256=ph, metadata=dest.relative_to(root).as_posix(), original_source=str(source), judge_logs=logs))
        assert sha(exp) == receipts[dataset["id"]]["experiment_sha256"] and sha(summary) == receipts[dataset["id"]]["summary_sha256"]
    assert len(rows) == spec["expected_records"]
    for row in rows:
        assert sha(Path(row["original_source"])) == row["source_sha256"]
    save(root / "COLLECTION.json", dict(schema="archived_compiler_metadata_v1", utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), rows=rows, datasets=receipts, model_calls=0, eda_calls=0, shared_locks_or_model_modified=False, archived_source_unchanged=True))
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix != ".zip")
    save(root / "MANIFEST.json", dict(files=[dict(path=p.relative_to(root).as_posix(), bytes=p.stat().st_size, sha256=sha(p)) for p in files]))
    z = root / "metadata.zip"
    with zipfile.ZipFile(z, "x", zipfile.ZIP_DEFLATED) as a:
        for p in files + [root / "MANIFEST.json"]:
            a.write(p, p.relative_to(root).as_posix())
    print(json.dumps(dict(records=len(rows), files=len(files), sha256=sha(z), bytes=z.stat().st_size, model_calls=0, eda_calls=0)))


if __name__ == "__main__":
    main()
