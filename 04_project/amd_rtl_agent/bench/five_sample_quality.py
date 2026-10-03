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
import shutil
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
    """判一份解答。目录必须唯一，且必须确认结果是本轮生成的。

    第一版把判定输出写到可复用目录，又不检查子进程退出码——本次判定失败时
    可能读到上一轮留下的 verdict.json，把旧成绩当成本次成绩。所以这里先清空目录，
    再确认 verdict.json 确实由本次运行写出；拿不到就标为环境失败，不猜等级。
    """
    if os.path.exists(outdir):
        shutil.rmtree(outdir, ignore_errors=True)
    os.makedirs(outdir, exist_ok=True)
    jf = os.path.join(outdir, "verdict.json")
    proc = subprocess.run(["python3", "-B", str(JUDGE), "--task", str(task_dir),
                           "--solution", str(solution_path), "--outdir", outdir,
                           "--json", jf, "--timeout", "600"],
                          capture_output=True, text=True, errors="replace")
    if not os.path.isfile(jf):
        return {"tool_error": "judge produced no verdict (rc=%s)" % proc.returncode}
    try:
        verdict = json.loads(pathlib.Path(jf).read_text())
    except ValueError as exc:
        return {"tool_error": "unreadable verdict: %s" % exc}
    # 残余二：parseable 的新 verdict 也要看退出码。
    # 官方 judge 正常写出结果后返回 0；非零退出搭配新结果属判定异常，不能仅凭
    # JSON 可解析就默认成功——否则一次"写了成绩但进程失败"会被计成有效等级。
    if proc.returncode != 0:
        raw = verdict
        verdict = {"tool_error": "judge wrote a verdict but exited %s" % proc.returncode}
        # 原始 JSON 与退出码都保留，供追查，不丢失证据
        verdict["judge_raw_verdict"] = raw
        verdict["judge_returncode"] = proc.returncode
    return verdict


def evaluate_state(attempted, expected_cells, missing_tasks, summary):
    """把「尝试完成」与「可比较」拆成两个独立状态。

    只检查 attempted == expected_cells 是不够的：80 格全部环境失败时，
    尝试是齐全的，但两个模式的 scored_tasks 都是 0，官方汇总返回的 0 只是兜底，
    这种结果不能用来比较模型或版本。抽成纯函数是为了能直接测它，
    而不是在测试里重写一遍布尔公式。
    """
    attempts_complete = bool(attempted == expected_cells and not missing_tasks)
    coverage = {}
    incomparable = []
    if not attempts_complete:
        incomparable.append("尝试不齐全")
    for mode in ("agent", "baseline"):
        res = summary.get(mode) or {}
        tasks = res.get("tasks", 0)
        scored = res.get("scored_tasks", 0)
        coverage[mode] = round((scored / tasks) if tasks else 0.0, 4)
        if scored == 0:
            incomparable.append("%s 没有任何有效成绩" % mode)
    return dict(attempts_complete=attempts_complete,
                scored_coverage=coverage,
                comparable=not incomparable,
                incomparable_reasons=incomparable)


