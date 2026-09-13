# -*- coding: utf-8 -*-
"""Run all 156 VerilogEval spec-to-rtl problems against the cloud LLM.

Resumable: per-problem results are appended to progress.jsonl; rerunning the
script skips problems that already have a record. Safe to launch detached.

Usage:
    python bench/run_full_156.py            # run remaining problems
    python bench/run_full_156.py --status   # print progress and exit

API key resolution order: LLM_API_KEY env var, then outputs/.llm_api_key file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "bench" / "verilog-eval" / "dataset_spec-to-rtl"
RESULTS_DIR = ROOT / "bench" / "results"
KEY_FILE = ROOT / "outputs" / ".llm_api_key"

TOTAL = 156
PER_PROBLEM_TIMEOUT_S = 1800
MAX_RETRIES = 3
RETRY_BACKOFF_S = [30, 90, 240]

ENV_OVERRIDES = {
    "LLM_BASE_URL": "https://ws-zx533vazjgfeshi6.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "LLM_MODEL": "qwen3.6-27b",
    "LLM_ENABLE_THINKING": "false",
    "LLM_MAX_TOKENS": "2048",
    "LLM_TIMEOUT_SECONDS": "120",
    "LLM_TEMPERATURE": "0.2",
    "VIVADO_BIN": r"E:\vivado\2025.2\Vivado\bin",
}


def list_problems() -> list[str]:
    prompts = sorted(DATASET.rglob("*_prompt.txt"))
    return [p.name[: -len("_prompt.txt")] for p in prompts]


def find_run_dir() -> Path:
    """Reuse the newest full156 run dir with progress, else create one."""
    outputs = ROOT / "outputs"
    outputs.mkdir(exist_ok=True)
    candidates = sorted(outputs.glob("full156_*"), key=os.path.getmtime, reverse=True)
    for cand in candidates:
        if (cand / "progress.jsonl").is_file():
            return cand
    run_dir = outputs / ("full156_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_progress(run_dir: Path) -> dict[str, dict]:
    progress = {}
    path = run_dir / "progress.jsonl"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            progress[rec["problem"]] = rec
    return progress


def write_status(run_dir: Path, problems: list[str], progress: dict, current: str | None):
    done = [progress[p] for p in problems if p in progress]
    status = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "total": len(problems),
        "completed": len(done),
        "current_problem": current,
        "baseline_passed": sum(1 for r in done if r.get("baseline_pass")),
        "agent_passed": sum(1 for r in done if r.get("pass_at_1")),
        "failed_problems": [r["problem"] for r in done if r.get("error")],
        "run_dir": str(run_dir),
    }
    (run_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_one(offset: int, name: str, run_dir: Path, env: dict) -> dict:
    out_dir = run_dir / "problems" / f"{offset + 1:03d}_{name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ROOT / "agent.py"),
        "benchmark",
        "--dataset", str(DATASET),
        "--output-dir", str(out_dir),
        "--offset", str(offset),
        "--limit", "1",
        "--samples", "1",
        "--repairs", "1",
    ]
    log_path = out_dir / "subprocess.log"
    last_err = None
    for attempt in range(MAX_RETRIES):
        attempt_output = out_dir / f'run_attempt_{attempt + 1}'
        sequence = attempt + 1
        while attempt_output.exists():
            sequence += 1
            attempt_output = out_dir / f'run_attempt_{sequence}'
        cmd[cmd.index('--output-dir') + 1] = str(attempt_output)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n===== attempt {attempt + 1} {datetime.now().isoformat()} =====\n")
            log.flush()
            try:
                proc = subprocess.run(
                    cmd, cwd=ROOT, env=env, stdout=log, stderr=log,
                    timeout=PER_PROBLEM_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired:
                last_err = f"timeout after {PER_PROBLEM_TIMEOUT_S}s"
            else:
                if proc.returncode == 0:
                    bench = attempt_output / "benchmark.json"
                    if bench.is_file():
                        recs = json.loads(bench.read_text(encoding="utf-8")).get("records", [])
                        if recs:
                            return {
                                "problem": name,
                                "offset": offset,
                                "baseline_pass": recs[0].get("baseline_pass"),
                                "pass_at_1": recs[0].get("pass_at_1"),
                                "repair_succeeded": recs[0].get("repair_succeeded"),
                                "elapsed_s": recs[0].get("elapsed_s"),
                                "attempts": attempt + 1,
                            }
                        last_err = "benchmark.json has no records"
                    else:
                        last_err = "benchmark.json missing"
                else:
                    last_err = f"exit code {proc.returncode}"
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_BACKOFF_S[attempt])
    return {"problem": name, "offset": offset, "error": last_err,
            "baseline_pass": None, "pass_at_1": None, "attempts": MAX_RETRIES}


def write_final_summary(run_dir: Path, problems: list[str], progress: dict):
    records = [progress[p] for p in problems if p in progress]
    ok = [r for r in records if r.get("pass_at_1") is not None]
    summary = {
        "scope": "all 156 VerilogEval spec-to-rtl problems",
        "dataset_total": len(problems),
        "completed_problems": len(ok),
        "failed_problems": [r["problem"] for r in records if r.get("error")],
        "baseline_passed": sum(1 for r in ok if r.get("baseline_pass")),
        "agent_passed": sum(1 for r in ok if r.get("pass_at_1")),
        "agent_repairs_used": sum(1 for r in ok if r.get("repair_succeeded")),
        "model": {
            "model": ENV_OVERRIDES["LLM_MODEL"],
            "max_tokens": int(ENV_OVERRIDES["LLM_MAX_TOKENS"]),
            "temperature": float(ENV_OVERRIDES["LLM_TEMPERATURE"]),
            "context": 8192,
        },
        "evaluation_mode": "compile_simulation_synthesis",
        "elapsed_s_completed_problems": sum(r.get("elapsed_s") or 0 for r in ok),
        "records": records,
    }
    out = RESULTS_DIR / ("qwen_cloud_full156_" + datetime.now().strftime("%Y%m%d") + ".json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    problems = list_problems()
    if len(problems) != TOTAL:
        print(f"expected {TOTAL} problems, found {len(problems)}", file=sys.stderr)
        return 2
    run_dir = find_run_dir()

    if "--status" in sys.argv:
        progress = load_progress(run_dir)
        done = [progress[p] for p in problems if p in progress]
        print(f"run_dir: {run_dir}")
        print(f"completed: {len(done)}/{len(problems)}")
        ok = [r for r in done if r.get("pass_at_1") is not None]
        print(f"baseline pass: {sum(1 for r in ok if r.get('baseline_pass'))}/{len(ok)}")
        print(f"agent pass@1:  {sum(1 for r in ok if r.get('pass_at_1'))}/{len(ok)}")
        errs = [r["problem"] for r in done if r.get("error")]
        if errs:
            print(f"errors: {errs}")
        return 0

    api_key = os.environ.get("LLM_API_KEY")
    if not api_key and KEY_FILE.is_file():
        api_key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        print(f"no API key: set LLM_API_KEY or write {KEY_FILE}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    env.update(ENV_OVERRIDES)
    env["LLM_API_KEY"] = api_key
    env.pop("LLM_MOCK_FILE", None)

    progress = load_progress(run_dir)
    remaining = [(i, p) for i, p in enumerate(problems)
                 if p not in progress or progress[p].get('error')]
    print(f"run_dir={run_dir} completed={len(progress)} remaining={len(remaining)}", flush=True)

    with (run_dir / "progress.jsonl").open("a", encoding="utf-8") as sink:
        for i, name in remaining:
            write_status(run_dir, problems, progress, name)
            print(f"[{len(progress) + 1}/{len(problems)}] {name} ...", flush=True)
            rec = run_one(i, name, run_dir, env)
            progress[name] = rec
            sink.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sink.flush()
            print(f"    -> pass_at_1={rec.get('pass_at_1')} error={rec.get('error')}", flush=True)

    write_status(run_dir, problems, progress, None)
    out = write_final_summary(run_dir, problems, progress)
    print(f"ALL DONE. summary: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
