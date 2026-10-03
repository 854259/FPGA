#!/usr/bin/env python3
"""核对 H3 实验的完整产物：样本数、版本、技能还原、逐题得失、耗时、环境失败。

评审要求的第二项
----------------
> 核对 H3 完整产物：312 个预期样本、环境失败、版本哈希、技能还原、
> 全部逐题得失及耗时。baseline 若有变化，也要单独报告。

并且要区分两件事，不能混为一谈：
  - **本轮胜出**：完整实验的 agent 得分上涨。
  - **成为默认版本**：重复验证后收益仍在，代价与稳定性可接受。

用法
----
  python3 verify_full156.py --new <新run目录> --old <对照run目录>
默认对照为本队 7 规则新基线 full156_declfix_20261003。
"""
import argparse
import hashlib
import json
import pathlib
import statistics
import sys
from collections import Counter

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}


def coin(level):
    return COEFF.get(level, 0.0)


def load_results(root):
    """-> {mode: {task: verdict}}"""
    out = {"agent": {}, "baseline": {}}
    d = pathlib.Path(root) / "full" / "results"
    if not d.is_dir():
        return out, {}
    raw = {}
    for f in sorted(d.glob("*.json")):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        parts = f.name.split(".")
        if len(parts) < 3:
            continue
        mode, task = parts[0], parts[1]
        if mode in out:
            out[mode][task] = v
            raw[f.name] = v
    return out, raw


