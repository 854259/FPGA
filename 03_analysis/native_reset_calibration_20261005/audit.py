"""DRAFT read-only complete standalone native research evidence audit; no EDA."""
import argparse
import collections
import json
import zipfile
from pathlib import Path, PurePosixPath

import calibration as c
import native_reset_contract as native


def audit(archive, spec_sha):
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")

        def raw(name):
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name:
                raise ValueError("unsafe archive member")
            return z.read(name)

        def read(name):
            return json.loads(raw(name))

        manifest = read("ARCHIVE_MANIFEST.json")
        if set(names) != set(manifest["files"]) | {"ARCHIVE_MANIFEST.json"}:
            raise ValueError("archive completeness mismatch")
        for name, digest in manifest["files"].items():
            if c.sha(raw(name)) != digest:
                raise ValueError("archive file SHA mismatch")
        spec = read("run/RUN_SPEC.json")
        if c.sha(raw("run/RUN_SPEC.json")) != spec_sha or manifest["run_spec_sha256"] != spec_sha:
            raise ValueError("freeze spec binding changed")
        if c.sha(Path(__file__).read_bytes()) != spec["source_hashes"]["audit.py"]:
            raise ValueError("live auditor differs from frozen auditor")
        for name, module in (("calibration.py", c), ("native_reset_contract.py", native)):
            if c.sha(Path(module.__file__).read_bytes()) != spec["source_hashes"][name]:
                raise ValueError("live imported audit helper differs from frozen helper")
        for name, digest in spec["source_hashes"].items():
            if c.sha(raw("run/" + name)) != digest:
                raise ValueError("frozen source archive mismatch")
        if c.sha(raw("run/native_reset_contract.py")) != c.PARSER_SHA or c.sha(Path(native.__file__).read_bytes()) != c.PARSER_SHA:
            raise ValueError("delivered native parser byte binding changed")
        if c.sha(Path(c.__file__).read_bytes()) != spec["source_hashes"]["calibration.py"]:
            raise ValueError("live pure classifier differs from frozen classifier")
        for name, digest in spec["dependency_hashes"].items():
            if c.sha(raw("dependencies/" + name)) != digest:
                raise ValueError("frozen guard/command dependency mismatch")
        summary = read("run/results/summary.json")
        if summary["complete"] is not True or summary["evidence_complete"] is not True or summary["error"] is not None or summary["run_spec_sha256"] != spec_sha:
            raise ValueError("incomplete measured evidence")
        guard, resource = read("run/guard/status.json"), read("run/guard/resource_check.json")
        if not all(guard[key] for key in ("complete", "passed", "model_unchanged", "protected_files_unchanged", "own_slot_released")) or guard["stage_rc"] != 0 or not guard["owned_cleanup"]["verified"] or guard["owned_cleanup"]["remaining"]:
            raise ValueError("owned guard/protection/cleanup evidence incomplete")
        if resource["model_identity"] != spec["model_identity"] or resource["model_pid"] != spec["model_identity"]["pid"] or resource["model_starttime"] != spec["model_identity"]["starttime"]:
            raise ValueError("protected model identity mismatch")
        for key in ("slot_owner", "slot_lock_path", "llm_base_url", "model_name"):
            if resource[key] != spec[key]:
                raise ValueError("own FIFO/resource binding mismatch")
        inputs = read("run/INPUT_MANIFEST.json")
        if resource["protected"]["tasks"] != inputs["input_sha256"] or resource["protected"]["official"] != inputs["official_sha256"]:
            raise ValueError("protected input/official binding mismatch")
        if spec["model_requests_max"] != 0 or spec["controls"] != 14 or spec["compiles_max"] != 14 or spec["simulations_max"] != 14:
            raise ValueError("fixed14/0model budget changed")
        for name in ("iverilog", "vvp"):
            if c.sha(raw("run/tools/bin/" + name)) != spec["source_hashes"]["tool_journal.py"]:
                raise ValueError("actual transparent wrapper changed")
        private = read("run/raw_evidence/CONTROLS.json")
        controls = private["controls"]
        if tuple(control["label"] for control in controls) != c.ORDER or private["parser_sha256"] != c.PARSER_SHA or private["dataset_sha256"] != c.DATASET_SHA or private["generated_research_test"] is not True or private["original_harness"] is not False:
            raise ValueError("fixed private generated research controls changed")
        if [(row["index"], row["label"]) for row in summary["rows"]] != list(enumerate(c.ORDER)):
            raise ValueError("missing, duplicate or reordered14 result rows")
        # Independently inventory the entire results tree, including directories
        # absent from summary.rows. Extra/unknown calls cannot disappear from totals.
        global_receipt_names = []
        for name in names:
            parts = PurePosixPath(name).parts
            if parts[:2] != ("run", "results"):
                continue
            value = read(name) if name.endswith(".json") else None
            native_shaped = isinstance(value, dict) and (value.get("schema") == "owned_native_journal_v1" or {"name", "argv", "source_input_sha256"}.issubset(value))
            if "native_receipts" in parts[2:] or native_shaped:
                if len(parts) != 5 or parts[2] not in c.ORDER or parts[3] != "native_receipts":
                    raise ValueError("native evidence outside14 predetermined control directories")
                if name.endswith(".json"):
                    global_receipt_names.append(name)
        global_classes = collections.Counter()
        for name in global_receipt_names:
            receipt = read(name)
            tool = receipt.get("name")
            if tool not in ("iverilog", "vvp"):
                raise ValueError("unknown global native tool receipt")
            global_classes[(PurePosixPath(name).parts[2], tool)] += 1
        expected_classes = collections.Counter({(label, tool): 1 for label in c.ORDER for tool in ("iverilog", "vvp")})
        if len(global_receipt_names) != 28 or global_classes != expected_classes:
            raise ValueError("global native receipt count/classes must be exactly14x2")
        for field, expected in (("attempted_compile_commands", 14), ("attempted_simulation_commands", 14),
                                ("actual_compile_commands", 14), ("actual_simulation_commands", 14),
                                ("unconfirmed_native_attempts", 0)):
            if type(summary.get(field)) is not int or summary[field] != expected:
                raise ValueError("attempted/confirmed/global native totals inconsistent")
        if "journal_count_error" in summary:
            raise ValueError("native journal count error cannot qualify complete evidence")
        parsed_rows = []
        original_prompt, original_contract = None, None
        for control, row in zip(controls, summary["rows"]):
            c.validate_control_metadata(control, control["index"])
            base = "run/results/" + control["label"] + "/"
            folder = spec["cloud_root"] + "/results/" + control["label"]
            prompt = raw("run/" + control["prompt_path"])
            rtl = raw("run/" + control["rtl_path"])
            if c.sha(prompt) != control["prompt_sha256"] or c.sha(rtl) != control["rtl_sha256"]:
                raise ValueError("public prompt/control bytes changed")
            if control["label"] != "positive_renamed" and c.sha(prompt) != c.ORIGINAL_PROMPT_SHA:
                raise ValueError("original public prompt byte binding changed")
            contract = native.parse(prompt.decode("utf-8"))
            if contract["status"] != "supported" or contract["module"] != control["module"] or contract["roles"] != control["roles"] or contract["checks"] != 69:
                raise ValueError("complete original/renamed native prompt binding mismatch")
            if control["label"] == "positive":
                original_prompt, original_contract = prompt, contract
            if control["label"] == "positive_renamed":
                c.validate_renamed_prompt(original_prompt, prompt, original_contract, contract)
            tb = c.planned_tb(contract, control).encode("utf-8")
            if c.sha(tb) != control["tb_sha256"] or raw("run/" + control["tb_path"]) != tb:
                raise ValueError("generated research TB changed")
            hashes = {"candidate.sv": c.sha(rtl), "tb.sv": c.sha(tb)}
            if read(base + "SOURCE_MANIFEST.json") != hashes or raw(base + "candidate.sv") != rtl or raw(base + "tb.sv") != tb:
                raise ValueError("actual materialized source binding mismatch")
            env = dict(PATH=spec["cloud_root"] + "/tools/bin:" + spec["toolchain"]["prefix"] + "/bin:" + spec["inherited_path"],
                       PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0",
                       OWN_CALIBRATION_ROOT=spec["cloud_root"], OWN_NATIVE_JOURNAL=folder + "/native_receipts")
            clean = ["/usr/bin/env", "-i", *[key + "=" + value for key, value in env.items()]]
            compile_args = ["-g2012", "-s", control["probe_module"], "-o", folder + "/compiled.vvp", folder + "/candidate.sv", folder + "/tb.sv"]
            sim_args = [folder + "/compiled.vvp"]
            for key, tool, arguments, logfile in (("compile_outer", "iverilog", compile_args, "compile.outer.log"),
                                                   ("simulation_outer", "vvp", sim_args, "simulation.outer.log")):
                command = row[key]
                if row[key + "_argv"] != clean + [spec["cloud_root"] + "/tools/bin/" + tool, *arguments]:
                    raise ValueError("clean-environment outer argv changed")
                output = raw(base + logfile)
                if command["log"] != folder + "/" + logfile or c.sha(output) != command["log_sha256"] or len(output) != command["log_bytes"] or command["timeout"] or command["launch_error"] is not None or command["remaining_live_group"]:
                    raise ValueError("actual outer command output/completion mismatch")
            receipts = [read(name) for name in sorted(global_receipt_names) if name.startswith(base + "native_receipts/")]
            if len(receipts) != 2 or {receipt["name"] for receipt in receipts} != {"iverilog", "vvp"}:
                raise ValueError("unknown/repeated/missing native call")
            native_calls = {receipt["name"]: receipt for receipt in receipts}
            for tool, arguments in (("iverilog", compile_args), ("vvp", sim_args)):
                receipt = native_calls[tool]
                if receipt["argv"] != [spec["real_tools"][tool]["path"], *arguments] or receipt["cwd"] != folder or receipt["executable_sha256"] != spec["real_tools"][tool]["sha256"] or receipt["xmls"]:
                    raise ValueError("actual standalone argv/tool/output binding mismatch")
                for key in ("stdout", "stderr"):
                    data = raw(base + "native_receipts/" + receipt[key]["path"])
                    if c.sha(data) != receipt[key]["sha256"] or len(data) != receipt[key]["bytes"]:
                        raise ValueError("full native stdout/stderr hash mismatch")
            build, sim = native_calls["iverilog"], native_calls["vvp"]
            if type(build["returncode"]) is not int or build["returncode"] != 0 or type(row["compile_outer"]["returncode"]) is not int or row["compile_outer"]["returncode"] != 0 or build["source_input_sha256"] != {folder + "/candidate.sv": hashes["candidate.sv"], folder + "/tb.sv": hashes["tb.sv"]}:
                raise ValueError("candidate and TB actual compile inputs/rc mismatch")
            artifact = build["artifacts"]["compiled"]
            compiled = raw(base + "native_receipts/" + artifact["path"])
            if not compiled.startswith(b"#!") or c.sha(compiled) != artifact["sha256"] or raw(base + "compiled.vvp") != compiled or artifact["original_path"] != folder + "/compiled.vvp":
                raise ValueError("full compiled blob binding mismatch")
            if sim["source_input_sha256"] != {folder + "/compiled.vvp": artifact["sha256"]} or sim["started_ns"] < build["started_ns"] or sim["returncode"] != row["simulation_outer"]["returncode"]:
                raise ValueError("actual simulation input/timing/rc mismatch")
            stdout = raw(base + "native_receipts/" + sim["stdout"]["path"]).decode("utf-8")
            stderr = raw(base + "native_receipts/" + sim["stderr"]["path"]).decode("utf-8")
            classified = c.classify(control, contract, stdout, stderr, sim["returncode"])
            parsed = read(base + "PARSED.json")
            if classified != parsed or c.sha(raw(base + "PARSED.json")) != row["parsed_sha256"] or not classified["returncode_consistent"]:
                raise ValueError("complete actual69/both-output/rc parsed binding mismatch")
            if row["intent"] != control["intent"] or row["control_matched"] != classified["control_matched"] or row["false_acceptance"] != classified["false_acceptance"] or row["checks"] != 69 or row["mismatches"] != classified["parsed"]["mismatches"] or row["generated_research_test"] is not True or row["original_harness"] is not False:
                raise ValueError("control measurement/qualification binding mismatch")
            parsed_rows.append(dict(label=control["label"], intent=control["intent"], returncode=sim["returncode"],
                                    checks=69, retained_scalar_actual_values=138,
                                    mismatches=classified["parsed"]["mismatches"],
                                    control_matched=classified["control_matched"], false_acceptance=classified["false_acceptance"]))
        qualified = all(row["control_matched"] for row in parsed_rows)
        if summary["qualified_for_generated_control_discrimination"] != qualified or summary["actual_compile_commands"] != 14 or summary["actual_simulation_commands"] != 14:
            raise ValueError("measurement totals/qualification recomputation mismatch")
        if summary["model_calls"] != 0 or summary["independent_model_tasks"] != 0 or summary["independent_quality_admitted"] != 0 or summary["eligible_for_independent_models"] is not False or summary["adoption"] is not False or summary["generated_research_test"] is not True or summary["original_harness"] is not False or not summary["source_unchanged"] or not summary["dependencies_unchanged"]:
            raise ValueError("zero model/quality and research provenance changed")
        return dict(evidence_complete=True, qualified_for_generated_control_discrimination=qualified,
                    archive_sha256=c.sha(Path(archive).read_bytes()), spec_sha256=spec_sha,
                    native_compile_commands=14, native_simulation_commands=14,
                    global_native_receipts=28, attempted_compile_commands=14,
                    attempted_simulation_commands=14, unconfirmed_native_attempts=0,
                    generated_research_test=True, original_harness=False, controls=parsed_rows,
                    audit_model_calls=0, audit_eda_calls=0, model_calls=0,
                    independent_quality_admitted=0, eligible_for_independent_models=False, adoption=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--spec-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive, args.spec_sha)
    args.out.mkdir(exist_ok=False)
    c.save(args.out / "RESULTS.json", result)
    print(json.dumps(result, indent=2))
