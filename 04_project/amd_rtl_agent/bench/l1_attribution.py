#!/usr/bin/env python3
"""对 38 道 L1 做根因归因：用「首次失配时刻」等信号判断根因是否聚成类别。

评审意见
--------
我曾写"40 个不同错误，静态手段无从下手"。评审指出：**输出信号名与错配比例分散，
不能证明根因没有共性**——它们仍可能集中在位宽/符号/优先级/复位/时序偏移等类别上。

本脚本用可机械提取的信号做归因，而不是靠肉眼看信号名：
  - 首次失配时刻 first_t，以及它与测试台时长的关系
  - 失配比例 ratio = mismatches / samples
  - 失配是否集中在单个输出（逐信号 Hint 只有一条）

分类假设（写死，先于观察）：
  first_t 极小（<= 2 个时钟周期量级）  -> 复位/初值/基础行为错
  first_t 早但对后续有大量失配      -> 基础逻辑错
  first_t 晚且失配比例小            -> 边界/时序偏移（差一拍之类）
  first_t 晚但失配比例大            -> 时序语义整体错
"""
import json
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict

SRC = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   "/workspace/team/runs/fpga_owner/l1_forensics_20261003/l1_forensics.json")
FIRST_RE = re.compile(r"Output '([^']+)' has (\d+) mismatches\. First mismatch occurred at time (\d+)")
TOTAL_RE = re.compile(r"Total mismatched samples is (\d+) out of (\d+) samples")


def parse(rows):
    out = []
    for r in rows:
        firsts = []
        for h in r.get("hints", []):
            m = FIRST_RE.search(h)
            if m:
                firsts.append((m.group(1), int(m.group(2)), int(m.group(3))))
        if not firsts:
            continue
        # 取最早失配的那个信号
        sig, mism, t = min(firsts, key=lambda x: x[2])
        out.append(dict(task=r["task"], signal=sig, signal_mismatches=mism,
                        first_t=t, n_signals_named=len(firsts),
                        mismatches=r.get("mismatches"), samples=r.get("samples"),
                        ratio=(r["mismatches"] / r["samples"]) if r.get("samples") else None,
                        shape=r.get("shape")))
    return out


def classify(r):
    t, ratio = r["first_t"], r["ratio"] or 0
    if t <= 5:
        return "复位/初值或基础行为错" if ratio >= 0.5 else "复位/初值（局部）"
    if t <= 30:
        return "早期基础逻辑错" if ratio >= 0.3 else "早期局部错"
    if ratio >= 0.3:
        return "时序语义整体错"
    return "边界/时序偏移（晚期局部）"


def main():
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    data = parse(rows)
    print("可归因题目: %d / %d" % (len(data), len(rows)))
    print()

    print("=== 首次失配时刻分布 ===")
    ts = sorted(r["first_t"] for r in data)
    print("  min=%d  p25=%d  中位=%d  p75=%d  max=%d" % (
        ts[0], ts[len(ts) // 4], statistics.median(ts), ts[3 * len(ts) // 4], ts[-1]))
    buckets = Counter()
    for t in ts:
        buckets["<=5" if t <= 5 else "6-15" if t <= 15 else "16-30" if t <= 30
                else "31-60" if t <= 60 else ">60"] += 1
    for k in ("<=5", "6-15", "16-30", "31-60", ">60"):
        if buckets[k]:
            print("  %-6s %2d 题" % (k, buckets[k]))

    print()
    print("=== 失配比例分布 ===")
    rs = sorted(r["ratio"] for r in data if r["ratio"] is not None)
    print("  min=%.3f  中位=%.3f  max=%.3f" % (rs[0], statistics.median(rs), rs[-1]))
    rb = Counter()
    for x in rs:
        rb["<=0.05" if x <= 0.05 else "0.05-0.3" if x <= 0.3 else "0.3-0.7" if x <= 0.7 else ">0.7"] += 1
    for k in ("<=0.05", "0.05-0.3", "0.3-0.7", ">0.7"):
        if rb[k]:
            print("  %-9s %2d 题" % (k, rb[k]))

    print()
    print("=== 归因分类（规则先于观察写定）===")
    cats = Counter()
    groups = defaultdict(list)
    for r in data:
        c = classify(r)
        r["category"] = c
        cats[c] += 1
        groups[c].append(r)
    for k, v in cats.most_common():
        print("  %-26s %2d 题 (%.0f%%)" % (k, v, 100.0 * v / len(data)))

    print()
    print("=== 逐题 ===")
    for r in sorted(data, key=lambda x: x["first_t"]):
        print("  %-32s 首失配 t=%-4d 比例=%.3f  %s"
              % (r["task"], r["first_t"], r["ratio"] or 0, r["category"]))

    print()
    print("=== 判读 ===")
    early = sum(v for k, v in cats.items() if k.startswith("复位") or k.startswith("早期"))
    late = sum(v for k, v in cats.items() if k.startswith("边界") or k.startswith("时序"))
    print("  早期类（复位/初值/基础逻辑）: %d 题" % early)
    print("  晚期类（时序语义/边界偏移）  : %d 题" % late)
    print()
    print("  - 若两类都占相当比例，说明根因【确实聚成类别】，此前的'无从下手'站不住")
    print("  - 早期类可用'复位/初值检查'类静态手段覆盖；晚期类需要时序语义检查")
    print("  - 这只是第一步归因，用于决定是否值得继续；不等于已有可用的检查实现")

    out = SRC.parent / "l1_attribution.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print("  明细已写出:", out)


if __name__ == "__main__":
    raise SystemExit(main())
