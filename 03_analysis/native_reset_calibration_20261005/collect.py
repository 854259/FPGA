"""Archive complete generated research calibration; no model/native execution."""
import argparse
import datetime
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def sha(data):
    return hashlib.sha256(data).hexdigest()


def collect(root, archive):
    root, archive = root.resolve(), archive.resolve()
    if archive.exists() or archive.is_relative_to(root):
        raise ValueError("fresh archive outside owned run required")
    spec_bytes = (root / "RUN_SPEC.json").read_bytes()
    spec = json.loads(spec_bytes)
    spec_sha = sha(spec_bytes)
    summary = json.loads((root / "results/summary.json").read_bytes())
    guard = json.loads((root / "guard/status.json").read_bytes())
    if summary.get("complete") is not True or summary.get("evidence_complete") is not True or summary.get("error") is not None or summary.get("run_spec_sha256") != spec_sha:
        raise ValueError("complete error-free measurement bound to this spec required")
    if not all(guard.get(key) is True for key in ("complete", "passed", "model_unchanged", "protected_files_unchanged", "own_slot_released")) or guard.get("stage_rc") != 0 or guard.get("owned_cleanup", {}).get("verified") is not True or guard["owned_cleanup"].get("remaining"):
        raise ValueError("complete owned guard, cleanup and release required")
    if summary.get("model_calls") != 0 or summary.get("generated_research_test") is not True or summary.get("original_harness") is not False:
        raise ValueError("zero-model research provenance required")
    # Control discrimination can fail while all measurement evidence is valid.
    for key, expected in (("actual_compile_commands", 14), ("actual_simulation_commands", 14),
                          ("attempted_compile_commands", 14), ("attempted_simulation_commands", 14),
                          ("global_native_receipts", 28), ("unconfirmed_native_attempts", 0)):
        if type(summary.get(key)) is not int or summary[key] != expected:
            raise ValueError("complete fourteen-control call accounting required")
    if "journal_count_error" in summary or len(summary.get("rows", [])) != 14:
        raise ValueError("incomplete measurement rows/accounting")
    if sha(Path(__file__).read_bytes()) != spec["source_hashes"]["collect.py"]:
        raise ValueError("live collector differs from frozen collector")
    files = {}

    def add(path, name, digest=None):
        safe = PurePosixPath(name)
        if safe.is_absolute() or ".." in safe.parts or "\\" in name or name in files:
            raise ValueError("unsafe/duplicate archive path")
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular evidence files required")
        data = path.read_bytes()
        if len(data) >= 50 * 1024 ** 2 or (digest is not None and sha(data) != digest):
            raise ValueError("evidence byte/size binding changed")
        files[name] = data

    for name, digest in spec["source_hashes"].items():
        safe = PurePosixPath(name)
        if safe.is_absolute() or ".." in safe.parts or "\\" in name:
            raise ValueError("unsafe source path")
        path = root / name
        if not path.resolve().is_relative_to(root):
            raise ValueError("source escaped owned run")
        add(path, "run/" + name, digest)
    add(root / "RUN_SPEC.json", "run/RUN_SPEC.json")
    add(root / "PREPARATION_RECEIPT.json", "run/PREPARATION_RECEIPT.json")
    for directory in ("results", "guard", "tools"):
        for path in sorted((root / directory).rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_file():
                add(path, "run/" + path.relative_to(root).as_posix())
    for name, digest in spec["dependency_hashes"].items():
        safe = PurePosixPath(name)
        if safe.is_absolute() or ".." in safe.parts or "\\" in name:
            raise ValueError("unsafe dependency path")
        add(Path(spec["dependencies_cloud"]) / name, "dependencies/" + name, digest)
    manifest = dict(schema="native_reset_generated_research_archive_v1",
                    captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    run_spec_sha256=spec_sha, collector_sha256=sha(Path(__file__).read_bytes()),
                    collector_model_calls=0, collector_eda_calls=0,
                    generated_research_test=True, original_harness=False,
                    files={name: sha(data) for name, data in files.items()})
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            out.writestr(name, data)
        out.writestr("ARCHIVE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    return dict(archive=str(archive), archive_sha256=sha(archive.read_bytes()), files=len(files),
                evidence_complete=True,
                qualified_for_generated_control_discrimination=summary["qualified_for_generated_control_discrimination"],
                collector_model_calls=0, collector_eda_calls=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.root, args.archive)))
