"""Freeze fixed generated research controls; no model/native/cloud execution."""
import ast
import datetime
import subprocess
import zipfile
from pathlib import Path

import calibration as c

ROOT = Path(__file__).resolve().parent


if __name__ == "__main__":
    if (ROOT / "RUN_SPEC.json").exists() or (ROOT / "raw_evidence/preparation.zip").exists():
        raise ValueError("refuse to replace a frozen research package")
    private, cases = c.validate_private(ROOT)
    previous = c.read(ROOT.parent / "natural_edge_calibration_20261005/RUN_SPEC.json")
    bindings = c.read(ROOT / "raw_evidence/DEPENDENCY_BINDINGS.json")
    provenance = c.read(ROOT / "PUBLIC_PROMPT_PROVENANCE.json")
    for filename, methods, subchecks, hashes in (("LOCAL_CHECKS.json", "tests", "subtests", "source_sha256"),
                                                ("COLLECT_CHECKS.json", "methods", "subchecks", "source_hashes")):
        checks = c.read(ROOT / filename)
        expected = (16, 82) if filename == "LOCAL_CHECKS.json" else (4, 13)
        if checks["status"] != "passed" or (checks[methods], checks[subchecks]) != expected or checks["failures"] != 0 or checks["errors"] != 0 or checks["actual_model_calls"] != 0 or checks["actual_eda_calls"] != 0:
            raise ValueError("actual pure check receipt required")
        for name, digest in checks[hashes].items():
            if c.sha((ROOT / name).read_bytes()) != digest:
                raise ValueError("source changed after pure check receipt")
    if provenance["dataset_sha256"] != c.DATASET_SHA or provenance["prompt_sha256"] != c.ORIGINAL_PROMPT_SHA or provenance["exact_original_public_prompt"] is not True:
        raise ValueError("exact public prompt provenance required")
    public = ["native_reset_contract.py", "tool_journal.py", "calibration.py", "stage.py",
              "audit.py", "test_preparation.py", "guard_wrapper.py", "collect.py", "prepare.py",
              "INPUT_MANIFEST.json", "PUBLIC_PROMPT_PROVENANCE.json", "test_collect.py"]
    private_sources = {"raw_evidence/CONTROLS.json", "raw_evidence/DEPENDENCY_BINDINGS.json"}
    for control, _, _, _ in cases:
        private_sources.update(control[key] for key in ("prompt_path", "rtl_path", "tb_path"))
    if len(private_sources) != 32:
        raise ValueError("exact31 private control assets plus dependency binding required")
    sources = public + sorted(private_sources)
    for name in sources:
        path = c.contained(ROOT, name)
        if name.endswith(".py"):
            ast.parse(path.read_bytes(), filename=name)
            compile(path.read_bytes(), name, "exec")
    if bindings["toolchain"] != previous["toolchain"]:
        raise ValueError("reviewed real toolchain binding changed")
    spec = dict(
        schema="native_reset_generated_research_frozen_v1",
        identity="native_reset_calibration_20261005_v1",
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        cloud_root="/workspace/team/runs/fpga_owner/native_reset_calibration_20261005_v1",
        kit=previous["kit"], dependencies_cloud=previous["dependencies_cloud"],
        dependency_hashes=previous["dependency_hashes"],
        source_hashes={name: c.sha(c.contained(ROOT, name).read_bytes()) for name in sources},
        dataset_sha256=c.DATASET_SHA, prompt_sha256=c.ORIGINAL_PROMPT_SHA,
        parser_sha256=c.PARSER_SHA, control_order=list(c.ORDER),
        controls=14, compiles_max=14, simulations_max=14, model_requests_max=0,
        stage_timeout_s=1200, guard_timeout_s=1300, native_command_timeout_s=30, slot_minutes=25,
        inherited_path=previous["inherited_path"],
        slot_owner="codex_native_reset_calibration_20261005_v1",
        slot_lock_path=previous["slot_lock_path"], model_identity=previous["model_identity"],
        llm_base_url=previous["llm_base_url"], model_name=previous["model_name"],
        toolchain=bindings["toolchain"],
        real_tools={name: dict(path=bindings["toolchain"]["prefix"] + "/bin/" + name,
                              sha256=bindings["toolchain"]["files"]["bin/" + name])
                    for name in ("iverilog", "vvp")},
        generated_research_test=True, original_harness=False,
        acceptance="Complete all14 fixed controls with exactly14 compile and14 simulation receipts, no unconfirmed attempts, intact source/dependencies/resources and owned cleanup. Evidence completeness and control discrimination are separate: retain any wrong-control false acceptance and do not retune or retry. This generated research TB grants no original-harness, model-quality, full156, independence, formal-five, offline or deployment qualification.",
        policy=dict(public_prompt_only=True, original_module_names=True,
                    renamed_positive_changes_names_only=True, evaluation_controls_only=True,
                    generated_research_test=True, original_harness=False,
                    LLM_calls=0, retries=0, whole_task_FIFO=True,
                    full156_qualification_unchanged=True,
                    independent_model_calls_blocked_until_full_qualification=True,
                    adoption=False))
    c.save(ROOT / "RUN_SPEC.json", spec)
    c.save(ROOT / "PREPARATION_RECEIPT.json", dict(
        spec_sha256=c.sha((ROOT / "RUN_SPEC.json").read_bytes()), assets=len(sources),
        static_parse_compile_passed=True, pure_methods=16, pure_subchecks=82,
        actual_eda_calls=0, actual_model_calls=0, planned_native_trials=14,
        planned_native_commands=28, actual_fifo_submitted=False,
        generated_research_test=True, original_harness=False))
    with zipfile.ZipFile(ROOT / "raw_evidence/preparation.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ["RUN_SPEC.json", "PREPARATION_RECEIPT.json"]:
            archive.write(ROOT / name, name)
    c.save(ROOT / "PREPARATION_ARCHIVE.json", dict(
        archive_sha256=c.sha((ROOT / "raw_evidence/preparation.zip").read_bytes()),
        spec_sha256=c.sha((ROOT / "RUN_SPEC.json").read_bytes()), assets=len(sources)))
    print((ROOT / "PREPARATION_ARCHIVE.json").read_text())
