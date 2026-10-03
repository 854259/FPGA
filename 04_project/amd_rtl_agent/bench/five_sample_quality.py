#!/usr/bin/env python3
"""5 样本质量评测：取 5 个样本，**用官方汇总函数**算成绩。

为什么重写（第二版）
--------------------
第一版只是"同请求打 5 次看返回是否相同"，不是协议。
第二版我自己算了分数，但**算法与官方口径不符**：

| 项 | 我第二版的做法 | 官方口径（score.py::summarize） |
|---|---|---|
| 空答案 | 排除出平均分 | **属于 L0，系数 0，留在分母里** |
| `pass@5` | 任意一次 L3 才记 1 | **取各样本等级系数的最大值** |
| `tool_error` | 未单独处理 | **单列排除**；整题全为环境失败则记录不计分 |

反例（评审给的，已在官方函数上核对过）：
  1xL3 + 4x空答 -> 官方 pass@1=0.2   （我算成 1.0）
  5xL2          -> 官方 pass@5=0.7   （我算成 0）

所以本版**不再自己算**，而是把判定器的 verdict 原样交给官方 `summarize()`。
判定器的 verdict 本来就含 `level` / `coefficient` / `tool_error`，可直接喂入。

为什么还有第三版
----------------
第二版之后又发现三处会让 200 次请求的结论失真，且都不在"统计口径"上：

1. **接口失败必须与判定环境错误分开。** 旧第三版错误地把非 200/连接失败
   标成 `tool_error` 排除，虚高了可用性不足时的成绩。pinned API_CONTRACT.md
   §4（119–120 行）规定超时、连接断开、返回格式错均为 L0，不重试。
   现在这些结果留在分母，另加 `solve_error`；仅判定器环境错误按官方规则排除。
2. **端到端耗时没有留档。** `el` 被接住就丢掉，计划要求的均值/P50/P95/最大值
   无从计算。现在逐格记 `e2e_elapsed_s`，与判定耗时、内部 trace 区间分列。
3. **nonce/参数/版本只在内存里。** 现在发第一个请求**之前**先写 `schedule.json`
   （固定的 题→模式→采样 顺序 + 每格 nonce）与 `run_manifest.json`（入口/技能/
   判定器/manifest 的哈希与模型参数）。顺序"事先固定"从此有证据，而不是口头承诺。

第三版仍然**不自己算分**：`official.summarize()` 是唯一的计分口径，
耗时那一段显式标为"非计分"。

说明
----
- "五次中是否出现 L3"仍有参考价值，但**另起名字** `any_l3`，不叫 pass@5。
- 报告里同时给出 `scored_tasks / tasks`：**缺结果必须表现为"评测不完整"，不能静默跳过**。
- 这只是**子集**评测，不是完整 1560 次协议。
- 不改 agent、不改题集、不改判定器，只读官方汇总函数。
"""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

