"""AMD-only isolated Icarus setup and official-example fixture controls; zero LLM."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run(a):
    assert sys.platform == "linux"
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    spec = json.loads((HERE / "CVDP_ENV_SPEC_20261004.json").read_text())
    for name, digest in spec["files"].items():
        assert sha(a.materials / name) == digest, name
    requirements = HERE / "CVDP_MINIMAL_REQUIREMENTS_20261004.txt"
    assert sha(requirements) == spec["requirements_sha256"]
    module_spec = importlib.util.spec_from_file_location(
        "cvdp_owned", REPO / "03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py")
    paired = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(paired)
    paired.check_resource(a.resource_check, a.kit, first=True)
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    result = dict(schema="cvdp_environment_controls_v1", complete=False, model_calls=0,
                  full_experiment_complete=False, independent_tasks_admitted=0,
                  source_commit=(REPO / "DELIVERY_COMMIT").read_text().strip(),
                  commands=[], controls=[], error=None)
    def publish(phase):
        result.update(phase=phase, elapsed_s=time.monotonic() - tick)
        save(a.out / "summary.json", result)
        print(json.dumps(dict(phase=phase, elapsed_s=result["elapsed_s"],
                              controls=len(result["controls"]), model_calls=0)), flush=True)
    def gate():
        paired.check_resource(a.resource_check, a.kit)
        if shutil.disk_usage(a.out).free < spec["minimum_free_gib"] * 1024**3:
            raise RuntimeError("disk reserve exhausted")
        if time.monotonic() - tick > spec["stop_new_work_after_s"]:
            raise TimeoutError("stop new work reserve")
    def command(name, argv, cwd, cap, env=None, allow_nonzero=False):
        gate()
        if env:
            argv = ["/usr/bin/env"] + [k + "=" + v for k, v in env.items()] + [str(x) for x in argv]
        receipt = paired.owned_command([str(x) for x in argv], cwd, a.out / (name + ".log"), cap)
        result["commands"].append(dict(name=name, **receipt))
        publish(name)
        if receipt.get("timeout") or receipt.get("launch_error") or receipt.get("remaining_live_group") != []:
            raise RuntimeError("command supervision failed: " + name)
        if not allow_nonzero and receipt["returncode"] != 0:
            raise RuntimeError("command failed: " + name)
        return receipt
    try:
        publish("source_hashes_verified")
        build_tools = a.out / "build_tools"
        build_tools.mkdir()
        for name in spec["files"]:
            if name.endswith(".deb"):
                command("unpack_" + name.split("_")[0],
                        ["dpkg-deb", "-x", a.materials / name, build_tools], a.out, 30)
        source = a.out / "source"
        source.mkdir()
        with tarfile.open(a.materials / "iverilog_v13_0_30a7d1a.tar.gz") as archive:
            for member in archive:
                if not (source / member.name).resolve().is_relative_to(source.resolve()):
                    raise RuntimeError("unsafe tar path")
            archive.extractall(source, filter="data")
        with zipfile.ZipFile(a.materials / "cvdp_tooling_8e894cf.zip") as archive:
            for name in archive.namelist():
                if not (source / name).resolve().is_relative_to(source.resolve()):
                    raise RuntimeError("unsafe zip path")
            archive.extractall(source)
        icarus = source / ("iverilog-" + spec["iverilog_commit"])
        upstream = source / ("cvdp_benchmark-" + spec["cvdp_tool_commit"])
        prefix = a.out / "toolchain"
        build_env = {
            "PATH": str(build_tools / "usr/bin") + ":" + os.environ["PATH"],
            "BISON_PKGDATADIR": str(build_tools / "usr/share/bison"),
            "LD_LIBRARY_PATH": str(build_tools / "usr/lib/x86_64-linux-gnu"),
            "CPPFLAGS": "-I" + str(build_tools / "usr/include"),
            "LDFLAGS": "-L" + str(build_tools / "usr/lib/x86_64-linux-gnu"),
        }
        command("autoconf", ["sh", "autoconf.sh"], icarus, 120, build_env)
        command("configure", ["sh", "configure", "--prefix=" + str(prefix)], icarus, 180, build_env)
        command("build", ["make", "-j" + str(spec["build_jobs"])], icarus, 1500, build_env)
        command("install_prefix", ["make", "install"], icarus, 120, build_env)
        site = a.out / "python_site"
        command("python_dependencies", [
            "/usr/bin/python3", "-m", "pip", "install", "--target", site,
            "--no-deps", "--no-cache-dir", "--only-binary=:all:", "--require-hashes",
            "--index-url", "https://pypi.org/simple", "-r", requirements], a.out, 300)
        env = {
            "PATH": str(prefix / "bin") + ":" + os.environ["PATH"],
            "PYTHONPATH": str(site),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "COCOTB_RANDOM_SEED": str(spec["seed"]),
        }
        command("iverilog_version", [prefix / "bin/iverilog", "-V"], a.out, 10, env)
        example = upstream / spec["example_file"]
        rows = [json.loads(line) for line in example.read_text().splitlines() if line.strip()]
        assert len(rows) == 1 and rows[0]["id"] == "cvdp_copilot_lfsr_0001"
        row = rows[0]
        original = row["output"]["context"]["rtl/lfsr_8bit.sv"]
        assert sha(a.controls) == spec["private_controls_sha256"]
        private = json.loads(a.controls.read_text())
        assert private["example_id"] == row["id"]
        assert hashlib.sha256(original.encode()).hexdigest() == private["original_sha256"]
        inverted = private["mutants"]["invert_output"]
        zero = private["mutants"]["stuck_zero"]
        source_hashes = {}
        for label, rtl in zip(spec["controls"], [original, inverted, zero]):
            folder = a.out / "controls" / label
            folder.mkdir(parents=True)
            for rel, content in row["harness"]["files"].items():
                target = folder / rel
                assert target.resolve().is_relative_to(folder.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            design = folder / "rtl/lfsr_8bit.sv"
            design.parent.mkdir()
            design.write_text(rtl)
            source_hashes[label] = {str(p.relative_to(folder)): sha(p)
                                    for p in folder.rglob("*") if p.is_file()}
        save(a.out / "CONTROL_MANIFEST.json", dict(example_sha256=sha(example),
             source_hashes=source_hashes, seed=spec["seed"], controls=spec["controls"]))
        publish("all_control_inputs_frozen")
        for label in spec["controls"]:
            folder = a.out / "controls" / label
            case_env = dict(env, SIM="icarus", TOPLEVEL_LANG="verilog",
                TOPLEVEL="lfsr_8bit", MODULE="test_lfsr",
                VERILOG_SOURCES=str(folder / "rtl/lfsr_8bit.sv"),
                PYTHONPATH=str(site) + ":" + str(folder / "src"))
            receipt = command(label, ["/usr/bin/python3", "-m", "pytest",
                "-q", "-p", "no:cacheprovider", "--junitxml=" + str(folder / "pytest.xml"),
                folder / "src/test_runner.py"], folder, 90, case_env, allow_nonzero=True)
            suites = []
            for xml in folder.rglob("*.xml"):
                if xml.name == "pytest.xml":
                    continue
                parsed = ET.parse(xml)
                cases = parsed.findall(".//testcase")
                if cases:
                    suites.append(dict(path=str(xml.relative_to(folder)), tests=len(cases),
                        failures=sum(c.find("failure") is not None for c in cases),
                        errors=sum(c.find("error") is not None for c in cases),
                        skipped=sum(c.find("skipped") is not None for c in cases)))
            tests = sum(x["tests"] for x in suites)
            failures = sum(x["failures"] + x["errors"] for x in suites)
            valid = tests == 3 and sum(x["skipped"] for x in suites) == 0
            passed = valid and receipt["returncode"] == 0 and failures == 0
            rejected = valid and receipt["returncode"] != 0 and failures > 0
            result["controls"].append(dict(label=label, complete_simulation=valid,
                reference_passed=passed if label == "original_reference" else None,
                negative_detected=rejected if label != "original_reference" else None,
                tests=tests, failures=failures, returncode=receipt["returncode"], suites=suites,
                expected_met=passed if label == "original_reference" else rejected))
            publish("observed_" + label)
        gate()
        result.update(complete=True, execution_valid=all(x["complete_simulation"] for x in result["controls"]),
            fixture_admission_passed=all(x["expected_met"] for x in result["controls"]),
            installed_scope="isolated Icarus and six pinned Python dependencies, not full official Docker image",
            toolchain=str(prefix), python_site=str(site), example_family_role="development_not_holdout",
            tool_files={str(p.relative_to(prefix)):sha(p) for p in prefix.rglob("*") if p.is_file()},
            package_metadata={p.parent.name:sha(p) for p in site.glob("*.dist-info/METADATA")})
        assert all(sha(a.materials / n) == h for n,h in spec["files"].items())
        assert all(sha(a.out/"controls"/label/rel) == h for label,files in source_hashes.items()
                   for rel,h in files.items())
        publish("completed_no_dataset_admission")
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        publish("finished" if result["complete"] else "failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["kit", "out", "resource-check", "materials", "controls"]:
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())
