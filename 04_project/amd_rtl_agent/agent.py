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
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_VIVADO_BIN = Path(r"F:\vivado\2026.1\Vivado\bin")
TARGET_PART = "xczu3eg-sbva484-1-e"
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


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    """Replace a checkpoint only after its complete contents have been written."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_text(temporary, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def quality(result: dict) -> tuple:
    # Within the same simulation stage prefer fewer mismatched samples.
    # Only compare normalized counts when the simulator reports a denominator.
    counts = re.findall(r"Mismatches\s*:\s*(\d+)\s+in\s+(\d+)\s+samples",
                        str(result.get("feedback", "")), re.IGNORECASE)
    mismatch_rate = max((int(n) / int(d) for n, d in counts if int(d) > 0), default=1.0)
    return (bool(result["passed"]), STAGE_ORDER.get(str(result["highest_stage"]), 0),
            -mismatch_rate)


def functional_pass(result: dict) -> bool | None:
    # Format-only and synthesis-only checks are not functional evidence.
    if result.get("eda_skipped") or not result.get("testbench_available", False):
        return None
    return bool(result["passed"] and result.get("functional_checked"))


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
    thinking = os.environ.get("LLM_ENABLE_THINKING")
    if thinking is not None:
        body["enable_thinking"] = thinking.lower() in ("1", "true", "yes")
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
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("model response content must be a non-empty string")
        return content
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
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
    # An explicit installation must not silently fall back to another version.
    if override:
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
        process = subprocess.Popen(
            actual,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
        )
        try:
            output, _ = process.communicate(timeout=timeout)
            returncode = process.returncode
            timed_out = False
        except BaseException as exc:
            # Kill the launcher and its EDA children before collecting output.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass  # Still terminate the direct process below.
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                output = getattr(exc, 'stdout', None) or ""
                process.stdout.close()
                process.wait(timeout=5)
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            if not isinstance(exc, subprocess.TimeoutExpired):
                write_text(log_path, output + "\nINTERRUPTED")
                raise
            output += "\nTIMEOUT"
            returncode = 124
            timed_out = True
    except OSError as exc:
        output = f"ERROR: unable to start command: {exc}"
        returncode = 127
        timed_out = False
    elapsed = time.monotonic() - started
    write_text(log_path, output)
    # These failures cannot be repaired by changing the generated RTL. Preserve
    # the log, abort this run, and leave the problem without a score/checkpoint.
    if returncode == 127 or re.search(
        r"(?im)^(?:ERROR:\s*(?:\[[^\]]+\]\s*)?)?(?:"
        r"Could not obtain the necessary license|"
        r"Vivado Design Suite cannot be launched because a valid license|"
        r"A valid license was not found|Failed to get a license|License checkout failed|"
        r"required target part \S+ is not installed|"
        r".*error while loading shared libraries:|"
        r"'.+' is not recognized as an internal or external command)", output
    ):
        raise RuntimeError(f"EDA environment error; scoring stopped. See {log_path}")
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
    context_remaining = 0
    for line in output.splitlines():
        diagnostic = marker.search(line)
        # Vivado may put the time and source location on separate lines.
        context = context_remaining > 0 and re.match(
            r"\s*(?:Time|File|Scope|Process|Iteration)\s*:", line, re.IGNORECASE)
        context_remaining = 2 if diagnostic else max(0, context_remaining - 1)
        if diagnostic or context:
            # Long absolute workspace paths otherwise crowd out the root error.
            cleaned = re.sub(r"\[[^\[\]\n]*[\\/][^\[\]\n]*:(\d+)\]", r"[line \1]", line.strip())
            if cleaned not in selected:
                selected.append(cleaned)
    if not selected:
        return output[-limit:]
    text = "\n".join(selected)
    if len(text) <= limit:
        return text
    # Keep the first compiler diagnostics AND the simulator's final totals.
    tail = min(limit // 3, 1024)
    return text[:limit - tail - 5] + "\n...\n" + text[-tail:]


def repair_output_declarations(code: str, feedback: str) -> str | None:
    """Fix only simple ANSI output nets named by Vivado's procedural-write error.

    Deliberately not a Verilog parser: grouped/non-ANSI/parameterized ports and
    preprocessor constructs fall back to model repair. The result still needs EDA.
    """
    names = set(re.findall(r"\[VRFC 10-1280\] procedural assignment to a non-register (\w+)\b", feedback))
    if not names or '`' in code:
        return None
    # Mask comments without shifting offsets, so comments cannot become ports.
    masked = re.sub(r"//[^\n]*|/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m[0]), code, flags=re.DOTALL)
    if len(re.findall(r"\bmodule\b", masked)) != 1:
        return None
    header = re.search(r"\bmodule\s+TopModule\s*\((.*?)\)\s*;", masked, re.DOTALL)
    if not header:
        return None
    changes = []
    for segment in re.finditer(r"[^,]+", header[1]):
        match = re.fullmatch(r"\s*output\s+(?:(wire)\s+)?(?:signed\s+)?(?:\[[^\[\]]+\]\s*)?(\w+)\s*", segment[0])
        if not match or match[2] not in names:
            continue
        # A following unqualified grouped port would inherit the changed type.
        rest = header[1][segment.end():].lstrip(', \t\r\n')
        if rest and not re.match(r"(?:input|output|inout)\b", rest):
            continue
        base = header.start(1) + segment.start()
        if match[1]:
            changes.append((base + match.start(1), base + match.end(1), 'reg'))
        else:
            pos = base + re.search(r"\boutput\b", segment[0]).end()
            changes.append((pos, pos, ' reg'))
    for start, end, replacement in reversed(changes):
        code = code[:start] + replacement + code[end:]
    return code if changes else None


def repair_feedback(code: str, feedback: str) -> str:
    """Add only contradictions explicitly exposed by simulator feedback."""
    notes = []
    if "non-register" in feedback:
        notes.append("过程赋值的目标必须声明为 reg 或 logic（包括 output）；wire 不能在 always 中赋值。保留端口方向和位宽。")
    if "keyword 'wire' used in incorrect context" in feedback:
        notes.append("不要在 always 的过程块内声明 wire；将组合连线移到模块作用域并用 assign，或使用块内变量和过程赋值。")
    if "endmodule is missing" in feedback or "code fence" in feedback:
        notes.append("输出可能被截断。请重写为简短完整实现：重复位运算使用固定边界 for 循环或向量表达式，省略解释和长注释，必须以 endmodule 结束。")
    # Inspect only simple ANSI ports of TopModule. Do not infer directions from
    # comments, other modules, range expressions, or unsupported declarations.
    masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', ' ', code, flags=re.DOTALL)
    header = re.search(r"\bmodule\s+TopModule\s*\((.*?)\)\s*;", masked, re.DOTALL)
    input_ports = set()
    if header and '`' not in masked:
        for declaration in re.finditer(
            r"\binput\s+(?:(?:wire|reg|logic)\s+)?(?:(?:signed|unsigned)\s+)?"
            r"(?:\[[^\[\]]+\]\s*)?([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*"
            r"(?=[;)]|,\s*(?:input|output|inout)\b)", header[1] + ')'):
            input_ports.update(name.strip() for name in declaration[1].split(','))
    for port in re.findall(r"Output ['\"]([A-Za-z_]\w*)['\"].*mismatch", feedback, re.IGNORECASE):
        if port in input_ports:
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
    if any((work / name).exists() for name in (
        '01_xvlog.log', '02_xelab.log', '03_xsim.log', '04_vivado.log', 'synthesis'
    )):
        raise RuntimeError(f"evaluation directory contains previous evidence: {work}; use a new directory")
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
        mismatches = re.findall(r"^\s*Mismatches\s*:\s*(\d+)\b", simulation_output, re.IGNORECASE | re.MULTILINE)
        simulation_ok = (
            simulation_step["returncode"] == 0
            and "TIMEOUT" not in simulation_output.upper()
            and bool(mismatches)
            and all(int(value) == 0 for value in mismatches)
            and not re.search(r"^\s*(?:ERROR|FATAL)\b", simulation_output, re.MULTILINE | re.IGNORECASE)
        )
        if not simulation_ok:
            explanation = simulation_output
            if simulation_step["returncode"] == 0 and not mismatches:
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
    if vivado_step["returncode"] != 0 or re.search(r"^\s*(?:ERROR|FATAL)\b", str(vivado_step["output"]), re.MULTILINE | re.IGNORECASE):
        result = _failed("synthesis", vivado_step)
        result["steps"] = steps
        result["functional_checked"] = functional_checked
        return result
    marker = f"RTL_SYNTHESIS_PASS part={TARGET_PART} clock_period_ns=5.000"
    required = ('PASS', 'post_synth.dcp', 'timing.rpt', 'utilization.rpt')
    if marker not in str(vivado_step['output']).splitlines() or any(
        not (synthesis_dir / name).is_file() or not (synthesis_dir / name).stat().st_size
        for name in required
    ):
        raise RuntimeError(f"EDA synthesis completion evidence is missing; scoring stopped. See {work / '04_vivado.log'}")
    metadata = dict(line.split('=', 1) for line in read_text(synthesis_dir / 'PASS').splitlines() if '=' in line)
    if metadata.get('part') != TARGET_PART or metadata.get('clock_period_ns') != '5.000':
        raise RuntimeError(f"EDA synthesis metadata mismatch: {synthesis_dir / 'PASS'}")
    # A constraint is not a measured timing pass. Retain the report for review.
    timing = {
        'requested_clock_period_ns': 5.0,
        'constrained_clock_ports': metadata.get('constrained_clock_ports', '').split(),
        'timing_pass': None,
        'report': str(synthesis_dir / 'timing.rpt'),
    }
    return {
        "passed": True,
        "highest_stage": "synthesis",
        "functional_checked": functional_checked,
        "feedback": "",
        "steps": steps,
        "synthesis_skipped": False,
        "timing": timing,
    }


def baseline_generate(problem: str, output: str | Path, seed: int = 1) -> dict[str, object]:
    if Path(output).exists():
        raise RuntimeError(f"baseline output already exists: {output}; use a new path")
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
        {"role": "system", "content": skill_text() + "\n" + read_text(ROOT / "skill" / "RTL_REPAIR_SKILL.md")},
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
    best_evaluation = None
    best_code = ""
    selected_attempt = 0
    seen = {}
    model_calls = 0
    repair_from_attempt = None
    for attempt in range(max_repairs + 1):
        patched = (repair_output_declarations(code, str(evaluation.get('feedback', '')))
                   if attempt and evaluation['highest_stage'] == 'compile' else None)
        origin = 'compiler_declaration_repair' if patched is not None else 'model'
        generation_started = time.monotonic()
        if patched is not None:
            response = patched
        else:
            response = call_model(messages, seed + attempt * 1000)
            model_calls += 1
        generation_elapsed = time.monotonic() - generation_started if patched is None else 0.0
        code = extract_verilog(response)
        digest = sha256_text(code)
        prior = seen.get(digest)
        duplicate_of = prior[0] if prior else None
        write_text(output, code)
        attempt_dir = eval_dir / f"attempt_{attempt + 1}"
        write_text(attempt_dir / "response.txt", response)
        write_text(attempt_dir / "candidate.sv", code)
        reusable = (prior is not None and prior[1]['highest_stage'] in ('format', 'compile')
                    and not prior[1]['passed']
                    and all(not s.get('timed_out') and s.get('returncode') not in (124, 127)
                            for s in prior[1].get('steps', [])))
        evaluation_started = time.monotonic()
        if reusable:
            evaluation = {**prior[1], 'steps': [], 'reused_from_attempt': prior[0]}
        elif skip_eda:
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
            "source": origin,
            "repair_from_attempt": repair_from_attempt,
            "duplicate_of_attempt": duplicate_of,
            "evaluation_reused": reusable,
            "model_elapsed_s": round(generation_elapsed, 3),
            "eda_elapsed_s": round(time.monotonic() - evaluation_started, 3) if not reusable and not skip_eda else 0.0,
        })
        if digest not in seen:
            seen[digest] = (attempt + 1, evaluation)
        write_json(attempt_dir / "evaluation.json", evaluation)
        if best_evaluation is None or quality(evaluation) > quality(best_evaluation):
            best_evaluation = evaluation
            best_code = code
            selected_attempt = attempt + 1
        if evaluation["passed"]:
            break
        if attempt < max_repairs:
            repair_from_attempt = attempt + 1
            regressed = quality(evaluation) < quality(best_evaluation)
            if regressed:
                code, evaluation = best_code, best_evaluation
                repair_from_attempt = selected_attempt
            feedback = repair_feedback(code, str(evaluation.get("feedback", "")))
            feedback = (f"本次修复基于第 {repair_from_attempt} 次候选；"
                        f"未通过阶段：{evaluation['highest_stage']}。\n" + feedback)
            if regressed:
                feedback += "\n上一次修改的验证结果退步，已恢复验证结果较好的候选。请从当前代码继续修复。"
            if duplicate_of is not None:
                feedback += "\n上一次返回的代码与已失败的第 " + str(duplicate_of) + " 次尝试完全相同。请针对上述错误修改实现，不要原样重发。"
            messages = repair_messages(problem, code, feedback)
    evaluation = best_evaluation
    write_text(output, best_code)
    return {
        "path": str(output),
        "seed": seed,
        "attempts": len(attempts),
        "selected_attempt": selected_attempt,
        "attempt_history": attempts,
        "model_calls": model_calls,
        "model_elapsed_s": round(sum(a['model_elapsed_s'] for a in attempts), 3),
        "eda_elapsed_s": round(sum(a['eda_elapsed_s'] for a in attempts), 3),
        "passed": evaluation["passed"],
        "highest_stage": evaluation["highest_stage"],
        "feedback": evaluation.get("feedback", ""),
        "timing": evaluation.get("timing"),
        "functional_checked": evaluation.get("functional_checked", False),
        "testbench_available": bool(testbench),
        "eda_skipped": skip_eda,
        "elapsed_s": round(time.monotonic() - started, 3),
    }


def run_problem(args: argparse.Namespace) -> dict[str, object]:
    problem = read_text(args.problem)
    out = Path(args.output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise RuntimeError(f"output directory is not empty: {out}; use a new directory")
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
        "testbench_available": bool(args.testbench),
        "eda_skipped": args.skip_eda,
        "timing": baseline_eval.get("timing"),
    })
    write_json(out / "logs" / "baseline" / "evaluation.json", baseline_eval)

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

    best = max(samples, key=lambda item: (*quality(item), -int(item["attempts"])))
    shutil.copy2(best["path"], out / "best.sv")
    result = {
        "schema_version": 2,
        "problem_sha256": sha256_text(problem),
        "model": model_settings(),
        "skill_sha256": sha256_text(skill_text()),
        "repair_skill_sha256": sha256_text(read_text(ROOT / "skill" / "RTL_REPAIR_SKILL.md")),
        "evaluation_mode": "format_only" if args.skip_eda else (
            "compile_simulation" if args.skip_synthesis else "compile_simulation_synthesis"),
        "mock_model": bool(os.environ.get("LLM_MOCK_FILE")),
        "baseline_pass": functional_pass(baseline),
        "baseline": baseline,
        "samples": samples,
        "pass_at_1": functional_pass(samples[0]),
        "pass_at_5": (any(functional_pass(item) for item in samples)
                      if len(samples) == 5 and functional_pass(samples[0]) is not None else None),
        "best": Path(best["path"]).name,
        "elapsed_s": round(time.monotonic() - started, 3),
        "official_target": TARGET_PART,
        "clock_period_ns": 5.0,
        "clock_period_is_constraint": True,
        "timing": best.get("timing"),
        "model_calls": baseline['calls'] + sum(s['model_calls'] for s in samples),
        "model_elapsed_s": round(baseline['elapsed_s'] + sum(s['model_elapsed_s'] for s in samples), 3),
        "eda_elapsed_s": round(sum(s.get('elapsed_s', 0) for s in baseline_eval.get('steps', []))
                               + sum(s['eda_elapsed_s'] for s in samples), 3),
    }
    write_json(out / "result.json", result)
    return result


def experiment_config(args, prompts, dataset):
    """Fingerprint effective inputs; credentials are never persisted."""
    return {
        'model': model_settings(),
        'settings': {key: os.environ.get(key, '') for key in (
            'LLM_ENABLE_THINKING', 'LLM_MODEL_REVISION', 'LLM_QUANTIZATION',
            'LLM_TIMEOUT_SECONDS', 'EDA_TIMEOUT_SECONDS', 'TB_TOP', 'VIVADO_BIN')},
        'endpoint_sha256': sha256_text(os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8000/v1')),
        'mock_sha256': (sha256_text(read_text(os.environ['LLM_MOCK_FILE']))
                        if os.environ.get('LLM_MOCK_FILE') else None),
        'samples': args.samples, 'repairs': args.repairs, 'seed': args.seed,
        'offset': getattr(args, 'offset', 0),
        'skip_eda': args.skip_eda, 'skip_synthesis': args.skip_synthesis,
        'implementation': {name: sha256_text(read_text(ROOT / name)) for name in (
            'agent.py', 'vivado_eval.tcl', 'skill/RTL_SKILL.md', 'skill/RTL_REPAIR_SKILL.md')},
        'inputs': [{
            'problem': str(p.relative_to(dataset)),
            'sha256': {suffix: sha256_file(p.with_name(
                p.name[:-len('_prompt.txt')] + suffix))
                       for suffix in ('_prompt.txt', '_ref.sv', '_test.sv')}
        } for p in prompts],
    }


def benchmark(args: argparse.Namespace) -> dict[str, object]:
    """One writer per output directory; completed problems survive interruption."""
    if args.limit is not None and args.limit <= 0:
        raise ValueError('benchmark limit must be positive')
    if getattr(args, 'offset', 0) < 0:
        raise ValueError('benchmark offset must be non-negative')
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.benchmark.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f'benchmark directory is locked: {lock}; check the owner process before removing a stale lock')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(str(os.getpid()))
        return _benchmark(args)
    finally:
        lock.unlink(missing_ok=True)


def _benchmark(args: argparse.Namespace) -> dict[str, object]:
    if args.limit is not None and args.limit <= 0:
        raise ValueError("benchmark limit must be positive")
    offset = getattr(args, "offset", 0)
    if offset < 0:
        raise ValueError("benchmark offset must be non-negative")
    dataset = Path(args.dataset).resolve()
    prompts = sorted(dataset.rglob("*_prompt.txt"))[offset:]
    if args.limit:
        prompts = prompts[:args.limit]
    if not prompts:
        raise RuntimeError(f"no *_prompt.txt files found below {dataset}")
    # Reject incomplete data before spending any inference budget.
    for prompt in prompts:
        prefix = prompt.name[:-len("_prompt.txt")]
        for suffix in ("_ref.sv", "_test.sv"):
            if not prompt.with_name(prefix + suffix).is_file():
                raise RuntimeError(f"incomplete dataset triple: {prompt.with_name(prefix + suffix)}")
    output_root = Path(args.output_dir).resolve()
    config = experiment_config(args, prompts, dataset)
    manifest = output_root / 'experiment.json'
    resume = getattr(args, 'resume', False)
    if resume:
        if not manifest.is_file() or json.loads(read_text(manifest)) != config:
            raise RuntimeError('resume configuration/input mismatch or missing experiment.json; use a new output directory')
    else:
        if any(p.name != '.benchmark.lock' for p in output_root.iterdir()):
            raise RuntimeError('output directory is not empty; use --resume or a new output directory')
        write_json(manifest, config)
    records = []
    completed = {}
    for prompt in prompts:
        name = str(prompt.relative_to(dataset))
        checkpoint = output_root / '.checkpoints' / (sha256_text(name) + '.json')
        if resume and checkpoint.exists():
            saved = json.loads(read_text(checkpoint))
            if saved['record']['problem'] != name or not saved['artifacts']:
                raise RuntimeError(f'invalid checkpoint for {name}')
            for relative, digest in saved['artifacts'].items():
                artifact = (output_root / relative).resolve()
                if not artifact.is_relative_to(output_root) or not artifact.is_file() or sha256_file(artifact) != digest:
                    raise RuntimeError(f'resume artifact missing or changed: {relative}')
            completed[name] = saved['record']
    records = [completed[str(p.relative_to(dataset))] for p in prompts if str(p.relative_to(dataset)) in completed]

    def save_summary(complete=False):
        def rate(key):
            values = [r[key] for r in records]
            return (sum(values) / len(values)
                    if values and all(v is not None for v in values) else None)
        comparable = [r for r in records if r["baseline_pass"] is not None and r["pass_at_1"] is not None]
        summary = {
            "schema_version": 4, "dataset": str(dataset),
            "offset": offset,
            "complete": complete, "requested_problems": len(prompts), "problems": len(records),
            "baseline_pass_rate": rate("baseline_pass"),
            "pass_at_1": rate("pass_at_1"), "pass_at_5": rate("pass_at_5"),
            "improved_problems": sum(not r["baseline_pass"] and r["pass_at_1"] for r in comparable),
            "repaired_problems": (sum(r["repair_succeeded"] for r in records)
                                  if records and all(r["repair_succeeded"] is not None for r in records) else None),
            "regressed_problems": sum(r["baseline_pass"] and not r["pass_at_1"] for r in comparable),
            "mean_elapsed_s": sum(r["elapsed_s"] for r in records) / len(records) if records else None,
            "mock_model": bool(os.environ.get("LLM_MOCK_FILE")),
            "total_model_calls": (sum(r['model_calls'] for r in records)
                                  if records and all(r['model_calls'] is not None for r in records) else None),
            "total_model_elapsed_s": (round(sum(r['model_elapsed_s'] for r in records), 3)
                                      if records and all(r['model_elapsed_s'] is not None for r in records) else None),
            "total_eda_elapsed_s": (round(sum(r['eda_elapsed_s'] for r in records), 3)
                                    if records and all(r['eda_elapsed_s'] is not None for r in records) else None),
            "records": records,
        }
        write_json(output_root / "benchmark.json", summary)
        return summary

    save_summary()
    for position, prompt in enumerate(prompts):
        name = str(prompt.relative_to(dataset))
        if name in completed:
            continue
        prefix = prompt.name[:-len("_prompt.txt")]
        reference = prompt.with_name(prefix + "_ref.sv")
        testbench = prompt.with_name(prefix + "_test.sv")
        problem_output = output_root / prompt.relative_to(dataset).parent / prefix
        # Preserve all evidence from an interrupted problem. Restart that problem
        # in a fresh directory; only completed problems are resumed.
        if problem_output.exists() and any(problem_output.iterdir()):
            retry = 1
            while (problem_output / f'restart_{retry}').exists():
                retry += 1
            problem_output = problem_output / f'restart_{retry}'
        child = argparse.Namespace(
            problem=str(prompt),
            output_dir=str(problem_output),
            testbench=str(testbench),
            reference=str(reference),
            samples=args.samples,
            repairs=args.repairs,
            seed=args.seed + (offset + position) * 100,
            skip_eda=args.skip_eda,
            skip_synthesis=args.skip_synthesis,
        )
        try:
            result = run_problem(child)
        except Exception as exc:
            write_json(problem_output / 'error.json', {'problem': name, 'error': str(exc)})
            raise
        # Compare the first agent sample with its own initial attempt, not with
        # the independent baseline. Keep this aligned with pass_at_1.
        first = result["samples"][0]
        repair_succeeded = (bool(result["pass_at_1"] and first["selected_attempt"] > 1
                                 and not first["attempt_history"][0]["passed"])
                            if result["pass_at_1"] is not None else None)
        record = {
            "problem": str(prompt.relative_to(dataset)),
            "baseline_pass": result["baseline_pass"],
            "pass_at_1": result["pass_at_1"],
            "pass_at_5": result["pass_at_5"],
            "elapsed_s": result["elapsed_s"],
            "repair_succeeded": repair_succeeded,
            "result_path": str((problem_output / 'result.json').relative_to(output_root)),
            "model_calls": result.get('model_calls'),
            "model_elapsed_s": result.get('model_elapsed_s'),
            "eda_elapsed_s": result.get('eda_elapsed_s'),
        }
        write_json(problem_output / 'result.json', result)
        artifacts = {str(p.relative_to(output_root)): sha256_file(p)
                     for p in problem_output.rglob('*') if p.is_file() and
                     (p.suffix in ('.sv', '.json', '.txt', '.log', '.rpt', '.dcp') or p.name == 'PASS')}
        write_json(output_root / '.checkpoints' / (sha256_text(name) + '.json'),
                   {'record': record, 'artifacts': artifacts})
        completed[name] = record
        records = [completed[str(p.relative_to(dataset))] for p in prompts if str(p.relative_to(dataset)) in completed]
        save_summary()
        print(f"[{len(records)}/{len(prompts)}] {prefix}", file=sys.stderr, flush=True)
    return save_summary(complete=True)


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
    bench_parser.add_argument("--offset", type=int, default=0, help="skip this many sorted problems before applying limit")
    bench_parser.add_argument("--resume", action="store_true", help="resume completed problems with identical configuration and inputs")
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
