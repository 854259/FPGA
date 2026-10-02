#!/usr/bin/env python3
"""把 38 道 L1（编译通过、仿真失败）的失败形态分类。

为什么做这个
------------
agent 的分级是 L3 111 / L1 38 / L0 7。L0 已经逐个诊断过，**38 道 L1 是最大的剩余池子**：
若能把其中三成转成 L3，按满分线 2.5 估算约值 +6 分。

但"仿真失败"只是一个计数（mismatches/samples），**不知道错在哪**。
本脚本用官方测试台跑一遍这些解答，抓逐信号 Hint，**看有没有可归纳的形态**——
若有，就可能写成一条技能规则（零工具成本）；若没有，则说明这是纯粹的模型能力问题，
任何静态手段都无从下手。**两种结论都有价值。**

注意
----
- 官方测试台**只用于本次离线分析**，不进入 agent、不进提交包（规则要求）
- 纯 EDA 负载，不调用模型，不占模型槽
- 等全量配对结束后再跑，避免 CPU 争用影响它的墙钟测量
"""
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

KIT = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
TASKS = KIT / "bench" / "tasks_veval"
BASE = pathlib.Path("/workspace/team/runs/fpga_owner/"
                    "skillfix_full156_20261001T235258Z/full156")
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/l1_forensics_20261003")


def env():
    e = os.environ.copy()
    e.update(
        PATH="/workspace/AMD/2026.1/Vivado/bin:" + e["PATH"],
        LD_LIBRARY_PATH="/workspace/team/udev-stub",
        XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic",
        XILINX_VIVADO="/workspace/AMD/2026.1/Vivado",
        EDA_TMP=str(OUT / "scratch"), SELFTEST_TMP=str(OUT / "scratch"),
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
    )
    return e


def run_tb(task_dir, solution, workdir):
    spec = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    top = spec.get("tb_top", "tb")
    os.makedirs(workdir, exist_ok=True)
    for src, dst in ((solution, "dut.sv"),
                     (task_dir / spec["reference_module"], "ref.sv"),
                     (task_dir / spec["testbench"], "tb.sv")):
        shutil.copyfile(src, os.path.join(workdir, dst))
    text = []
    for cmd in (["xvlog", "-sv", "--nolog", "dut.sv", "ref.sv", "tb.sv"],
                ["xelab", top, "-s", "snap", "--nolog"],
                ["xsim", "snap", "-R"]):
        try:
            p = subprocess.run(cmd, cwd=workdir, env=env(), capture_output=True,
                               text=True, errors="replace", timeout=600)
        except subprocess.TimeoutExpired:
            text.append("TIMEOUT " + cmd[0])
            break
        text.append(p.stdout + p.stderr)
        if p.returncode != 0 and cmd[0] != "xsim":
            break
    return "\n".join(text)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)

    l1 = []
    for p in sorted(glob.glob(str(BASE / "results" / "agent.*.json"))):
        d = json.loads(pathlib.Path(p).read_text())
        if d.get("level") == 1:
            l1.append(d["task_id"])
    print("L1 题数: %d" % len(l1), flush=True)

    rows = []
    for i, task in enumerate(l1, 1):
        task_dir = TASKS / task
        src = BASE / "agent" / task / "s0" / "solution.v"
        if not (task_dir.is_dir() and src.is_file()):
            continue
        text = run_tb(task_dir, src, str(OUT / task))

        m = re.search(r"Mismatches:\s+(\d+)\s+in\s+(\d+)\s+samples", text)
        mism = int(m.group(1)) if m else None
        samp = int(m.group(2)) if m else None
        hints = [s.strip() for s in text.splitlines() if "Hint:" in s]
        seen, uniq = set(), []
        for h in hints:
            if h not in seen:
                seen.add(h)
                uniq.append(h)

        # 形态归类
        if mism is None:
            shape = "无判定行"
        elif samp and mism >= samp:
            shape = "全错(每个样本都不匹配)"
        elif samp and mism >= samp * 0.5:
            shape = "多数错(>=50%)"
        elif mism <= 3:
            shape = "接近正确(<=3 处)"
        else:
            shape = "部分错"

        rows.append(dict(task=task, mismatches=mism, samples=samp, shape=shape,
                         hints=uniq[:4]))
        print("  [%2d/%d] %-30s %-22s %s/%s"
              % (i, len(l1), task, shape, mism, samp), flush=True)
        (OUT / "l1_forensics.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=== 形态分布 ===")
    from collections import Counter
    c = Counter(r["shape"] for r in rows)
    for k, v in c.most_common():
        print("  %-24s %d 题 (%.0f%%)" % (k, v, 100.0 * v / max(len(rows), 1)))
    print()
    print("=== 逐信号 Hint 汇总（最常见的）===")
    hc = Counter()
    for r in rows:
        for h in r["hints"]:
            hc[re.sub(r"\d+", "N", h)] += 1
    for k, v in hc.most_common(12):
        print("  %3d 次  %s" % (v, k[:100]))
    print()
    print("判读：若形态高度集中（例如多为『接近正确』），说明差一点点，可能有针对性手段；")
    print("      若分散且多为『全错』，说明是模型能力问题，静态手段无从下手。")


if __name__ == "__main__":
    raise SystemExit(main())
