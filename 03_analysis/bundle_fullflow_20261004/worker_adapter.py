"""Owned best-runtime worker replay; first reply fixed, later repair is live.

Private research process only. It does not modify runtime/baseline file bytes,
start a server, or send a testbench/grade to the model.
"""
import argparse
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import urllib.request

from guarded_bundle import decide


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    for name in ("root", "task", "out", "kit", "resource-check"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--arm", choices=("A", "C"), required=True)
    args = ap.parse_args()
    root, out = args.root.resolve(), args.out.resolve()
    spec = json.loads((root / "RUN_SPEC.json").read_text())
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    paired = load("flow_owned", Path(spec["dependencies_cloud"]) / "paired_checkpoint.py")
    lexical = load("flow_lexical", root / "lexical_mask.py")
    runtime = load("flow_runtime", root / "package/agent/runtime.py")
    import baseline
    original_extract = baseline.extract
    base = types.SimpleNamespace(extract=original_extract)
    original_open = urllib.request.urlopen
    requests, extraction = [], []
    initial = (args.task / "initial_response.json").read_bytes()
    out.mkdir(parents=True, exist_ok=False)
    work = out / "work"
    work.mkdir()
    # Runtime reads only a prompt-only input directory, not replay/TB assets.
    prompt_only = out / "prompt_only"
    prompt_only.mkdir()
    (prompt_only / "prompt.txt").write_bytes((args.task / "prompt.txt").read_bytes())
    (out / "solution.v").write_text("")
    (out / "trace.jsonl").write_text("")

    def journal_open(request, *positional, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if not url.endswith("/chat/completions"):
            return original_open(request, *positional, **kwargs)
        assert url == "http://127.0.0.1:8000/v1/chat/completions"
        assert isinstance(request, urllib.request.Request) and request.get_method() == "POST"
        index = len(requests)
        assert index < 2, "original one-repair budget"
        payload = json.loads(request.data)
        expected_system = runtime.skill_texts()[0]
        if index:
            expected_system += "\n" + runtime.skill_texts()[1]
        assert payload["messages"][0] == dict(role="system", content=expected_system)
        assert payload["model"] == spec["model"] and payload["temperature"] == 0
        assert payload["top_p"] == 1 and payload["max_tokens"] == 8192
        folder = out / "requests" / str(index)
        folder.mkdir(parents=True)
        save(folder / "request.json", payload)
        entry = dict(index=index, replayed=index == 0, response_received=False)
        requests.append(entry)
        save(out / "requests.json", requests)
        tick = time.monotonic()
        if index == 0:
            raw = initial
        else:
            paired.check_resource(args.resource_check, args.kit)
            paired.model_idle("http://127.0.0.1:8000/v1", spec["model"])
            # Same explicit research timeout in both arms; runtime's 300s default
            # is capped by this experiment, never presented as official cost.
            with original_open(request, timeout=spec["request_timeout_s"]) as response:
                raw = response.read()
        (folder / "response.json").write_bytes(raw)
        data = json.loads(raw)
        choice = data["choices"][0]
        entry.update(response_received=True, elapsed_s=time.monotonic() - tick,
                     finish_reason=choice.get("finish_reason"), response_id=data.get("id"))
        save(out / "requests.json", requests)
        if choice.get("finish_reason") != "stop" or not choice["message"].get("content"):
            raise RuntimeError("Incomplete live/replayed response: stop, no retry")
        return io.BytesIO(raw)

    def guarded_extract(text, track):
        assert track == "rtl"
        index = len(extraction)
        if args.arm == "A":
            code, receipt = original_extract(text, track), dict(decision="original_baseline")
        else:
            code, receipt = decide(text, base, lexical._strip_noncode, paired,
                                   out / ("candidate_gate_" + str(index)), os.environ["VIVADO_BIN"])
        (out / ("extracted_" + str(index) + ".sv")).write_text(code, encoding="utf-8")
        extraction.append(receipt)
        save(out / "extraction.json", extraction)
        return code

    urllib.request.urlopen = journal_open
    baseline.extract = guarded_extract
    os.chdir(work)
    started = time.monotonic()
    runtime.worker(prompt_only, out)
    assert len(requests) == len(extraction) and 1 <= len(requests) <= 2
    assert all(x["response_received"] for x in requests)
    events = [json.loads(line) for line in (out / "trace.jsonl").read_text().splitlines()]
    assert not any(e.get("error") for e in events)
    result = dict(complete=True, arm=args.arm, requests=len(requests),
                  replayed_requests=1, actual_model_requests=len(requests) - 1,
                  elapsed_s=time.monotonic() - started, extraction=extraction)
    save(out / "worker_result.json", result)
    print(json.dumps({k:v for k,v in result.items() if k != "extraction"}), flush=True)


if __name__ == "__main__":
    main()
