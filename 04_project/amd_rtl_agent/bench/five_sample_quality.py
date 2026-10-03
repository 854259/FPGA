#!/usr/bin/env python3
"""5 样本质量评测：按赛事方的调用方式取 5 个样本，并用官方判定器逐个评分。

为什么重写
----------
第一版只是"同一请求打 5 次，看返回是否相同"。那不是 5 样本协议：
  - 五次相同不是成功标准。五次不同可以合法；五次相同也可能全错。
  - 只跑 agent，没有 baseline，无法算增益。
  - 没有判定，等级从哪来都不知道。
  - 空答案（契约允许的"做不出来返回空串"）会被当成"一致"。
  - development profile 与比赛配置不同。

本脚本按协议真正要测的东西来：
  对每题、每个模式（agent/baseline）、每个样本：
      发请求 -> 存 solution + trace -> 交给官方 judge 判 L0..L3
  然后算 pass@1（逐样本等级的均值）与 pass@5（5 次里有任意一次达 L3 的比例）

边界
----
- 这只是**子集**（默认 8 题 x 2 模式 x 5 = 80 次），不是完整 1560 次协议。
- 不改 agent、不改题集、不改判定器。
- profile 由 RTL_PROFILE 决定；比赛用 submission，本地开发常用 development——
  结果里会打印实际用的 profile，避免混淆。
"""
import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
import urllib.request

KIT = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
TASKS_DIR = KIT / "bench" / "tasks_veval"
JUDGE = KIT / "official_reference" / "selftest" / "judge.py"
COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}
TOKEN = "five-sample-quality-token"

DEFAULT_PICK = [
    "Prob001_zero", "Prob009_popcount3", "Prob050_kmap1", "Prob058_alwaysblock2",
    "Prob070_ece241_2013_q2", "Prob082_lfsr32", "Prob145_circuit8", "Prob147_circuit10",
]


def endpoint_url(port, path):
    return "http://127.0.0.1:%d%s" % (port, path)


def post_solve(port, task_id, prompt, mode, deadline):
    body = json.dumps({"task_id": task_id, "nonce": "%s-%d" % (task_id, time.time_ns()),
                       "mode": mode, "prompt": prompt, "interface": "",
                       "deadline_s": deadline}).encode()
    req = urllib.request.Request(endpoint_url(port, "/v1/solve"), data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + TOKEN})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=deadline + 60) as r:
            return r.status, json.loads(r.read().decode()), time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return None, {"error": type(exc).__name__}, time.time() - t0


def wait_ready(port, timeout=90):
    """只有真的 ready:true 才算就绪；只检查"有没有响应"会把 401/500 当成正常。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(endpoint_url(port, "/v1/health"),
                                         headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode())
            if r.status == 200 and d.get("ready") is True:
                return True, d
            last = d
        except Exception as exc:                        # noqa: BLE001
            last = {"error": type(exc).__name__}
        time.sleep(2)
    return False, locals().get("last", {})


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
    ap.add_argument("--port", type=int, default=7865)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/workspace/team/runs/fpga_owner/five_sample_quality_20261003"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scratch").mkdir(exist_ok=True)
    profile = os.environ.get("RTL_PROFILE", "(unset)")
    print("profile=%s  题数=%d  模式=agent+baseline  每模式 %d 样本  合计 %d 次"
          % (profile, len(args.tasks), args.samples,
             len(args.tasks) * 2 * args.samples), flush=True)

    env = os.environ.copy()
    env.update(FPGACHINA_TOKEN=TOKEN, PYTHONUTF8="1",
               EDA_TMP=str(args.out / "scratch"), SELFTEST_TMP=str(args.out / "scratch"))
    srv = subprocess.Popen(
        [sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
         "serve", "--port", str(args.port)],
        cwd=str(KIT), env=env, stdout=open(args.out / "server.log", "w"),
        stderr=subprocess.STDOUT, start_new_session=True)
    try:
        ok, detail = wait_ready(args.port)
        print("就绪:", ok, detail, flush=True)
        if not ok:
            print("服务未就绪，放弃（先查令牌与 ready 条件）", flush=True)
            return 1

        rows = []
        for task in args.tasks:
            task_dir = TASKS_DIR / task
            prompt_file = task_dir / "prompt.txt"
            if not prompt_file.is_file():
                print("  跳过（题不存在）:", task, flush=True)
                continue
            prompt = prompt_file.read_text(encoding="utf-8")
            for mode in ("agent", "baseline"):
                levels, elapsed, empties = [], [], 0
                for k in range(args.samples):
                    d = args.out / task / mode / ("s%d" % k)
                    d.mkdir(parents=True, exist_ok=True)
                    code, payload, el = post_solve(args.port, task, prompt, mode, args.deadline)
                    sol = payload.get("solution") or ""
                    (d / "solution.v").write_text(sol, encoding="utf-8")
                    (d / "trace.jsonl").write_text(payload.get("trace") or "", encoding="utf-8")
                    (d / "response.json").write_text(json.dumps(payload, ensure_ascii=False)[:20000],
                                                     encoding="utf-8")
                    if not sol.strip():
                        empties += 1
                        levels.append(None)       # 空答案不计等级，但如实记下来
                        elapsed.append(round(el, 1))
                        continue
                    v = run_judge(task_dir, d / "solution.v", str(d / "judge"))
                    levels.append(v.get("level"))
                    elapsed.append(round(el, 1))
                graded = [x for x in levels if x is not None]
                rows.append(dict(task=task, mode=mode, levels=levels,
                                 graded=graded, empties=empties,
                                 elapsed=elapsed,
                                 mean_level=round(statistics.mean(graded), 3) if graded else None,
                                 pass_at_1=round(statistics.mean(COEFF[x] for x in graded), 4) if graded else 0.0,
                                 pass_at_5=1.0 if any(x == 3 for x in graded) else 0.0))
                print("  %-32s %-8s 等级=%-22s 空答=%d 均值=%s pass@1=%.3f pass@5=%.0f 耗时=%s"
                      % (task, mode, levels, empties, rows[-1]["mean_level"],
                         rows[-1]["pass_at_1"], rows[-1]["pass_at_5"], elapsed), flush=True)
                (args.out / "quality.json").write_text(
                    json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

        print()
        print("=== 汇总（%d 题 x %d 样本）===" % (len(args.tasks), args.samples))
        for mode in ("agent", "baseline"):
            sel = [r for r in rows if r["mode"] == mode]
            if not sel:
                continue
            p1 = statistics.mean(r["pass_at_1"] for r in sel)
            p5 = statistics.mean(r["pass_at_5"] for r in sel)
            emp = sum(r["empties"] for r in sel)
            print("  %-9s 题集得分(pass@1)=%.4f  pass@5=%.4f  空答案 %d 次"
                  % (mode, p1, p5, emp))
        ag = [r for r in rows if r["mode"] == "agent"]
        bl = [r for r in rows if r["mode"] == "baseline"]
        if ag and bl:
            a = statistics.mean(r["pass_at_1"] for r in ag)
            b = statistics.mean(r["pass_at_1"] for r in bl)
            print("  增益 = %.4f" % (a / b if b else 0))
        print()
        print("说明：pass@1 取逐样本等级系数的均值；pass@5 取 5 次中有任意一次达 L3。")
        print("      空答案按契约是合法返回，不计等级，但在上面单独计数——")
        print("      五次都是空答案会表现为 pass@1=0，不会被误判成'一致=通过'。")
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