def resolve_kit():
    """Locate the kit in either layout.

    Cloud deployment keeps it at a fixed path; the repository keeps the same tree
    under 04_project/amd_rtl_agent/, which is this file's grandparent. Resolving
    instead of hardcoding means the summary logic can be exercised by tests on a
    machine that has no cloud path at all.
    """
    override = os.environ.get("RTL_KIT")
    candidates = []
    if override:
        candidates.append(pathlib.Path(override))
    candidates.append(pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project"))
    candidates.append(pathlib.Path(__file__).resolve().parents[1])
    for candidate in candidates:
        if (candidate / "official_reference" / "selftest" / "score.py").is_file():
            return candidate
    return candidates[-1]


KIT = resolve_kit()
TASKS_DIR = KIT / "bench" / "tasks_veval"
JUDGE = KIT / "official_reference" / "selftest" / "judge.py"
OFFICIAL_SCORE = KIT / "official_reference" / "selftest" / "score.py"
TOKEN = "five-sample-quality-token"
_evaluation = None

DEFAULT_PICK = [
    "Prob001_zero", "Prob009_popcount3", "Prob050_kmap1", "Prob058_alwaysblock2",
    "Prob070_ece241_2013_q2", "Prob082_lfsr32", "Prob145_circuit8", "Prob147_circuit10",
]


def load_official_score():
    """官方汇总函数。绝不自己重写统计口径。"""
    spec = importlib.util.spec_from_file_location("official_score", OFFICIAL_SCORE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    if not hasattr(module, "summarize"):
        raise RuntimeError("官方 score.py 里找不到 summarize()")
    return module


def load_evaluation():
    """Use the same pinned-judge adapter as the full evaluation driver."""
    global _evaluation
    if _evaluation is None:
        spec = importlib.util.spec_from_file_location("quality_official_eval", KIT / "official_eval.py")
        _evaluation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_evaluation)
    return _evaluation


def owns_listener(pid, port, proc_root=pathlib.Path('/proc')):
    """Linux: the child PID must hold the actual loopback listening socket."""
    try:
        inodes = set()
        for line in (proc_root / 'net/tcp').read_text().splitlines()[1:]:
            fields = line.split()
            if (len(fields) > 9 and fields[3] == '0A'
                    and fields[1].upper() == '0100007F:%04X' % port):
                inodes.add('socket:[' + fields[9] + ']')
        for fd in (proc_root / str(pid) / 'fd').iterdir():
            try:
                if os.readlink(fd) in inodes:
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def require_free_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1', port))


def wait_ready(port, timeout=90, process=None):
    """Accept readiness only from our live child and its listening socket."""
    if process is None:
        raise ValueError('the owned service process is required')
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        if process.poll() is not None:
            return False, {'error': 'owned service exited', 'returncode': process.returncode}
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/v1/health" % port,
                                         headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=5) as r:
                last = json.loads(r.read().decode())
            if (r.status == 200 and last.get("ready") is True
                    and process.poll() is None and owns_listener(process.pid, port)):
                return True, last
        except Exception as exc:                        # noqa: BLE001
            last = {"error": type(exc).__name__}
        time.sleep(2)
    return False, last


def post_solve(port, task_id, prompt, mode, deadline, nonce=None):
    """发一次 /v1/solve，返回 (http 状态码, 响应体, 端到端墙钟秒)。

    非 200、连接层失败或返回格式错误按 API_CONTRACT.md §4 记 L0，
    不伪装成判定器 tool_error 排除；另留错误详情便于排查。传输失败的具体
    根因可能尚未确定，这不改变接口契约的失败计分规则。

    `nonce` 由调用方给定并写进顺序表；省略时沿用"每题一个时间戳"的旧行为。
    """
    if nonce is None:
        nonce = "%s-%d" % (task_id, time.time_ns())
    body = json.dumps({"task_id": task_id, "nonce": nonce, "mode": mode,
                       "prompt": prompt, "interface": "",
                       "deadline_s": deadline}).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/solve" % port, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + TOKEN})
    t0 = time.time()
    status = None
    raw = None
    try:
        with urllib.request.urlopen(req, timeout=deadline + 20) as r:
            status = r.status
            raw = r.read().decode('utf-8')
            payload = json.loads(raw)
        elapsed = time.time() - t0
        valid = (isinstance(payload, dict) and payload.get('task_id') == task_id
                 and isinstance(payload.get('solution'), str)
                 and isinstance(payload.get('trace'), str)
                 and type(payload.get('elapsed_s')) in (int, float)
                 and 0 <= payload['elapsed_s'] < float('inf'))
        if not valid or elapsed > deadline + 20:
            return status, {'error': 'InvalidResponse' if not valid else 'DeadlineExceeded',
                            'detail': 'invalid response fields or request deadline exceeded',
                            'raw_response': raw}, elapsed
        return status, payload, elapsed
    except urllib.error.HTTPError as exc:               # 4xx/5xx 也要留下状态码
        failure = {"error": "HTTPError", "detail": str(exc)[:200], 'raw_response': None}
        try:
            failure['raw_response'] = exc.read().decode('utf-8', errors='replace')
        except Exception as read_error:
            # Body collection is diagnostic: it must not hide the original HTTP error.
            failure['response_body_error'] = type(read_error).__name__ + ': ' + str(read_error)[:200]
        return exc.code, failure, time.time() - t0
    except Exception as exc:                            # noqa: BLE001
        return status, {"error": type(exc).__name__,
                        "detail": str(exc)[:200], 'raw_response': raw}, time.time() - t0


