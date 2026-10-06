"""AMD-only isolated formal-tool admission; constructed controls, no model/data corpus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

WHEELS = {
    "yowasp_yosys-0.69.0.0.post1233-py3-none-any.whl": "59284760d6455b764fce5dcf296d2c183b05dc980f59092461deddc9caa09bdd",
    "yowasp_runtime-1.96-py3-none-any.whl": "4ff456a4a6dff9d689c7feac9f68fb1492bed4cf873450d7b41259fa31645783",
    "wasmtime-47.0.1-py3-none-manylinux1_x86_64.whl": "9724600b036c6e95c4fe952e29fad83b4f02bdc11d23f25c4ee3ffff2c1d7257",
    "platformdirs-4.9.4-py3-none-any.whl": "68a9a4619a666ea6439f2ff250c12a853cd1cbd5158d258bd824a7df6be2f868",
    "click-8.3.1-py3-none-any.whl": "981153a64e25f12d547d3426c367a4857371575ee7ad18df2a6183ab0545b2a6",
}
COMB = """module top(input [3:0] a,b);
wire [4:0] reference_value = {1'b0,a}+{1'b0,b};
REPLACEMENT
always @* assert(dut_value === reference_value);
endmodule
"""
SEQUENTIAL = """module top(input clk, en);
reg [2:0] count = 0;
reg parity = 0;
always @(posedge clk) if(en) begin
  count <= count + 1'b1;
  parity <= ~parity;
