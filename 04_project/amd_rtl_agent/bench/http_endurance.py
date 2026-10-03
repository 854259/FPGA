#!/usr/bin/env python3
"""HTTP 接口耐久测试：超时、异常请求、并发之后，服务是否仍然可用、资源是否回收。

判定原则（第一版被评审否掉的地方，这里逐条改掉）
------------------------------------------------
第一版只"收集现象"，不能可靠判定通过：
  - 检查了 ready，却没把它纳入该步骤的通过条件；
  - 并发返回 [200, 500, 200] 时，汇总可能取到第一个 200 而误判通过；
  - 即使有步骤失败，脚本末尾仍返回成功退出码；
  - 恢复后的请求只看 HTTP 200，不看响应内容。

现在：
  - **并发时逐个检查全部响应码**，不看"第一个"；
  - **就绪检查参与判定**：每步之后 health 必须 200 且 ready:true，否则该步失败；
  - **任何必测项失败 → 整体返回非 0**；
  - 恢复后的正常请求**必须含非空 solution**，不能只看状态码；
  - 判据不确定时**宁可判失败**，不判通过。

边界
----
- 不修改 agent、题集、判定器。
- 这是接口耐久测试，不是质量评测，也不替代完整的 1560 次协议。
"""
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

KIT = pathlib.Path(os.environ.get("RTL_KIT", "/workspace/team/tasks/autodl-rtl-kit/project"))
TASKS_DIR = KIT / "bench" / "tasks_veval"
OUT = pathlib.Path("/workspace/team/runs/fpga_owner/http_endurance_20261003")
PORT = 7868
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
            return r.status, r.read(), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return None, str(exc).encode(), time.time() - t0


def health_state():
    """-> (ok, detail)。只有 200 且 ready:true 才算就绪。"""
    code, body, _ = request("/v1/health", timeout=10)
    if code != 200:
        return False, "HTTP %s" % code
    try:
        d = json.loads(body.decode())
    except ValueError:
        return False, "unparseable body"
    if d.get("ready") is not True:
        return False, "ready=%r" % d.get("ready")
    return True, d


