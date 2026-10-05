"""DRAFT standalone generated research calibration; own wholeFIFO guard required.

No model calls. Missing freeze/resources fail before execution. No automatic retry.
"""
import argparse
import collections
import ctypes
import importlib.util
import os
import sys
import time
from pathlib import Path

import calibration as c

ROOT = Path(__file__).resolve().parent


def file_sha(path):
    return c.sha(Path(path).read_bytes())


def dependencies(spec):
    for key in ("toolchain",):
        item = spec[key]
        base = Path(item["prefix"])
        actual = {p.relative_to(base).as_posix(): file_sha(p) for p in base.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        if actual != item["files"]:
            raise ValueError("frozen toolchain dependency bytes changed")
    for name, digest in spec["dependency_hashes"].items():
        if file_sha(c.contained(spec["dependencies_cloud"], name)) != digest:
            raise ValueError("guard command dependency changed")


def native_receipts(folder, spec, candidate_sha, tb_sha):
    receipts = [c.read(path) for path in sorted((folder / "native_receipts").glob("*.json"))]
    result = {}
    for receipt in receipts:
        name = receipt["name"]
        if name not in ("iverilog", "vvp") or name in result:
            raise ValueError("unknown/repeated native tool call; do not retry")
        if receipt["cwd"] != str(folder) or receipt["executable_sha256"] != spec["real_tools"][name]["sha256"]:
            raise ValueError("actual native invocation binding changed")
        for key in ("stdout", "stderr"):
            raw = c.contained(folder / "native_receipts", receipt[key]["path"]).read_bytes()
            if c.sha(raw) != receipt[key]["sha256"] or len(raw) != receipt[key]["bytes"]:
                raise ValueError("native output journal bytes changed")
        for path, digest in receipt["source_input_sha256"].items():
            target = Path(path)
            if not target.is_relative_to(folder) or file_sha(target) != digest:
                raise ValueError("native input source/blob binding changed")
        result[name] = receipt
    if "iverilog" in result:
        receipt = result["iverilog"]
        if receipt["source_input_sha256"] != {str(folder / "candidate.sv"): candidate_sha, str(folder / "tb.sv"): tb_sha}:
            raise ValueError("both candidate and TB must bind actual compile input")
        artifact = receipt["artifacts"]["compiled"]
        blob = c.contained(folder / "native_receipts", artifact["path"]).read_bytes()
        if c.sha(blob) != artifact["sha256"] or artifact["original_path"] != str(folder / "compiled.vvp") or file_sha(folder / "compiled.vvp") != artifact["sha256"]:
            raise ValueError("compiled blob journal binding changed")
    if "vvp" in result:
        if result["vvp"]["source_input_sha256"] != {str(folder / "compiled.vvp"): result["iverilog"]["artifacts"]["compiled"]["sha256"]}:
            raise ValueError("simulation must consume exact compiled blob")
    return result


def recount_native(out, summary, require_complete=False):
    """Pure global receipt accounting; launch attempts cannot stand in for calls."""
    out = Path(out)
    classes = collections.Counter()
    total = 0
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(out).parts
        value = c.read(path) if path.suffix == ".json" else None
        native_shaped = isinstance(value, dict) and (value.get("schema") == "owned_native_journal_v1" or {"name", "argv", "source_input_sha256"}.issubset(value))
        if "native_receipts" not in parts and not native_shaped:
            continue
        if len(parts) != 3 or parts[0] not in c.ORDER or parts[1] != "native_receipts":
            raise ValueError("native evidence outside14 predetermined control directories")
        if path.suffix != ".json":
            continue
        receipt = value
        tool = receipt.get("name")
        if tool not in ("iverilog", "vvp"):
            raise ValueError("unknown global native tool receipt")
        classes[(parts[0], tool)] += 1
        if classes[(parts[0], tool)] != 1:
            raise ValueError("repeated global native tool receipt")
        total += 1
    for field in ("attempted_compile_commands", "attempted_simulation_commands"):
        if type(summary.get(field)) is not int or not 0 <= summary[field] <= 14:
            raise ValueError("invalid or excessive native attempts")
    confirmed_compiles = sum(count for (_, tool), count in classes.items() if tool == "iverilog")
    confirmed_sims = sum(count for (_, tool), count in classes.items() if tool == "vvp")
    if confirmed_compiles > summary["attempted_compile_commands"] or confirmed_sims > summary["attempted_simulation_commands"]:
        raise ValueError("confirmed calls exceed recorded attempts")
    summary.update(actual_compile_commands=confirmed_compiles, actual_simulation_commands=confirmed_sims,
                   global_native_receipts=total,
                   unconfirmed_native_attempts=summary["attempted_compile_commands"] + summary["attempted_simulation_commands"] - total)
    if require_complete:
        expected = collections.Counter({(label, tool): 1 for label in c.ORDER for tool in ("iverilog", "vvp")})
        if classes != expected or total != 28 or summary["attempted_compile_commands"] != 14 or summary["attempted_simulation_commands"] != 14 or summary["unconfirmed_native_attempts"] != 0 or "journal_count_error" in summary:
            raise ValueError("complete evidence requires28 confirmed receipts and14+14 attempts")


def final_accounting(out, summary):
    """A finally failure clears success and raises, overriding any pending rc0."""
    try:
        recount_native(out, summary, require_complete=summary.get("complete") is True)
    except BaseException as error:
        message = type(error).__name__ + ": " + str(error)
        prior = summary.get("error")
        summary.update(complete=False, evidence_complete=False,
                       qualified_for_generated_control_discrimination=False,
                       journal_count_error=message,
                       error=(prior + "; " if prior else "") + "journal_count_error: " + message)
        raise


def main(args):
    # ROOT/RUN_SPEC is supplied and frozen by the root task; this draft creates none.
    spec = c.read(ROOT / "RUN_SPEC.json")
    if sys.platform != "linux" or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise ValueError("Linux owned-process cleanup required")
    if str(ROOT) != spec["cloud_root"] or str(args.kit.resolve()) != spec["kit"] or os.environ["PATH"] != spec["inherited_path"]:
        raise ValueError("fixed deployment/runtime identity required")
    if spec["model_requests_max"] != 0 or spec["controls"] != 14 or spec["compiles_max"] != 14 or spec["simulations_max"] != 14:
        raise ValueError("fixed14/0model budget required")
    for name, digest in spec["source_hashes"].items():
        if file_sha(c.contained(ROOT, name)) != digest:
            raise ValueError("frozen source bytes changed")
    if args.resource_check.resolve() != (ROOT / "guard/resource_check.json").resolve():
        raise ValueError("own wholeFIFO guard resource admission required")
    dependencies(spec)
    private, prepared = c.validate_private(ROOT)
    inputs = c.read(ROOT / "INPUT_MANIFEST.json")
    loader = importlib.util.spec_from_file_location("own_native_reset_commands", Path(spec["dependencies_cloud"]) / "paired_checkpoint.py")
    paired = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(paired)
    paired.REPO = ROOT

    def admission(first=False):
        record = paired.check_resource(args.resource_check, args.kit, first=first)
        if record["model_identity"] != spec["model_identity"] or record["model_pid"] != spec["model_identity"]["pid"] or record["model_starttime"] != spec["model_identity"]["starttime"]:
            raise ValueError("protected shared model identity changed")
        for key in ("slot_owner", "slot_lock_path", "llm_base_url", "model_name"):
            if record[key] != spec[key]:
                raise ValueError("owned FIFO/resource identity changed")
        if record["protected"]["tasks"] != inputs["input_sha256"] or record["protected"]["official"] != inputs["official_sha256"]:
            raise ValueError("protected input/official resources changed")

    admission(first=True)
    out = ROOT / "results"
    out.mkdir(exist_ok=False)
    tools = ROOT / "tools/bin"
    tools.mkdir(parents=True, exist_ok=False)
    for name in ("iverilog", "vvp"):
        wrapper = tools / name
        wrapper.write_bytes((ROOT / "tool_journal.py").read_bytes())
        wrapper.chmod(0o755)
    rows = []
    summary = dict(schema="native_reset_generated_research_calibration_v1", complete=False,
                   evidence_complete=False, qualified_for_generated_control_discrimination=False,
                   error=None, rows=rows, run_spec_sha256=file_sha(ROOT / "RUN_SPEC.json"),
                   generated_research_test=True, original_harness=False,
                   model_calls=0, independent_model_tasks=0, independent_quality_admitted=0,
                   eligible_for_independent_models=False, adoption=False,
                   actual_compile_commands=0, actual_simulation_commands=0,
                   attempted_compile_commands=0, attempted_simulation_commands=0)
    tick = time.monotonic()
    try:
        # Materialize all controls before any native call; an existing result is refused.
        for control, contract, rtl, tb in prepared:
            folder = out / control["label"]
            folder.mkdir()
            (folder / "candidate.sv").write_bytes(rtl)
            (folder / "tb.sv").write_bytes(tb)
            c.save(folder / "SOURCE_MANIFEST.json", {"candidate.sv": c.sha(rtl), "tb.sv": c.sha(tb)})
        c.save(out / "PREPARED.json", dict(controls=14, all_materialized_before_execution=True))
        for control, contract, rtl, tb in prepared:
            folder = out / control["label"]
            journal = folder / "native_receipts"

            def gate():
                if time.monotonic() - tick >= spec["stage_timeout_s"] - 60:
                    raise ValueError("stage budget exhausted; no retry")
                admission()

            env = dict(PATH=str(tools) + ":" + spec["toolchain"]["prefix"] + "/bin:" + spec["inherited_path"],
                       PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0",
                       OWN_CALIBRATION_ROOT=str(ROOT), OWN_NATIVE_JOURNAL=str(journal))
            clean = ["/usr/bin/env", "-i", *[key + "=" + value for key, value in env.items()]]
            compile_args = ["-g2012", "-s", control["probe_module"], "-o", str(folder / "compiled.vvp"), str(folder / "candidate.sv"), str(folder / "tb.sv")]
            gate()
            summary["attempted_compile_commands"] += 1
            build = paired.owned_command(clean + [str(tools / "iverilog"), *compile_args], folder, folder / "compile.outer.log", spec["native_command_timeout_s"])
            if build["timeout"] or build["launch_error"] is not None or build["remaining_live_group"] or build["returncode"] != 0:
                raise ValueError("compile/tool failure; preserve evidence, never retry")
            receipts = native_receipts(folder, spec, c.sha(rtl), c.sha(tb))
            if set(receipts) != {"iverilog"} or receipts["iverilog"]["argv"] != [spec["real_tools"]["iverilog"]["path"], *compile_args] or receipts["iverilog"]["returncode"] != 0:
                raise ValueError("actual compile argv/rc count mismatch")
            summary["actual_compile_commands"] += 1
            gate()
            sim_args = [str(folder / "compiled.vvp")]
            summary["attempted_simulation_commands"] += 1
            sim = paired.owned_command(clean + [str(tools / "vvp"), *sim_args], folder, folder / "simulation.outer.log", spec["native_command_timeout_s"])
            if sim["timeout"] or sim["launch_error"] is not None or sim["remaining_live_group"]:
                raise ValueError("simulation/tool failure; preserve evidence, never retry")
            receipts = native_receipts(folder, spec, c.sha(rtl), c.sha(tb))
            if set(receipts) != {"iverilog", "vvp"} or receipts["vvp"]["argv"] != [spec["real_tools"]["vvp"]["path"], *sim_args] or receipts["vvp"]["returncode"] != sim["returncode"]:
                raise ValueError("actual simulation argv/rc count mismatch")
            summary["actual_simulation_commands"] += 1
            stdout = c.contained(journal, receipts["vvp"]["stdout"]["path"]).read_bytes().decode("utf-8")
            stderr = c.contained(journal, receipts["vvp"]["stderr"]["path"]).read_bytes().decode("utf-8")
            classified = c.classify(control, contract, stdout, stderr, sim["returncode"])
            c.save(folder / "PARSED.json", classified)
            rows.append(dict(index=control["index"], label=control["label"], intent=control["intent"],
                             generated_research_test=True, original_harness=False,
                             compile_outer=build, simulation_outer=sim,
                             compile_outer_argv=clean + [str(tools / "iverilog"), *compile_args],
                             simulation_outer_argv=clean + [str(tools / "vvp"), *sim_args],
                             parsed_sha256=file_sha(folder / "PARSED.json"),
                             control_matched=classified["control_matched"],
                             false_acceptance=classified["false_acceptance"],
                             checks=classified["parsed"]["checks"], mismatches=classified["parsed"]["mismatches"]))
            c.save(out / "summary.json", summary)
            if not classified["returncode_consistent"]:
                raise ValueError("unknown or contradictory native rc/trace outcome; no retry")
            if file_sha(folder / "candidate.sv") != c.sha(rtl) or file_sha(folder / "tb.sv") != c.sha(tb):
                raise ValueError("candidate/TB mutated during native calls")
        admission()
        dependencies(spec)
        for name, digest in spec["source_hashes"].items():
            if file_sha(c.contained(ROOT, name)) != digest:
                raise ValueError("frozen source changed after native controls")
        recount_native(out, summary, require_complete=True)
        if len(rows) != 14 or summary["actual_compile_commands"] != 14 or summary["actual_simulation_commands"] != 14:
            raise ValueError("incomplete14 measurement")
        summary.update(complete=True, evidence_complete=True,
                       qualified_for_generated_control_discrimination=all(row["control_matched"] for row in rows),
                       source_unchanged=True, dependencies_unchanged=True)
        return 0
    except BaseException as error:
        summary["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        try:
            final_accounting(out, summary)
        finally:
            summary["elapsed_s"] = time.monotonic() - tick
            c.save(out / "summary.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
