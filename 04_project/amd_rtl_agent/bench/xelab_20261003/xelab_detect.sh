#!/bin/bash
# 先证明"能识别"：在稳定基线的全部 156 道提交代码上跑 xelab，测成本 / 检出 / 误报。
#
# 判据（评审要求"判断一个新方法要同时看四件事"）：
#   正确代码被误报多少 / 错误代码能检出多少 / 检出后实际修好多少 / 增加多少耗时
# 本实验只回答前两项与耗时——"修好多少"需要模型槽，另做。
#
# 为什么用 xelab 而不是 xvlog：多驱动（VRCL 10-3818/10-3823）是**静态描述**错误，
# xvlog 只做语法分析不报，只有 xelab 才暴露。这正是 agent 自检通过、
# 官方判定失败的那个缺口。
set -u
K=/workspace/team/tasks/autodl-rtl-kit/project
RUN=/workspace/team/runs/fpga_owner/full156_declfix_20261003/full
OUT=/workspace/team/xelab_detect_20261003
mkdir -p "$OUT"

export PATH="/workspace/AMD/2026.1/Vivado/bin:$PATH"
export LD_LIBRARY_PATH="/workspace/team/udev-stub${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic"
export XILINX_VIVADO="/workspace/AMD/2026.1/Vivado"
export PYTHONDONTWRITEBYTECODE=1

python3 - <<'PYEOF' > "$OUT/run.sh"
import json, pathlib
K = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
RUN = pathlib.Path("/workspace/team/runs/fpga_owner/full156_declfix_20261003/full")
OUT = pathlib.Path("/workspace/team/xelab_detect_20261003")
rows = []
for f in sorted((RUN / "results").glob("agent.*.s0.json")):
    task = f.name.split(".")[1]
    sol = RUN / "agent" / task / "s0" / "solution.v"
    tj = K / "bench" / "tasks_veval" / task / "task.json"
    if not sol.is_file() or not tj.is_file():
        continue
    d = json.loads(tj.read_text(encoding="utf-8"))
    rows.append({"task": task, "top": d.get("top", "TopModule"),
                 "sol": str(sol), "level": json.loads(f.read_text(encoding="utf-8")).get("level")})
print(json.dumps(rows))
PYEOF

echo "题目数: $(python3 -c "import json;print(len(json.load(open('$OUT/run.sh'))))")"

python3 - <<'PYEOF'
import json, pathlib, subprocess, time, shutil, os
rows = json.load(open("/workspace/team/xelab_detect_20261003/run.sh"))
OUT = pathlib.Path("/workspace/team/xelab_detect_20261003")
WD = OUT / "w"
results = []
for i, r in enumerate(rows, 1):
    d = WD / r["task"]
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(r["sol"], d / "dut.sv")
    t0 = time.time()
    xv = subprocess.run(["xvlog", "-sv", "--nolog", "dut.sv"], cwd=d,
                        capture_output=True, text=True, errors="replace")
    t_xvlog = time.time() - t0
    t_xelab = None
    xelab_rc = None
    multi = []
    if xv.returncode == 0:
        t0 = time.time()
        xl = subprocess.run(["xelab", r["top"], "-s", "snap", "--nolog", "-timescale", "1ps/1ps"],
                            cwd=d, capture_output=True, text=True, errors="replace")
        t_xelab = time.time() - t0
        xelab_rc = xl.returncode
        for line in (xl.stdout + xl.stderr).splitlines():
            if "multiple concurrent drivers" in line or "invalid combination of procedural drivers" in line:
                multi.append(line.strip()[:150])
    results.append(dict(task=r["task"], top=r["top"], level=r["level"],
                        xvlog_rc=xv.returncode, xelab_rc=xelab_rc,
                        t_xvlog=round(t_xvlog, 2),
                        t_xelab=round(t_xelab, 2) if t_xelab else None,
                        multi_driver=multi))
    if i % 20 == 0:
        print("  ... %d/%d" % (i, len(rows)), flush=True)

(OUT / "detect.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print("写出:", OUT / "detect.json")
PYEOF

echo
echo "=== 汇总 ==="
python3 - <<'PYEOF'
import json, statistics, collections
d = json.load(open("/workspace/team/xelab_detect_20261003/detect.json"))
n = len(d)
xv_fail = [r for r in d if r["xvlog_rc"] != 0]
xl_fail = [r for r in d if r["xvlog_rc"] == 0 and r["xelab_rc"] not in (0, None)]
multi = [r for r in d if r["multi_driver"]]

print("  题目数            : %d" % n)
print("  xvlog 失败        : %d  %s" % (len(xv_fail), [r["task"] for r in xv_fail][:8]))
print("  xvlog 通过但 xelab 失败: %d" % len(xl_fail))
print("  其中报多驱动      : %d  %s" % (len(multi), [r["task"] for r in multi]))
print()
tx = [r["t_xvlog"] for r in d]
tl = [r["t_xelab"] for r in d if r["t_xelab"] is not None]
print("  耗时: xvlog 均 %.2fs 合计 %.0fs" % (statistics.mean(tx), sum(tx)))
if tl:
    print("        xelab 均 %.2fs 合计 %.0fs  (中位 %.2fs max %.2fs)"
          % (statistics.mean(tl), sum(tl), statistics.median(tl), max(tl)))
    print("        两者合计 %.0fs，单题均 %.1fs" % (sum(tx)+sum(tl), (sum(tx)+sum(tl))/n))
print()
print("=== 误报检查：官方判为 L3 的题里，xelab 失败的（应为 0）===")
fp = [r for r in d if r["level"] == 3 and r["xvlog_rc"] == 0 and r["xelab_rc"] not in (0, None)]
print("  %d 道  %s" % (len(fp), [r["task"] for r in fp]))
print()
print("=== 按官方等级看 xelab 结果 ===")
for lv in (0, 1, 2, 3):
    sel = [r for r in d if r["level"] == lv]
    if not sel: continue
    ok = sum(1 for r in sel if r["xelab_rc"] == 0)
    bad = sum(1 for r in sel if r["xvlog_rc"] == 0 and r["xelab_rc"] not in (0, None))
    xvf = sum(1 for r in sel if r["xvlog_rc"] != 0)
    print("  L%d: %3d 道   xelab通过 %3d   xelab失败 %2d   xvlog就失败 %2d" % (lv, len(sel), ok, bad, xvf))
PYEOF