def run_judge(task_dir, solution_path, outdir):
    """Delegate to the shared evidence-preserving judge; never overwrite a run.

    Adapter/evidence failures stop the batch. Official tool_error results stay
    unchanged and are separately excluded by the official scoring function.
    """
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    return load_evaluation().judge_sample(
        pathlib.Path(task_dir), pathlib.Path(solution_path), outdir,
        outdir / 'verdict.json', 600)


def judge_or_tool_error(code, detail, task_dir, solution_path, judge_outdir):
    """Service failures are L0; only genuine judge environment errors are excluded.

    API_CONTRACT.md:119-120 specifies deadline+20 and failure=L0 without retry.
    SCORING.md:175-182 excludes judge licensing/fixture failures, not HTTP faults.
    Keep the historical function name for callers; solve_error marks the distinct
    failure source without inventing a tool_error or attributing its root cause.
    """
    if code != 200 or detail:
        return {'level': 0, 'coefficient': 0.0, 'elapsed_s': 0.0,
                'stages': {'compile': False, 'simulate': False, 'synth': False},
                'tool_error': None,
                'solve_error': 'solve failed: HTTP %s %s' % (code, detail or '')}
    v = run_judge(task_dir, solution_path, judge_outdir)
    if not v:
        # 判定没产出结果：标为环境失败，让官方汇总单列，
        # 而不是当成 L0 静默计入（否则工具问题会被算成模型失分）
        return {"tool_error": "judge produced no verdict"}
    return v


def evaluate_state(attempted, expected_cells, missing_tasks, summary,
                   expected_tasks=None, expected_samples=None, solve_errors=0):
    """把「尝试完成」与「可比较」拆成两个独立状态。

    只检查 attempted == expected_cells 是不够的：80 格全部环境失败时，
    尝试是齐全的，但两个模式的 scored_tasks 都是 0，官方汇总返回的 0 只是兜底，
    这种结果不能用来比较模型或版本。抽成纯函数是为了能直接测它，
    而不是在测试里重写一遍布尔公式。
    """
    attempts_complete = bool(attempted == expected_cells and not missing_tasks)
    coverage = {}
    incomparable = []
    if not attempts_complete:
        incomparable.append("尝试不齐全")
    if solve_errors:
        incomparable.append('存在服务/传输/响应格式失败（按 L0 保留计分），不能宣称质量协议完整可比')
    for mode in ("agent", "baseline"):
        res = summary.get(mode) or {}
        tasks = res.get("tasks", 0)
        scored = res.get("scored_tasks", 0)
        coverage[mode] = round((scored / tasks) if tasks else 0.0, 4)
        if scored == 0:
            incomparable.append("%s 没有任何有效成绩" % mode)
        elif scored != tasks:
            incomparable.append("%s 有整题未得到有效判分" % mode)
        if res.get("tool_errors", 0):
            incomparable.append("%s 有采样因工具错误被排除" % mode)
        if expected_tasks is not None:
            rows = res.get("per_task", [])
            task_ids = [row.get("task_id") for row in rows]
            if (len(task_ids) != len(expected_tasks)
                    or set(task_ids) != set(expected_tasks)):
                incomparable.append("%s 实际题号与预定清单不一致" % mode)
            if expected_samples is not None and any(
                    row.get("samples") != expected_samples
                    or row.get("scored_samples") != expected_samples
                    for row in rows):
                incomparable.append("%s 每题有效采样数不符合预定协议" % mode)
    if summary.get("agent", {}).get("tasks") != summary.get("baseline", {}).get("tasks"):
        incomparable.append("两种模式的题目数量不一致")
    # 官方仍原样汇总排除工具错误后的成绩；这里更严格的门槛仅用于宣布
    # 预登记的配对实验完整有效，绝不改变官方系数、分母或留存 verdict。
    return dict(attempts_complete=attempts_complete,
                scored_coverage=coverage,
                comparable=not incomparable,
                incomparable_reasons=incomparable)


