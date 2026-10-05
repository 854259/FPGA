"""Prepare an isolated evaluation-only valid-port regression on AMD."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def prepare(a):
    assert sys.platform == "linux" and not a.out.exists()
    assert digest(a.archive.read_bytes()) == "b2cee6bfd50e1b12cfd78246c767880b1f11ddd09324d3ca717cc322fe9f9acf"
    with zipfile.ZipFile(a.archive) as z:
        manifest = json.loads(z.read("ARCHIVE_MANIFEST.json"))
        assert set(z.namelist()) == set(manifest["files"]) | {"ARCHIVE_MANIFEST.json"}
        assert len(z.namelist()) == len(set(z.namelist()))
        for n, h in manifest["files"].items():
            assert digest(z.read(n)) == h
        spec = json.loads(z.read("run/RUN_SPEC.json"))
        assert digest(z.read("run/RUN_SPEC.json")) == "b423bb37761744a33bc5fe91d3ae0d847dc06d29862afe2ab090059c97154a68"
        controls = json.loads(z.read("run/raw_evidence/CONTROLS.json"))
        case = next(c for c in controls["cases"] if c["record_id"] == "cvdp_copilot_gray_to_binary_0001")
        assert len(case["controls"]) == 6 and case["expected_pytest_tests"] == 5
        records = [json.loads(s) for s in z.read("run/raw_evidence/ORIGINAL_DATASET.jsonl").decode().splitlines()]
        record = next(r for r in records if r["id"] == case["record_id"])
        tb = record["harness"]["files"][case["test_path"]]
        assert digest(tb.encode()) == "6cbaca22add7d1e367d4f2969d3b0953c691e5fb28de2095f1cf4e7465ea78ef"
        assert "Assert the validity signal" in record["input"]["prompt"]
        patched_tb = once(tb, "        # Assertions\n",
                          "        # Assertions\n        assert dut.valid.value == 1, \"VALID_MUST_BE_HIGH\"\n")
        stage = z.read("run/stage.py").decode()
        stage = once(stage, "spec['stage_timeout_s']==1200 and len(spec['record_ids'])==3",
                     "spec['stage_timeout_s']==600 and len(spec['record_ids'])==1")
        stage = once(stage, "            for control in case['controls']:",
                     "            original=dict(original)\n"
                     "            original[case['test_path']]=(ROOT/'corrected_test.py').read_text()\n"
                     "            for control in case['controls']:")
        stage = stage.replace("natural_harness_calibration_v1", "natural_valid_guard_regression_v1")
        stage = stage.replace("original_harness=label!='failure_propagation'", "original_harness=False")
        stage = stage.replace("natural_original_harness_calibration", "corrected_harness_calibration")
        stage = once(stage, "result['actual_compile']==result['actual_sim']==50",
                     "result['actual_compile']==result['actual_sim']==30")
        audit = z.read("run/audit.py").decode()
        audit = once(audit, "contents=dict(original['harness']['files']);contents[case['rtl_path']]=control['rtl']",
                     "contents=dict(original['harness']['files']);contents[case['rtl_path']]=control['rtl']\n"
                     "                contents[case['test_path']]=z.read('run/corrected_test.py').decode()")
        audit = once(audit, "                        suites.append(", "                        if control['label']=='valid_zero':assert failures==1 and 'VALID_MUST_BE_HIGH' in cases[0].find('failure').attrib['error_msg']\n"
                     "                        suites.append(")
        audit = audit.replace("original_harness=control['label']!='failure_propagation'", "original_harness=False")
        audit = once(audit, "total==50==summary['actual_compile']", "total==30==summary['actual_compile']")
        audit = audit.replace("natural_original_harness_calibration", "corrected_harness_calibration")
        audit = audit.replace("original_harness_calibration", "corrected_harness_calibration")
        audit = audit.replace("natural_harness_calibration_readonly_audit_v1", "natural_valid_guard_readonly_audit_v1")
        audit = audit.replace("This is original-harness discrimination", "This is corrected-harness discrimination")
        a.out.mkdir(parents=True)
        files = {n: z.read("run/" + n) for n in spec["source_hashes"] if n not in
                 ("stage.py", "audit.py", "prepare.py", "raw_evidence/CONTROLS.json")}
        files.update({"stage.py": stage.encode(), "audit.py": audit.encode(),
                      "prepare.py": Path(__file__).read_bytes(), "corrected_test.py": patched_tb.encode(),
                      "raw_evidence/CONTROLS.json": (json.dumps({"cases": [case]}, indent=2)+"\n").encode()})
        for n, content in files.items():
            p = a.out / n
            assert p.resolve().is_relative_to(a.out.resolve())
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        for n, h in spec["dependency_hashes"].items():
            content = z.read("dependencies/" + n)
            assert digest(content) == h
            p = a.out / "dependencies" / n
            assert p.resolve().is_relative_to(a.out.resolve())
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        spec.update(cloud_root=str(a.out), dependencies_cloud=str(a.out/"dependencies"),
                    record_ids=[case["record_id"]], stage_timeout_s=600,
                    source_hashes={n: digest(b) for n,b in files.items()},
                    original_archive_sha256=digest(a.archive.read_bytes()),
                    evaluation_only=True, independent_model_tasks=0,
                    declared_change="Assert required valid output after existing settle delay; no RTL/control/prompt changes.",
                    original_test_sha256=digest(tb.encode()), corrected_test_sha256=digest(patched_tb.encode()),
                    required_outcome="positive all5 pass, four wrong controls all5 fail, sentinel all5 fail")
        (a.out/"RUN_SPEC.json").write_text(json.dumps(spec, indent=2)+"\n")
        print(json.dumps({"root":str(a.out), "spec_sha256":digest((a.out/"RUN_SPEC.json").read_bytes()),
                          "stage_sha256":digest(stage.encode()), "audit_sha256":digest(audit.encode()),
                          "corrected_test_sha256":digest(patched_tb.encode()), "model_calls_max":0,
                          "expected_compiles":30, "expected_simulations":30}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    prepare(p.parse_args())