end
always @* assert(parity == count[0]);
endmodule
"""
DELAYED = """module top(input clk);
reg [4:0] count = 0;
always @(posedge clk) count <= count + 1'b1;
always @* assert(count != 5'd12);
endmodule
"""
# Entire set and classifications frozen before execution. No candidate or task-specific RTL.
CASES = [
    ("comb_equivalent", COMB.replace("REPLACEMENT", "wire [4:0] dut_value = {1'b0,b}+{1'b0,a};"), "comb", "proved"),
    ("comb_missing_carry", COMB.replace("REPLACEMENT", "wire [3:0] narrow = a+b; wire [4:0] dut_value={1'b0,narrow};"), "comb", "counterexample"),
    ("comb_unknown_output", COMB.replace("REPLACEMENT", "wire [4:0] dut_value = 5'bxxxxx;"), "comb", "counterexample"),
    ("undriven_output", COMB.replace("REPLACEMENT", "wire [4:0] dut_value;"), "comb", "tool_error"),
    ("missing_dependency", COMB.replace("REPLACEMENT", "wire [4:0] dut_value; absent_dependency u(a,b,dut_value);"), "comb", "tool_error"),
    ("sequential_induction", SEQUENTIAL, "induction", "proved"),
    ("delayed_bounded", DELAYED, "bounded", "bounded_pass"),
    ("delayed_induction", DELAYED, "induction", "counterexample"),
]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def run(command, root, name, timeout_s, env):
    """Bound each owned process group by elapsed time and observed aggregate RSS."""
    start = time.monotonic()
    peak = 0
    stopped = None
    with (root / (name + ".log")).open("wb") as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while child.poll() is None:
                rss = 0
                for proc in Path("/proc").iterdir():
                    if not proc.name.isdigit():
                        continue
                    try:
                        stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
                        if int(stat[2]) == child.pid:
                            rss += int(stat[21]) * os.sysconf("SC_PAGE_SIZE")
                    except (FileNotFoundError, ProcessLookupError, PermissionError):
                        continue
                peak = max(peak, rss)
                if time.monotonic() - start > timeout_s:
                    stopped = "timeout"
                elif rss > 2 * 1024**3:
                    stopped = "memory_limit"
                if stopped:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    break
                time.sleep(0.1)
            rc = child.wait(timeout=10)
        finally:
            # No inherited descendants may outlive this particular subprocess.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=10)
    row = dict(command=command, returncode=rc, termination=stopped,
               elapsed_s=time.monotonic()-start, observed_peak_group_rss_bytes=peak)
    save(root / (name + ".json"), row)
    return row, (root / (name + ".log")).read_text(errors="replace")


def classify(row, log, mode):
    if row["termination"]:
        return row["termination"]
    if "Interrupted SAT solver: TIMEOUT!" in log:
        return "timeout"
    if row["returncode"] != 0:
        if ("SAT proof finished - model found: FAIL!" in log or
                "SAT temporal induction proof finished - model found for base case: FAIL!" in log):
            return "counterexample"
        if "Reached maximum number of time steps -> proof failed." in log:
            return "inconclusive"
        return "tool_error"
    if mode == "induction":
        return "proved" if "Induction step proven: SUCCESS!" in log else "unconfirmed"
    if "SAT proof finished - no model found: SUCCESS!" in log:
        return "bounded_pass" if mode == "bounded" else "proved"
    return "unconfirmed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wheels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resource-check", type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    if sys.platform != "linux" or not json.loads(args.resource_check.read_text()):
        raise RuntimeError("AMD Linux resource admission required")
    if shutil.disk_usage(args.out.parent).free < 2 * 1024**3:
        raise RuntimeError("less than 2 GiB free before isolated admission")
    # A failed induction step alone is not a reachable counterexample; bounded success
    # is not an inductive proof. These are parser controls, not real proof results.
    parser_cases = [
        (1, "Reached maximum number of time steps -> proof failed.", "induction", "inconclusive"),
        (1, "Interrupted SAT solver: TIMEOUT!", "induction", "timeout"),
        (0, "SAT proof finished - no model found: SUCCESS!", "bounded", "bounded_pass"),
        (0, "SAT proof finished - no model found: SUCCESS!", "induction", "unconfirmed"),
        (0, "", "comb", "unconfirmed"),
    ]
    for rc, log, mode, expected in parser_cases:
        assert classify(dict(termination=None, returncode=rc), log, mode) == expected
    wheels = args.wheels.resolve()
    for name, sha in WHEELS.items():
        if hashlib.sha256((wheels / name).read_bytes()).hexdigest() != sha:
            raise RuntimeError("frozen wheel drift: " + name)
    args.out.mkdir(exist_ok=False)
    root = args.out.resolve()
    tool, cache, temp = (root / name for name in ["tool", "cache", "tmp"])
    temp.mkdir()
    cpus = sorted(os.sched_getaffinity(0))[:2]
    os.sched_setaffinity(0, cpus)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               PIP_CONFIG_FILE="/dev/null", TMPDIR=str(temp), RAYON_NUM_THREADS="2")
    rows = []
    report = dict(schema="strict_formal_tool_20261006_v1", complete=False,
                  model_calls=0, corpus_tasks_opened=0, independent_admitted=0,
                  full_batch_complete=False, cpu_affinity=cpus, controls=rows,
                  yosys_invocations=0, wheel_sha256=WHEELS,
                  parser_controls=len(parser_cases),
                  scope="Constructed two-state finite-width proof controls only; "
                        "not official simulation or general sequential/SV admission.")
    try:
        row, _ = run([sys.executable, "-B", "-m", "pip", "install", "--no-index",
                      "--no-deps", "--no-compile", "--no-cache-dir",
                      "--target", str(tool), *[str(wheels / n) for n in WHEELS]],
                     root, "offline_install", 90, env)
        if row["termination"] or row["returncode"] != 0:
            raise RuntimeError("isolated offline installation failed")
        # Only this child environment can see the new packages or WASM mount.
        env.update(PYTHONPATH=str(tool), YOWASP_CACHE_DIR=str(cache),
                   YOWASP_MOUNT="/work=" + str(root))
        exe = [sys.executable, "-B", str(tool / "bin/yowasp-yosys")]
        row, version = run(exe + ["-V"], root, "version", 360, env)
        report["yosys_invocations"] += 1
        if row["termination"] or row["returncode"] or "Yosys 0.69" not in version:
            raise RuntimeError("pinned Yosys could not start")
        report["version_output"] = version.strip()
        for name, text, mode, expected in CASES:
            rtl = root / (name + ".sv")
            rtl.write_text(text)
            script = ("read_verilog -formal -sv /work/" + rtl.name + "; "
                      "hierarchy -check -top top; proc; flatten; opt; "
                      "dffunmap; chformal -lower; check -assert; ")
            proof = "sat -enable_undef -set-def-inputs -verify -prove-asserts -timeout 30"
            if mode == "induction":
                proof += " -seq 1 -tempinduct -maxsteps 16"
            elif mode == "bounded":
                proof += " -seq 4"
            script += proof
            (root / (name + ".ys")).write_text(script + "\n")
            row, log = run(exe + ["-s", "/work/" + name + ".ys"],
                           root, name, 60, env)
            report["yosys_invocations"] += 1
            actual = classify(row, log, mode)
            rows.append(dict(name=name, mode=mode, expected=expected, actual=actual,
                             complete_proof=(actual == "proved"),
                             source_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),
                             elapsed_s=row["elapsed_s"],
                             peak_rss_bytes=row["observed_peak_group_rss_bytes"]))
            if actual != expected:
                raise RuntimeError("frozen control failed: " + name)
        report["complete"] = True
        report["decision"] = ("Tool route only: next audit complete contracts, reference "
                              "trust, source families and independent exposure; no corpus admission.")
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["elapsed_s"] = time.monotonic()-started
        report["installed_files"] = {
            str(p.relative_to(tool)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tool.rglob("*") if p.is_file()
        } if tool.exists() else {}
        # Cache is a retained runtime dependency. Only task-owned empty temp dirs are removed.
        for path in sorted(temp.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        if temp.exists() and not any(temp.iterdir()):
            temp.rmdir()
        report["temporary_residue"] = [str(p.relative_to(root)) for p in temp.rglob("*")]
        save(root / "RESULT.json", report)


if __name__ == "__main__":
    main()
