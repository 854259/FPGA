"""Frozen three-task same-response pilot; calibrate all controls before models."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import urllib.request

from extract_bundle import extract_bundle


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, d):
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")


def load(name, p):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    for name in ("root", "kit", "resource-check"):
        ap.add_argument("--" + name, type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    spec = read(root / "RUN_SPEC.json")
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    deps = Path(spec["dependencies_cloud"])
    paired = load("helper_owned", deps / "paired_checkpoint.py")
    paired.REPO, paired.INHERITED_ORACLE = root, deps / "probe_runner.py"
    baseline = load("helper_baseline", deps / "baseline_extract.py")
    lexical = load("helper_lexical", root / "lexical_mask.py")
    paired.check_resource(args.resource_check, args.kit, first=True)
    out = root / "results"
    out.mkdir(exist_ok=False)
    start, spec_hash = time.monotonic(), sha(root / "RUN_SPEC.json")
    report = dict(schema="helper_contract_same_response_v1", complete=False, verified=False, attempts=0,
        responses=0, retries=0, controls={}, control_synthesis={}, format_controls={}, rows=[], run_spec_sha256=spec_hash)
    save(out / "summary.json", report)

    def gate():
        assert time.monotonic() - start < spec["stage_timeout_s"]
        assert sha(root / "RUN_SPEC.json") == spec_hash
        for name, h in spec["source_hashes"].items():
            assert sha(root / name) == h, name
        for name, h in spec["dependency_hashes"].items():
            assert sha(deps / name) == h, name
        paired.check_resource(args.resource_check, args.kit)

    def probe(contract, source, folder):
        gate()
        r = paired.oracle(dict(task=contract["task"], checks=contract["checks"], tb="inputs/" + contract["task"] + "/tb.sv"), source, folder)
        if r["status"] == "environment_error":
            raise RuntimeError("Probe environment error")
        return r

    def synth(source, folder):
        gate()
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "dut.sv").write_bytes(source.read_bytes())
        (folder / "run.tcl").write_text('if {[catch {read_verilog -sv dut.sv; synth_design -top TopModule -part ' + spec["part"] + '} err]} {puts "HELPER_SYNTHESIS_FAIL: $err"; exit 1}\nputs "HELPER_SYNTHESIS_PASS"\nexit 0\n')
        r = paired.owned_command(["/workspace/AMD/2026.1/Vivado/bin/vivado", "-mode", "batch", "-source", "run.tcl", "-nolog", "-nojournal"], folder, folder / "synth.log", 90)
        assert r["returncode"] == 0 and not r["remaining_live_group"]
        assert "\nHELPER_SYNTHESIS_PASS\n" in (folder / "synth.log").read_text()
        return r

    try:
        for contract in spec["contracts"]:
            task = contract["task"]
            inputs = root / "inputs" / task
            controls = {}
            for name in ["positive"] + contract["negative_controls"]:
                p = probe(contract, inputs / (name + ".sv"), out / "controls" / task / name)
                assert p["checks"] == contract["checks"]
                assert p["status"] == ("pass" if name == "positive" else "fail")
                if name != "positive":
                    assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0
                controls[name] = p
            report["controls"][task] = controls
            report["control_synthesis"][task] = synth(inputs / "positive.sv", out / "control_synthesis" / task)
            text = (inputs / "positive.sv").read_text()
            a = baseline.extract(text, "rtl")
            b, receipt = extract_bundle(text, baseline, lexical._strip_noncode)
            assert b.encode() == (inputs / "positive.sv").read_bytes() and receipt["changed"]
            folder = out / "format_sources" / task
            folder.mkdir(parents=True)
            (folder / "A.sv").write_text(a)
            (folder / "B.sv").write_text(b)
            save(folder / "receipt.json", receipt)
            a_probe = probe(contract, folder / "A.sv", out / "format_probes" / task / "A")
            assert a_probe["status"] == "fail"
            report["format_controls"][task] = dict(receipt=receipt, A=a_probe,
                B=controls["positive"], B_reused_positive_exact_bytes=True,
                B_synthesis=report["control_synthesis"][task])
        save(out / "preflight_verified.json", dict(controls=report["controls"], control_synthesis=report["control_synthesis"], format_controls=report["format_controls"], model_calls=0))
        save(out / "summary.json", report)
        print(json.dumps(dict(phase="preflight_verified", model_calls=0)), flush=True)
        for task, trial in spec["generation_order"]:
            gate()
            paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
            folder = out / "generated" / task / str(trial)
            folder.mkdir(parents=True)
            payload = dict(model=spec["model"], temperature=0, top_p=1, max_tokens=spec["max_tokens"], messages=[dict(role="system", content=baseline.SYS["rtl"]), dict(role="user", content=(root / "inputs" / task / "prompt.txt").read_text())])
            save(folder / "request.json", payload)
            row = dict(task=task, trial=trial, request_sha256=sha(folder / "request.json"), response_received=False)
            report["rows"].append(row)
            report["attempts"] += 1
            assert report["attempts"] <= spec["model_call_budget"]
            save(out / "summary.json", report)
            tick = time.monotonic()
            request = urllib.request.Request("http://127.0.0.1:8000/v1/chat/completions", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=spec["request_timeout_s"]) as response:
                raw = response.read()
            (folder / "response.json").write_bytes(raw)
            data = json.loads(raw)
            choice = data["choices"][0]
            row.update(response_received=True, response_sha256=sha(folder / "response.json"), response_id=data.get("id"), usage=data.get("usage"), finish_reason=choice.get("finish_reason"), request_elapsed_s=time.monotonic() - tick)
            report["responses"] += 1
            content = choice["message"].get("content")
            assert choice.get("finish_reason") == "stop" and isinstance(content, str) and content.strip(), "Incomplete response: stop without retry"
            (folder / "answer.txt").write_text(content)
            a = baseline.extract(content, "rtl")
            b, receipt = extract_bundle(content, baseline, lexical._strip_noncode)
            (folder / "A.sv").write_text(a)
            (folder / "B.sv").write_text(b)
            save(folder / "bundle_receipt.json", receipt)
            row.update(A_sha256=sha(folder / "A.sv"), B_sha256=sha(folder / "B.sv"), bundle_changed=a != b, bundle_receipt=receipt)
            save(out / "summary.json", report)
            print(json.dumps(dict(phase="generated", count=report["responses"], task=task, trial=trial)), flush=True)
        save(out / "generation_complete.json", dict(rows=report["rows"], grading_started=False))
        contracts = {c["task"]: c for c in spec["contracts"]}
        for row in report["rows"]:
            folder = out / "generated" / row["task"] / str(row["trial"])
            row["grades"] = {}
            for arm in ("A", "B"):
                p = probe(contracts[row["task"]], folder / (arm + ".sv"), out / "generated_probes" / row["task"] / str(row["trial"]) / arm)
                result = dict(probe=p)
                if p["status"] == "pass":
                    if arm == "B" and not row["bundle_changed"]:
                        result.update(synthesis=row["grades"]["A"]["synthesis"], synthesis_reused_identical_bytes=True)
                    else:
                        result["synthesis"] = synth(folder / (arm + ".sv"), out / "generated_synthesis" / row["task"] / str(row["trial"]) / arm)
                row["grades"][arm] = result
            save(out / "summary.json", report)
            print(json.dumps(dict(phase="graded", task=row["task"], trial=row["trial"], A=row["grades"]["A"]["probe"]["status"], B=row["grades"]["B"]["probe"]["status"])), flush=True)
        gate()
        report["complete"] = True
        report["verified"] = report["attempts"] == report["responses"] == spec["model_call_budget"]
    except BaseException as e:
        report["error"] = type(e).__name__ + ": " + str(e)
    finally:
        report["elapsed_s"] = time.monotonic() - start
        save(out / "summary.json", report)
    print(json.dumps({k: report.get(k) for k in ("complete", "verified", "attempts", "responses", "error", "elapsed_s")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
