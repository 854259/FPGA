"""Freeze a fresh CP8 same-factor full156 root after its one-time prompt intake."""
import argparse, datetime, hashlib, json, os, shutil, sys
from pathlib import Path

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_bytes())

def save(p, value):
    with Path(p).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    assert sys.platform == "linux" and sys.dont_write_bytecode and sys.version_info[:2] == (3, 12)
    assert sha(args.source/"SOURCE_MANIFEST.json") == "4936be247a5fe5d640704b96495f9199a8ff6d506aa17362ecf302d0adc2e214"
    assert sha(args.admission) == "4ca1afa894da77981a75489a4d21621556816bd11d3cd834c4373012ec07814e"
    manifest = read(args.source/"SOURCE_MANIFEST.json")
    assert len(manifest) == 117 and not args.output.exists()
    for name, expected in manifest.items():
        assert (args.source/name).resolve().is_relative_to(args.source.resolve())
        assert sha(args.source/name) == expected
    root = args.output
    root.mkdir(parents=True)
    for name in manifest:
        target = root/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.source/name, target)
    shutil.copyfile(args.admission, root/"PRODUCTION_ADMISSION.json")
    shutil.copyfile(__file__, root/"prepare_full156.py")
    base = read(root/"QUALIFYING_CP8_SPEC.json")
    os.environ.update(base["compiler_env"])
    os.environ.update(RTL_MAX_TOKENS="8192", RTL_REPAIRS="1", RTL_TEMPERATURE="0",
                      MODEL_NAME=base["model"], LLM_BASE_URL="http://127.0.0.1:8000/v1")
    sys.path.insert(0, str(root))
    import protected_sources, guard_wrapper, preparation_inputs, factor_proof, pilot, metrics
    protection = read(root/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json")
    checked = protected_sources.check(protection)
    external = read(root/"EXTERNAL_SOURCE_MANIFEST.json")
    retained = {}
    for group in protection["groups"].values():
        for name, digest in group["source_hashes"].items():
            key = (Path(group["cloud_root"])/name).relative_to(external["cloud_root"]).as_posix()
            assert key not in retained or retained[key] == digest
            retained[key] = digest
    assert all(retained.get(n) == h for n, h in external["source_hashes"].items())
    factor = factor_proof.verify(root, require_native=True)
    assert factor == read(root/"SOURCE_FACTOR_PROOF.json")
    kit = Path(base["kit"])
    selected = preparation_inputs.validate_kit(root, kit)
    assert len(selected["task_ids"]) == 156 and len(selected["guard_tasks"]) == 113
    env = pilot.validate_environment()
    assert env["tools"] == base["compiler_tools"] and env["udev_files"] == base["udev_files"]
    model = guard_wrapper.identity(base["model_pid"])
    assert model == base["model_identity"]
    protected = guard_wrapper.protected(kit)
    inputs = read(root/"INPUT_MANIFEST.json")
    assert protected["tasks"] == inputs["input_sha256"] and protected["official"] == inputs["official_sha256"]
    assert shutil.disk_usage(root).free >= base["minimum_disk_free_bytes"]
    capture = dict(environment=env, model_identity=model, protected=protected,
                   source_check=checked, free_bytes=shutil.disk_usage(root).free,
                   observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   model_calls=0, eda_calls=0, fifo_submitted=False)
    save(root/"FULL156_ENVIRONMENT_CAPTURE.json", capture)
    spec = dict(base)
    spec.update(schema="serial_framing_synthesis_full156_frozen_v1", identity=root.name,
                cloud_root=str(root), dependencies_cloud=str(root/"dependencies"), **selected,
                max_actual_model_requests=624, stage_timeout_s=43200,
                guard_timeout_s=43600, slot_minutes=740,
                environment_capture_sha256=sha(root/"FULL156_ENVIRONMENT_CAPTURE.json"),
                protected_groups_capture_sha256=sha(root/"raw_evidence/PROTECTED_GROUPS_CAPTURE.json"),
                protected_group_count=len(protection["groups"]),
                protected_source_assets=protection["source_assets"], protected_unique_files=len(retained),
                frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                acceptance="Original full156 paired levels and historical113; per-task unchanged-grade/historical-correct and total P cost <= C; P L3>=120 and weighted>=0.80; no deadlines/tool errors; complete original audit.",
                limits=["156 seen development tasks; not independent generalization or complete inclusive batch.",
                        "Native qualification remains finite binary; no parameter/XZ general proof."],
                source_hashes={f.relative_to(root).as_posix():sha(f) for f in sorted(root.rglob("*")) if f.is_file()})
    save(root/"RUN_SPEC.json", spec)
    assert pilot.frozen(kit) == spec
    receipt = dict(passed=True, spec_sha256=sha(root/"RUN_SPEC.json"), source_files=len(spec["source_hashes"]),
                   task_count=156, outputs=312, max_requests=624, model_calls=0, eda_calls=0,
                   fifo_submitted=False, expected_protection_receipts=625)
    save(root/"FULL156_PREPARATION_RECEIPT.json", receipt)
    print(json.dumps(receipt), flush=True)

if __name__ == "__main__":
    main()

