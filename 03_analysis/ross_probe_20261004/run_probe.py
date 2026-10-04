"""Collect original logs and reports in isolated, owned Vivado subprocesses."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_one(root, spec, name, config, mode="lint"):
    case = spec["inputs"][name]
    source = root / case["file"]
    if sha(source) != case["sha256"]:
        raise RuntimeError("frozen input changed: " + name)
    directory = root / "results" / (name + "__" + config + "__" + mode)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "candidate.sv").write_bytes(source.read_bytes())
    command = ['set_param general.maxThreads 2', 'read_verilog -sv candidate.sv']
    if config == "official_csv_option":
        command.insert(1, spec["csv_option"])
    command.append('synth_design -top ' + case["top"] + ' -part ' + spec["part"] +
                   (' -lint -file linter.csv' if mode == "lint" else ''))
    script = ('puts "PROBE_VERSION:[version -short]"\n'
              'if {[catch {\n' + '\n'.join(command) +
              '\n} problem]} { puts "PROBE_ERROR:$problem"; exit 2 }\n'
              'puts "PROBE_COMPLETE"\nexit 0\n')
    (directory / "probe.tcl").write_text(script, encoding="utf-8")
    executable = os.environ["VIVADO_BIN"] + "/vivado"
    start = time.monotonic()
    with (directory / "stdout.log").open("xb") as log:
        result = subprocess.run([executable, "-mode", "batch", "-nojournal", "-nolog", "-source", "probe.tcl"],
                                cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                timeout=spec["timeout_s_per_run"])
    elapsed = time.monotonic() - start
    log_text = (directory / "stdout.log").read_text(errors="replace")
    counts = [int(x) for x in re.findall(r'Total of (\d+) linter message\(s\) generated', log_text)]
    report = directory / "linter.csv"
    messages = [x for x in log_text.splitlines() if re.match(r'^(?:ERROR|CRITICAL WARNING|WARNING): \[(?:Synth|Common|Place|Route) ', x)]
    row = dict(case=name, role=case["role"], configuration=config, mode=mode,
               source_sha256=sha(source), run_source_sha256=sha(directory / "candidate.sv"),
               tcl_sha256=sha(directory / "probe.tcl"), log_sha256=sha(directory / "stdout.log"),
               rc=result.returncode, elapsed_s=elapsed, marker_complete="PROBE_COMPLETE" in log_text,
               linter_counts=counts, tool_messages=messages, report_exists=report.exists(),
               report_bytes=report.stat().st_size if report.exists() else 0,
               report_sha256=sha(report) if report.exists() else None)
    row["tool_execution_valid"] = (result.returncode == 0 and row["marker_complete"] and
                                    not any(x.startswith("ERROR:") for x in messages) and
                                    (mode != "lint" or (report.exists() and len(counts) == 1)))
    save(directory / "result.json", row)
    print(json.dumps({"case": name, "config": config, "mode": mode, "rc": row["rc"],
                      "count": counts, "seconds": round(elapsed, 2), "messages": len(messages)}), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    check = json.loads(args.resource_check.read_text())
    if check.get("resource_idle") is not True or check.get("model_name") != "Qwen3.6-27B-Q4_K_M":
        raise RuntimeError("guard admission absent or wrong")
    spec = json.loads((root / "RUN_SPEC.json").read_text())
    before = {p: sha(root / x["file"]) for p, x in spec["inputs"].items()}
    rows = []
    for config in spec["configurations"]:
        for name in spec["inputs"]:
            rows.append(run_one(root, spec, name, config))
            save(root / "progress.json", dict(complete=False, rows=rows))
            if not rows[-1]["tool_execution_valid"]:
                save(root / "summary.json", dict(complete=False, failure="tool execution invalid", rows=rows))
                return 1
    rows.append(run_one(root, spec, "old_faults", "archived_default", "synthesis"))
    unchanged = before == {p: sha(root / x["file"]) for p, x in spec["inputs"].items()}
    summary = dict(schema="ross_vivado_lint_raw_probe_v1", complete=True, model_calls=0,
                   inputs_unchanged=unchanged, rows=rows,
                   tool_execution_valid=all(x["tool_execution_valid"] for x in rows))
    save(root / "summary.json", summary)
    return 0 if unchanged and summary["tool_execution_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
