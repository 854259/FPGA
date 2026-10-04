"""Frozen 12-case A/raw-B/guarded-C challenge; zero model requests."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

from extract_bundle import extract_bundle
from guarded_bundle import decide


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, obj):
    p.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    for key in ("root", "kit", "resource-check"):
        ap.add_argument("--" + key, type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    spec = read(root / "RUN_SPEC.json")
    deps = Path(spec["dependencies_cloud"])
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    paired = load("guard_owned", deps / "paired_checkpoint.py")
    paired.REPO, paired.INHERITED_ORACLE = root, deps / "probe_runner.py"
    baseline = load("guard_baseline", deps / "baseline_extract.py")
    lexical = load("guard_lexical", root / "lexical_mask.py")
    paired.check_resource(args.resource_check, args.kit, first=True)
    out = root / "results"
    out.mkdir(exist_ok=False)
    start, spec_hash = time.monotonic(), sha(root / "RUN_SPEC.json")
    report = dict(schema="bundle_guard_challenge_v1", complete=False, verified=False,
                  model_calls=0, controls={}, rows=[], actual_probes=0, gate_commands=0,
                  run_spec_sha256=spec_hash)

    def gate():
        assert time.monotonic() - start < spec["stage_timeout_s"]
        assert sha(root / "RUN_SPEC.json") == spec_hash
        for name, digest in spec["source_hashes"].items():
            assert sha(root / name) == digest, name
        for name, digest in spec["dependency_hashes"].items():
            assert sha(deps / name) == digest, name
        paired.check_resource(args.resource_check, args.kit)

    def probe(task, source, folder):
        gate()
        p = paired.oracle(dict(task=task, checks=spec["checks"][task],
                              tb="inputs/" + task + "/tb.sv"), source, folder)
        report["actual_probes"] += 1
        if p["status"] == "environment_error":
            raise RuntimeError("Probe environment error")
        return p

    try:
        for task in spec["checks"]:
            pair = {}
            for name in ("positive", "negative"):
                p = probe(task, root / "inputs" / task / (name + ".sv"),
                          out / "controls" / task / name)
                assert p["checks"] == spec["checks"][task]
                assert p["status"] == ("pass" if name == "positive" else "fail")
                if name == "negative":
                    assert p["failure_kind"] == "semantic_mismatch" and p["mismatches"] > 0
                pair[name] = p
            report["controls"][task] = pair
        for case in spec["cases"]:
            gate()
            text = (root / case["answer"]).read_text(encoding="utf-8")
            a = baseline.extract(text, "rtl")
            b, raw = extract_bundle(text, baseline, lexical._strip_noncode)
            folder = out / "sources" / case["id"]
            folder.mkdir(parents=True)
            # This decision is made solely from reply bytes plus candidate tools,
            # before any A/B/C functional probe for this case.
            c, guarded = decide(text, baseline, lexical._strip_noncode, paired,
                                out / "candidate_gates" / case["id"], os.environ["VIVADO_BIN"])
            report["gate_commands"] += len(guarded.get("stages", []))
            row = dict(id=case["id"], task=case["task"], kind=case["kind"],
                       raw=raw, guarded=guarded, probes={})
            report["rows"].append(row)
            save(folder / "receipt.json", dict(raw=raw, guarded=guarded))
            for arm, code in (("A", a), ("B", b), ("C", c)):
                p = folder / (arm + ".sv")
                p.write_text(code, encoding="utf-8")
                row[arm + "_sha256"] = sha(p)
                row["probes"][arm] = probe(case["task"], p, out / "probes" / case["id"] / arm)
            save(out / "summary.json", report)
            print(json.dumps(dict(case=case["id"], decision=guarded["decision"],
                                  grades={k: v["status"] for k, v in row["probes"].items()})), flush=True)
        report["complete"] = True
        report["expectations_met"] = all(
            row["guarded"]["decision"] == case["C_decision"] and
            all(row["probes"][arm]["status"] == grade for arm, grade in case["expected"].items())
            for row, case in zip(report["rows"], spec["cases"]))
        report["verified"] = report["expectations_met"] and len(report["rows"]) == len(spec["cases"])
        gate()
    except BaseException as e:
        report["error"] = type(e).__name__ + ": " + str(e)
    finally:
        report["elapsed_s"] = time.monotonic() - start
        save(out / "summary.json", report)
    print(json.dumps({k: report.get(k) for k in ("complete", "verified", "error", "elapsed_s")}), flush=True)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
