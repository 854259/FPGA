#!/usr/bin/env python3
"""实测自写测试台的真实成本 —— 逐步计时。

为什么先测成本
--------------
完美预言机测出天花板 +4.28 分，但它用的是**免费**的官方测试台。
真实实现要额外付：

  生成测试台(1 次模型调用) + 编译失败重试(可能再 1 次) + xsim + 检出后修设计(再 1 次调用)

若总增量 ≥20 秒，代价项要掉 4 分以上，**即使可用率 100% 也不划算**。
所以先把这个数测出来，再决定要不要投入做完整实现。

本脚本不改任何生产代码，只做测量。
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
BASE_RUN = pathlib.Path("/workspace/team/runs/fpga_owner/"
                        "skillfix_full156_20261001T235258Z/full156")
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/tbcost_20261003")
SKILL_GEN = KIT / "submission" / "skill" / "rtl-generation" / "SKILL.md"

LLM = "http://127.0.0.1:8000/v1/chat/completions"
MODEL = "Qwen3.6-27B-Q4_K_M"

TB_PROMPT = """Write a self-checking Verilog testbench that verifies a module named TopModule against the specification above.

Requirements:
- The testbench module must be named tb and instantiate TopModule as the device under test.
- Apply deterministic stimulus covering the behaviours the specification requires.
- Compare the device outputs against the expected behaviour on every step.
- Maintain two integers: errors and samples.
- Print exactly one final line in this format: Mismatches: <errors> in <samples> samples
- Include a watchdog that aborts after a bounded number of cycles.
- Output only the testbench module; no explanation."""


def env():
    e = os.environ.copy()
    e.update(
        PATH="/workspace/AMD/2026.1/Vivado/bin:" + e["PATH"],
        LD_LIBRARY_PATH="/workspace/team/udev-stub",
        XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic",
        XILINX_VIVADO="/workspace/AMD/2026.1/Vivado",
        EDA_TMP=str(OUT / "scratch"), SELFTEST_TMP=str(OUT / "scratch"),
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    )
    return e


def extract_tb(text):
    m = re.findall(r"```(?:verilog|systemverilog|sv|v)?\s*\n(.*?)```", text, re.S)
    code = max(m, key=len) if m else text
    start = code.find("module")
    if start > 0:
        code = code[start:]
    end = code.rfind("endmodule")
    if end >= 0:
        code = code[:end + len("endmodule")]
    return code.strip() + "\n"


def call_llm(messages, max_tokens=8192):
    body = json.dumps(dict(model=MODEL, messages=messages, max_tokens=max_tokens,
                           temperature=0.0)).encode()
    req = urllib.request.Request(LLM, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"]["content"], d.get("usage", {})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)

    l1 = []
    for p in sorted(glob.glob(str(BASE_RUN / "results" / "agent.*.json"))):
        d = json.loads(pathlib.Path(p).read_text())
        if d.get("level") == 1:
            l1.append(d["task_id"])
    sample = l1[:5]
    print("抽样题: %s" % ", ".join(sample), flush=True)
    print(flush=True)

    skill = SKILL_GEN.read_text(encoding="utf-8")
    rows = []

    for task in sample:
        task_dir = TASKS / task
        dut = BASE_RUN / "agent" / task / "s0" / "solution.v"
        if not (task_dir.is_dir() and dut.is_file()):
            continue
        d = OUT / task
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        prompt = (task_dir / "prompt.txt").read_text(encoding="utf-8")

        timings = {}
        # 1) 生成测试台
        t0 = time.time()
        try:
            reply, usage = call_llm([dict(role="system", content=skill),
                                     dict(role="user",
                                          content=prompt + "\n\n" + TB_PROMPT)])
            tb = extract_tb(reply)
        except Exception as exc:                       # noqa: BLE001
            print("  %-24s 生成失败 %s" % (task, type(exc).__name__), flush=True)
            continue
        timings["gen_tb"] = time.time() - t0
        timings["tb_tokens"] = usage.get("completion_tokens")
        (d / "tb.sv").write_text(tb, encoding="utf-8")

        # 2) 编译测试台
        shutil.copyfile(dut, d / "dut.sv")
        t0 = time.time()
        p = subprocess.run(["xvlog", "-sv", "--nolog", "dut.sv", "tb.sv"],
                           cwd=d, env=env(), capture_output=True, text=True,
                           errors="replace", timeout=300)
        timings["compile_tb"] = time.time() - t0
        timings["compile_ok"] = p.returncode == 0

        # 3) 若编译失败，重试一次
        if p.returncode != 0:
            err = "\n".join(s for s in (p.stdout + p.stderr).splitlines()
                            if "ERROR" in s)[:1200]
            t0 = time.time()
            try:
                reply, usage2 = call_llm([
                    dict(role="system", content=skill),
                    dict(role="user", content=prompt + "\n\n" + TB_PROMPT +
                         "\n\nPrevious testbench:\n" + tb +
                         "\nCompile errors:\n" + err +
                         "\nReturn a corrected complete testbench.")])
                tb = extract_tb(reply)
            except Exception:                          # noqa: BLE001
                pass
            timings["regen_tb"] = time.time() - t0
            (d / "tb.sv").write_text(tb, encoding="utf-8")
            t0 = time.time()
            p = subprocess.run(["xvlog", "-sv", "--nolog", "dut.sv", "tb.sv"],
                               cwd=d, env=env(), capture_output=True, text=True,
                               errors="replace", timeout=300)
            timings["compile_tb2"] = time.time() - t0
            timings["compile_ok_after_retry"] = p.returncode == 0

        # 4) 若编译通过，跑 xsim
        timings["xsim"] = 0.0
        timings["mismatches"] = None
        if p.returncode == 0:
            t0 = time.time()
            subprocess.run(["xelab", "tb", "-s", "snap", "--nolog"], cwd=d, env=env(),
                           capture_output=True, text=True, errors="replace", timeout=300)
            r = subprocess.run(["xsim", "snap", "-R"], cwd=d, env=env(),
                               capture_output=True, text=True, errors="replace",
                               timeout=300)
            timings["xsim"] = time.time() - t0
            m = re.search(r"Mismatches:\s+(\d+)\s+in\s+(\d+)\s+samples",
                          r.stdout + r.stderr)
            if m:
                timings["mismatches"] = int(m.group(1))

        total = (timings.get("gen_tb", 0) + timings.get("compile_tb", 0) +
                 timings.get("regen_tb", 0) + timings.get("compile_tb2", 0) +
                 timings.get("xsim", 0))
        timings["total_extra_s"] = round(total, 1)
        rows.append(dict(task=task, **{k: (round(v, 1) if isinstance(v, float) else v)
                                       for k, v in timings.items()}))
        print("  %-24s 总增量 %5.1fs  (生成 %.1fs 编译 %.1f 重试 %s xsim %.1f) tb_tokens=%s 编译OK=%s"
              % (task, total, timings.get("gen_tb", 0), timings.get("compile_tb", 0),
                 round(timings.get("regen_tb", 0), 1) if "regen_tb" in timings else "-",
                 timings.get("xsim", 0), timings.get("tb_tokens"),
                 timings.get("compile_ok_after_retry", timings.get("compile_ok"))),
              flush=True)
        (OUT / "tbcost_results.json").write_text(
            json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    if rows:
        avg = sum(r["total_extra_s"] for r in rows) / len(rows)
        print()
        print("=== 成本结论 ===")
        print("  样本数            : %d" % len(rows))
        print("  平均每题额外耗时  : %.1f 秒" % avg)
        agent_mean = 19.75
        ratio_before = 16.58 / agent_mean
        ratio_after = 16.58 / (agent_mean + avg)
        print("  代价比值          : %.3f -> %.3f" % (ratio_before, ratio_after))
        print("  代价分            : %.2f -> %.2f   即 %+.2f"
              % (10 * ratio_before, 10 * ratio_after,
                 10 * ratio_after - 10 * ratio_before))
        print()
        print("  对照：完美预言机的收益上限是 +4.28 分。")
        print("  若成本损失 >= 4.28，则**即使测试台 100% 可用也不划算**。")


if __name__ == "__main__":
    raise SystemExit(main())
