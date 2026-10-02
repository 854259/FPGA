#!/usr/bin/env python3
"""5 样本协议的子集验证：按赛事方的调用方式（HTTP）对同一批题各跑 5 次。

为什么做
--------
计分规则要求 5 样本协议（156 题 x 2 模式 x 5 = 1560 次顶层运行）。我们目前只验过
1 道题 x 5 次。单样本能过，不代表 5 样本能过——重复调用可能暴露：
  - 临时目录/输出目录冲突
  - 锁或超时交互问题
  - 磁盘/进程泄漏（每轮累积）
  - 时间随轮次漂移

本脚本用 HTTP（赛事方的实际入口）跑 20 题 x 5 次 = 100 次，逐轮记录：
  HTTP 码、解答哈希、耗时、服务是否仍健康、磁盘/进程是否增长

边界
----
- 这是**子集验证**，不是完整的 1560 次协议。结论只能说"20 题 x 5 次无异常"。
- 不改 agent、不改题集、不改判定器。只用一个 HTTP 服务客户端。
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

KIT = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
TASKS_DIR = KIT / "bench" / "tasks_veval"
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/five_sample_subset_20261003")
PORT = 7864
TOKEN = "five-sample-subset-token"
SAMPLES = 5
# 挑题：覆盖不同难度与不同机制（简单/中等/长输出/曾失败）
PICK = [
    "Prob001_zero", "Prob009_popcount3", "Prob028_m2014_q4a", "Prob034_dff8",
    "Prob050_kmap1", "Prob058_alwaysblock2", "Prob070_ece241_2013_q2",
    "Prob082_lfsr32", "Prob099_m2014_q6c", "Prob108_rule90",
    "Prob122_kmap4", "Prob128_fsm_ps2", "Prob134_2014_q3c",
    "Prob140_fsm_hdlc", "Prob144_conwaylife", "Prob145_circuit8",
    "Prob147_circuit10", "Prob151_review2015_fsm",
    "Prob152_lemmings3", "Prob156_review2015_fancytimer",
]


def env():
    e = os.environ.copy()
    e.update(
        PATH="/workspace/AMD/2026.1/Vivado/bin:" + e["PATH"],
        LD_LIBRARY_PATH="/workspace/team/udev-stub",
        XILINXD_LICENSE_FILE="/workspace/team/Xilinx.lic",
        XILINX_VIVADO="/workspace/AMD/2026.1/Vivado",
        LLM_BASE_URL="http://127.0.0.1:8000/v1",
        MODEL_NAME="Qwen3.6-27B-Q4_K_M",
        RTL_PROFILE="development", RTL_REPAIRS="1",
        RTL_MAX_TOKENS="8192", RTL_TEMPERATURE="0",
        FPGACHINA_TOKEN=TOKEN, NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
        EDA_TMP=str(OUT / "scratch"), SELFTEST_TMP=str(OUT / "scratch"),
        PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
    )
    return e


def post(task_id, prompt, deadline=300):
    body = json.dumps({"task_id": task_id, "nonce": "%s-%d" % (task_id, time.time_ns()),
                       "mode": "agent", "prompt": prompt, "interface": "",
                       "deadline_s": deadline}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/solve" % PORT, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + TOKEN})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=deadline + 60) as r:
            d = json.loads(r.read().decode())
        return r.status, d, time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return None, {"error": type(exc).__name__}, time.time() - t0


def health():
    req = urllib.request.Request("http://127.0.0.1:%d/v1/health" % PORT,
                                 headers={"Authorization": "Bearer " + TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:                                   # noqa: BLE001
        return None


def disk_free_gb():
    st = os.statvfs("/workspace")
    return st.f_bavail * st.f_frsize / 1024 ** 3


def procs():
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines()
               if any(k in line for k in ("judge.py", "xvlog", "xelab", "xsim", "vivado")))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)

    tasks = [t for t in PICK if (TASKS_DIR / t / "prompt.txt").is_file()]
    print("题目数 %d，每題 %d 次，合计 %d 次 HTTP 调用" % (len(tasks), SAMPLES, len(tasks) * SAMPLES))
    print("服务端口 %d" % PORT, flush=True)

    srv = subprocess.Popen(
        [sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
         "serve", "--port", str(PORT)],
        cwd=str(KIT), env=env(), stdout=open(OUT / "server.log", "w"),
        stderr=subprocess.STDOUT, start_new_session=True)
    try:
        for _ in range(30):
            if health():
                break
            time.sleep(1)
        print("服务就绪:", health(), flush=True)

        rows = []
        for i, task in enumerate(tasks, 1):
            prompt = (TASKS_DIR / task / "prompt.txt").read_text(encoding="utf-8")
            hs, codes, times = [], [], []
            for k in range(SAMPLES):
                code, d, el = post(task, prompt)
                sol = d.get("solution") or ""
                hs.append(hashlib.sha256(sol.encode()).hexdigest()[:10] if sol else "-")
                codes.append(code)
                times.append(el)
            ok = all(c == 200 for c in codes)
            same = len(set(h for h in hs if h != "-")) <= 1
            rows.append(dict(task=task, codes=codes, hashes=hs,
                             times=[round(t, 1) for t in times],
                             all_200=ok, identical=same,
                             disk_free_gb=round(disk_free_gb(), 2), procs=procs()))
            print("  [%2d/%d] %-32s %s  哈希 %d 种  耗时 %s  磁盘余 %.1fG  相关进程 %d"
                  % (i, len(tasks), task,
                     "全200" if ok else "有非200 %s" % codes,
                     len(set(hs)), [round(t, 1) for t in times],
                     rows[-1]["disk_free_gb"], rows[-1]["procs"]), flush=True)
            (OUT / "five_sample_subset.json").write_text(
                json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

        print()
        print("=== 汇总 ===")
        print("  题目数        : %d" % len(rows))
        print("  全部返回 200  : %d" % sum(1 for r in rows if r["all_200"]))
        print("  5 次完全一致  : %d" % sum(1 for r in rows if r["identical"]))
        print("  总调用次数    : %d" % (len(rows) * SAMPLES))
        print("  磁盘余量变化  : %.2f -> %.2f GB"
              % (rows[0]["disk_free_gb"], rows[-1]["disk_free_gb"]))
        print("  相关进程峰值  : %d" % max(r["procs"] for r in rows))
        print()
        print("判读：")
        print("  - 若『全部 200』= 题数 且『完全一致』= 题数，则该子集上 5 样本协议成立")
        print("  - 磁盘余量不下降、相关进程无残留，说明重复调用无泄漏")
        print("  - 这**不是**完整的 1560 次协议，结论只能限定在这 %d 题上" % len(rows))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()
        print("\n服务已停")


if __name__ == "__main__":
    raise SystemExit(main())
