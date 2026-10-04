"""Discover real tool schemas before issuing any Vivado session mutation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from mcp_client import StdioClient

BINARY_SHA256 = "2d1ac42f2628dab2db37bd214b4ad45d2275e541fe6eb71e879ac6ea123bb8bc"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resource-check", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    check = json.loads(args.resource_check.read_text())
    assert check["resource_idle"] and check["model_pid"] == 2013333
    binary = root / "vivado-mcp-server"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == BINARY_SHA256
    out = root / "handshake"
    out.mkdir(exist_ok=False)
    command = [str(binary), "--stdio", "--state-dir=" + str(out / "state"),
               "--vivado-path=/workspace/AMD/2026.1/Vivado/bin/vivado",
               "--enable-lsf=false", "--enable-ssh=false", "--disable-telemetry", "--disable-otel",
               "--max-sessions=1", "--limit-ai-output=false"]
    result = dict(complete=False, passed=False, command=command, model_calls=0, vivado_sessions_started=0)
    client = None
    started = time.monotonic()
    try:
        client = StdioClient(command, out, os.environ.copy(), out / "rpc.jsonl", out / "stderr.log")
        initialization = client.request("initialize", dict(protocolVersion="2025-11-25", capabilities={},
                                        clientInfo=dict(name="fpga-isolated-ross-probe", version="0.1")))
        assert initialization["protocolVersion"] in ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]
        client.notify("notifications/initialized")
        tools = client.request("tools/list", {})
        (out / "tools.json").write_text(json.dumps(tools, ensure_ascii=False, indent=2) + "\n")
        result.update(initialization=initialization, tool_names=[t["name"] for t in tools["tools"]], passed=True)
    except BaseException as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if client:
            client.close()
            result["server_exit_code"] = client.proc.returncode
        result.update(complete=True, elapsed_s=time.monotonic() - started)
        (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
