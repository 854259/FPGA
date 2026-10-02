#!/usr/bin/env python3
"""完美预言机实验：功能反馈的天花板有多高。

问题
----
agent 缺功能反馈是已知瓶颈。但"给它功能反馈值不值得做"取决于一个更前置的问题：
**如果反馈是完美的，它能修好多少题？**

做法
----
用**官方测试台**当完美预言机（只在离线实验里用，绝不进提交包）：

  1. 取该题在基线跑里已有的 agent 解答，用官方测试台跑一遍，抓完整仿真输出
     （含 `Mismatches: N in M samples` 与逐信号 `Hint:`）—— 这就是 agent 若拥有
     完美测试台会看到的反馈
  2. 按 runtime 的修复格式把反馈喂给模型，生成一次修复
  3. 用官方 judge 判修复后的解答
  4. 记录 原等级 → 新等级

判读
----
- 救回很多（15+/38）→ 功能反馈是真金，值得投入做自写测试台
- 救回很少（3/38）  → **连完美反馈都救不动**，整条路放弃，省下数天

边界
----
- 官方测试台仅用于本次离线测量，不进入 agent、不进提交包（规则要求）
- 修复一轮，与 runtime 的 RTL_REPAIRS=1 一致；温度 0
- 不修改题目、官方 baseline、判定器
"""
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import urllib.request

KIT = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
TASKS = KIT / "bench" / "tasks_veval"
JUDGE = KIT / "official_reference" / "selftest" / "judge.py"
BASE_RUN = pathlib.Path("/workspace/team/runs/fpga_owner/"
                        "skillfix_full156_20261001T235258Z/full156")
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/oracle_20261003")

SKILL_GEN = KIT / "submission" / "skill" / "rtl-generation" / "SKILL.md"
SKILL_REPAIR = KIT / "submission" / "skill" / "rtl-feedback-repair" / "SKILL.md"

LLM = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "Qwen3.6-27B-Q4_K_M"
COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}


def env():
    e = os.environ.copy()
    e.update(
        PATH="/workspace/AMD/2026.1/Vivado/bin:" + e["PATH"],
        LD_LIBRARY_PATH="/workspace/team/udev-stub",
        XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic",
        XILINX_VIVADO="/workspace/AMD/2026.1/Vivado",
        EDA_TMP=str(OUT / "scratch"), SELFTEST_TMP=str(OUT / "scratch"),
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
    )
    return e


def extract_code(text):
    m = re.findall(r"```(?:verilog|systemverilog|sv|v)?\s*\n(.*?)```", text, re.S)
    code = max(m, key=len) if m else text
    start = code.find("module")
    if start > 0:
        code = code[start:]
    end = code.rfind("endmodule")
    if end >= 0:
        code = code[:end + len("endmodule")]
    return code.strip() + "\n"


