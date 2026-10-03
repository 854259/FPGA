#!/usr/bin/env python3
"""H3 产物验收：逐项核对并与预期比对，**成绩一律走官方汇总函数**。

第二版被评审否掉的原因（本版逐条改掉）
--------------------------------------
| 问题 | 第二版实际做法 | 本版 |
|---|---|---|
| **成绩算错** | 自己实现汇总，且把"采样编号→verdict 的字典"当成 verdict，读不到 level/coefficient，**全部按 0 计**；环境失败也数不出来 | 转成官方要的"题目→verdict 列表"，**直接调用官方 `score.summarize()`** |
| 技能哈希只是统计 | 打印观察到的哈希，全错/混用都不阻止通过 | **作为通过条件**：每个预期 agent 样本都必须有元数据且哈希等于预先固定的变体 |
| 把 trace 跨度叫"真实求解耗时" | 夸大 | 改称**"已记录执行区间"**；baseline 往往只有一个带 ts 的事件，另报 `llm.sec` |
| 不可比仍给胜负 | 只加 warning，继续打印"胜出/持平" | **不可比 → 只报共同题目变化，结论写"暂不可判定"** |

数据来源
--------
- `full/results/<mode>.<task>.s<k>.json`：官方判定结果
- `full/<mode>/<task>/s<k>/trace.jsonl`：agent_meta（skill_sha256、repairs）、llm（含 sec）、lint、ts
- `full/<mode>/<task>/s<k>/solution.v`：提交代码（判空答案）
- `full/experiment.json`：upstream_commit、input_sha256、submission_sha256
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import statistics
import sys
from collections import Counter

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}
KIT_CANDIDATES = [
    pathlib.Path("/workspace/team/tasks/autodl-rtl-kit/project"),
    pathlib.Path(__file__).resolve().parents[1],
]


def script_identity():
    """本脚本自身的 SHA-256。

    为什么要写进结果：曾经发生过"本地已修好、实例上跑的仍是旧版"，
    于是同一份产物由不同版本的脚本得出不同结论（成绩被算成全 0）。
    把执行者的哈希钉进输出与 verification.json，事后才能判断"这次验收是谁跑的"。
    本地测试通过与远端使用正确版本，是两件需要分别证明的事。
    """
    try:
        return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return "(unavailable)"


def load_official_score():
    """官方汇总函数。绝不自己重写统计口径。"""
    for kit in KIT_CANDIDATES:
        p = kit / "official_reference" / "selftest" / "score.py"
        if p.is_file():
            spec = importlib.util.spec_from_file_location("official_score_verify", p)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except SystemExit:
                pass
            if hasattr(module, "summarize"):
                return module
    raise RuntimeError("找不到官方 score.py 的 summarize()")


def to_official_shape(by_idx):
    """{task: {idx: verdict}} -> {task: [verdict, ...]}，与官方 collect() 结构一致。

    这里曾经写错过一次，代价是成绩全按 0 算：
        {task: [by_idx[i] for i in sorted(by_idx)] for task in sorted(by_idx)}
    内层用外层键索引，于是 by_idx['ProbA'] 取回整张 {idx: verdict} 字典，
    等于把"采样编号 -> verdict"又多包了一层，官方 summarize 读不到 level 就按 0 计。
    正确写法是内外两层各自遍历自己的键。
    """
    return {task: [by_idx[task][i] for i in sorted(by_idx[task])]
            for task in sorted(by_idx)}


def find_run(path):
    p = pathlib.Path(path)
    if (p / "full" / "results").is_dir():
        return p
    if (p / "results").is_dir():
        return p.parent if (p.parent / "full").is_dir() else p
    return p


def load_results(run):
    """-> ({mode: {task: {idx: verdict}}}, {mode: {task: set(idx)}})"""
    out = {"agent": {}, "baseline": {}}
    idxs = {"agent": {}, "baseline": {}}
    rdir = run / "full" / "results"
    if not rdir.is_dir():
        rdir = run / "results"
    for f in sorted(rdir.glob("*.json")):
        parts = f.name.split(".")
        if len(parts) < 4:
            continue
        mode, task, sk = parts[0], parts[1], parts[2]
        if mode not in out:
            continue
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        idx = int(sk[1:]) if sk.startswith("s") and sk[1:].isdigit() else 0
        out[mode].setdefault(task, {})[idx] = v
        idxs[mode].setdefault(task, set()).add(idx)
    return out, idxs


def read_trace(run, mode, task, idx):
    """-> (meta, recorded_window_seconds, llm_seconds, n_ts_events)"""
    for base in (run / "full", run):
        p = base / mode / task / ("s%d" % idx) / "trace.jsonl"
        if p.is_file():
            break
    else:
        return None, None, None, 0
    events = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    meta = next((e for e in events if e.get("tool") == "agent_meta"), None)
    ts = [e["ts"] for e in events if isinstance(e.get("ts"), (int, float))]
    span = (max(ts) - min(ts)) if len(ts) >= 2 else None
    llm = [e.get("sec") for e in events
           if e.get("tool") == "llm" and isinstance(e.get("sec"), (int, float))]
    return meta, span, (sum(llm) if llm else None), len(ts)


def solution_is_empty(run, mode, task, idx):
    for base in (run / "full", run):
        p = base / mode / task / ("s%d" % idx) / "solution.v"
        if p.is_file():
            return not p.read_text(encoding="utf-8", errors="replace").strip()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old", default="/workspace/team/runs/fpga_owner/full156_declfix_20261003")
    ap.add_argument("--tasks", default=None, help="预期题目清单；省略则用 experiment.json 的 task_ids")
    ap.add_argument("--expect-runtime", default="cea6479c6364fbfc")
    ap.add_argument("--expect-generation-skill", default="f4c4c8e2d97ec476",
                    help="实验结束后现场应有的生成技能哈希（还原后的稳定版）")
    ap.add_argument("--variant-skill", default="8fb63de303486c9e",
                    help="本轮实验【预先固定】的变体哈希；agent 样本必须全部等于它")
    ap.add_argument("--deployed-skill-file",
                    default="/workspace/team/tasks/autodl-rtl-kit/project/submission/skill/rtl-generation/SKILL.md")
    ap.add_argument("--expect-baseline", default="537783e39db22079")
    ap.add_argument("--expect-upstream", default="afd135e7ba5f6ec4c6d77e7c927c894327537801")
    args = ap.parse_args()

    official = load_official_score()
    run, oldrun = find_run(args.new), find_run(args.old)
    problems, warnings = [], []

    print("=" * 70)
    print("H3 产物验收（成绩走官方 summarize）")
    print("=" * 70)
    printable_sha = script_identity()
    print("执行脚本 sha256: %s" % printable_sha)
    print("  （写进结果是为了区分「本地测试通过」与「远端确实用了这一版」）")
    print("新 : %s" % run)
    print("旧 : %s" % oldrun)
    print()

    new, nidx = load_results(run)
    old, _oidx = load_results(oldrun)

    exp_json = run / "full" / "experiment.json"
    if not exp_json.is_file():
        exp_json = run / "experiment.json"
    exp = {}
    if exp_json.is_file():
        try:
            exp = json.loads(exp_json.read_text(encoding="utf-8"))
        except ValueError:
            exp = {}

    tasks_path = pathlib.Path(args.tasks) if args.tasks else None
    if tasks_path and tasks_path.is_file():
        expected = [l.strip() for l in tasks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        expected = exp.get("task_ids", [])
    exp_samples = int(exp.get("samples", 1) or 1)

    # ---------- 1. 完整性 ----------
    print("【1】样本完整性（严格核对题号与采样编号）")
    print("  预期题目 %d 题，每题采样 %d" % (len(expected), exp_samples))
    complete = {}
    for mode in ("agent", "baseline"):
        got, exp_set = set(new[mode]), set(expected)
        missing = sorted(exp_set - got)
        extra = sorted(got - exp_set) if exp_set else []
        bad_idx = sorted(t for t, s in nidx[mode].items() if s != set(range(exp_samples)))
        n = sum(len(v) for v in new[mode].values())
        want = len(expected) * exp_samples if expected else n
        ok = not missing and not extra and not bad_idx and n == want
        complete[mode] = bool(ok)
        print("  %-9s 条目 %3d/%d  缺题 %d  多题 %d  采样编号异常 %d  %s"
              % (mode, n, want, len(missing), len(extra), len(bad_idx), "OK" if ok else "★ 不完整"))
        if missing:
            print("      缺: %s" % missing[:8])
        if not ok:
            problems.append("%s 样本不完整（缺题 %d，编号异常 %d，条目 %d/%d）"
                            % (mode, len(missing), len(bad_idx), n, want))

    # ---------- 2. 版本哈希 ----------
    print()
    print("【2】版本哈希（与预期比对）")
    ss = exp.get("submission_sha256", {})
    up = exp.get("upstream_commit", "")
    if up == args.expect_upstream:
        print("  upstream_commit  %s  OK" % up[:16])
    else:
        print("  upstream_commit  %s  ★ 期望 %s" % (up[:16], args.expect_upstream[:16]))
        problems.append("upstream_commit 不匹配")
    for name, want, label in (("agent/runtime.py", args.expect_runtime, "运行时"),
                              ("baseline.py", args.expect_baseline, "裸模型基线")):
        got = ss.get(name, "(未记录)")
        print("  %-18s %s  %s  %s" % (name, got[:16], label,
                                      "OK" if got.startswith(want) else "★ 期望 %s" % want))
        if not got.startswith(want):
            problems.append("%s 哈希不匹配" % name)
    if not ss:
        problems.append("experiment.json 里没有 submission_sha256")

    # ---------- 3. 逐样本技能哈希：通过条件 ----------
    print()
    print("【3】逐样本技能哈希（通过条件，不只是统计）")
    seen = Counter()
    n_agent_samples = sum(len(v) for v in new["agent"].values())
    n_with_meta = n_variant = n_other = 0
    other_examples = []
    for task in sorted(new["agent"]):
        for idx in sorted(new["agent"][task]):
            meta, _s, _l, _n = read_trace(run, "agent", task, idx)
            sha = str((meta or {}).get("skill_sha256", ""))[:16]
            if not sha:
                continue
            n_with_meta += 1
            seen[sha] += 1
            if sha.startswith(args.variant_skill):
                n_variant += 1
            else:
                n_other += 1
                if len(other_examples) < 5:
                    other_examples.append("%s.s%d=%s" % (task, idx, sha))
    print("  agent 样本 %d，其中有元数据 %d，等于预定变体 %s… 的 %d，其它 %d"
          % (n_agent_samples, n_with_meta, args.variant_skill[:8], n_variant, n_other))
    for sha, n in seen.most_common(6):
        print("    %s  ×%d" % (sha, n))
    if n_with_meta != n_agent_samples:
        print("  ★ 有 %d 个 agent 样本缺元数据" % (n_agent_samples - n_with_meta))
        problems.append("%d 个 agent 样本缺 agent_meta" % (n_agent_samples - n_with_meta))
    if n_other:
        print("  ★ 有 %d 个样本用了非预定技能: %s" % (n_other, other_examples))
        problems.append("%d 个 agent 样本的生成技能不是预定变体" % n_other)
    if n_variant != n_agent_samples:
        print("  → 本轮的『有效对照实验』结论不成立")

    # ---------- 4. 技能还原 ----------
    print()
    print("【4】技能还原（读部署中的 SKILL.md）")
    skf = pathlib.Path(args.deployed_skill_file)
    if skf.is_file():
        got = hashlib.sha256(skf.read_bytes()).hexdigest()
        if got.startswith(args.expect_generation_skill):
            print("  现场 SKILL.md = %s  OK（已还原）" % got[:16])
        elif got.startswith(args.variant_skill):
            print("  现场 SKILL.md = %s  ★ 仍是变体，未还原" % got[:16])
            problems.append("技能未还原")
        else:
            print("  现场 SKILL.md = %s  ★ 既非稳定版也非变体" % got[:16])
            problems.append("技能哈希异常: %s" % got[:16])
    else:
        print("  ★ 找不到 %s" % skf)
        problems.append("找不到部署中的 SKILL.md")

    # ---------- 5. 空答案 ----------
    print()
    print("【5】空答案（读 solution.v 内容）")
    for mode in ("agent", "baseline"):
        empty = unknown = 0
        for task, by_idx in new[mode].items():
            for idx in by_idx:
                e = solution_is_empty(run, mode, task, idx)
                if e is None:
                    unknown += 1
                elif e:
                    empty += 1
        l0 = sum(1 for by_idx in new[mode].values() for v in by_idx.values()
                 if v.get("level", 0) == 0 and not v.get("tool_error"))
        print("  %-9s 空 solution %d；L0 判定 %d；读不到 %d" % (mode, empty, l0, unknown))
        if unknown:
            warnings.append("%s 有 %d 个样本读不到 solution.v" % (mode, unknown))

    # ---------- 6. 时间 ----------
    print()
    print("【6】耗时（区分已记录执行区间 / 模型请求 / 判定）")
    for mode in ("agent", "baseline"):
        spans, llms, judges, single = [], [], [], 0
        for task, by_idx in new[mode].items():
            for idx, v in by_idx.items():
                _m, span, llm, nts = read_trace(run, mode, task, idx)
                if span is not None:
                    spans.append(span)
                elif nts == 1:
                    single += 1
                if llm is not None:
                    llms.append(llm)
                if isinstance(v.get("elapsed_s"), (int, float)):
                    judges.append(v["elapsed_s"])
        if spans:
            print("  %-9s 已记录执行区间(trace 首末 ts) n=%d 均 %.1fs 中位 %.1fs max %.1fs"
                  % (mode, len(spans), statistics.mean(spans), statistics.median(spans), max(spans)))
        else:
            print("  %-9s 已记录执行区间：不可得" % mode)
        if single:
            print("            其中 %d 个样本只有 1 个带 ts 的事件，无法求区间" % single)
        if llms:
            print("            模型请求耗时(llm.sec 合计) 均 %.1fs 中位 %.1fs"
                  % (statistics.mean(llms), statistics.median(llms)))
        if judges:
            print("            判定耗时(verdict.elapsed_s) 均 %.1fs（**非求解耗时**）"
                  % statistics.mean(judges))

    # ---------- 7. 官方成绩 ----------
    print()
    print("【7】成绩（官方 summarize）")
    res = {m: official.summarize(to_official_shape(new[m])) for m in ("agent", "baseline")}
    oldres = {m: official.summarize(to_official_shape(old[m])) for m in ("agent", "baseline")}
    for mode in ("agent", "baseline"):
        r = res[mode]
        print("  新 %-9s set=%.4f pass@5=%.4f 计分题 %d/%d 环境失败 %d"
              % (mode, r["set_score"], r["pass@5"], r["scored_tasks"], r["tasks"], r["tool_errors"]))
    for mode in ("agent", "baseline"):
        r = oldres[mode]
        print("  旧 %-9s set=%.4f pass@5=%.4f 计分题 %d/%d 环境失败 %d"
              % (mode, r["set_score"], r["pass@5"], r["scored_tasks"], r["tasks"], r["tool_errors"]))

    # ---------- 8. 可比性门槛 ----------
    print()
    print("【8】可比性门槛")
    comparable = True
    reasons = []
    if not all(complete.values()):
        comparable = False
        reasons.append("样本不完整")
    if res["agent"]["tasks"] != oldres["agent"]["tasks"]:
        comparable = False
        reasons.append("两轮评测题数不同（%d vs %d）" % (res["agent"]["tasks"], oldres["agent"]["tasks"]))
    if n_variant != n_agent_samples:
        comparable = False
        reasons.append("本轮 agent 样本并非全部使用预定技能")
    common = sorted(set(new["agent"]) & set(old["agent"]))
    if len(common) != res["agent"]["tasks"]:
        # 这里曾经只 append 原因、忘了置 False，于是"新题 ProbA、旧题 ProbB"
        # 这种题目完全不同的对照会被判成"可比：是"并宣布胜出。
        comparable = False
        reasons.append("共同题目 %d 少于本轮题数 %d（题目集合不同）"
                       % (len(common), res["agent"]["tasks"]))
    if res["agent"]["scored_tasks"] != res["agent"]["tasks"] or \
            oldres["agent"]["scored_tasks"] != oldres["agent"]["tasks"]:
        comparable = False
        reasons.append("有题无有效成绩（环境失败）")
    print("  可比: %s" % ("是" if comparable else "否"))
    for r in reasons:
        print("    - %s" % r)

    # 胜负判定的前置条件 = 可比 且 无验收问题（版本/技能/还原等）。
    # 两块失败条件必须共享，否则会出现"先宣布胜出、最后才报版本错误"的矛盾报告。
    verdict_allowed = comparable and not problems

    # ---------- 9. 共同题目变化 ----------
    up_list, down_list = [], []
    for t in common:
        a, b = new["agent"][t].get(0, {}), old["agent"][t].get(0, {})
        ca = a.get("coefficient", COEFF.get(a.get("level", 0), 0.0))
        cb = b.get("coefficient", COEFF.get(b.get("level", 0), 0.0))
        if ca > cb:
            up_list.append((t, b.get("level"), a.get("level"), ca - cb))
        elif ca < cb:
            down_list.append((t, b.get("level"), a.get("level"), ca - cb))
    print()
    print("【9】共同题目上的逐题变化（%d 题）" % len(common))
    print("  上升 %d   下降 %d   持平 %d" % (len(up_list), len(down_list),
                                          len(common) - len(up_list) - len(down_list)))
    for t, lo, ln, d in up_list:
        print("    ↑ %-30s L%s -> L%s (+%.2f)" % (t, lo, ln, d))
    for t, lo, ln, d in down_list:
        print("    ↓ %-30s L%s -> L%s (%.2f)" % (t, lo, ln, d))
    delta_common = sum(x[3] for x in up_list) + sum(x[3] for x in down_list)
    print("  共同题目系数净变化 = %+.2f（%d 题）" % (delta_common, len(common)))

    print()
    print("【10】结论")
    if not verdict_allowed:
        print("  ★ 暂不可判定 —— 不满足判定条件：")
        if not comparable:
            print("    [可比性]")
            for r in reasons:
                print("       - %s" % r)
        if problems:
            print("    [验收]")
            for p in problems:
                print("       - %s" % p)
        print("  共同题目上的变化可以报告，但不能据此宣布胜出或退步。")
    else:
        d = res["agent"]["set_score"] - oldres["agent"]["set_score"]
        print("  agent 变化 = %+.4f" % d)
        if d > 0:
            print("  → 本轮胜出。但这只说明胜出；『成为默认版本』还需重复验证收益仍在、代价与稳定性可接受")
        elif d == 0:
            print("  → 持平，不采纳")
        else:
            print("  → 未胜出，不采纳")

    print()
    print("=" * 70)
    if problems:
        print("★ 验收不通过，共 %d 项：" % len(problems))
        for p in problems:
            print("   - %s" % p)
    else:
        print("验收通过：完整性、版本、技能、空答案、耗时均已核对")
    if warnings:
        print("注意（不构成失败，但影响解读）：")
        for w in warnings:
            print("   - %s" % w)
    print("=" * 70)

    try:
        (run / "verification.json").write_text(json.dumps(dict(
            verifier_sha256=script_identity(),
            problems=problems, warnings=warnings, comparable=comparable, reasons=reasons,
            agent_up=[list(x) for x in up_list], agent_down=[list(x) for x in down_list],
            common_tasks=len(common), delta_common=delta_common,
            new=res, old=oldres, skills_seen=dict(seen),
            n_agent_samples=n_agent_samples, n_variant=n_variant), indent=2, ensure_ascii=False),
            encoding="utf-8")
    except OSError as exc:
        print("写出明细失败:", exc)

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
