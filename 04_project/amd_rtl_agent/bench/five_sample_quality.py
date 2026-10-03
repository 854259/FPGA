#!/usr/bin/env python3
"""5 样本质量评测：取 5 个样本，**用官方汇总函数**算成绩。

为什么重写（第二版）
--------------------
第一版只是"同请求打 5 次看返回是否相同"，不是协议。
第二版我自己算了分数，但**算法与官方口径不符**：

| 项 | 我第二版的做法 | 官方口径（score.py::summarize） |
|---|---|---|
| 空答案 | 排除出平均分 | **属于 L0，系数 0，留在分母里** |
| `pass@5` | 任意一次 L3 才记 1 | **取各样本等级系数的最大值** |
| `tool_error` | 未单独处理 | **单列排除**；整题全为环境失败则记录不计分 |

反例（评审给的，已在官方函数上核对过）：
  1xL3 + 4x空答 -> 官方 pass@1=0.2   （我算成 1.0）
  5xL2          -> 官方 pass@5=0.7   （我算成 0）

所以本版**不再自己算**，而是把判定器的 verdict 原样交给官方 `summarize()`。
判定器的 verdict 本来就含 `level` / `coefficient` / `tool_error`，可直接喂入。

说明
----
- "五次中是否出现 L3"仍有参考价值，但**另起名字** `any_l3`，不叫 pass@5。
- 报告里同时给出 `scored_tasks / tasks`：**缺结果必须表现为"评测不完整"，不能静默跳过**。
- 这只是**子集**评测，不是完整 1560 次协议。
- 不改 agent、不改题集、不改判定器，只读官方汇总函数。
"""
import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

