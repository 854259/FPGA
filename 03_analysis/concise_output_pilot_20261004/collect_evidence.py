"""Read-only, bounded collection of accepted immutable samples. No model/EDA."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile


SPEC_SHA = "105d05a41f304be3e5e029949c6bdf352d4dfc919c0aab8f7fa3922274d20398"
TEXT = {".py", ".md", ".json", ".jsonl", ".sv", ".v", ".log", ".txt", ".tcl",
        ".jou", ".prj", ".sh", ".csv"}
SKIP = {"xsim.dir", ".Xil", "__pycache__", "scratch"}
MAX_FILE = 50 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def schedule(spec):
    items = []
    for index, task in enumerate(spec["task_ids"]):
        items.extend((arm, task) for arm in (("A", "C") if index % 2 == 0 else ("C", "A")))
    return items


def collect(run, archive, allow_partial=False):
    run, archive = Path(run).resolve(), Path(archive).resolve()
    if archive.exists() or archive.is_relative_to(run):
        raise ValueError("Fresh archive outside the frozen run required")
    spec_raw = (run / "RUN_SPEC.json").read_bytes()
    assert sha(spec_raw) == SPEC_SHA
    spec = json.loads(spec_raw)
    status_raw = (run / "queue_status.json").read_bytes()
    status = json.loads(status_raw)
    assert status["source_spec_sha256"] == SPEC_SHA
    n = status["completed_samples"]
    assert type(n) is int and 0 <= n <= 24
    if not allow_partial:
        assert status["complete"] is True and status["state"] == "complete" and n == 24
    kit = Path(spec["kit"]).resolve()
    dependency = Path(spec["dependencies_cloud"]).resolve()
    manifest = read(run / "INPUT_MANIFEST.json")
    assets = {}

    def add(path, name, expected=None):
        path = Path(path)
        assert path.is_file() and not path.is_symlink(), str(path)
        raw = path.read_bytes()
        assert len(raw) <= MAX_FILE
        if expected is not None:
            assert sha(raw) == expected, name
        assert name not in assets, name
        assets[name] = raw

    for name, digest in spec["source_hashes"].items():
        add(run / name, "run/" + name, digest)
    assets["run/RUN_SPEC.json"] = spec_raw
    assets["run/queue_status.json"] = status_raw
    add(run / "LAUNCH.json", "run/LAUNCH.json")
    for name, digest in spec["dependency_hashes"].items():
        add(dependency / name, "dependencies/" + name, digest)
    for name, digest in manifest["input_sha256"].items():
        add(kit / "bench/tasks_veval" / name, "kit/bench/tasks_veval/" + name, digest)
    for name, digest in manifest["official_sha256"].items():
        add(kit / "official_reference" / name, "kit/official_reference/" + name, digest)

    def tree(directory):
        assert directory.is_dir() and directory.is_relative_to(run)
        for path in sorted(directory.rglob("*")):
            rel = path.relative_to(run)
            if any(part in SKIP for part in rel.parts) or not path.is_file():
                continue
            if path.suffix in TEXT:
                add(path, "run/" + rel.as_posix())

    accepted = [("controls", spec["preflight_task"])] + schedule(spec)[:n]
    for arm, task in accepted:
        folder = run / "samples" / arm / task
        row = read(folder / "accepted_row.json")
        assert row["complete"] and row["valid"]
        guard = Path(row["guard_directory"]).resolve()
        assert guard.is_relative_to(run / "admission")
        tree(folder)
        tree(guard)
        launcher = guard.with_suffix(".launcher.log")
        if launcher.is_file():
            add(launcher, "run/" + launcher.relative_to(run).as_posix())
    # Recheck the frozen assets after collection; accepted files are immutable,
    # while later samples are deliberately excluded from a progress snapshot.
    for name, digest in spec["source_hashes"].items():
        assert sha((run / name).read_bytes()) == digest, name
    for name, digest in spec["dependency_hashes"].items():
        assert sha((dependency / name).read_bytes()) == digest, name
    receipt = dict(schema="concise_output_pilot_archive_v1",
        captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        run_root=str(run), source_spec_sha256=SPEC_SHA, completed_samples=n,
        run_complete_at_capture=status["complete"], accepted_schedule=accepted,
        collector_sha256=sha(Path(__file__).read_bytes()),
        source_files_verified=len(spec["source_hashes"]),
        inputs_verified=len(manifest["input_sha256"]),
        official_files_verified=len(manifest["official_sha256"]),
        model_calls=0, eda_calls=0, skipped_compiled_binaries=True,
        files={name: sha(raw) for name, raw in sorted(assets.items())})
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in sorted(assets.items()):
            bundle.writestr(name, raw)
        bundle.writestr("ARCHIVE_MANIFEST.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return dict(archive=str(archive), archive_sha256=sha(archive.read_bytes()),
                files=len(assets), completed_samples=n, complete=status["complete"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    print(json.dumps(collect(args.run_root, args.archive, args.allow_partial)))