def resources():
    procs = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    related = sum(1 for line in procs.splitlines()
                  if any(k in line for k in ("judge.py", "veval-judge", "xvlog", "xelab",
                                             "xsim", "vivado", "runtime.py worker")))
    scratch = OUT / "scratch"
    temps = len(list(scratch.glob("rtl-*"))) if scratch.is_dir() else 0
    st = os.statvfs(str(OUT))
    return dict(procs=related, temps=temps,
                free_gb=round(st.f_bavail * st.f_frsize / 1024 ** 3, 2))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scratch").mkdir(exist_ok=True)
    prompt_file = TASKS_DIR / "Prob001_zero" / "prompt.txt"
    if not prompt_file.is_file():
        print("找不到题目 %s（KIT=%s）" % (prompt_file, KIT))
        return 1
    prompt = prompt_file.read_text(encoding="utf-8")
    body_ok = json.dumps({"task_id": "e1", "nonce": "n1", "mode": "agent",
                          "prompt": prompt, "interface": "", "deadline_s": 120}).encode()

    srv = subprocess.Popen([sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
                            "serve", "--port", str(PORT)],
                           cwd=str(KIT), env=env(), stdout=open(OUT / "server.log", "w"),
                           stderr=subprocess.STDOUT, start_new_session=True)
    steps = []
    failures = []
    try:
        ready = False
        for _ in range(45):
            ready, _d = health_state()
            if ready:
                break
            time.sleep(2)
        if not ready:
            print("服务未就绪，终止（先查令牌与 ready 条件）")
            return 1
        base = resources()
        print("初始就绪: True")
        print("基线资源:", base, flush=True)

        def record(name, ok, detail, expected=None, note=""):
            """一步的判据 = 条件满足 AND 服务仍就绪。任一不满足即失败。"""
            after = resources()
            still_ok, _hd = health_state()
            passed = bool(ok) and still_ok
            steps.append(dict(step=name, expected=expected, ok=bool(ok),
                              service_ready=still_ok, passed=passed,
                              detail=detail, after=after, note=note))
            if not passed:
                failures.append(name)
            print("  %-22s %s  期望=%-14s 实测=%-24s 就绪=%-5s 进程=%-3d 临时=%-2d 磁盘余=%.1fG"
                  % (name, "PASS" if passed else "FAIL", str(expected), str(detail),
                     still_ok, after["procs"], after["temps"], after["free_gb"]), flush=True)

        print()
        print("=== 施加压力；每步判据 = 条件满足 且 服务仍 ready:true ===")

        # 1) 极短 deadline：契约要求 200 + 空解答，不报错
        code, body, _ = request("/v1/solve", json.dumps(
            {"task_id": "e2", "prompt": prompt, "interface": "", "deadline_s": 1}).encode(),
            timeout=120)
        try:
            solved = json.loads(body.decode()).get("solution") or ""
        except Exception:                               # noqa: BLE001
            solved = "<unparsable>"
        record("极短deadline(1s)", code == 200 and solved == "",
               "HTTP %s solution=%s" % (code, len(solved) if isinstance(solved, str) else "?"),
               expected="200 且解答空")

        # 2) 超大请求体
        code, _b, _ = request("/v1/solve", b"x" * (1024 * 1024 + 10), timeout=60)
        record("超大请求体(>1MB)", code == 400, "HTTP %s" % code, expected=400)

        # 3) 非法 JSON
        code, _b, _ = request("/v1/solve", b"{not json", timeout=30)
        record("非法JSON", code == 400, "HTTP %s" % code, expected=400)

        # 4) 缺必填字段
        code, _b, _ = request("/v1/solve", b'{"prompt":"x"}', timeout=30)
        record("缺task_id", code == 400, "HTTP %s" % code, expected=400)

        # 5) 错误令牌（两个端点都要 401）
        c1, _b, _ = request("/v1/solve", body_ok, token="wrong", timeout=30)
        record("solve错误令牌", c1 == 401, "HTTP %s" % c1, expected=401)
        c2, _b, _ = request("/v1/health", token="wrong", timeout=30)
        record("health错误令牌", c2 == 401, "HTTP %s" % c2, expected=401)

        # 6) 不存在路径
        code, _b, _ = request("/v1/nope", b"{}", timeout=30)
        record("不存在路径", code == 404, "HTTP %s" % code, expected=404)

        # 7) 并发 3 个：逐个检查全部响应码，绝不取"第一个"
        codes = []
        lock = threading.Lock()

        def one(i):
            c, _b, _e = request("/v1/solve", json.dumps(
                {"task_id": "c%d" % i, "prompt": prompt, "interface": "",
                 "deadline_s": 120}).encode(), timeout=300)
            with lock:
                codes.append(c)

        ts = [threading.Thread(target=one, args=(i,)) for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        # 逐个断言：三个都必须 200
        record("并发3请求", sorted(codes) == [200, 200, 200],
               "全部响应码=%s" % sorted(codes), expected="[200,200,200]")

        # 8) 恢复后的正常请求：必须含非空 solution，不能只看状态码
        code, body, _ = request("/v1/solve", body_ok, timeout=300)
        sol_len, has_nonempty = 0, False
        try:
            sol = json.loads(body.decode()).get("solution") or ""
            sol_len = len(sol)
            has_nonempty = bool(sol.strip())
        except Exception:                               # noqa: BLE001
            pass
        record("恢复后正常请求", code == 200 and has_nonempty,
               "HTTP %s solution=%d字符" % (code, sol_len), expected="200 且解答非空")

        print()
        print("=== 汇总 ===")
        print("  步骤数        : %d" % len(steps))
        print("  通过          : %d" % sum(1 for s in steps if s["passed"]))
        print("  失败          : %d %s" % (len(failures), failures if failures else ""))
        final = resources()
        print("  基线资源      : %s" % base)
        print("  结束资源      : %s" % final)
        print("  资源回收      : 进程 %s，临时目录 %s，磁盘 %s"
              % ("已回收" if final["procs"] <= base["procs"] else "残留 %d" % (final["procs"] - base["procs"]),
                 "已回收" if final["temps"] == 0 else "残留 %d" % final["temps"],
                 "无下降" if final["free_gb"] >= base["free_gb"] - 0.05 else "下降 %.2fG" % (base["free_gb"] - final["free_gb"])))

        (OUT / "endurance.json").write_text(
            json.dumps(dict(base=base, final=final, steps=steps, failures=failures),
                       indent=2, ensure_ascii=False), encoding="utf-8")

        if failures:
            print()
            print("验收失败：以下步骤未通过 —— %s" % ", ".join(failures))
            print("（判据是「条件满足」且「服务仍 ready:true」同时成立）")
            return 1
        print()
        print("验收通过：全部步骤条件满足，且每步之后服务仍 ready:true。")
        print("仍须注意：这是接口耐久测试，不是质量评测，也不替代完整 1560 次协议。")
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