def resolve_kit():
    """Locate the kit in either layout.

    Cloud deployment keeps it at a fixed path; the repository keeps the same tree
    under 04_project/amd_rtl_agent/, which is this file's grandparent. Resolving
    instead of hardcoding means the summary logic can be exercised by tests on a
    machine that has no cloud path at all.
    """
    override = os.environ.get("RTL_KIT")
    candidates = []
    if override:
        candidates.append(pathlib.Path(override))
    candidates.append(pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project"))
    candidates.append(pathlib.Path(__file__).resolve().parents[1])
    for candidate in candidates:
        if (candidate / "official_reference" / "selftest" / "score.py").is_file():
            return candidate
    return candidates[-1]


KIT = resolve_kit()
TASKS_DIR = KIT / "bench" / "tasks_veval"
JUDGE = KIT / "official_reference" / "selftest" / "judge.py"
OFFICIAL_SCORE = KIT / "official_reference" / "selftest" / "score.py"
TOKEN = "five-sample-quality-token"

DEFAULT_PICK = [
    "Prob001_zero", "Prob009_popcount3", "Prob050_kmap1", "Prob058_alwaysblock2",
    "Prob070_ece241_2013_q2", "Prob082_lfsr32", "Prob145_circuit8", "Prob147_circuit10",
]


def load_official_score():
    """官方汇总函数。绝不自己重写统计口径。"""
    spec = importlib.util.spec_from_file_location("official_score", OFFICIAL_SCORE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    if not hasattr(module, "summarize"):
        raise RuntimeError("官方 score.py 里找不到 summarize()")
    return module


def wait_ready(port, timeout=90):
    """只有 200 且 ready:true 才算就绪；只看"有没有响应"会把 401/500 当正常。"""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/v1/health" % port,
                                         headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=5) as r:
                last = json.loads(r.read().decode())
            if last.get("ready") is True:
                return True, last
        except Exception as exc:                        # noqa: BLE001
            last = {"error": type(exc).__name__}
        time.sleep(2)
    return False, last


def post_solve(port, task_id, prompt, mode, deadline):
    body = json.dumps({"task_id": task_id, "nonce": "%s-%d" % (task_id, time.time_ns()),
                       "mode": mode, "prompt": prompt, "interface": "",
                       "deadline_s": deadline}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/solve" % port, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + TOKEN})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=deadline + 60) as r:
            return r.status, json.loads(r.read().decode()), time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return None, {"error": type(exc).__name__}, time.time() - t0


def run_judge(task_dir, solution_path, outdir):
    os.makedirs(outdir, exist_ok=True)
    jf = os.path.join(outdir, "verdict.json")
    subprocess.run(["python3", "-B", str(JUDGE), "--task", str(task_dir),
                    "--solution", str(solution_path), "--outdir", outdir,
                    "--json", jf, "--timeout", "600"],
                   capture_output=True, text=True, errors="replace")
    if os.path.isfile(jf):
        try:
            return json.loads(pathlib.Path(jf).read_text())
        except ValueError:
            return {}
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", nargs="*", default=DEFAULT_PICK)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--deadline", type=float, default=300.0)
    ap.add_argument("--port", type=int, default=7867)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/workspace/team/runs/fpga_owner/five_sample_quality_20261003"))
    args = ap.parse_args()

    official = load_official_score()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scratch").mkdir(exist_ok=True)
    print("官方口径: summarize() 来自 %s" % OFFICIAL_SCORE.name, flush=True)
    print("profile=%s 题数=%d 模式=agent+baseline 每模式 %d 样本"
          % (os.environ.get("RTL_PROFILE", "(unset)"), len(args.tasks), args.samples), flush=True)

    env = os.environ.copy()
    env.update(FPGACHINA_TOKEN=TOKEN, PYTHONUTF8="1",
               EDA_TMP=str(args.out / "scratch"), SELFTEST_TMP=str(args.out / "scratch"))
    srv = subprocess.Popen([sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
                            "serve", "--port", str(args.port)],
                           cwd=str(KIT), env=env, stdout=open(args.out / "server.log", "w"),
                           stderr=subprocess.STDOUT, start_new_session=True)
    try:
        ok, detail = wait_ready(args.port)
        print("就绪:", ok, detail, flush=True)
        if not ok:
            print("服务未就绪，放弃（先查令牌与 ready 条件）", flush=True)
            return 1

        # by_task[mode][task_id] = [verdict, ...]   —— 与官方 collect() 的结构一致
        by_task = {"agent": {}, "baseline": {}}
        for task in args.tasks:
            task_dir = TASKS_DIR / task
            prompt_file = task_dir / "prompt.txt"
            if not prompt_file.is_file():
                print("  跳过（题不存在）:", task, flush=True)
                continue
            prompt = prompt_file.read_text(encoding="utf-8")
            for mode in ("agent", "baseline"):
                by_task[mode].setdefault(task, [])
                for k in range(args.samples):
                    d = args.out / task / mode / ("s%d" % k)
                    d.mkdir(parents=True, exist_ok=True)
                    code, payload, el = post_solve(args.port, task, prompt, mode, args.deadline)
                    sol = payload.get("solution") or ""
                    (d / "solution.v").write_text(sol, encoding="utf-8")
                    (d / "trace.jsonl").write_text(payload.get("trace") or "", encoding="utf-8")
                    (d / "response.json").write_text(
                        json.dumps(payload, ensure_ascii=False)[:20000], encoding="utf-8")
                    # 空答案交给官方判定器：它会判为 L0（judge.py 明确写了"空解属于 L0"）
                    v = run_judge(task_dir, d / "solution.v", str(d / "judge"))
                    if not v:
                        # 判定没产出结果：标记为环境失败，让官方汇总把它单列，
                        # 而不是当成 L0 静默计入（否则会把工具问题算成模型失分）
                        v = {"task_id": task, "tool_error": "judge produced no verdict"}
                    v.setdefault("task_id", task)
                    by_task[mode][task].append(v)
                lv = [s.get("level") for s in by_task[mode][task]]
                te = sum(1 for s in by_task[mode][task] if s.get("tool_error"))
                print("  %-32s %-8s 等级=%-22s 环境失败=%d"
                      % (task, mode, lv, te), flush=True)

        print()
        print("=== 官方 summarize() 的结果 ===")
        summary = {}
        for mode in ("agent", "baseline"):
            res = official.summarize(by_task[mode])
            summary[mode] = res
            print("  %-9s 题集得分(pass@1)=%.4f  pass@5=%.4f  计分题 %d/%d  环境失败 %d"
                  % (mode, res["set_score"], res["pass@5"],
                     res["scored_tasks"], res["tasks"], res["tool_errors"]))
            if res["scored_tasks"] != res["tasks"]:
                print("    ⚠ 评测不完整：%d 题未计入（见 excluded）"
                      % (res["tasks"] - res["scored_tasks"]))
        a = summary["agent"]["set_score"]
        b = summary["baseline"]["set_score"]
        gain, gscore = official.gain_score(a, b)
        print("  增益 = %s   增益得分(满分线 %.1f) = %.2f"
              % ("%.4f" % gain if gain is not None else "N/A", official.GAIN_FULL_MARK, gscore))

        # 另起名字的辅助指标：五次中是否出现过 L3
        print()
        print("=== 辅助指标（不叫 pass@5，避免与官方口径混淆）===")
        for mode in ("agent", "baseline"):
            anyl3 = 0
            for t, samples in by_task[mode].items():
                good = [s for s in samples if not s.get("tool_error")]
                if any(s.get("level") == 3 for s in good):
                    anyl3 += 1
            print("  %-9s any_l3（5 次中出现过 L3 的题数）= %d / %d"
                  % (mode, anyl3, len(by_task[mode])))

        (args.out / "quality_official.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        (args.out / "by_task.json").write_text(
            json.dumps(by_task, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print("说明：空答案按官方口径是 L0（judge.py 写明「空解属于 L0」），留在分母里。")
        print("      环境失败按官方口径单列排除；整题全为环境失败时该题不计分，")
        print("      代码注释如此，但官方算术会给 set_score 一个 0 —— 所以这里同时报")
        print("      scored_tasks/tasks，让「评测不完整」可见，而不是静默通过。")
        print("      这是子集评测，不是完整 1560 次协议。")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
