#!/usr/bin/env python3
"""判定链静默降级审计（离线，只读留存产物）。

背景（历史触发源未被直接见证）
------------------------
`Prob005_notgate` 的相同候选在旧轮 L3、新轮 L2，随后 14 次复判均 L3。
独立干预能复现：综合中断且无 synth.json 时，官方链可能返回 L2 而不标
tool_error。时间线与宽泛 pkill 脚本是强线索，但原始底层日志已丢失，
不能据此确定历史样本究竟被谁中断。此工具只标出待检查样本。

更糟的是我们自己的适配层加重了它：
  * 固定版 `judge.py` 调用 `veval-judge` 时带 `--quiet`，`judge.py::_dump()`
    因此把空字符串写成 `judge_logs/<task>.judge.log`——日志恒为 0 字节；
  * `judge.py` 的工作目录在未设 `SELFTEST_KEEP_WORK=1` 时被 `_cleanup()` 删除，
    `synth/synth.log`（唯一能区分"被杀"与"真失败"的原始证据）随之消失。
两轮 312 样本的 judge log **全部为 0 字节**，所以事后无法从日志本身判断当时
到底发生了什么。

本工具做什么
------------
只看留存的 verdict 与文件系统事实，找出**可疑样本**，不修改任何东西：

  1. `tool_error` 为空，但阶段组合与已知的合法组合不符；
  2. 判为 L2/L1（`simulate=True`）却 `synth=False`，即"综合阶段没通过"——
     这正是静默降级落地的位置；
  3. `judge_logs/<task>.judge.log` 为 0 字节（我们的适配层缺陷，使所有样本都命中）；
  4. `elapsed_s` 明显短于同 run 内通过综合的样本（被杀会变短）。

输出：可疑样本清单 + 每类的计数 + 一份可复判清单，供
`rejudge_suspects.py` 用固定条件独立复判。**审计不重跑推理，也不改 verdict。**

用法：
    python3 audit_judge_chain.py --run <run_dir> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}
# 已知合法的阶段组合（严格递进）。任何其它组合都值得看一眼。
LEGAL_STAGES = {
    (True, True, True),     # L3
    (True, True, False),    # L2
    (True, False, False),   # L1
    (False, False, False),  # L0
}


def load_results(run: pathlib.Path) -> dict:
    out = {}
    rdir = run / "full" / "results"
    if not rdir.is_dir():
        rdir = run / "results"
    for f in sorted(rdir.glob("*.json")):
        parts = f.name.split(".")
        if len(parts) < 4:
            continue
        mode, task, sk = parts[0], '.'.join(parts[1:-2]), parts[-2]
        if mode not in ('agent', 'baseline') or not re.fullmatch(r's\d+', sk):
            continue
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError('Cannot read result %s: %s' % (f, exc)) from exc
        if not isinstance(v, dict) or v.get('task_id', task) != task:
            raise ValueError('Result task identity mismatch: %s' % f)
        out[(mode, task, sk)] = dict(v, _file=str(f), _sample=sk)
    return out


def judge_log_path(run: pathlib.Path, mode: str, task: str, sample: str) -> pathlib.Path:
    layout = run / 'full' if (run / 'full' / 'results').is_dir() else run
    return layout / mode / task / sample / "judge_logs" / ("%s.judge.log" % task)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="要审计的 run 目录")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    run = pathlib.Path(args.run)
    res = load_results(run)
    if not res:
        print("找不到判定结果:", run)
        return 2

    print("=" * 96)
    print("判定链静默降级审计  %s" % run)
    print("=" * 96)
    print("样本数 %d" % len(res))

    # ---- 每种模式的耗时基线（用于"明显偏短"判据）----
    synth_ok = {}
    for (mode, _t, _s), v in res.items():
        if v.get("stages", {}).get("synth") and isinstance(v.get("elapsed_s"), (int, float)):
            synth_ok.setdefault(mode, []).append(v["elapsed_s"])
    med = {m: statistics.median(x) for m, x in synth_ok.items() if x}
    print("通过综合样本的判定耗时中位数: %s" % {m: round(s, 1) for m, s in med.items()})

    suspects = {"no_synth_but_sim_pass": [], "illegal_stages": [], "empty_log": [],
                "short_elapsed": [], "tool_error": []}
    empty_log_n = 0
    for (mode, task, sample), v in sorted(res.items()):
        st = v.get("stages", {})
        key = (bool(st.get("compile")), bool(st.get("simulate")), bool(st.get("synth")))
        if v.get("tool_error"):
            suspects["tool_error"].append((mode, task, sample, str(v["tool_error"])[:60]))
        if key not in LEGAL_STAGES:
            suspects["illegal_stages"].append((mode, task, sample, key))
        # 核心判据：仿真过了、综合没过 ⇒ 这正是静默降级落地处
        if key == (True, True, False) and not v.get("tool_error"):
            suspects["no_synth_but_sim_pass"].append(
                (mode, task, sample, v.get("elapsed_s"), v.get("mismatches"), v.get("samples")))
        # 日志为空（我们的适配层缺陷，预期全部命中）
        lp = judge_log_path(run, mode, task, sample)
        if lp.is_file():
            if lp.stat().st_size == 0:
                empty_log_n += 1
                suspects["empty_log"].append((mode, task, sample))
        # 明显偏短的 L2（被杀会缩短墙钟）
        if key == (True, True, False) and mode in med and isinstance(v.get("elapsed_s"), (int, float)):
            if v["elapsed_s"] < med[mode] - 4.0:
                suspects["short_elapsed"].append((mode, task, sample, v["elapsed_s"], round(med[mode], 1)))

    print()
    print("【1】仿真通过但综合未通过（静默降级可能落点）: %d 个"
          % len(suspects["no_synth_but_sim_pass"]))
    for mode, task, sample, el, mm, ss in suspects["no_synth_but_sim_pass"]:
        print("    %-6s %-32s %s elapsed=%-6s mismatches=%s samples=%s" % (mode, task, sample, el, mm, ss))
    print()
    print("【2】judge_logs 为 0 字节: %d 个（适配层传 --quiet 所致，全 run 性缺陷）" % empty_log_n)
    print("【3】阶段组合不合法: %d 个" % len(suspects["illegal_stages"]))
    for mode, task, sample, key in suspects["illegal_stages"]:
        print("    %-6s %-32s %s %s" % (mode, task, sample, key))
    print("【4】L2 且耗时显著短于通过综合的中位数（可能是被杀）: %d 个"
          % len(suspects["short_elapsed"]))
    for mode, task, sample, el, m in suspects["short_elapsed"]:
        print("    %-6s %-32s %s elapsed=%s  中位=%s" % (mode, task, sample, el, m))
    print("【5】已标 tool_error: %d 个" % len(suspects["tool_error"]))

    verdict = ("本 run 有 %d 个空的外层 judge log；应结合 judge_work_logs 原始证据检查，"
               "空日志本身不能证明综合失败原因。" % empty_log_n
               if empty_log_n else "本 run 未发现空日志症状。")
    print()
    print("结论: " + verdict)

    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(
            {"run": str(run), "samples": len(res),
             "median_elapsed_synth_ok": med,
             "suspects": {k: [list(x) for x in v] for k, v in suspects.items()},
             "empty_judge_logs": empty_log_n,
             "note": "审计只读；不重跑推理；不改 verdict"},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print("明细已写入", args.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
