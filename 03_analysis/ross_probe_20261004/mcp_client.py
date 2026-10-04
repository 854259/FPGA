"""Small sequential stdio MCP client used only by the isolated ROSS probe."""
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


class StdioClient:
    def __init__(self, command, cwd, env, transcript, stderr):
        self.events = queue.Queue()
        self.next_id = 0
        self.stderr = Path(stderr).open("xb")
        self.transcript = Path(transcript).open("x", encoding="utf-8")
        self.write_lock = threading.Lock()
        self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.stderr, cwd=cwd, env=env, bufsize=0)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def record(self, direction, value):
        with self.write_lock:
            self.transcript.write(json.dumps(dict(ts=time.time(), direction=direction, message=value), ensure_ascii=False) + "\n")
            self.transcript.flush()

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(16 * 1024 * 1024)
                if not line:
                    self.events.put(EOFError("MCP server closed stdout"))
                    return
                if not line.endswith(b"\n"):
                    raise ValueError("MCP message is oversized or unterminated")
                value = json.loads(line)
                if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                    raise ValueError("non-MCP stdout message")
                self.record("server", value)
                self.events.put(value)
        except BaseException as exc:
            self.events.put(exc)

    def send(self, value):
        self.record("client", value)
        self.proc.stdin.write((json.dumps(value, separators=(",", ":")) + "\n").encode())
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        message = dict(jsonrpc="2.0", method=method)
        if params is not None:
            message["params"] = params
        self.send(message)

    def request(self, method, params=None, timeout=40):
        self.next_id += 1
        request_id = self.next_id
        message = dict(jsonrpc="2.0", id=request_id, method=method)
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("MCP request deadline: " + method)
            try:
                value = self.events.get(timeout=left)
            except queue.Empty:
                raise TimeoutError("MCP request deadline: " + method)
            if isinstance(value, BaseException):
                raise value
            if value.get("id") == request_id and "method" not in value:
                if "error" in value:
                    raise RuntimeError("MCP RPC error: " + json.dumps(value["error"]))
                return value["result"]
            if "method" in value and "id" in value:
                # No model sampling, automatic approvals or external research.
                if value["method"] == "ping":
                    response = dict(jsonrpc="2.0", id=value["id"], result={})
                else:
                    response = dict(jsonrpc="2.0", id=value["id"], error=dict(code=-32601, message="Unsupported client request"))
                self.send(response)

    def tool(self, name, arguments, timeout=90):
        result = self.request("tools/call", dict(name=name, arguments=arguments), timeout=timeout)
        if result.get("isError") is True:
            raise RuntimeError("MCP tool error: " + name + ": " + json.dumps(result, ensure_ascii=False)[:2000])
        return result

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
        self.thread.join(timeout=2)
        self.proc.stdout.close()
        self.stderr.close()
        self.transcript.close()
