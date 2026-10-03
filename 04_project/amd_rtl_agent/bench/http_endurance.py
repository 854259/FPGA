#!/usr/bin/env python3
"""HTTP 接口耐久测试：超时、异常请求、并发之后，服务是否仍然可用、资源是否回收。

为什么单独做
------------
五样本质量评测回答的是"答案好不好"。它不回答"服务会不会被拖垮"。
契约写明：单题墙钟以赛事方发出到收到响应为准，超时按 L0 且**不重试**——
也就是说，服务一旦进入不可用状态，**后面每一个样本都是 0 分**。

本脚本主动施加以下压力，每一步之后都验证服务仍可用：
  1. 极短 deadline（触发队伍侧自我限时与 worker 被杀）
  2. 超大请求体（超过 1 MB 上限）
  3. 非法 JSON
  4. 缺必填字段
  5. 错误令牌
  6. 并发请求（单槽下应串行，不应崩）
  7. 不存在的路径

每一步记录：服务是否仍应答 / 是否仍 ready / 相关进程数 / 临时目录数 / 磁盘余量。
最后给出资源回收判定。

边界
----
- 不修改 agent、题集、判定器。
- 这是**接口耐久**测试，不是质量评测，也不替代完整的 1560 次协议。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

KIT = pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project")
TASKS_DIR = KIT / "bench" / "tasks_veval"
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/http_endurance_20261003")
PORT = 7866
TOKEN = "endurance-token"


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


def request(path, data=None, token=TOKEN, timeout=120, method=None):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, body, time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return None, str(exc).encode(), time.time() - t0


def health_ok():
    code, body, _ = request("/v1/health", timeout=10)
    if code != 200:
        return False, "HTTP %s" % code
    try:
        d = json.loads(body.decode())
    except ValueError:
        return False, "bad json"
    return d.get("ready") is True, d


def resource_snapshot():
    procs = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    related = sum(1 for line in procs.splitlines()
                  if any(k in line for k in ("judge.py", "veval-judge", "xvlog", "xelab",
                                             "xsim", "vivado", "runtime.py worker")))
    scratch = OUT / "scratch"
    temps = len(list(scratch.glob("rtl-*"))) if scratch.is_dir() else 0
    st = os.statvfs(str(OUT))
    free = st.f_bavail * st.f_frsize / 1024 ** 3
    return dict(procs=related, temps=temps, free_gb=round(free, 2))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)
    prompt = (TASKS_DIR / "Prob001_zero" / "prompt.txt").read_text(encoding="utf-8")
    body_ok = json.dumps({"task_id": "e1", "nonce": "n1", "mode": "agent",
                          "prompt": prompt, "interface": "", "deadline_s": 120}).encode()

    srv = subprocess.Popen([sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
                            "serve", "--port", str(PORT)],
                           cwd=str(KIT), env=env(), stdout=open(OUT / "server.log", "w"),
                           stderr=subprocess.STDOUT, start_new_session=True)
    results = []
    try:
        for _ in range(45):
            ok, _d = health_ok()
            if ok:
                break
            time.sleep(2)
        ok, detail = health_ok()
        print("初始就绪: %s %s" % (ok, detail), flush=True)
        base = resource_snapshot()
        print("基线资源:", base, flush=True)

        def step(name, expect, call, note=""):
            before = resource_snapshot()
            code, body, el = call()
            time.sleep(2)
            after = resource_snapshot()
            still_ok, hd = health_ok()
            good = (code == expect) if expect is not None else (code is not None)
            results.append(dict(step=name, code=code, expected=expect, ok=good,
                                service_alive=still_ok, before=before, after=after,
                                seconds=round(el, 1), note=note))
            print("  %-26s HTTP %-5s 期望 %-5s %s  服务仍就绪=%s  进程 %d->%d  临时目录 %d->%d  磁盘余 %.1fG"
                  % (name, code, expect, "OK" if good else "FAIL", still_ok,
                     before["procs"], after["procs"], before["temps"], after["temps"],
                     after["free_gb"]), flush=True)
            return code, body

        print("\n=== 施加压力，每步之后验证服务仍可用 ===")
        # 1) 极短 deadline：应返回 200 与空解答（契约要求不报错），且服务活着
        step("极短deadline(1s)", 200,
             lambda: request("/v1/solve", json.dumps(
                 {"task_id": "e2", "prompt": prompt, "interface": "",
                  "deadline_s": 1}).encode(), timeout=120),
             "触发队伍侧自我限时")

        # 2) 超大请求体：契约上限 1 MB
        step("超大请求体(>1MB)", 400,
             lambda: request("/v1/solve", b"x" * (1024 * 1024 + 10), timeout=60))

        # 3) 非法 JSON
        step("非法JSON", 400, lambda: request("/v1/solve", b"{not json", timeout=30))

        # 4) 缺必填字段
        step("缺task_id", 400, lambda: request("/v1/solve", b'{"prompt":"x"}', timeout=30))

        # 5) 错误令牌
        step("错误令牌", 401,
             lambda: request("/v1/solve", body_ok, token="wrong-token", timeout=30))
        step("health错误令牌", 401,
             lambda: request("/v1/health", token="wrong-token", timeout=30))

        # 6) 不存在路径
        step("不存在路径", 404, lambda: request("/v1/nope", b"{}", timeout=30))

        # 7) 并发 3 个请求（单槽应串行，不应崩）
        def concurrent():
            out = []
            def one(i):
                c, b, e = request("/v1/solve", json.dumps(
                    {"task_id": "c%d" % i, "prompt": prompt, "interface": "",
                     "deadline_s": 120}).encode(), timeout=300)
                out.append(c)
            ts = [threading.Thread(target=one, args=(i,)) for i in range(3)]
            t0 = time.time()
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            return (200 if all(c == 200 for c in out) else (out[0] if out else None),
                    json.dumps(out).encode(), time.time() - t0)
        step("并发3请求", 200, concurrent, "单槽下应串行")

        # 8) 恢复正常请求，确认服务确实还能干活
        c, b = step("恢复后正常请求", 200,
                    lambda: request("/v1/solve", body_ok, timeout=300))
        sol_len = 0
        try:
            sol_len = len(json.loads(b.decode()).get("solution") or "")
        except Exception:                               # noqa: BLE001
            pass

        print("\n=== 汇总 ===")
        print("  压力步骤        : %d" % len(results))
        print("  符合期望        : %d" % sum(1 for r in results if r["ok"]))
        print("  每步后服务仍就绪: %d / %d" % (sum(1 for r in results if r["service_alive"]), len(results)))
        print("  恢复后解答字符数: %d" % sol_len)
        final = resource_snapshot()
        print("  基线资源        : %s" % base)
        print("  结束资源        : %s" % final)
        print("  资源回收        : 进程 %s，临时目录 %s，磁盘 %s"
              % ("已回收" if final["procs"] <= base["procs"] else "有残留 %d" % (final["procs"] - base["procs"]),
                 "已回收" if final["temps"] == 0 else "有残留 %d" % final["temps"],
                 "无下降" if final["free_gb"] >= base["free_gb"] - 0.05 else "下降 %.2fG" % (base["free_gb"] - final["free_gb"])))

        (OUT / "endurance.json").write_text(
            json.dumps(dict(base=base, final=final, steps=results, solution_len=sol_len),
                       indent=2, ensure_ascii=False), encoding="utf-8")
        print("\n判读：")
        print("  - 全部步骤符合期望 HTTP 码，且每步之后 health 仍 ready，说明服务能扛住异常输入")
        print("  - 进程/临时目录回到基线，说明超时与并发之后资源被回收")
        print("  - 这是接口耐久测试，不是质量评测，也不替代完整 1560 次协议")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
