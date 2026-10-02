#!/usr/bin/env python3
"""Offline retrospective for a pinned-official-evaluator run (L0-L3).

Reads a pulled run directory produced by run_amd_evaluation.py / official_eval.py:

    <run>/<stage>/experiment.json
    <run>/<stage>/graded_summary.json
    <run>/<stage>/results/<mode>.<task>.s<k>.json
    <run>/<stage>/<mode>/<task>/s<k>/trace.jsonl

and writes a Markdown retrospective. Stdlib only; never calls a model or a tool.

Design notes
------------
* Scores come from the official graded_summary.json verbatim. This script does not
  re-derive set_score, because re-deriving it would silently diverge from the
  pinned official scorer. It only cross-checks the per-sample records against it.
* "improved"/"regressed" are coefficient deltas per task, paired within the same run.
  An earlier historical run is never used as the baseline for those counts.
* Truncation is reported from trace.jsonl finish_reason, because a length-limited
  call is the dominant known failure mode and it does not show up in the level alone.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}
LEVEL_NAME = {0: "L0 未通过", 1: "L1 可编译", 2: "L2 仿真通过", 3: "L3 可综合"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_modes(obj: dict) -> dict[str, dict]:
    """Accept either the official graded_summary shape or the older bench-report shape.

    official_eval.py writes {"modes": {mode: {set_score, level_counts, ...}}}.
    The 2026-09-27 AutoDL report instead uses {"summaries": {...}, "graded_scores": {...}}.
    Normalising here keeps the comparison honest: scores are read, never recomputed.
    """
    if "modes" in obj:
        return obj["modes"]
    scores = obj.get("graded_scores") or {}
    summaries = obj.get("summaries") or {}
    out: dict[str, dict] = {}
    for mode, s in summaries.items():
        levels = s.get("levels") or {}
        out[mode] = {
            "set_score": scores.get(mode),
            "level_counts": {f"L{k}": v for k, v in levels.items()},
        }
    return out


def read_results(stage: Path) -> dict[str, dict[str, dict]]:
    """mode -> task_id -> per-sample record (first sample wins if duplicated)."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in sorted((stage / "results").glob("*.json")):
        rec = load_json(p)
        mode = p.name.split(".", 1)[0]
        tid = rec.get("task_id") or p.name.split(".")[1]
        out[mode][tid] = rec
    return out


def read_traces(stage: Path) -> dict[str, list[dict]]:
    """mode -> list of llm call events across all tasks/samples.

    trace.jsonl is written by submission/agent/runtime.py; the discriminator
    field is `tool` (not `event`). The official baseline additionally records
    `empty_content` and `sec`, which the agent path does not.
    Each event: {task, round, finish, tokens_in, tokens_out, error, empty, sec}
    """
    events: dict[str, list[dict]] = defaultdict(list)
    for mode_dir in sorted(p for p in stage.iterdir() if p.is_dir() and p.name in ("agent", "baseline")):
        mode = mode_dir.name
        for tid_dir in sorted(p for p in mode_dir.iterdir() if p.is_dir()):
            for s_dir in sorted(p for p in tid_dir.iterdir() if p.is_dir()):
                tp = s_dir / "trace.jsonl"
                if not tp.is_file():
                    continue
                for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("tool") != "llm":
                        continue
                    events[mode].append({
                        "task": tid_dir.name,
                        "round": ev.get("round"),
                        "finish": ev.get("finish"),
                        "tokens_in": ev.get("tokens_in"),
                        "tokens_out": ev.get("tokens_out"),
                        "error": ev.get("error"),
                        "empty": ev.get("empty_content"),
                        "sec": ev.get("sec"),
                    })
    return events


def pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", type=Path, required=True, help="pulled run directory")
    ap.add_argument("--stage", default="full156", help="stage subdirectory (default full156)")
    ap.add_argument("--out", type=Path, required=True, help="markdown output path")
    ap.add_argument("--compare", type=Path, default=None,
                    help="optional earlier graded_summary.json for a method-compatible comparison")
    ap.add_argument("--compare-label", default="earlier run")
    args = ap.parse_args()

    stage = args.run / args.stage
    summary = load_json(stage / "graded_summary.json")
    experiment = load_json(stage / "experiment.json")
    results = read_results(stage)
    traces = read_traces(stage)

    modes = list(summary["modes"].keys())
    # A reference-only stage has no agent/baseline pair; still render it.
    modes = [m for m in modes if m != "reference"] or modes
    agent_mode = "agent" if "agent" in modes else (modes[0] if modes else None)
    base_mode = "baseline" if "baseline" in modes else None

    L: list[str] = []
    A = L.append

    A(f"# {args.stage} 官方 L0–L3 复盘（离线）")
    A("")
    A(f"- 运行目录：`{stage.as_posix()}`")
    A(f"- 上游官方提交：`{experiment.get('upstream_commit')}`")
    A(f"- 模型：`{experiment.get('model')}`")
    # vivado -version writes locale warnings before the banner; keep only the banner line.
    vv = str(experiment.get("vivado_version") or "").splitlines()
    vv = next((ln.strip() for ln in vv if ln.strip().lower().startswith("vivado v")), "unknown")
    A(f"- Vivado：`{vv}`")
    A(f"- 采样：{experiment.get('samples')} 次/题/模式；单题墙钟上限 {experiment.get('local_deadline_s')} 秒")
    A(f"- 完成标志：`complete={experiment.get('complete')}`")
    A("")

    # ---- headline -------------------------------------------------------
    A("## 1. 总览")
    A("")
    A("| 模式 | 题集得分 (pass@1) | pass@5 | L3 | L1 | L0 | 工具错误 | 判定耗时 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    store = {}
    for m in modes:
        s = summary["modes"][m]
        store[m] = s
        lc = s["level_counts"]
        A(f"| {m} | **{s['set_score']:.4f}** | {s['pass@5']:.4f} | "
          f"{lc.get('L3', 0)} | {lc.get('L1', 0)} | {lc.get('L0', 0)} | "
          f"{s['tool_errors']} | {s['judge_elapsed_s']:.0f}s |")
    A("")

    if agent_mode and base_mode:
        a, b = store[agent_mode], store[base_mode]
        cap = 30.0 * a["set_score"]
        A(f"- **能力分** = 30 × {a['set_score']:.4f} = **{cap:.2f} / 30**")
        if b["set_score"] > 0:
            gain = a["set_score"] / b["set_score"]
            A(f"- **增益** = {a['set_score']:.4f} / {b['set_score']:.4f} = **{gain:.3f}×**")
            A("  （增益得分需要赛前公告的满分线倍数，本地无法计算正式值）")
        A(f"- **诊断** pass@5 − pass@1 = {a['pass@5'] - a['pass@1']:.4f}")
        A("")

    # ---- pairing --------------------------------------------------------
    if agent_mode and base_mode and agent_mode in results and base_mode in results:
        A("## 2. 逐题配对（同一次运行内）")
        A("")
        ra, rb = results[agent_mode], results[base_mode]
        tasks = sorted(set(ra) & set(rb))
        improved, regressed, same = [], [], 0
        for t in tasks:
            ca = ra[t].get("coefficient", COEFF.get(ra[t].get("level"), 0.0))
            cb = rb[t].get("coefficient", COEFF.get(rb[t].get("level"), 0.0))
            if ca > cb:
                improved.append((t, cb, ca))
            elif ca < cb:
                regressed.append((t, cb, ca))
            else:
                same += 1
        A(f"- 配对题目：**{len(tasks)}**")
        A(f"- agent 更好：**{len(improved)}**｜持平：**{same}**｜agent 更差：**{len(regressed)}**")
        A(f"- 净增：**{len(improved) - len(regressed)}** 题")
        A("")
        if improved:
            A("### 2.1 agent 相对基线做好的题")
            A("")
            A("| 题目 | 基线 | agent |")
            A("|---|---:|---:|")
            for t, cb, ca in sorted(improved, key=lambda x: x[2] - x[1], reverse=True):
                A(f"| {t} | {cb:.2f} | {ca:.2f} |")
            A("")
        if regressed:
            A("### 2.2 agent 相对基线做差的题（回归）")
            A("")
            A("| 题目 | 基线 | agent |")
            A("|---|---:|---:|")
            for t, cb, ca in sorted(regressed, key=lambda x: x[2] - x[1]):
                A(f"| {t} | {cb:.2f} | {ca:.2f} |")
            A("")

    # ---- truncation / call stats ---------------------------------------
    A("## 3. 模型调用与截断（来自 trace.jsonl）")
    A("")
    if not traces:
        A("_未找到 trace.jsonl；无法分析调用与截断。_")
        A("")
    else:
        A("| 模式 | 调用数 | 因长度截断 | 截断占比 | 报错调用 | 平均输出 tokens | 最大输出 tokens |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for m in sorted(traces):
            evs = traces[m]
            total = len(evs)
            trunc = sum(1 for e in evs if e.get("finish") == "length")
            errs = sum(1 for e in evs if e.get("error"))
            toks = [e["tokens_out"] for e in evs if isinstance(e.get("tokens_out"), int)]
            avg = sum(toks) / len(toks) if toks else 0
            mx = max(toks) if toks else 0
            A(f"| {m} | {total} | {trunc} | {pct(trunc, total)} | {errs} | {avg:.0f} | {mx} |")
        A("")
        for m in sorted(traces):
            known = [e for e in traces[m] if e.get("empty") is not None]
            if known:
                empt = sum(1 for e in known if e["empty"])
                A(f"- **{m}** 记录了空响应标志：{empt}/{len(known)} 次调用内容为空")
        A("")

        # tasks whose every call was truncated
        A("### 3.1 全程被截断的题目")
        A("")
        for m in sorted(traces):
            per_task: dict[str, list[dict]] = defaultdict(list)
            for e in traces[m]:
                per_task[e["task"]].append(e)
            all_trunc = [t for t, es in sorted(per_task.items())
                         if es and all(e.get("finish") == "length" for e in es)]
            any_trunc = [t for t, es in sorted(per_task.items())
                         if any(e.get("finish") == "length" for e in es)]
            A(f"- **{m}**：任一调用截断 {len(any_trunc)} 题；全部调用截断 {len(all_trunc)} 题")
            if all_trunc:
                A(f"  - 全部截断：{', '.join(all_trunc)}")
        A("")

        A("### 3.2 调用报错的题目")
        A("")
        for m in sorted(traces):
            errs = [(e["task"], e["error"]) for e in traces[m] if e.get("error")]
            if errs:
                c = Counter(x[1] for x in errs)
                A(f"- **{m}**：{dict(c)}；题目：{', '.join(sorted({x[0] for x in errs}))[:400]}")
        A("")

    # ---- failure anatomy ------------------------------------------------
    A("## 4. 失败阶段与未达标题目")
    A("")
    A("阶段取自官方判定器的 `stages` 字段（compile / simulate / synth），每题取所达到的最高级别。")
    A("")
    A("| 模式 | L3 全通过 | 编译失败 | 仿真失败 | 综合失败 |")
    A("|---|---:|---:|---:|---:|")
    for m in modes:
        comp = sim = syn = full = 0
        for tid, r in sorted(results.get(m, {}).items()):
            st = r.get("stages") or {}
            if st.get("compile") and st.get("simulate") and st.get("synth"):
                full += 1
            elif not st.get("compile"):
                comp += 1
            elif not st.get("simulate"):
                sim += 1
            else:
                syn += 1
        A(f"| {m} | {full} | {comp} | {sim} | {syn} |")
    A("")

    for m in modes:
        s = summary["modes"][m]
        bad = [(t["task_id"], t["levels"]) for t in s["per_task"]
               if t.get("levels") and max(t["levels"]) < 3]
        A(f"### 未达 L3 的题目（{m}，{len(bad)} 题）")
        A("")
        if bad:
            A("| 题目 | 级别 |")
            A("|---|---|")
            for t, lv in bad:
                A(f"| {t} | {', '.join('L%d' % x for x in lv)} |")
        else:
            A("_无_")
        A("")

    # ---- optional cross-run comparison ---------------------------------
    A(f"## 5. 与{args.compare_label}对照（同口径：官方 L0–L3）")
    A("")
    if args.compare and args.compare.is_file():
        old = load_json(args.compare)
        old_modes = normalize_modes(old)
        A("| 模式 | 本次 set_score | 对照 set_score | 差值 | 本次 L3 | 对照 L3 | 对照 L0 |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for m in modes:
            if m in old_modes:
                new_s, old_s = store[m]["set_score"], old_modes[m].get("set_score")
                if old_s is None:
                    continue
                A(f"| {m} | {new_s:.4f} | {old_s:.4f} | {new_s - old_s:+.4f} | "
                  f"{store[m]['level_counts'].get('L3', 0)} | "
                  f"{old_modes[m]['level_counts'].get('L3', 0)} | "
                  f"{old_modes[m]['level_counts'].get('L0', 0)} |")
        A("")
        A(f"对照来源：`{args.compare.as_posix()}`")
        A("")
        A("> 注意：对照轮与本轮的**模型/推理配置可能不同**（例如思考开关、推理后端）。"
          "差值只描述结果，不构成因果。")
    else:
        A("_本次未提供对照文件（`--compare`），无法给出跨运行对比。_")
    A("")

    # ---- caveats --------------------------------------------------------
    A("## 6. 结论边界")
    A("")
    A(f"- 本次为 `{experiment.get('model')}` 在开发档（development profile）下的结果，"
      "**不是赛事方最终隔离镜像验收**。")
    A("- 单样本，pass@1 为计分口径；pass@5 仅为诊断。")
    A("- 增益得分需赛前公告的满分线倍数；代价分需赛前公告的基准时长——本地均无法给出正式值。")
    A("- 参考自检中非 L3 的题目属于上游数据集已知异常，保留原始分母，不做剔除。")
    A("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(L), encoding="utf-8")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
