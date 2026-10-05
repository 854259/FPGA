"""AMD-only evaluator diagnosis from a private frozen control manifest; no LLM."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run(a):
    assert sys.platform == "linux"
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    assert sha(a.freeze) == a.freeze_sha256
    spec = json.loads(a.freeze.read_text())
    assert spec["model_requests_max"] == 0
    assert len(spec["controls"]) == spec["compiles_max"] == spec["simulations_max"] == 3
    assert sha(spec["paired"]) == spec["paired_sha256"]
    module_spec = importlib.util.spec_from_file_location("owned", spec["paired"])
    paired = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(paired)
    paired.check_resource(a.resource_check, a.kit, first=True)
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    result = dict(schema="cvdp_false_acceptance_S7", complete=False,
                  source_commit=a.source_commit, private_freeze_sha256=a.freeze_sha256,
                  model_calls=0, independent_tasks_admitted=0, full_batch_complete=False,
                  diagnostic_families=1, controls=[], error=None)

    def publish(phase):
        result.update(phase=phase, elapsed_s=time.monotonic() - tick)
        save(a.out / "summary.json", result)
        print(json.dumps(dict(phase=phase, controls=len(result["controls"]),
                              elapsed_s=result["elapsed_s"])), flush=True)

    def gate():
        paired.check_resource(a.resource_check, a.kit)
        assert shutil.disk_usage(a.out).free > 2 * 1024**3
        assert time.monotonic() - tick < spec["stop_new_work_after_s"]

    def dependencies():
        assert sha(a.freeze) == a.freeze_sha256
        assert sha(spec["data"]) == spec["data_sha256"]
        assert sha(spec["paired"]) == spec["paired_sha256"]
        assert sha(spec["toolchain_manifest"]) == spec["toolchain_manifest_sha256"]
        installed = json.loads(Path(spec["toolchain_manifest"]).read_text())
        prefix = Path(installed["prefix"])
        assert {str(p.relative_to(prefix)): sha(p) for p in prefix.rglob("*")
                if p.is_file()} == installed["files"]
        site = Path(spec["python_site"])
        assert {str(p.relative_to(site)): sha(p) for p in site.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts} == spec["python_files"]
        return prefix, site

    try:
        publish("checking_frozen_dependencies")
        prefix, site = dependencies()
        rows = [json.loads(line) for line in Path(spec["data"]).read_text().splitlines() if line.strip()]
        selected = [r for r in rows if r["id"] == spec["record_id"]]
        assert len(selected) == 1
        row = selected[0]
        assert hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest() == spec["record_sha256"]
        assert {p: hashlib.sha256(s.encode()).hexdigest() for p, s in row["harness"]["files"].items()} == spec["harness_sha256"]
        source_hashes = {}
        for control in spec["controls"]:
            folder = a.out / control["label"]
            assert folder.resolve().is_relative_to(a.out.resolve())
            folder.mkdir()
            contents = dict(row["harness"]["files"])
            if control.get("test_override") is not None:
                assert control["label"] == "failure_propagation"
                contents[spec["test_path"]] = control["test_override"]
            contents[spec["rtl_path"]] = control["rtl"]
            for rel, content in contents.items():
                target = folder / rel
                assert target.resolve().is_relative_to(folder.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            source_hashes[control["label"]] = {rel: sha(folder / rel) for rel in contents}
        save(a.out / "CONTROL_MANIFEST.json", source_hashes)
        publish("all_three_controls_materialized_before_execution")
        for control in spec["controls"]:
            gate()
            label = control["label"]
            folder = a.out / label
            env = dict(PATH=str(prefix / "bin") + ":" + os.environ["PATH"],
                       PYTHONPATH=str(site) + ":" + str(folder / "src"),
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
                       PYTHONHASHSEED="0", COCOTB_RANDOM_SEED=str(spec["seed"]),
                       SIM="icarus", TOPLEVEL_LANG="verilog", TOPLEVEL=spec["top"],
                       MODULE=spec["module"], VERILOG_SOURCES=str(folder / spec["rtl_path"]))
            argv = ["/usr/bin/env"] + [k + "=" + v for k, v in env.items()] + [
                "/usr/bin/python3", "-B", "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
                "--junitxml=" + str(folder / "pytest.xml"), str(folder / "src/test_runner.py")]
            receipt = paired.owned_command(argv, folder, a.out / (label + ".log"), spec["command_timeout_s"])
            entry = dict(label=label, command=receipt)
            result["controls"].append(entry)
            publish("command_finished_" + label)
            assert not receipt.get("timeout") and not receipt.get("launch_error")
            assert receipt.get("remaining_live_group") == []
            suites = []
            for xml in folder.rglob("*.xml"):
                if xml.name == "pytest.xml":
                    continue
                cases = ET.parse(xml).findall(".//testcase")
                if cases:
                    suites.append(dict(path=str(xml.relative_to(folder)), tests=len(cases),
                        failures=sum(c.find("failure") is not None for c in cases),
                        errors=sum(c.find("error") is not None for c in cases),
                        skipped=sum(c.find("skipped") is not None for c in cases)))
            tests = sum(x["tests"] for x in suites)
            failures = sum(x["failures"] for x in suites)
            log = (a.out / (label + ".log")).read_text()
            valid = tests == spec["expected_tests"] and all(x["errors"] == x["skipped"] == 0 for x in suites)
            # A real simulator run must also have built an artifact and emitted the timed cocotb result.
            artifacts = list(folder.rglob("*.vvp"))
            valid = valid and bool(artifacts) and "TESTS=" in log and "SIM TIME" in log
            entry.update(suites=suites, valid_simulation=valid, tests=tests, failures=failures,
                         compiled_artifacts=[str(p.relative_to(folder)) for p in artifacts],
                         harness_original=control.get("test_override") is None)
            assert valid, "missing or invalid simulation evidence"
            passed = receipt["returncode"] == 0 and failures == 0
            failed = receipt["returncode"] != 0 and failures == 1
            entry.update(simulation_passed=passed, simulation_failed=failed,
                         expected_pattern_met=failed if control["expected_failures"] else passed)
            if label == "failure_propagation":
                entry["sentinel_observed"] = control["failure_marker"] in log
                assert failed and entry["sentinel_observed"], "failure propagation not established"
            else:
                assert passed or failed, "inconsistent XML and process return code"
                entry["known_wrong_accepted"] = passed
            publish("observed_" + label)
        gate()
        dependencies()
        assert all(sha(a.out / label / rel) == digest for label, files in source_hashes.items()
                   for rel, digest in files.items())
        result.update(complete=True, immutable_inputs_verified=True,
            failure_propagation_verified=result["controls"][0]["sentinel_observed"],
            false_acceptances=sum(x.get("known_wrong_accepted", False) for x in result["controls"]),
            actual_compile=len(result["controls"]), actual_sim=len(result["controls"]),
            conclusion="Evaluator diagnostic only; reject uncalibrated fixture admission, no solver result.")
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        publish("completed" if result["complete"] else "failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["kit", "out", "resource-check", "freeze"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    run(parser.parse_args())