def exit_code_for(state):
    """退出码策略，供自动消费者区分三种状态。

    0 = 尝试齐全且可比较；2 = 尝试不齐全；3 = 尝试齐全但不可比较。
    此前只有 0/2，于是「80 格全环境失败」会得到 0，被当成可用实验。
    """
    if not state["attempts_complete"]:
        return 2
    if not state["comparable"]:
        return 3
    return 0


def _sha16(path):
    """文件 SHA256 前 16 位；读不到返回 None —— 不猜，也不填占位符。"""
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def trace_span(trace_text):
    """trace.jsonl 里首末两条带 ts 的事件之差（秒）。少于两条则返回 None。

    这是"内部 trace 区间"，与端到端墙钟、判定耗时是三个不同的量，计划要求分列。
    """
    tss = []
    for line in trace_text.splitlines():
        try:
            ts = json.loads(line).get("ts")
        except ValueError:
            continue
        if isinstance(ts, (int, float)):
            tss.append(float(ts))
    return round(max(tss) - min(tss), 2) if len(tss) >= 2 else None


def latency_stats(values):
    """耗时分布（最近秩分位）。**非计分**：等级与得分一律来自官方 summarize()。"""
    xs = sorted(v for v in values if isinstance(v, (int, float)))
    if not xs:
        return dict(n=0, mean=None, p50=None, p95=None, max=None)

    def pct(q):
        return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]

    return dict(n=len(xs), mean=round(sum(xs) / len(xs), 1),
                p50=pct(0.50), p95=pct(0.95), max=xs[-1])


def build_manifest(run_id, args, schedule):
    """冻结本次运行用到的版本与参数。

    计划要求"保存 nonce、参数、版本"。只有哈希能证明两侧跑的是同一份入口/技能/判定器，
    文档里写一句"版本一致"不作数。缺文件时记 None，不编造。
    """
    env_keys = ("RTL_PROFILE", "RTL_REPAIRS", "RTL_MAX_TOKENS", "RTL_TEMPERATURE",
                "MODEL_NAME", "LLM_BASE_URL")
    files = {
        "script": pathlib.Path(__file__).resolve(),
        "official_score": OFFICIAL_SCORE,
        "judge": JUDGE,
        "judge_adapter": KIT / "official_eval.py",
        "veval_judge": KIT / "official_reference/selftest/judge/veval-judge",
        "synth_tcl": KIT / "official_reference/selftest/judge/l3_synth.tcl",
        "upstream_lock": KIT / "official_reference/UPSTREAM.json",
        "runtime": KIT / "submission/agent/runtime.py",
        "baseline": KIT / "submission/baseline.py",
        "manifest_json": KIT / "submission/manifest.json",
        "skill_rtl_generation": KIT / "submission/skill/rtl-generation/SKILL.md",
        "skill_rtl_feedback_repair": KIT / "submission/skill/rtl-feedback-repair/SKILL.md",
    }
    for task in sorted({c['task'] for c in schedule}):
        for path in sorted((TASKS_DIR / task).rglob('*')):
            if path.is_file():
                files['task/' + task + '/' + path.relative_to(TASKS_DIR / task).as_posix()] = path
    return dict(
        run_id=run_id,
        started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        kit=str(KIT),
        tasks=sorted({c["task"] for c in schedule}),
        samples=args.samples, modes=["agent", "baseline"],
        deadline_s=args.deadline, port=args.port, out=str(args.out),
        order="task -> mode -> sample（分块；发第一个请求前先写 schedule.json）",
        params={k: os.environ.get(k) for k in env_keys},
        files={name: dict(path=str(p), sha256_16=_sha16(p)) for name, p in files.items()},
        note="服务启动前冻结；每格请求前及收尾复核。快照一致不证明两个快照之间从未发生改动。",
    )


