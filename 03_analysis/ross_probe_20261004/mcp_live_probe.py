"""Bounded real MCP checks; no model, scoring, generated testbench or repair."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from mcp_client import StdioClient


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def payload(result):
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    texts = [b["text"] for b in result.get("content", []) if b.get("type") == "text"]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            pass
    return result


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def session_ids(value):
    found = set()
    if isinstance(value, dict):
        if isinstance(value.get("session_id"), str):
            found.add(value["session_id"])
        for item in value.values():
            found.update(session_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(session_ids(item))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    spec = json.loads((root / "MCP_SPEC.json").read_text())
    check = json.loads(args.resource_check.read_text())
    assert check["resource_idle"] and check["model_pid"] == spec["model_pid"]
    assert sha(root / "vivado-mcp-server") == spec["binary_sha256"]
    for filename, digest in spec["source_hashes"].items():
        assert sha(root / filename) == digest, filename
    out = root / "live"
    out.mkdir(exist_ok=False)
    work = out / "work"
    work.mkdir()
    command = [str(root / "vivado-mcp-server"), "--stdio", "--state-dir=" + str(out / "state"),
               "--vivado-path=" + spec["vivado_path"], "--enable-lsf=false", "--enable-ssh=false",
               "--disable-telemetry", "--disable-otel", "--max-sessions=1", "--limit-ai-output=false"]
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/workspace/team/udev-stub" + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost,::1"
    result = dict(complete=False, passed=False, model_calls=0, rows=[], command=command,
                  closed_session_ids=[],
                  scope="Real MCP transport/session/diagnostic probe with fresh case sessions, not autonomous model integration or scoring")
    client = None
    owned_session = None
    started = time.monotonic()
    calls = 0

    def tool(name, arguments, timeout=120):
        nonlocal calls
        calls += 1
        tick = time.monotonic()
        raw = client.tool(name, arguments, timeout=timeout)
        save(out / ("%02d_%s.json" % (calls, name)), raw)
        data = payload(raw)
        save(out / "progress.json", dict(tool_calls=calls, last_tool=name, elapsed_s=time.monotonic()-started))
        if isinstance(data, dict):
            if data.get("success") is False or data.get("status") in ["error", "failed"]:
                raise RuntimeError("embedded tool failure: " + name + ": " + json.dumps(data)[:2000])
        print(json.dumps(dict(tool=name, seconds=round(time.monotonic()-tick, 3))), flush=True)
        return data

    def execute(command):
        data = tool("vivado_execute", dict(session_id=owned_session, command=command, mode="proxy", capture_log=True, verbosity="full"), timeout=360)
        if isinstance(data, dict) and data.get("status") == "running":
            # Bounded handoff polling, no extra command while Tcl is occupied.
            for _ in range(3):
                time.sleep(30)
                status = tool("vivado_status", dict(session_id=owned_session, action="session"))
                if status.get("is_command_running") is False:
                    assert status.get("last_completed_code") == 0, status
                    return data
            raise TimeoutError("MCP command still running after bounded status checks")
        if isinstance(data, dict):
            for key in ["code", "return_code", "exit_code"]:
                if type(data.get(key)) is int and data[key] != 0:
                    raise RuntimeError("nonzero Tcl response: " + json.dumps(data)[:2000])
        return data

    try:
        client = StdioClient(command, out, env, out / "rpc.jsonl", out / "stderr.log")
        init = client.request("initialize", dict(protocolVersion="2025-11-25", capabilities={}, clientInfo=dict(name="fpga-isolated-ross-probe", version="0.1")))
        assert init["serverInfo"]["version"] == "2026.9.1"
        client.notify("notifications/initialized")
        before = tool("vivado_list_sessions", {})
        assert not session_ids(before), "Existing sessions: refuse to adopt any"
        tick = time.monotonic()
        start = tool("vivado_start", dict(working_dir=str(work), session_type="general", gui_mode=False, display_mode="none", external=False), timeout=120)
        ids = session_ids(start)
        assert len(ids) == 1, "Cannot identify exactly one owned session"
        owned_session = next(iter(ids))
        result.update(session_id=owned_session, start_elapsed_s=time.monotonic()-tick)
        # Bind to the log path returned by the real tool, never infer a filename.
        log_path = Path(start["log_file"]).resolve()
        assert log_path.is_relative_to(work.resolve()) and log_path.is_file()
        result["vivado_log_file"] = str(log_path)
        tool("vivado_todos", dict(operation="plan", session_id=owned_session, title="Isolated diagnostic probe", tasks=[dict(id="1",content="Verify version and target"),dict(id="2",content="Run fixed positive and negative controls"),dict(id="3",content="Collect diagnostics and close owned session")]))
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="1", status="active"))
        version = execute('puts "MCP_PROBE_VERSION:[version -short]"; puts "MCP_PROBE_PARTS:[llength [get_parts ' + spec["part"] + ']]"')
        text = "\n".join(strings(version))
        assert "MCP_PROBE_VERSION:2026.1" in text and "MCP_PROBE_PARTS:1" in text, text[:2000]
        result["version_verified"] = True
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="1", status="done", summary="Vivado 2026.1 and competition part verified"))
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="2", status="active"))
        for index, item in enumerate(spec["runs"]):
            case = spec["inputs"][item["case"]]
            directory = work / (item["case"] + "__" + item["mode"])
            directory.mkdir()
            source = directory / "candidate.sv"
            source.write_bytes((root / case["file"]).read_bytes())
            assert sha(source) == case["sha256"]
            execute("create_project -in_memory -part " + spec["part"])
            setting = 'set_param general.maxThreads 2; '
            if item["mode"] == "lint":
                setting += spec["csv_option"] + "; "
            execute(setting + 'read_verilog -sv {' + str(source) + '}')
            offset = log_path.stat().st_size
            tick = time.monotonic()
            report = directory / "linter.csv"
            synth = 'synth_design -top ' + case["top"] + ' -part ' + spec["part"]
            if item["mode"] == "lint":
                synth += ' -lint -file {' + str(report) + '}'
            execute(synth)
            elapsed = time.monotonic()-tick
            marker = "MCP_PROBE_CASE_DONE:" + item["case"] + ":" + item["mode"]
            data = execute('puts "' + marker + '"')
            assert marker in "\n".join(strings(data))
            log = log_path.read_bytes()[offset:]
            (directory / "diagnostic.log").write_bytes(log)
            text = log.decode(errors="replace")
            counts = [int(x) for x in re.findall(r'Total of (\d+) linter message\(s\) generated', text)]
            errors = re.findall(r'^ERROR:.*', text, re.M)
            assert not errors, errors
            if item["mode"] == "lint":
                assert report.exists() and len(counts) == 1, "Missing lint report or count"
            messages = re.findall(r'^(?:CRITICAL WARNING|WARNING): \[.*', text, re.M)
            row = dict(case=item["case"],mode=item["mode"],source_sha256=sha(source), elapsed_s=elapsed, linter_counts=counts, messages=messages, log_sha256=sha(directory / "diagnostic.log"), report_bytes=report.stat().st_size if report.exists() else None, report_sha256=sha(report) if report.exists() else None, tool_execution_valid=True)
            result["rows"].append(row)
            save(directory / "result.json", row)
            save(out / "summary.json", result)
            tool("vivado_log_messages",dict(session_id=owned_session,max_messages=100))
            execute("close_project")
            if index + 1 < len(spec["runs"]):
                tool("vivado_todos", dict(operation="update", session_id=owned_session, id="2", status="done", summary="This fixed control completed"))
                tool("vivado_todos", dict(operation="update", session_id=owned_session, id="3", status="done", summary="Diagnostics collected; closing this case session"))
                tool("vivado_stop", dict(session_id=owned_session, close_vivado=True),timeout=60)
                assert owned_session not in session_ids(tool("vivado_list_sessions", {}))
                result["closed_session_ids"].append(owned_session)
                owned_session = None
                next_work = work / ("session_%d" % (index + 2))
                next_work.mkdir()
                new_start = tool("vivado_start", dict(working_dir=str(next_work), session_type="general", gui_mode=False, display_mode="none", external=False),timeout=120)
                new_ids = session_ids(new_start)
                assert len(new_ids) == 1 and not new_ids.intersection(result["closed_session_ids"])
                owned_session = next(iter(new_ids))
                result["session_id"] = owned_session
                log_path = Path(new_start["log_file"]).resolve()
                assert log_path.is_relative_to(next_work.resolve()) and log_path.is_file()
                tool("vivado_todos", dict(operation="plan",session_id=owned_session,title="Independent case probe",tasks=[dict(id="1",content="Verify version"),dict(id="2",content="Execute next fixed control"),dict(id="3",content="Collect and close")]))
                version = execute('puts "MCP_PROBE_VERSION:[version -short]"; puts "MCP_PROBE_PARTS:[llength [get_parts ' + spec["part"] + ']]"')
                version_text = "\n".join(strings(version))
                assert "MCP_PROBE_VERSION:2026.1" in version_text and "MCP_PROBE_PARTS:1" in version_text
                tool("vivado_todos", dict(operation="update",session_id=owned_session,id="1",status="done",summary="Version and part verified in fresh process"))
                tool("vivado_todos", dict(operation="update",session_id=owned_session,id="2",status="active"))
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="2", status="done", summary="Frozen controls completed; lint counts are observations only"))
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="3", status="active"))
        result["final_session_status"] = tool("vivado_status", dict(session_id=owned_session,action="session"))
        tool("vivado_todos", dict(operation="update", session_id=owned_session, id="3", status="done", summary="Diagnostics retained; own-session stop follows"))
        result["passed"] = True
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if client and owned_session:
            try:
                result["stop_response"] = tool("vivado_stop",dict(session_id=owned_session,close_vivado=True),timeout=60)
                result["own_session_absent_after_stop"] = owned_session not in session_ids(tool("vivado_list_sessions", {}))
                if not result["own_session_absent_after_stop"]:
                    result["passed"] = False
                else:
                    result["closed_session_ids"].append(owned_session)
            except BaseException as exc:
                result.update(passed=False,stop_error=type(exc).__name__ + ": " + str(exc))
        if client:
            client.close()
            result["server_exit_code"] = client.proc.returncode
        result.update(complete=True,tool_calls=calls,elapsed_s=time.monotonic()-started)
        save(out / "summary.json", result)
    print(json.dumps(result),flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