def call_llm(messages, max_tokens=8192, temperature=0.0):
    body = json.dumps(dict(model=MODEL, messages=messages, max_tokens=max_tokens,
                           temperature=temperature)).encode()
    req = urllib.request.Request(LLM, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"]["content"]


def run_tb(task_dir, solution, workdir):
    """用官方测试台跑一遍，返回 (是否通过, 反馈文本)。"""
    spec = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    top = spec.get("tb_top", "tb")
    os.makedirs(workdir, exist_ok=True)
    for src, dst in ((solution, "dut.sv"),
                     (task_dir / spec["reference_module"], "ref.sv"),
                     (task_dir / spec["testbench"], "tb.sv")):
        shutil.copyfile(src, os.path.join(workdir, dst))
    out = []
    for cmd in (["xvlog", "-sv", "--nolog", "dut.sv", "ref.sv", "tb.sv"],
                ["xelab", top, "-s", "snap", "--nolog"],
                ["xsim", "snap", "-R"]):
        try:
            p = subprocess.run(cmd, cwd=workdir, env=env(), capture_output=True,
                               text=True, errors="replace", timeout=600)
        except subprocess.TimeoutExpired:
            out.append("TIMEOUT in " + cmd[0])
            break
        out.append(p.stdout + p.stderr)
        if p.returncode != 0 and cmd[0] != "xsim":
            break
    text = "\n".join(out)
    m = re.search(r"Mismatches:\s+(\d+)\s+in\s+(\d+)\s+samples", text)
    passed = bool(m) and int(m.group(1)) == 0
    lines = [s.strip() for s in text.splitlines()
             if re.search(r"Mismatches:|Hint:|ERROR|FATAL", s)]
    seen, uniq = set(), []
    for s in lines:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return passed, "\n".join(uniq)[:2048]


def run_judge(task_dir, solution, outdir):
    os.makedirs(outdir, exist_ok=True)
    jf = os.path.join(outdir, "verdict.json")
    subprocess.run(["python3", "-B", str(JUDGE), "--task", str(task_dir),
                    "--solution", str(solution), "--outdir", outdir,
                    "--json", jf, "--timeout", "600"],
                   env=env(), capture_output=True, text=True, errors="replace")
    if os.path.isfile(jf):
        try:
            return json.loads(pathlib.Path(jf).read_text()).get("level")
        except ValueError:
            return None
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)

    l1 = []
    for p in sorted(glob.glob(str(BASE_RUN / "results" / "agent.*.json"))):
        d = json.loads(pathlib.Path(p).read_text())
        if d.get("level") == 1:
            l1.append(d["task_id"])
    print("L1 题数: %d" % len(l1), flush=True)

    skill_gen = SKILL_GEN.read_text(encoding="utf-8")
    skill_rep = SKILL_REPAIR.read_text(encoding="utf-8")
    rows = []

    for i, task in enumerate(l1, 1):
        task_dir = TASKS / task
        src = BASE_RUN / "agent" / task / "s0" / "solution.v"
        if not (task_dir.is_dir() and src.is_file()):
            print("  [%d/%d] %-28s skip" % (i, len(l1), task), flush=True)
            continue
        d = OUT / task
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        t0 = time.time()

        passed, fb = run_tb(task_dir, src, str(d / "tb0"))
        if passed:
            rows.append(dict(task=task, level_before=1, tb_passed=True,
                             level_after=None, feedback=fb[:300]))
            print("  [%d/%d] %-28s 测试台判定通过，跳过" % (i, len(l1), task), flush=True)
            (OUT / "oracle_results.json").write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            continue

        prompt = (task_dir / "prompt.txt").read_text(encoding="utf-8")
        iface = task_dir / "interface.txt"
        if iface.is_file() and iface.read_text(encoding="utf-8").strip():
            prompt += "\n\nInterface:\n" + iface.read_text(encoding="utf-8")
        code = src.read_text(encoding="utf-8")
        msgs = [dict(role="system", content=skill_gen + "\n" + skill_rep),
                dict(role="user", content=prompt + "\nPrevious candidate:\n" + code +
                     "\nCandidate diagnostics:\n" + fb)]
        try:
            fixed = extract_code(call_llm(msgs))
            (d / "fixed.sv").write_text(fixed, encoding="utf-8")
        except Exception as exc:                        # noqa: BLE001
            rows.append(dict(task=task, level_before=1, tb_passed=False,
                             level_after=None, error=type(exc).__name__))
            print("  [%d/%d] %-28s LLM %s" % (i, len(l1), task, type(exc).__name__),
                  flush=True)
            (OUT / "oracle_results.json").write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            continue

        lv1 = run_judge(task_dir, d / "fixed.sv", str(d / "judge1"))
        rows.append(dict(task=task, level_before=1, tb_passed=False, level_after=lv1,
                         feedback=fb[:400], elapsed_s=round(time.time() - t0, 1)))
        print("  [%d/%d] %-28s L1 -> L%s  %.0fs"
              % (i, len(l1), task, lv1, time.time() - t0), flush=True)
        (OUT / "oracle_results.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    valid = [r for r in rows if r.get("level_after") is not None]
    up = [r for r in valid if r["level_after"] > 1]
    to3 = [r for r in valid if r["level_after"] == 3]
    print()
    print("=== 完美预言机：天花板 ===")
    print("  可判定题数 : %d / %d" % (len(valid), len(rows)))
    print("  等级提升   : %d" % len(up))
    print("  达 L3      : %d" % len(to3))
    if valid:
        after = sum(COEFF.get(r["level_after"], 0) for r in valid)
        before = 0.2 * len(valid)
        print("  系数合计   : %.2f -> %.2f" % (before, after))
        print("  题集得分增量（分母156）: %+.4f" % ((after - before) / 156))
    print()
    print("判读：这是【上限】。上限低则整条功能自检方向放弃；上限高才值得做自写测试台。")


if __name__ == "__main__":
    raise SystemExit(main())