def manifest_changes(manifest):
    problems = []
    for name, entry in manifest['files'].items():
        current = _sha16(entry['path'])
        if entry['sha256_16'] is None or current != entry['sha256_16']:
            problems.append('file changed or unavailable: ' + name)
    for name, value in manifest['params'].items():
        if os.environ.get(name) != value:
            problems.append('parameter changed: ' + name)
    return problems


def main():
    global TOKEN
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", nargs="*", default=DEFAULT_PICK)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--deadline", type=float, default=300.0)
    ap.add_argument("--port", type=int, default=7867)
    ap.add_argument("--out", type=pathlib.Path,
                    default=pathlib.Path("/workspace/team/runs/fpga_owner/five_sample_quality_20261003"))
    args = ap.parse_args()
    if not args.tasks or len(set(args.tasks)) != len(args.tasks):
        ap.error('tasks must be nonempty and unique')
    if args.samples not in range(1, 6) or not 0 < args.deadline < float('inf'):
        ap.error('samples must be 1..5 and deadline finite and positive')
    if any(not task or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in task)
           for task in args.tasks):
        ap.error('task IDs must contain only ASCII letters, digits, underscores or hyphens')
    require_free_port(args.port)
    load_evaluation().verify_upstream()

    official = load_official_score()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "scratch").mkdir()
    print("官方口径: summarize() 来自 %s" % OFFICIAL_SCORE.name, flush=True)
    print("profile=%s 题数=%d 模式=agent+baseline 每模式 %d 样本"
          % (os.environ.get("RTL_PROFILE", "(unset)"), len(args.tasks), args.samples), flush=True)
    # 本脚本不自己设模型参数，全部继承调用方环境。未导出即"参数不明"，
    # 这类运行不能拿来比较版本，所以先告警——并记进 run_manifest.json 备查。
    unset = [k for k in ("RTL_TEMPERATURE", "RTL_MAX_TOKENS", "MODEL_NAME", "LLM_BASE_URL")
             if not os.environ.get(k)]
    if unset:
        ap.error('model parameters must be explicit: ' + ', '.join(unset))

    # Freeze before starting the service so its loaded runtime matches the snapshot.
    run_id = "%s-%s" % (args.out.name, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    schedule, missing = [], []
    for task in args.tasks:
        if not (TASKS_DIR / task / "prompt.txt").is_file():
            missing.append(task)
            continue
        for mode in ("agent", "baseline"):
            for k in range(args.samples):
                schedule.append(dict(order=len(schedule), task=task, mode=mode, sample=k,
                                     nonce="%s|%s|%s|s%d" % (run_id, task, mode, k)))
    (args.out / "schedule.json").write_text(
        json.dumps(dict(run_id=run_id, order="task -> mode -> sample（分块）",
                        cells=schedule), indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = build_manifest(run_id, args, schedule)
    (args.out / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    changes = manifest_changes(manifest)
    if missing or changes:
        raise RuntimeError('preflight failed: ' + repr(dict(missing_tasks=missing, versions=changes)))

    TOKEN = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env.update(FPGACHINA_TOKEN=TOKEN, PYTHONUTF8="1",
               EDA_TMP=str(args.out / "scratch"), SELFTEST_TMP=str(args.out / "scratch"))
    with open(args.out / 'server.log', 'w', encoding='utf-8') as server_log:
        srv = subprocess.Popen([sys.executable, "-B", str(KIT / "submission/agent/runtime.py"),
                                "serve", "--port", str(args.port)],
                               cwd=str(KIT), env=env, stdout=server_log,
                               stderr=subprocess.STDOUT, start_new_session=True)
    run_status = {'run_id': run_id, 'complete': False, 'comparable': False, 'service_pid': srv.pid}
    try:
        (args.out / 'run_status.json').write_text(json.dumps(run_status, indent=2), encoding='utf-8')
        ok, detail = wait_ready(args.port, process=srv)
        print("就绪:", ok, detail, flush=True)
        if not ok:
            print("服务未就绪，放弃（先查令牌与 ready 条件）", flush=True)
            return 1

        # by_task[mode][task_id] = [verdict, ...]   —— 与官方 collect() 的结构一致
        by_task = {"agent": {}, "baseline": {}}
        # 完整性台账：预期 vs 实际。只比 scored_tasks 与 tasks 会漏掉两种情形：
        #   - 请求了 20 题，其中 1 题不存在 -> 仍显示 19/19，看不出少了
        #   - 某题 5 次采样只有 1 次有效，其余环境失败 -> 仍算"已计分题"
        # 所以按 题目 x 模式 x 采样 逐格记账。
        ledger = dict(expected_tasks=len(args.tasks), missing_tasks=[],
                      expected_cells=len(args.tasks) * 2 * args.samples,
                      attempted=0, empty=0, tool_error=0, graded=0,
                      solve_error=0, judge_error=0)

        # 顺序必须先定后跑，并留下证据。本脚本的顺序是 题 -> 模式 -> 采样 的分块顺序
        # （与原嵌套循环逐个格子完全一致），但顺序表在发第一个请求【之前】写盘，
        # 事后任何重排都会与它对不上。没有这份表，"交错顺序事先固定"只是口头承诺。
        ledger["missing_tasks"] = missing
        for task in missing:
            print("  ⚠ 题目不存在，未评测:", task, flush=True)
        print("先写盘：schedule.json（%d 格，顺序固定）与 run_manifest.json" % len(schedule),
              flush=True)

        for cell in schedule:
            changes = manifest_changes(manifest)
            if changes:
                raise RuntimeError('version changed before request: ' + '; '.join(changes))
            if srv.poll() is not None or not owns_listener(srv.pid, args.port):
                raise RuntimeError('owned service no longer owns the listening port')
            task, mode, k = cell["task"], cell["mode"], cell["sample"]
            task_dir = TASKS_DIR / task
            prompt = (task_dir / "prompt.txt").read_text(encoding="utf-8")
            by_task[mode].setdefault(task, [])
            d = args.out / task / mode / ("s%d" % k)
            d.mkdir(parents=True, exist_ok=False)
            code, payload, el = post_solve(args.port, task, prompt, mode, args.deadline,
                                           nonce=cell["nonce"])
            sol = payload.get("solution") or ""
            (d / "solution.v").write_text(sol, encoding="utf-8")
            (d / "trace.jsonl").write_text(payload.get("trace") or "", encoding="utf-8")
            (d / "response.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            # HTTP/传输/格式失败按契约记 L0 并保留分母，另记 solve_error；
            # 不应冒用授权/题目等判定环境错误的排除规则。
            v = judge_or_tool_error(code, payload.get("error") or payload.get("detail"),
                                    task_dir, d / "solution.v", str(d / "judge"))
            v.setdefault("task_id", task)
            # 逐格留档：端到端墙钟、HTTP 状态、nonce、内部 trace 区间。
            # 判定耗时用判定器自报的 elapsed_s（官方 summarize() 只读这个字段），不覆盖。
            v["e2e_elapsed_s"] = round(el, 2)
            v["http_status"] = code
            v["nonce"] = cell["nonce"]
            span = trace_span(payload.get("trace") or "")
            if span is not None:
                v["trace_span_s"] = span
            (d / 'sample.json').write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
            by_task[mode][task].append(v)
            ledger["attempted"] += 1
            if v.get('solve_error'):
                ledger['solve_error'] += 1
            if v.get("tool_error"):
                ledger["tool_error"] += 1
                ledger["judge_error"] += 1
            else:
                ledger["graded"] += 1
                if not sol.strip() and not v.get('solve_error'):
                    ledger["empty"] += 1
            lv = [s.get("level") for s in by_task[mode][task]]
            te = sum(1 for s in by_task[mode][task] if s.get("tool_error"))
            print("  %-32s %-8s s%d HTTP=%-4s 等级=%-24s 环境失败=%d"
                  % (task, mode, k, code, lv, te), flush=True)

        print()
        print("=== 完整性台账（预期 vs 实际）===")
        print("  预期题数          : %d" % ledger["expected_tasks"])
        print("  题目不存在（未评测）: %d %s"
              % (len(ledger["missing_tasks"]),
                 ledger["missing_tasks"] if ledger["missing_tasks"] else ""))
        print("  预期采样格数      : %d （题 x 2 模式 x %d）"
              % (ledger["expected_cells"], args.samples))
        print("  实际尝试          : %d" % ledger["attempted"])
        print("  有效判分          : %d" % ledger["graded"])
        print("  其中空答案(记 L0) : %d" % ledger["empty"])
        print('  服务/传输失败(L0) : %d（留在计分分母，不重试）' % ledger['solve_error'])
        print("  判定环境失败(排除): %d" % ledger["tool_error"])
        # 残余一：把"尝试完成"与"可比较"分成两个状态（见 evaluate_state）。
        print()
        print("=== 官方 summarize() 的结果 ===")
        summary = {}
        for mode in ("agent", "baseline"):
            res = official.summarize(by_task[mode])
            summary[mode] = res
            print("  %-9s 题集得分(pass@1)=%.4f  pass@5=%.4f  计分题 %d/%d  环境失败 %d"
                  % (mode, res["set_score"], res["pass@5"],
                     res["scored_tasks"], res["tasks"], res["tool_errors"]))
            if res["scored_tasks"] != res["tasks"]:
                print("    ⚠ 该模式有 %d 题无有效成绩"
                      % (res["tasks"] - res["scored_tasks"]))
        a = summary["agent"]["set_score"]
        b = summary["baseline"]["set_score"]
        gain, gscore = official.gain_score(a, b)
        print("  增益 = %s   增益得分(满分线 %.1f) = %.2f"
              % ("%.4f" % gain if gain is not None else "N/A", official.GAIN_FULL_MARK, gscore))

        # 耗时三件套分列（计划要求）：端到端、内部 trace 区间、判定耗时。
        # 这一段**不参与计分**：等级、pass@1、pass@5、增益全部来自官方 summarize()。
        print()
        print("=== 耗时（非计分；等级与得分只来自官方 summarize()）===")
        latency = {}
        for mode in ("agent", "baseline"):
            cells = [s for t in by_task[mode] for s in by_task[mode][t]]
            lat = dict(
                e2e=latency_stats([s.get("e2e_elapsed_s") for s in cells]),
                judge=latency_stats([s.get("elapsed_s") for s in cells
                                     if not s.get("tool_error")]),
                trace_span=latency_stats([s.get("trace_span_s") for s in cells]),
            )
            latency[mode] = lat
            for label, key in (("端到端", "e2e"), ("判定", "judge"), ("trace区间", "trace_span")):
                st = lat[key]
                print("  %-9s %-9s n=%-3d mean=%-8s p50=%-8s p95=%-8s max=%s"
                      % (mode, label, st["n"], st["mean"], st["p50"], st["p95"], st["max"]))

        # 残余一：把"尝试完成"与"可比较"分成两个状态（见 evaluate_state）。
        # 必须放在 summary 之后——它要用计分题数算覆盖比例。
        state = evaluate_state(ledger["attempted"], ledger["expected_cells"],
                               ledger["missing_tasks"], summary,
                               expected_tasks=args.tasks, expected_samples=args.samples,
                               solve_errors=ledger['solve_error'])
        changes = manifest_changes(manifest)
        if changes:
            state['comparable'] = False
            state['incomparable_reasons'].extend(changes)
        attempts_complete = state["attempts_complete"]
        coverage = state["scored_coverage"]
        comparable = state["comparable"]
        incomparable = state["incomparable_reasons"]

        print()
        print("=== 状态（三个分开的标志）===")
        print("  attempts_complete : %s" % attempts_complete)
        print("  scored_coverage   : agent=%.2f  baseline=%.2f（有效成绩覆盖比例）"
              % (coverage["agent"], coverage["baseline"]))
        print("  comparable        : %s" % comparable)
        if incomparable:
            for r in incomparable:
                print("    不可比较原因: %s" % r)
            print("  ★ 尝试齐全但不可比较时，不得用本结果比较模型或版本。")

        # 另起名字的辅助指标：五次中是否出现过 L3
        print()
        print("=== 辅助指标（不叫 pass@5，避免与官方口径混淆）===")
        for mode in ("agent", "baseline"):
            anyl3 = 0
            for t, samples in by_task[mode].items():
                good = [s for s in samples if not s.get("tool_error")]
                if any(s.get("level") == 3 for s in good):
                    anyl3 += 1
            print("  %-9s any_l3（5 次中出现过 L3 的题数）= %d / %d"
                  % (mode, anyl3, len(by_task[mode])))

        (args.out / "quality_official.json").write_text(
            json.dumps(dict(summary=summary, ledger=ledger, latency=latency,
                            run_id=run_id,
                            attempts_complete=attempts_complete,
                            scored_coverage=coverage,
                            comparable=comparable,
                            incomparable_reasons=incomparable),
                       indent=2, ensure_ascii=False), encoding="utf-8")
        (args.out / "by_task.json").write_text(
            json.dumps(by_task, indent=2, ensure_ascii=False), encoding="utf-8")
        print()
        print("说明：空答案按官方口径是 L0（judge.py 写明「空解属于 L0」），留在分母里。")
        print('      服务/传输/响应格式失败也按 API_CONTRACT.md §4 记 L0，不重试。')
        print("      只有判定器环境失败按官方口径单列排除。")
        print("      【更正一处此前的表述】：一道题全为环境失败，并不会让整个题集成绩变成 0；")
        print("      只有【所有题都未计分】时，官方汇总才返回 0 作为兜底。")
        print("      关键是把「无有效成绩」标出来，而不是把兜底的 0 当成真实得分。")
        print("      这是子集评测，不是完整 1560 次协议。")
        # 退出码策略（供自动消费者识别三种状态）：
        #   0 = 尝试齐全 且 可比较
        #   2 = 尝试不齐全
        #   3 = 尝试齐全但不可比较（例如有模式全为环境失败）
        # 此前只有 0/2，于是"80 格全环境失败"会得到 0，被自动消费者当成可用实验。
        run_status.update(complete=attempts_complete, comparable=comparable)
        return exit_code_for(state)
    except Exception as exc:
        run_status['error'] = repr(exc)
        raise
    finally:
        try:
            run_status['final_version_changes'] = manifest_changes(manifest)
            (args.out / 'run_status.json').write_text(
                json.dumps(run_status, indent=2, ensure_ascii=False), encoding='utf-8')
        finally:
            # A failed status write (for example full disk) must not skip cleanup.
            if srv.poll() is None:
                srv.terminate()
                try:
                    srv.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    srv.kill()
                    srv.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
