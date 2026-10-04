"""Collect completed owned run evidence; no model/EDA/instance mutations."""
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import socket
import urllib.request
import zipfile

ROOT = Path("/workspace/team/runs/fpga_owner/local_bit_contract_20261004_v1")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    spec = json.loads((ROOT / "RUN_SPEC.json").read_text())
    guard = json.loads((ROOT / "guard/status.json").read_text())
    summary = json.loads((ROOT / "results/summary.json").read_text())
    assert guard["complete"] and guard["passed"] and summary["complete"] and summary["verified"]
    assert guard["own_slot_released"] and guard["owned_cleanup"]["verified"] and not guard["owned_cleanup"]["remaining"]
    deps = Path(spec["dependency_cloud_directory"])
    snapshot = ROOT / "dependency_snapshot"
    snapshot.mkdir(exist_ok=False)
    for name, digest in spec["dependency_hashes"].items():
        assert sha(deps / name) == digest
        shutil.copyfile(deps / name, snapshot / name)
    for name, digest in spec["source_hashes"].items():
        assert sha(ROOT / name) == digest
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open("http://127.0.0.1:8000/" + path, timeout=10) as response:
            return json.load(response)
    health, slots = get("health"), get("slots")
    processing = sum(bool(x["is_processing"]) for x in slots)
    def listening(port):
        with socket.socket() as connection:
            connection.settimeout(2)
            return connection.connect_ex(("127.0.0.1", port)) == 0
    postflight = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), model_health=health,
        processing_slots=processing, slot_exists=Path("/workspace/team/SLOT.lock").exists(),
        ports={str(p): listening(p) for p in (8000, 7860, 7867)},
        workspace_free_gib=shutil.disk_usage("/workspace").free / 2**30,
        model_pid=spec["model_pid"], instance_shutdown_or_model_restart=False)
    assert health["status"] == "ok" and processing == 0 and not postflight["slot_exists"]
    assert Path("/proc/" + str(spec["model_pid"])).exists()
    save(ROOT / "postflight.json", postflight)
    allowed = {".json", ".jsonl", ".py", ".sv", ".v", ".txt", ".log", ".rpt", ".tcl", ".md"}
    excluded_dirs = {"xsim.dir", "__pycache__", ".Xil"}
    files = [p for p in ROOT.rglob("*") if p.is_file() and not p.is_symlink()
        and not excluded_dirs.intersection(p.relative_to(ROOT).parts)
        and (p.suffix in allowed or p.name in (".gitignore", ".gitattributes"))
        and p.name != "MANIFEST.json"]
    rows = [dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(files)]
    save(ROOT / "MANIFEST.json", dict(schema="local_bit_contract_manifest_v1", files=rows))
    archive = ROOT / "evidence.zip"
    assert not archive.exists()
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files) + [ROOT / "MANIFEST.json"]:
            z.write(p, str(p.relative_to(ROOT)))
    print(json.dumps(dict(sha256=sha(archive), bytes=archive.stat().st_size, files=len(rows),
        private_raw_directory="raw_evidence", archive_not_in_git=True, postflight=postflight)))


if __name__ == "__main__":
    main()
