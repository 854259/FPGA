#!/usr/bin/env python3
"""实测两轮同配置运行的逐题差异 —— 噪声底。

为什么需要这个
--------------
队友指出过一个正确的批评：不能用 VerilogEval 两轮的 5/156 翻转，去推断
RTLLM 44 题的方差或「1.25σ、在噪声内」这类断言。噪声底必须在**该题集、
该配置**上实测。

当两轮运行的代码、模型、技能、参数完全相同时（哈希可核），逐题差异就是
纯运行波动，不需要任何统计假设。本脚本就做这件事。

用法
----
    compare_repeatability.py <runA_results_dir> <runB_results_dir> [--json out.json]

两个目录都含 agent.<task>.s0.json / baseline.<task>.s0.json
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys


def load(results_dir: pathlib.Path):
    """-> {(mode, task): (level, coefficient)}"""
    out = {}
    for p in sorted(results_dir.glob("*.json")):
        name = p.stem                      # e.g. agent.Prob001_zero.s0
        parts = name.split(".")
        if len(parts) < 3:
            continue
        mode, task = parts[0], ".".join(parts[1:-1])
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            continue
        level = d.get("level")
        coeff = d.get("coefficient")
        if level is None:
            continue
        out[(mode, task)] = (level, coeff)
    return out


def summarise(a, b, label):
    common = sorted(set(a) & set(b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    flips = []
    for k in common:
        if a[k][0] != b[k][0]:
            flips.append((k, a[k][0], b[k][0]))
    n = len(common)
    rate = (len(flips) / n) if n else 0.0
    print("=== %s ===" % label)
    print("  共同题数      : %d" % n)
    if only_a:
        print("  仅 A 有       : %s" % ", ".join(t for _, t in only_a[:8]))
    if only_b:
        print("  仅 B 有       : %s" % ", ".join(t for _, t in only_b[:8]))
    print("  级别翻转      : %d / %d = %.1f%%" % (len(flips), n, 100 * rate))
    sa = sum(a[k][1] for k in common if a[k][1] is not None)
    sb = sum(b[k][1] for k in common if b[k][1] is not None)
    print("  系数合计      : A=%.2f  B=%.2f  差 %+.2f  (占 %d 题 => 题集得分差 %+.4f)"
          % (sa, sb, sb - sa, n, (sb - sa) / n if n else 0))
    if flips:
        up = sum(1 for _, x, y in flips if y > x)
        down = sum(1 for _, x, y in flips if y < x)
        print("  方向          : 上升 %d / 下降 %d" % (up, down))
        print("  翻转明细:")
        for (m, t), x, y in sorted(flips):
            print("    %-8s %-30s L%d -> L%d" % (m, t, x, y))
    print()
    return dict(common=n, flips=len(flips), flip_rate=rate,
                score_a=sa / n if n else 0, score_b=sb / n if n else 0,
                flips_detail=[dict(mode=m, task=t, a=x, b=y) for (m, t), x, y in sorted(flips)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_a", type=pathlib.Path)
    ap.add_argument("run_b", type=pathlib.Path)
    ap.add_argument("--json", type=pathlib.Path, default=None)
    args = ap.parse_args()

    a = load(args.run_a)
    b = load(args.run_b)
    if not a or not b:
        print("读不到结果：A=%d 条 B=%d 条" % (len(a), len(b)), file=sys.stderr)
        return 1

    print("A =", args.run_a)
    print("B =", args.run_b)
    print()
    result = {}
    for mode in ("agent", "baseline"):
        ra = {k: v for k, v in a.items() if k[0] == mode}
        rb = {k: v for k, v in b.items() if k[0] == mode}
        result[mode] = summarise(ra, rb, "%s 重复性" % mode)

    both_a = {k: v for k, v in a.items()}
    both_b = {k: v for k, v in b.items()}
    result["all"] = summarise(both_a, both_b, "agent+baseline 合计")

    print("=== 判读 ===")
    print("  两轮代码/模型/技能/参数已核实相同，因此以上翻转率就是【本套题集在本配置下的实测噪声底】。")
    print("  baseline 也翻转，说明这不是 agent 侧引入的；baseline 不读技能，本应逐题不变。")
    print("  后续任何单题级别的改善/退化，若落在该翻转率量级内，不作为结论。")

    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("\n已写出:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