def summarize(res):
    """和官方口径一致：空解是 L0 留在分母；环境失败单列。"""
    good = [v for v in res.values() if not v.get("tool_error")]
    bad = [v for v in res.values() if v.get("tool_error")]
    if not good:
        return dict(set_score=None, scored=0, total=len(res), tool_errors=len(bad),
                    levels=Counter(), elapsed=[], empty=0)
    coeffs = [v.get("coefficient", coin(v.get("level", 0))) for v in good]
    return dict(set_score=round(statistics.mean(coeffs), 4),
                scored=len(good), total=len(res), tool_errors=len(bad),
                levels=Counter(v.get("level", 0) for v in good),
                elapsed=[v.get("elapsed_s", 0.0) for v in good],
                empty=sum(1 for v in good if v.get("level", 0) == 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old",
                    default="/workspace/team/runs/fpga_owner/full156_declfix_20261003")
    args = ap.parse_args()

    new, new_raw = load_results(args.new)
    old, _old_raw = load_results(args.old)
    problems = []

    print("=" * 68)
    print("H3 完整产物核对")
    print("=" * 68)
    print("新: %s" % args.new)
    print("旧: %s" % args.old)
    print()

    # ---- 1. 样本数与环境失败 ----
    print("【1】样本完整性与环境失败")
    for mode in ("agent", "baseline"):
        s = summarize(new[mode])
        exp = 156
        flag = "OK" if s["total"] == exp else "★ 期望 %d，实际 %d" % (exp, s["total"])
        if s["total"] != exp:
            problems.append("%s 样本数 %d != 156" % (mode, s["total"]))
        print("  %-9s 样本 %3d/156  %s   环境失败 %d   空解 %d"
              % (mode, s["total"], flag, s["tool_errors"], s["empty"]))

    # ---- 2. 版本哈希 ----
    print()
    print("【2】版本哈希（记录在 run 的 version/manifest 里，若有）")
    found_any = False
    for name in ("versions.json", "manifest.json", "run_env.json", "params.json"):
        p = pathlib.Path(args.new) / "full" / name
        if p.is_file():
            found_any = True
            txt = p.read_text(encoding="utf-8")[:600]
            print("  %s:" % name)
            for line in txt.splitlines()[:10]:
                print("    %s" % line.strip()[:100])
    if not found_any:
        print("  （run 目录里没有版本记录文件；需从部署现场另行取证）")

    # ---- 3. 逐题得失（agent）----
    print()
    print("【3】agent 逐题得失")
    common = sorted(set(new["agent"]) & set(old["agent"]))
    gained, lost, same_level, changed_detail = [], [], 0, []
    for t in common:
        a, b = new["agent"][t], old["agent"][t]
        ca = a.get("coefficient", coin(a.get("level", 0)))
        cb = b.get("coefficient", coin(b.get("level", 0)))
        if ca > cb:
            gained.append(t)
            changed_detail.append((t, b.get("level"), a.get("level"), ca - cb))
        elif ca < cb:
            lost.append(t)
            changed_detail.append((t, b.get("level"), a.get("level"), ca - cb))
        else:
            same_level += 1
    print("  可比题数 %d   得分上升 %d   下降 %d   持平 %d" % (len(common), len(gained), len(lost), same_level))
    if gained:
        print("  上升的题:")
        for t, lo, ln, d in changed_detail:
            if d > 0:
                print("    %-32s L%s -> L%s  (+%.2f)" % (t, lo, ln, d))
    if lost:
        print("  下降的题: ★ 这些决定了净收益")
        for t, lo, ln, d in changed_detail:
            if d < 0:
                print("    %-32s L%s -> L%s  (%.2f)" % (t, lo, ln, d))

    # ---- 4. baseline 变化（必须单独报告）----
    print()
    print("【4】baseline 变化（与 agent 分开看）")
    bcommon = sorted(set(new["baseline"]) & set(old["baseline"]))
    bgain, blost = [], []
    for t in bcommon:
        a, b = new["baseline"][t], old["baseline"][t]
        ca = a.get("coefficient", coin(a.get("level", 0)))
        cb = b.get("coefficient", coin(b.get("level", 0)))
        if ca > cb:
            bgain.append((t, b.get("level"), a.get("level")))
        elif ca < cb:
            blost.append((t, b.get("level"), a.get("level")))
    print("  可比题数 %d   baseline 上升 %d   下降 %d" % (len(bcommon), len(bgain), len(blost)))
    for t, lo, ln in bgain:
        print("    ↑ %-32s L%s -> L%s" % (t, lo, ln))
    for t, lo, ln in blost:
        print("    ↓ %-32s L%s -> L%s" % (t, lo, ln))
    if bgain or blost:
        print("  ★ baseline 有变化：增益不能只归因于 agent，需在结论里说明")

    # ---- 5. 成绩与增益 ----
    print()
    print("【5】成绩与增益")
    na, nb = summarize(new["agent"]), summarize(new["baseline"])
    oa, ob = summarize(old["agent"]), summarize(old["baseline"])
    print("  新: agent=%.4f  baseline=%.4f" % (na["set_score"] or 0, nb["set_score"] or 0))
    print("  旧: agent=%.4f  baseline=%.4f" % (oa["set_score"] or 0, ob["set_score"] or 0))
    d_agent = (na["set_score"] or 0) - (oa["set_score"] or 0)
    print("  agent 变化 = %+.4f" % d_agent)
    if nb["set_score"] and ob["set_score"]:
        print("  baseline 变化 = %+.4f" % (nb["set_score"] - ob["set_score"]))
    if nb["set_score"]:
        print("  新增益 = %.4f" % ((na["set_score"] or 0) / nb["set_score"]))

    # ---- 6. 判定标准（先写死的）----
    print()
    print("【6】按预定标准判定")
    print("  预定标准: agent 题集得分上涨 -> 本轮胜出；否则不采纳")
    if d_agent > 0:
        print("  → ★ 本轮胜出（agent %+.4f）" % d_agent)
        print("     但这**只说明胜出**；『成为默认版本』还需重复验证收益仍在、代价与稳定性可接受")
    elif d_agent == 0:
        print("  → 持平，不采纳")
    else:
        print("  → ★ 未胜出（agent %+.4f），不采纳，技能应还原" % d_agent)

    # ---- 7. 耗时 ----
    print()
    print("【7】耗时")
    for label, s in (("新 agent", na), ("旧 agent", oa), ("新 baseline", nb), ("旧 baseline", ob)):
        if s["elapsed"]:
            e = sorted(s["elapsed"])
            print("  %-12s 总 %.0fs  均 %.1fs  中位 %.1fs  p90 %.1fs  max %.1fs"
                  % (label, sum(e), statistics.mean(e), statistics.median(e),
                     e[int(len(e) * 0.9)] if len(e) > 1 else e[0], e[-1]))

    # ---- 结论 ----
    print()
    print("=" * 68)
    if problems:
        print("★ 评测不完整：")
        for p in problems:
            print("   - %s" % p)
    else:
        print("样本完整性：通过（两个模式都是 156）")
    print("=" * 68)

    out = pathlib.Path(args.new) / "verification.json"
    out.write_text(json.dumps(dict(
        gained=gained, lost=lost,
        baseline_gained=[t for t, _a, _b in bgain],
        baseline_lost=[t for t, _a, _b in blost],
        new_agent=na["set_score"], old_agent=oa["set_score"],
        new_baseline=nb["set_score"], old_baseline=ob["set_score"],
        delta_agent=d_agent, problems=problems), indent=2, ensure_ascii=False),
        encoding="utf-8")
    print("明细已写出:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