def exit_code_for(state):
    """退出码策略，供自动消费者区分三种状态。

    0 = 尝试齐全且可比较；2 = 尝试不齐全；3 = 尝试齐全但不可比较。
    此前只有 0/2，于是「80 格全环境失败」会得到 0，被当成可用实验。
    """
    if not state["attempts_complete"]:
        return 2
    if not state["comparable"]:
        return 3
    return 0


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
        # 完整性台账：预期 vs 实际。只比 scored_tasks 与 tasks 会漏掉两种情形：
        #   - 请求了 20 题，其中 1 题不存在 -> 仍显示 19/19，看不出少了
        #   - 某题 5 次采样只有 1 次有效，其余环境失败 -> 仍算"已计分题"
        # 所以按 题目 x 模式 x 采样 逐格记账。
        ledger = dict(expected_tasks=len(args.tasks), missing_tasks=[],
                      expected_cells=len(args.tasks) * 2 * args.samples,
                      attempted=0, empty=0, tool_error=0, graded=0)
        for task in args.tasks:
            task_dir = TASKS_DIR / task
            prompt_file = task_dir / "prompt.txt"
            if not prompt_file.is_file():
                ledger["missing_tasks"].append(task)
                print("  ⚠ 题目不存在，未评测:", task, flush=True)
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
                    # 空答案交给官方判定器：它会判为 L0（judge.py 明确写了空解属于 L0）
                    v = run_judge(task_dir, d / "solution.v", str(d / "judge"))
                    if not v:
                        # 判定没产出结果：标为环境失败，让官方汇总单列，
                        # 而不是当成 L0 静默计入（否则工具问题会被算成模型失分）
                        v = {"tool_error": "judge produced no verdict"}
                    v.setdefault("task_id", task)
                    by_task[mode][task].append(v)
                    ledger["attempted"] += 1
                    if v.get("tool_error"):
                        ledger["tool_error"] += 1
                    else:
                        ledger["graded"] += 1
                        if not sol.strip():
                            ledger["empty"] += 1
                lv = [s.get("level") for s in by_task[mode][task]]
                te = sum(1 for s in by_task[mode][task] if s.get("tool_error"))
                print("  %-32s %-8s 等级=%-22s 环境失败=%d"
                      % (task, mode, lv, te), flush=True)

        print()
        print("=== 完整性台账（预期 vs 实际）===")
        print("  预期题数          : %d" % ledger["expected_tasks"])
        print("  题目不存在（未评测）: %d %s"
              % (len(ledger["missing_tasks"]),
                 ledger["missing_tasks"] if ledger["missing_tasks"] else ""))
        print("  预期采样格数      : %d （题 x 2 模式 x %d）"
              % (ledger["expected_cells"], args.samples))
        print("  实际尝试          : %d" % ledger["attempted"])
        print("  有效判分          : %d" % ledger["graded"])
        print("  其中空答案(记 L0) : %d" % ledger["empty"])
        print("  环境失败(单列)    : %d" % ledger["tool_error"])
        # 残余一：把"尝试完成"与"可比较"分成两个状态（见 evaluate_state）。
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
                print("    ⚠ 该模式有 %d 题无有效成绩"
                      % (res["tasks"] - res["scored_tasks"]))
        a = summary["agent"]["set_score"]
        b = summary["baseline"]["set_score"]
        gain, gscore = official.gain_score(a, b)
        print("  增益 = %s   增益得分(满分线 %.1f) = %.2f"
              % ("%.4f" % gain if gain is not None else "N/A", official.GAIN_FULL_MARK, gscore))

        # 残余一：把"尝试完成"与"可比较"分成两个状态（见 evaluate_state）。
        # 必须放在 summary 之后——它要用计分题数算覆盖比例。
        state = evaluate_state(ledger["attempted"], ledger["expected_cells"],
                               ledger["missing_tasks"], summary)
        attempts_complete = state["attempts_complete"]
        coverage = state["scored_coverage"]
        comparable = state["comparable"]
        incomparable = state["incomparable_reasons"]

        print()
        print("=== 状态（三个分开的标志）===")
        print("  attempts_complete : %s" % attempts_complete)
        print("  scored_coverage   : agent=%.2f  baseline=%.2f（有效成绩覆盖比例）"
              % (coverage["agent"], coverage["baseline"]))
        print("  comparable        : %s" % comparable)
        if incomparable:
            for r in incomparable:
                print("    不可比较原因: %s" % r)
            print("  ★ 尝试齐全但不可比较时，不得用本结果比较模型或版本。")

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
            json.dumps(dict(summary=summary, ledger=ledger,
                            attempts_complete=attempts_complete,
                            scored_coverage=coverage,
                            comparable=comparable,
                            incomparable_reasons=incomparable),
                       indent=2, ensure_ascii=False), encoding="utf-8")
        (args.out / "by_task.json").write_text(
            json.dumps(by_task, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print("说明：空答案按官方口径是 L0（judge.py 写明「空解属于 L0」），留在分母里。")
        print("      环境失败按官方口径单列排除。")
        print("      【更正一处此前的表述】：一道题全为环境失败，并不会让整个题集成绩变成 0；")
        print("      只有【所有题都未计分】时，官方汇总才返回 0 作为兜底。")
        print("      关键是把「无有效成绩」标出来，而不是把兜底的 0 当成真实得分。")
        print("      这是子集评测，不是完整 1560 次协议。")
        # 退出码策略（供自动消费者识别三种状态）：
        #   0 = 尝试齐全 且 可比较
        #   2 = 尝试不齐全
        #   3 = 尝试齐全但不可比较（例如有模式全为环境失败）
        # 此前只有 0/2，于是"80 格全环境失败"会得到 0，被自动消费者当成可用实验。
        return exit_code_for(state)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
