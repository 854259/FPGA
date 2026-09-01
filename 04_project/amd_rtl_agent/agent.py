#!/usr/bin/env python3
"""Minimal offline RTL generation and Vivado feedback loop.

The baseline is deliberately strict: one model call, a user message containing
only the problem, no skill text, no retry, and no EDA tool call.  The agent path
uses the same model settings and may run Vivado plus at most two repairs.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_VIVADO_BIN = Path(r"F:\vivado\2025.2\Vivado\bin")
STAGE_ORDER = {"not_checked": 0, "format": 1, "compile": 2, "elaboration": 3,
               "simulation": 4, "synthesis": 5}
_MOCK_CACHE: dict[str, dict[str, object]] = {}


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def model_settings() -> dict[str, object]:
    return {
        "model": os.environ.get("LLM_MODEL", "local-model"),
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "context": int(os.environ.get("LLM_CONTEXT", "8192")),
    }


def _next_mock(path: str) -> str:
    state = _MOCK_CACHE.get(path)
    if state is None:
        raw = read_text(path)
        try:
            parsed = json.loads(raw)
            responses = parsed.get("responses") if isinstance(parsed, dict) else parsed
            if not isinstance(responses, list) or not all(isinstance(x, str) for x in responses):
                raise ValueError("mock JSON must be a string array or {responses: [...]}")
        except json.JSONDecodeError:
            responses = [raw]
        if not responses:
            raise ValueError("mock response file is empty")
        state = {"responses": responses, "index": 0}
        _MOCK_CACHE[path] = state
    responses = state["responses"]
    index = int(state["index"])
    state["index"] = index + 1
    return responses[index % len(responses)]


def call_model(messages: list[dict[str, str]], seed: int) -> str:
    """Call one OpenAI-compatible completion; mock mode is for deterministic tests."""
    mock_file = os.environ.get("LLM_MOCK_FILE")
    if mock_file:
        return _next_mock(mock_file)

    settings = model_settings()
    body = {
        "model": settings["model"],
        "messages": messages,
        "max_tokens": settings["max_tokens"],
        "temperature": settings["temperature"],
        "seed": seed,
        "stream": False,
    }
    base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = int(os.environ.get("LLM_TIMEOUT_SECONDS", "600"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"model request failed: {exc}") from exc


def extract_verilog(text: str) -> str:
    fenced = re.findall(
        r"```(?:systemverilog|verilog|sv)?\s*\r?\n(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    code = fenced[0] if fenced else text
    code = code.strip()
    start = re.search(r"(?m)^\s*(?:`\w+.*\n\s*)*module\b", code)
    end = list(re.finditer(r"\bendmodule\b", code))
    if start and end:
        code = code[start.start():end[-1].end()]
    return code.rstrip() + "\n" if code else ""


def basic_check(code: str) -> str | None:
    if not code.strip():
        return "model returned empty output"
    if "```" in code:
        return "output still contains a Markdown code fence"
    if not re.search(r"\bmodule\s+TopModule\b", code):
        return "required module TopModule is missing"
    if not re.search(r"\bendmodule\b", code):
        return "endmodule is missing"
    return None


def tool_path(name: str) -> str:
    override = os.environ.get("VIVADO_BIN")
    directory = Path(override) if override else DEFAULT_VIVADO_BIN
    suffix = ".bat" if os.name == "nt" else ""
    candidate = directory / f"{name}{suffix}"
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name) or shutil.which(name + suffix)
    return found or str(candidate)


def command_path(path: str | Path) -> str:
    """Return an 8.3 path on Windows when available for fragile .bat/Tcl args."""
    resolved = str(Path(path).resolve())
    if os.name != "nt" or " " not in resolved:
        return resolved
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(resolved, buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else resolved


def run_process(command: list[str], cwd: Path, timeout: int, log_path: Path) -> dict[str, object]:
    env = os.environ.copy()
    env.setdefault("PROCESSOR_ARCHITECTURE", "AMD64")
    if os.name == "nt" and Path(command[0]).stem.lower() == "vivado":
        # The user's optional TclStore apps are irrelevant to batch scoring and
        # can fail before our Tcl runs.  This supported switch disables them.
        env["XILINX_LOCAL_USER_DATA"] = "no"
    actual = command
    if os.name == "nt" and command[0].lower().endswith((".bat", ".cmd")):
        # `call` makes cmd preserve quoting for both the batch file and paths
        # containing spaces (for example C:\Users\Ken Zou\...).
        actual = [env.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", "call", *command]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            actual,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = completed.stdout
        returncode = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\nTIMEOUT"
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        returncode = 124
        timed_out = True
    except OSError as exc:
        output = f"ERROR: unable to start command: {exc}"
        returncode = 127
        timed_out = False
    elapsed = time.monotonic() - started
    write_text(log_path, output)
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_s": round(elapsed, 3),
        "output": output,
        "log": str(log_path),
    }


def _failed(stage: str, process: dict[str, object] | None, message: str = "") -> dict[str, object]:
    output = str(process.get("output", "")) if process else message
    return {
        "passed": False,
        "highest_stage": stage,
        "functional_checked": False,
        "feedback": compact_feedback(output or message),
        "steps": [],
    }


def compact_feedback(output: str, limit: int = 4096) -> str:
    selected = []
    marker = re.compile(r"error|critical|fatal|mismatch|timeout|syntax|failed", re.IGNORECASE)
    for line in output.splitlines():
        if marker.search(line):
            selected.append(line.strip())
    text = "\n".join(selected[-40:]) if selected else output[-limit:]
    return text[-limit:]


def repair_feedback(code: str, feedback: str) -> str:
    """Add only contradictions explicitly exposed by simulator feedback."""
    notes = []
    for port in re.findall(r"Output ['\"]([A-Za-z_]\w*)['\"].*mismatch", feedback, re.IGNORECASE):
        input_port = re.search(
            rf"\binput\b[^;\n]*\b{re.escape(port)}\b",
            code,
            re.IGNORECASE,
        )
        if input_port:
            notes.append(
                f"仿真反馈将端口 {port} 标识为 DUT 输出，但当前候选将其声明为 input；"
                "请检查并修正端口方向。"
            )
    return feedback + ("\n" + "\n".join(dict.fromkeys(notes)) if notes else "")


def evaluate_candidate(
    candidate: str | Path,
    work_dir: str | Path,
    testbench: str | Path | None = None,
    reference: str | Path | None = None,
    skip_synthesis: bool = False,
) -> dict[str, object]:
    """Run the official RTL stage order; reference/test files are never sent to the model."""
    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    candidate_copy = work / "candidate.sv"
    source = Path(candidate).resolve()
    if source != candidate_copy:
        shutil.copy2(source, candidate_copy)

    format_error = basic_check(read_text(candidate_copy))
    if format_error:
        result = _failed("format", None, format_error)
        result["steps"] = []
        return result

    compile_inputs = [str(candidate_copy)]
    if reference:
        compile_inputs.append(str(Path(reference).resolve()))
    if testbench:
        compile_inputs.append(str(Path(testbench).resolve()))
    steps: list[dict[str, object]] = []
    timeout = int(os.environ.get("EDA_TIMEOUT_SECONDS", "180"))

    compile_step = run_process(
        [tool_path("xvlog"), "-sv", "--relax", *compile_inputs],
        work,
        timeout,
        work / "01_xvlog.log",
    )
    steps.append({k: v for k, v in compile_step.items() if k != "output"})
    if compile_step["returncode"] != 0:
        result = _failed("compile", compile_step)
        result["steps"] = steps
        return result

    top = os.environ.get("TB_TOP", "tb") if testbench else "TopModule"
    snapshot = "sim_snapshot" if testbench else "dut_snapshot"
    elaborate_step = run_process(
        [tool_path("xelab"), top, "-s", snapshot, "--relax"],
        work,
        timeout,
        work / "02_xelab.log",
    )
    steps.append({k: v for k, v in elaborate_step.items() if k != "output"})
    if elaborate_step["returncode"] != 0:
        result = _failed("elaboration", elaborate_step)
        result["steps"] = steps
        return result

    functional_checked = False
    if testbench:
        simulation_step = run_process(
            [tool_path("xsim"), snapshot, "-runall"],
            work,
            timeout,
            work / "03_xsim.log",
        )
        steps.append({k: v for k, v in simulation_step.items() if k != "output"})
        simulation_output = str(simulation_step["output"])
        mismatch = re.search(r"Mismatches\s*:\s*(\d+)", simulation_output, re.IGNORECASE)
        simulation_ok = (
            simulation_step["returncode"] == 0
            and "TIMEOUT" not in simulation_output.upper()
            and mismatch is not None
            and int(mismatch.group(1)) == 0
        )
        if not simulation_ok:
            explanation = simulation_output
            if simulation_step["returncode"] == 0 and mismatch is None:
                explanation += "\nERROR: simulator did not emit the required 'Mismatches: N' marker"
            result = _failed("simulation", {**simulation_step, "output": explanation})
            result["steps"] = steps
            result["functional_checked"] = True
            return result
        functional_checked = True

    if skip_synthesis:
        return {
            "passed": True,
            "highest_stage": "simulation" if functional_checked else "elaboration",
            "functional_checked": functional_checked,
            "feedback": "",
            "steps": steps,
            "synthesis_skipped": True,
        }

    synthesis_dir = work / "synthesis"
    synthesis_dir.mkdir(exist_ok=True)
    vivado_step = run_process(
        [
            tool_path("vivado"), "-mode", "batch", "-nolog", "-nojournal", "-notrace",
            "-source", command_path(ROOT / "vivado_eval.tcl"), "-tclargs",
            command_path(candidate_copy), command_path(synthesis_dir),
        ],
        work,
        max(timeout, 300),
        work / "04_vivado.log",
    )
    steps.append({k: v for k, v in vivado_step.items() if k != "output"})
    if vivado_step["returncode"] != 0 or re.search(r"^ERROR:", str(vivado_step["output"]), re.MULTILINE):
        result = _failed("synthesis", vivado_step)
        result["steps"] = steps
        result["functional_checked"] = functional_checked
        return result
    return {
        "passed": True,
        "highest_stage": "synthesis",
        "functional_checked": functional_checked,
        "feedback": "",
        "steps": steps,
        "synthesis_skipped": False,
    }


def baseline_generate(problem: str, output: str | Path, seed: int = 1) -> dict[str, object]:
    started = time.monotonic()
    # This exact one-message call is the competition baseline contract.
    response = call_model([{"role": "user", "content": problem}], seed)
    code = extract_verilog(response)
    write_text(output, code)
    return {
        "path": str(Path(output)),
        "elapsed_s": round(time.monotonic() - started, 3),
        "calls": 1,
        "seed": seed,
    }


def skill_text() -> str:
    return read_text(ROOT / "skill" / "RTL_SKILL.md")


def first_agent_messages(problem: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": skill_text()},
        {"role": "user", "content": problem},
    ]


def repair_messages(problem: str, previous: str, feedback: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": skill_text()},
        {
            "role": "user",
            "content": (
                f"题目：\n{problem}\n\n当前候选代码：\n{previous}\n\n"
                f"本地验证反馈：\n{feedback}\n\n修复代码。只输出完整的 TopModule 源码。"
            ),
        },
    ]


def generate_agent_sample(
    problem: str,
    output: Path,
    eval_dir: Path,
    seed: int,
    testbench: str | Path | None,
    reference: str | Path | None,
    max_repairs: int,
    skip_eda: bool,
    skip_synthesis: bool,
) -> dict[str, object]:
    started = time.monotonic()
    messages = first_agent_messages(problem)
    attempts = []
    code = ""
    evaluation: dict[str, object] = _failed("not_checked", None, "not evaluated")
    for attempt in range(max_repairs + 1):
        response = call_model(messages, seed + attempt * 1000)
        code = extract_verilog(response)
        write_text(output, code)
        attempt_dir = eval_dir / f"attempt_{attempt + 1}"
        if skip_eda:
            error = basic_check(code)
            evaluation = {
                "passed": error is None,
                "highest_stage": "format" if error else "not_checked",
                "functional_checked": False,
                "feedback": error or "",
                "steps": [],
                "eda_skipped": True,
            }
        else:
            evaluation = evaluate_candidate(
                output,
                attempt_dir,
                testbench=testbench,
                reference=reference,
                skip_synthesis=skip_synthesis,
            )
        attempts.append({
            "attempt": attempt + 1,
            "passed": evaluation["passed"],
            "highest_stage": evaluation["highest_stage"],
            "feedback": evaluation.get("feedback", ""),
        })
        if evaluation["passed"]:
            break
        if attempt < max_repairs:
            feedback = repair_feedback(code, str(evaluation.get("feedback", "")))
            messages = repair_messages(problem, code, feedback)
    return {
        "path": str(output),
        "seed": seed,
        "attempts": len(attempts),
        "attempt_history": attempts,
        "passed": evaluation["passed"],
        "highest_stage": evaluation["highest_stage"],
        "functional_checked": evaluation.get("functional_checked", False),
        "elapsed_s": round(time.monotonic() - started, 3),
    }


def run_problem(args: argparse.Namespace) -> dict[str, object]:
    problem = read_text(args.problem)
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    baseline_path = out / "baseline.sv"
    baseline = baseline_generate(problem, baseline_path, args.seed)
    if args.skip_eda:
        baseline_eval = {
            "passed": basic_check(read_text(baseline_path)) is None,
            "highest_stage": "not_checked",
            "functional_checked": False,
            "eda_skipped": True,
        }
    else:
        baseline_eval = evaluate_candidate(
            baseline_path,
            out / "logs" / "baseline",
            args.testbench,
            args.reference,
            skip_synthesis=args.skip_synthesis,
        )
    baseline.update({
        "passed": baseline_eval["passed"],
        "highest_stage": baseline_eval["highest_stage"],
        "functional_checked": baseline_eval.get("functional_checked", False),
    })

    samples = []
    for index in range(1, args.samples + 1):
        samples.append(generate_agent_sample(
            problem=problem,
            output=out / f"candidate_{index}.sv",
            eval_dir=out / "logs" / f"candidate_{index}",
            seed=args.seed + index,
            testbench=args.testbench,
            reference=args.reference,
            max_repairs=args.repairs,
            skip_eda=args.skip_eda,
            skip_synthesis=args.skip_synthesis,
        ))

    best = max(samples, key=lambda item: (bool(item["passed"]), STAGE_ORDER.get(str(item["highest_stage"]), 0), -int(item["attempts"])))
    shutil.copy2(best["path"], out / "best.sv")
    result = {
        "schema_version": 1,
        "problem_sha256": sha256_text(problem),
        "model": model_settings(),
        "baseline": baseline,
        "samples": samples,
        "pass_at_1": bool(samples and samples[0]["passed"]),
        "pass_at_5": any(bool(item["passed"]) for item in samples[:5]),
        "best": Path(best["path"]).name,
        "elapsed_s": round(time.monotonic() - started, 3),
        "official_target": "xczu3eg-sbva484-1-e",
        "clock_period_ns": 5.0,
    }
    write_text(out / "result.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def benchmark(args: argparse.Namespace) -> dict[str, object]:
    dataset = Path(args.dataset).resolve()
    prompts = sorted(dataset.rglob("*_prompt.txt"))
    if args.limit:
        prompts = prompts[:args.limit]
    if not prompts:
        raise RuntimeError(f"no *_prompt.txt files found below {dataset}")
    output_root = Path(args.output_dir).resolve()
    records = []
    for prompt in prompts:
        prefix = prompt.name[:-len("_prompt.txt")]
        reference = prompt.with_name(prefix + "_ref.sv")
        testbench = prompt.with_name(prefix + "_test.sv")
        if not reference.exists() or not testbench.exists():
            continue
        child = argparse.Namespace(
            problem=str(prompt),
            output_dir=str(output_root / prefix),
            testbench=str(testbench),
            reference=str(reference),
            samples=args.samples,
            repairs=args.repairs,
            seed=args.seed + len(records) * 100,
            skip_eda=args.skip_eda,
            skip_synthesis=args.skip_synthesis,
        )
        result = run_problem(child)
        records.append({
            "problem": prefix,
            "baseline_pass": result["baseline"]["passed"],
            "pass_at_1": result["pass_at_1"],
            "pass_at_5": result["pass_at_5"],
            "elapsed_s": result["elapsed_s"],
        })
    count = len(records)
    summary = {
        "schema_version": 1,
        "dataset": str(dataset),
        "problems": count,
        "baseline_pass_rate": sum(bool(x["baseline_pass"]) for x in records) / count if count else 0.0,
        "pass_at_1": sum(bool(x["pass_at_1"]) for x in records) / count if count else 0.0,
        "pass_at_5": sum(bool(x["pass_at_5"]) for x in records) / count if count else 0.0,
        "records": records,
    }
    write_text(output_root / "benchmark.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal AMD RTL local agent")
    sub = parser.add_subparsers(dest="command", required=True)

    baseline_parser = sub.add_parser("baseline", help="one problem-only model call")
    baseline_parser.add_argument("--problem", required=True)
    baseline_parser.add_argument("--output", required=True)
    baseline_parser.add_argument("--seed", type=int, default=1)

    run_parser = sub.add_parser("run", help="baseline plus RTL agent samples")
    run_parser.add_argument("--problem", required=True)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--testbench")
    run_parser.add_argument("--reference")
    run_parser.add_argument("--samples", type=int, default=5, choices=range(1, 6))
    run_parser.add_argument("--repairs", type=int, default=2, choices=range(0, 3))
    run_parser.add_argument("--seed", type=int, default=1)
    run_parser.add_argument("--skip-eda", action="store_true", help="generation smoke only")
    run_parser.add_argument("--skip-synthesis", action="store_true", help="compile/simulation development smoke")

    eval_parser = sub.add_parser("evaluate", help="evaluate one existing RTL candidate")
    eval_parser.add_argument("--candidate", required=True)
    eval_parser.add_argument("--work-dir", required=True)
    eval_parser.add_argument("--testbench")
    eval_parser.add_argument("--reference")
    eval_parser.add_argument("--skip-synthesis", action="store_true")

    bench_parser = sub.add_parser("benchmark", help="run *_prompt/ref/test triples")
    bench_parser.add_argument("--dataset", required=True)
    bench_parser.add_argument("--output-dir", required=True)
    bench_parser.add_argument("--limit", type=int)
    bench_parser.add_argument("--samples", type=int, default=5, choices=range(1, 6))
    bench_parser.add_argument("--repairs", type=int, default=2, choices=range(0, 3))
    bench_parser.add_argument("--seed", type=int, default=1)
    bench_parser.add_argument("--skip-eda", action="store_true")
    bench_parser.add_argument("--skip-synthesis", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "baseline":
            result = baseline_generate(read_text(args.problem), args.output, args.seed)
        elif args.command == "run":
            result = run_problem(args)
        elif args.command == "evaluate":
            result = evaluate_candidate(
                args.candidate, args.work_dir, args.testbench, args.reference, args.skip_synthesis
            )
        else:
            result = benchmark(args)
        print(json.dumps(result, ensure_ascii=False))
        if args.command == "evaluate" and not result.get("passed", False):
            return 2
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
