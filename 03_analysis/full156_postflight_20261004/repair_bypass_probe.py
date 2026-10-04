"""Local fake-transport/tool causal probe of the CURRENT frozen C control flow.

No real compiler, simulator, synthesis or model. Does not establish RTL grades.
"""
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "full156_bundle_20261004"
sys.path.insert(0, str(FROZEN))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def probe(output):
    output = Path(output)
    assert not output.exists()
    spec = json.loads((FROZEN / "RUN_SPEC.json").read_text(encoding="utf-8"))
    for name, digest in spec["source_hashes"].items():
        assert sha((FROZEN / name).read_bytes()) == digest, name
    baseline = load("probe_baseline", FROZEN / "package/baseline.py")
    runtime = load("probe_runtime", FROZEN / "package/agent/runtime.py")
    lexical = load("probe_lexical", FROZEN / "lexical_mask.py")
    candidate = load("probe_current_C", FROZEN / "guarded_bundle.py")
    original_extract = baseline.extract
    prompt = "Implement a combinational exclusive-or: y is one exactly when a and b differ."
    top = """module TopModule(input a, input b, output y);
  helper_gate h (.a(a), .b(b), .y(y));
endmodule"""
    wrong_helper = """module helper_gate(input a, input b, output y);
  assign y = a & b;
endmodule"""
    first_reply = top + "\n" + wrong_helper + "\n"
    repaired_reply = """module TopModule(input a, input b, output y);
  assign y = a ^ b;
endmodule
"""
    rows = {}
    with tempfile.TemporaryDirectory(prefix="current-C-bypass-") as temporary:
        root = Path(temporary)
        tool = root / "bin/xvlog"
        tool.parent.mkdir()
        tool.write_text("fake fixture")
        for arm in ("A", "C"):
            task, out, work = (root / arm / name for name in ("task", "out", "work"))
            for directory in (task, out, work):
                directory.mkdir(parents=True)
            (task / "prompt.txt").write_text(prompt, encoding="utf-8")
            requests, extractions, fake_tools = [], [], []

            def fake_open(request, *args, **kwargs):
                requests.append(json.loads(request.data))
                reply = first_reply if len(requests) == 1 else repaired_reply
                assert len(requests) <= 2
                return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=reply), finish_reason="stop")],
                    usage=dict(prompt_tokens=1, completion_tokens=1))).encode())

            def fake_native(argv, **kwargs):
                assert Path(argv[0]) == tool and argv[1] == "--sv"
                fake_tools.append(dict(scope="fake native xvlog", source_sha256=sha(Path(argv[2]).read_bytes())))
                return subprocess.CompletedProcess(argv, 0, stdout="Fake parser accepted fixture.\n")

            def fake_gate(argv, cwd, log, seconds):
                assert Path(argv[0]).name in ("xvlog", "xelab") and seconds == 60
                raw = b"Fake candidate compile/elaboration accepted fixture.\n"
                Path(log).write_bytes(raw)
                fake_tools.append(dict(scope="fake C gate", tool=Path(argv[0]).name))
                return dict(timeout=False, launch_error=None, returncode=0, remaining_live_group=[],
                    elapsed_s=0., log=str(log), log_sha256=sha(raw), log_bytes=len(raw), group_signals=[])

            def extract(reply, track):
                if arm == "A":
                    code, receipt = original_extract(reply, track), dict(decision="original_baseline")
                else:
                    code, receipt = candidate.decide(reply, types.SimpleNamespace(extract=original_extract),
                        lexical._strip_noncode, types.SimpleNamespace(owned_command=fake_gate),
                        out / ("gate_" + str(len(extractions))), str(tool.parent))
                extractions.append(receipt)
                return code

            previous_cwd = Path.cwd()
            try:
                os.chdir(work)
                with patch.dict(sys.modules, {"baseline": baseline}), \
                     patch.dict(os.environ, {"MODEL_NAME": spec["model"], "RTL_REPAIRS": "1",
                         "RTL_TEMPERATURE": "0", "RTL_MAX_TOKENS": "8192", "LLM_BASE_URL": "http://127.0.0.1:8000/v1"}), \
                     patch("urllib.request.urlopen", fake_open), patch("subprocess.run", fake_native), \
                     patch.object(runtime, "vivado_tool", lambda _: str(tool)), \
                     patch.object(baseline, "extract", extract):
                    runtime.worker(task, out)
            finally:
                os.chdir(previous_cwd)
            final = (out / "solution.v").read_text(encoding="utf-8")
            events = [json.loads(line) for line in (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            rows[arm] = dict(fake_response_requests=len(requests), first_request=requests[0],
                final_source=final, extractions=extractions,
                tools=[e["tool"] for e in events], fake_tools=fake_tools)
        assert rows["A"]["first_request"] == rows["C"]["first_request"]
        assert rows["A"]["fake_response_requests"] == 2 and rows["C"]["fake_response_requests"] == 1
        assert rows["A"]["final_source"] == original_extract(repaired_reply, "rtl")
        assert rows["C"]["extractions"][0]["decision"] == "candidate_accepted"
        assert rows["C"]["final_source"].startswith(original_extract(first_reply, "rtl") + "\n")
        assert "assign y = a & b;" in rows["C"]["final_source"]
        assert "check_submodules" in rows["A"]["tools"] and "check_submodules" not in rows["C"]["tools"]
    for row in rows.values():
        row["first_request_sha256"] = sha(json.dumps(row.pop("first_request"), sort_keys=True).encode())
        row["final_source_sha256"] = sha(row.pop("final_source").encode())
    result = dict(schema="current_C_repair_bypass_control_probe_v1",
        observed_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        complete=True, control_flow_risk_reproduced=True, model_calls=0, eda_calls=0,
        scope="Constructed local fake transport and compiler; actual frozen runtime and C extraction executed",
        source_spec_sha256=sha((FROZEN / "RUN_SPEC.json").read_bytes()),
        rows=rows, boolean_expressions_differ_on=sum((a ^ b) != (a & b) for a in (0, 1) for b in (0, 1)),
        boolean_domain_inputs=4, actual_rtl_functional_judgement=False,
        conclusion="Appending an unchanged top plus wrong-but-compilable helper can bypass original successful repair. Top preservation and compile gate do not preserve original final behavior.",
        action="No automatic promotion from full156 score alone; need explicit preservation or revised placement before integration.",
        frozen_cloud_run_modified=False, probe_sha256=sha(Path(__file__).read_bytes()))
    output.mkdir(parents=True)
    (output / "RESULTS.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8", newline="\n")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.out), ensure_ascii=False))
