"""One AMD-only prompt/interface intake; no scoring, model, EDA or retries."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    assert sys.platform == "linux" and sys.dont_write_bytecode
    source, output = args.source.resolve(), args.output.resolve()
    assert not output.exists(), "An existing attempt must not be overwritten."
    assert sha(source / "SOURCE_MANIFEST.json") == args.manifest_sha256
    manifest = json.loads((source / "SOURCE_MANIFEST.json").read_bytes())
    for name, expected in manifest.items():
        path = (source / name).resolve()
        assert path.is_relative_to(source) and sha(path) == expected, name
    assert sha(source / "synthesis.py") == "aaac33da469438e8c157a5c284ed5367c43256d126b9392392676fb01b1b3ed5"
    assert sha(source / "reserved_keywords.py") == "3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e"
    tasks = json.loads((source / "upstream/RUN_SPEC.json").read_bytes())["task_ids"]
    assert len(tasks) == len(set(tasks)) == 156 and tasks == sorted(tasks)
    inputs = json.loads((source / "upstream/INPUT_MANIFEST.json").read_bytes())["input_sha256"]
    texts = {}
    for task in tasks:
        assert Path(task).name == task
        texts[task] = {}
        for name in ("prompt.txt", "interface.txt"):
            path = args.kit / "bench/tasks_veval" / task / name
            expected = inputs.get(task + "/" + name)
            if expected is None:
                assert not path.exists()
                texts[task][name] = ""
            else:
                raw = path.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == expected
                texts[task][name] = raw.decode("utf-8")
    output.mkdir(parents=True)
    start = time.monotonic()
    plan = dict(schema="full156_prompt_only_intake_once_v1",
                manifest_sha256=args.manifest_sha256, source_files=len(manifest),
                task_count=156, model_calls=0, eda_calls=0, retries=0,
                execution_watchdog_s=60, input_use="seen-development-prompt-interface-only",
                pid=os.getpid(), stat=Path("/proc/self/stat").read_text(),
                command_sha256=sha("/proc/self/cmdline"), script_sha256=sha(__file__))
    (output / "INTENT.json").write_text(json.dumps(plan, indent=2) + "\n")
    def deadline(signum, frame):
        raise TimeoutError("Frozen intake watchdog")
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(60)
    try:
        sys.path.insert(0, str(source))
        spec = importlib.util.spec_from_file_location("frozen_producer", source / "synthesis.py")
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        def deny_external(event, audit_args):
            if event == "open" or event.startswith(("socket.", "subprocess.", "os.system", "os.exec", "os.spawn")):
                raise RuntimeError("Producer external access forbidden: " + event)
        # Enable only during production calls, without exposing task identity to the producer.
        active = [False]
        sys.addaudithook(lambda event, values: deny_external(event, values) if active[0] else None)
        rows = {}
        for task in tasks:
            active[0] = True
            try:
                result = producer.synthesize(texts[task]["prompt.txt"], texts[task]["interface.txt"])
            finally:
                active[0] = False
            assert type(result["emitted"]) is bool
            assert result["actual_model_requests"] == result["actual_eda_calls"] == result["external_io_calls"] == 0
            rows[task] = result
        for name, expected in manifest.items():
            assert sha(source / name) == expected
        admission = dict(schema="full156_prompt_only_production_admission_v1",
                         task_count=156, tasks=rows, source_manifest_sha256=args.manifest_sha256,
                         actual_model_calls=0, actual_eda_calls=0, accuracy_measured=False,
                         full_run_admitted=False, elapsed_execution_s=time.monotonic()-start)
        (output / "PRODUCTION_ADMISSION.json").write_text(json.dumps(admission, indent=2) + "\n")
        print(json.dumps(dict(task_count=156, emitted=sum(r["emitted"] for r in rows.values()),
                              abstained=sum(not r["emitted"] for r in rows.values()),
                              model_calls=0, eda_calls=0,
                              admission_sha256=sha(output / "PRODUCTION_ADMISSION.json"),
                              elapsed_execution_s=admission["elapsed_execution_s"])), flush=True)
    except BaseException as exc:
        (output / "FAILURE.json").write_text(json.dumps(dict(type=type(exc).__name__, message=str(exc)))+"\n")
        raise
    finally:
        signal.alarm(0)

if __name__ == "__main__":
    main()

