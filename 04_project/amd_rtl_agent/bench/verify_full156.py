#!/usr/bin/env python3
"""H3 产物验收：逐项核对，并且**与预期值比对**，不是只打印。

评审指出的六处"宣称与实现不一致"，本版逐条改掉
------------------------------------------------
| 宣称 | 第一版实际做法 | 本版 |
|---|---|---|
| 版本哈希 | 找文件打印，无比对；漏了云端实际用的 experiment.json | 读 experiment.json **并与预期比对**；另从每题 trace 的 agent_meta 取**逐样本** skill_sha256 |
| 技能还原 | 没读还原后的 Skill | 实际读部署中的 SKILL.md 并比对 |
| 样本完整性 | 只看两个模式各 156 条 | 严格核对**预期题目清单**与**采样编号**，缺哪题报哪题 |
| 空答案 | 把全部 L0 都算空答案 | **读 solution.v 内容**判断，不看等级 |
| 耗时 | 用 verdict 的 elapsed_s（那是**判定**耗时） | 从 trace 的 ts 跨度算**求解**耗时；判定耗时另列 |
| 验收失败 | 有问题仍返回成功 | **有问题返回非 0** |

数据来源
--------
- `full/results/<mode>.<task>.s<k>.json`  ：官方判定结果（level/coefficient/tool_error/elapsed_s=判定耗时）
- `full/<mode>/<task>/s<k>/trace.jsonl`   ：agent_meta（skill_sha256、repairs）、llm、lint、ts
- `full/<mode>/<task>/s<k>/solution.v`    ：提交的代码（判空答案用）
- `full/experiment.json`                  ：upstream_commit、input_sha256、submission_sha256
"""
import argparse
import json
import pathlib
import statistics
import sys
from collections import Counter

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}


def find_run(path):
    p = pathlib.Path(path)
    if (p / "full" / "results").is_dir():
        return p
    if (p / "results").is_dir():
        return p.parent if (p.parent / "full").is_dir() else p
    return p


def load_results(run):
    """-> {mode: {task: [verdict,...] 按采样编号}}, 以及采样编号集合"""
    out = {"agent": {}, "baseline": {}}
    samples = {"agent": {}, "baseline": {}}
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
        samples[mode].setdefault(task, set()).add(idx)
    return out, samples


def read_trace(run, mode, task, idx):
    p = run / "full" / mode / task / ("s%d" % idx) / "trace.jsonl"
    if not p.is_file():
        p2 = run / mode / task / ("s%d" % idx) / "trace.jsonl"
        if not p2.is_file():
            return None, None
        p = p2
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
    return meta, span


def solution_is_empty(run, mode, task, idx):
    for base in (run / "full", run):
        p = base / mode / task / ("s%d" % idx) / "solution.v"
        if p.is_file():
            return not p.read_text(encoding="utf-8", errors="replace").strip()
    return None      # 文件不在，无法判断——不猜


def summarize(res_by_idx):
    vals = list(res_by_idx.values())
    good = [v for v in vals if not v.get("tool_error")]
    bad = [v for v in vals if v.get("tool_error")]
    if not good:
        return dict(set_score=None, scored=0, total=len(vals), tool_errors=len(bad),
                    levels=Counter(), empty=0)
    coeffs = [v.get("coefficient", COEFF.get(v.get("level", 0), 0.0)) for v in good]
    return dict(set_score=round(statistics.mean(coeffs), 4), scored=len(good),
                total=len(vals), tool_errors=len(bad),
                levels=Counter(v.get("level", 0) for v in good), empty=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", required=True)
    ap.add_argument("--old", default="/workspace/team/runs/fpga_owner/full156_declfix_20261003")
    ap.add_argument("--tasks", default=None, help="预期题目清单文件（每行一个）；省略则用 experiment.json 的 task_ids")
    ap.add_argument("--expect-runtime", default="cea6479c6364fbfc")
    ap.add_argument("--expect-generation-skill", default="f4c4c8e2d97ec476",
                    help="实验结束后现场应有的生成技能哈希（即还原后的稳定版）")
    ap.add_argument("--variant-skill", default="8fb63de303486c9e", help="本轮实验变体，用于说明差异")
    ap.add_argument("--deployed-skill-file",
                    default="/workspace/team/tasks/autodl-rtl-kit/project/submission/skill/rtl-generation/SKILL.md")
    ap.add_argument("--expect-baseline", default="537783e39db22079")
    ap.add_argument("--expect-upstream", default="afd135e7ba5f6ec4c6d77e7c927c894327537801")
    args = ap.parse_args()

    import hashlib

    run = find_run(args.new)
    oldrun = find_run(args.old)
    problems = []
    warnings = []

    print("=" * 70)
    print("H3 产物验收")
    print("=" * 70)
    print("新 : %s" % run)
    print("旧 : %s" % oldrun)
    print()

    new, nsamples = load_results(run)
    old, _ = load_results(oldrun)

    # 预期题目清单
    tasks_path = pathlib.Path(args.tasks) if args.tasks else None
    exp_json = run / "full" / "experiment.json"
    if not exp_json.is_file():
        exp_json = run / "experiment.json"
    exp = {}
    if exp_json.is_file():
        try:
            exp = json.loads(exp_json.read_text(encoding="utf-8"))
        except ValueError:
            exp = {}
    if tasks_path and tasks_path.is_file():
        expected_tasks = [l.strip() for l in tasks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        expected_tasks = exp.get("task_ids", [])
    expected_samples = int(exp.get("samples", 1) or 1)

    # ---------- 1. 样本完整性：严格核对题号与采样编号 ----------
    print("【1】样本完整性（严格核对题号与采样编号）")
    print("  预期题目数 %d，每题采样 %d" % (len(expected_tasks), expected_samples))
    for mode in ("agent", "baseline"):
        got = set(new[mode])
        exp_set = set(expected_tasks)
        missing = sorted(exp_set - got)
        extra = sorted(got - exp_set) if exp_set else []
        bad_idx = sorted(t for t, idxs in nsamples[mode].items()
                         if idxs != set(range(expected_samples)))
        n = sum(len(v) for v in new[mode].values())
        ok = not missing and not extra and not bad_idx and n == len(expected_tasks) * expected_samples
        print("  %-9s 条目 %3d/%d  缺题 %d  多题 %d  采样编号异常 %d  %s"
              % (mode, n, len(expected_tasks) * expected_samples,
                 len(missing), len(extra), len(bad_idx), "OK" if ok else "★ 不完整"))
        if missing:
            print("      缺题: %s" % missing[:8])
            problems.append("%s 缺 %d 题" % (mode, len(missing)))
        if bad_idx:
            print("      采样编号异常: %s" % bad_idx[:8])
            problems.append("%s 采样编号异常 %d 题" % (mode, len(bad_idx)))
        if n != len(expected_tasks) * expected_samples:
            problems.append("%s 条目数 %d != %d" % (mode, n, len(expected_tasks) * expected_samples))

    # ---------- 2. 版本哈希：与预期比对 ----------
    print()
    print("【2】版本哈希（与预期比对，不是只打印）")
    ss = exp.get("submission_sha256", {})
    checks = [
        ("agent/runtime.py", args.expect_runtime, "运行时"),
        ("baseline.py", args.expect_baseline, "裸模型基线"),
    ]
    up = exp.get("upstream_commit", "")
    if up == args.expect_upstream:
        print("  upstream_commit  %s  OK" % up[:16])
    else:
        print("  upstream_commit  %s  ★ 期望 %s" % (up[:16], args.expect_upstream[:16]))
        problems.append("upstream_commit 不匹配")
    for name, want, label in checks:
        got = ss.get(name, "(未记录)")
        mark = "OK" if got.startswith(want) else "★ 期望 %s" % want
        print("  %-18s %s  %s  %s" % (name, got[:16], label, mark))
        if not got.startswith(want):
            problems.append("%s 哈希不匹配" % name)
    if not ss:
        problems.append("experiment.json 里没有 submission_sha256")

    # ---------- 3. 逐样本技能哈希（trace 的 agent_meta） ----------
    print()
    print("【3】逐样本技能哈希（来自每题 trace 的 agent_meta）")
    seen_skills = Counter()
    missing_trace = 0
    for task in sorted(new["agent"]):
        for idx in sorted(new["agent"][task]):
            meta, _span = read_trace(run, "agent", task, idx)
            if not meta:
                missing_trace += 1
                continue
            seen_skills[str(meta.get("skill_sha256"))[:16]] += 1
    if seen_skills:
        for sha, n in seen_skills.most_common():
            tag = ""
            if sha.startswith(args.variant_skill):
                tag = "← 本轮变体"
            elif sha.startswith(args.expect_generation_skill):
                tag = "← 稳定版"
            print("  %s  出现 %d 次  %s" % (sha, n, tag))
        variants = [s for s in seen_skills if s.startswith(args.variant_skill)]
        if len(seen_skills) > 1:
            warnings.append("同一次运行里出现了 %d 种技能哈希——需确认是否中途换过技能" % len(seen_skills))
    if missing_trace:
        print("  ★ 有 %d 个样本读不到 trace" % missing_trace)
        problems.append("%d 个样本缺 trace" % missing_trace)

    # ---------- 4. 技能是否已还原 ----------
    print()
    print("【4】技能还原（读部署中的 SKILL.md 并比对）")
    skf = pathlib.Path(args.deployed_skill_file)
    if skf.is_file():
        got = hashlib.sha256(skf.read_bytes()).hexdigest()
        if got.startswith(args.expect_generation_skill):
            print("  现场 SKILL.md = %s  OK（已还原为稳定版）" % got[:16])
        elif got.startswith(args.variant_skill):
            print("  现场 SKILL.md = %s  ★ 仍是本轮变体，尚未还原" % got[:16])
            problems.append("技能未还原，仍是变体 %s" % got[:16])
        else:
            print("  现场 SKILL.md = %s  ★ 既不是稳定版也不是本轮变体" % got[:16])
            problems.append("技能哈希既非稳定版也非变体: %s" % got[:16])
    else:
        print("  ★ 找不到部署中的 SKILL.md: %s" % skf)
        problems.append("找不到部署中的 SKILL.md")

    # ---------- 5. 空答案：读 solution.v 内容 ----------
    print()
    print("【5】空答案（读 solution.v 内容判断，不按等级推断）")
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
        print("  %-9s 空 solution 文件 %d 个；L0 判定 %d 个；读不到 %d 个" % (mode, empty, l0, unknown))
        if l0 and empty != l0:
            print("      （L0 多于空文件是正常的：代码非空但功能错也会是 L0——上一版把二者混为一谈）")
        if unknown:
            warnings.append("%s 有 %d 个样本读不到 solution.v，空答案数无法定论" % (mode, unknown))

    # ---------- 6. 耗时：trace 跨度（求解）vs elapsed_s（判定） ----------
    print()
    print("【6】耗时（分开报：求解耗时 vs 判定耗时）")
    for mode in ("agent", "baseline"):
        spans, judges = [], []
        for task, by_idx in new[mode].items():
            for idx, v in by_idx.items():
                _meta, span = read_trace(run, mode, task, idx)
                if span is not None:
                    spans.append(span)
                if isinstance(v.get("elapsed_s"), (int, float)):
                    judges.append(v["elapsed_s"])
        if spans:
            s = sorted(spans)
            print("  %-9s 求解耗时 总 %.0fs 均 %.1fs 中位 %.1fs p90 %.1fs max %.1fs（来自 trace ts 跨度）"
                  % (mode, sum(s), statistics.mean(s), statistics.median(s),
                     s[min(len(s) - 1, int(len(s) * 0.9))], s[-1]))
        if judges:
            j = sorted(judges)
            print("  %-9s 判定耗时 总 %.0fs 均 %.1fs 中位 %.1fs（来自 verdict.elapsed_s，非求解耗时）"
                  % (mode, sum(j), statistics.mean(j), statistics.median(j)))

    # ---------- 7. 逐题得失 ----------
    print()
    print("【7】逐题得失（agent）")
    common = sorted(set(new["agent"]) & set(old["agent"]))
    up_list, down_list = [], []
    for t in common:
        a = new["agent"][t].get(0, {})
        b = old["agent"][t].get(0, {})
        ca = a.get("coefficient", COEFF.get(a.get("level", 0), 0.0))
        cb = b.get("coefficient", COEFF.get(b.get("level", 0), 0.0))
        if ca > cb:
            up_list.append((t, b.get("level"), a.get("level"), ca - cb))
        elif ca < cb:
            down_list.append((t, b.get("level"), a.get("level"), ca - cb))
    print("  可比题 %d   上升 %d   下降 %d   持平 %d" % (len(common), len(up_list), len(down_list), len(common) - len(up_list) - len(down_list)))
    for t, lo, ln, d in up_list:
        print("    ↑ %-30s L%s -> L%s  (+%.2f)" % (t, lo, ln, d))
    for t, lo, ln, d in down_list:
        print("    ↓ %-30s L%s -> L%s  (%.2f)" % (t, lo, ln, d))
    print("  agent 系数净变化 = %+.2f" % (sum(d for *_x, d in up_list) + sum(d for *_x, d in down_list)))

    print()
    print("【8】baseline 变化（必须与 agent 分开报告）")
    bcommon = sorted(set(new["baseline"]) & set(old["baseline"]))
    bup, bdown = [], []
    for t in bcommon:
        a = new["baseline"][t].get(0, {})
        b = old["baseline"][t].get(0, {})
        ca = a.get("coefficient", COEFF.get(a.get("level", 0), 0.0))
        cb = b.get("coefficient", COEFF.get(b.get("level", 0), 0.0))
        if ca > cb:
            bup.append(t)
        elif ca < cb:
            bdown.append(t)
    print("  可比题 %d   baseline 上升 %d  下降 %d" % (len(bcommon), len(bup), len(bdown)))
    if bup or bdown:
        print("  ★ 裸模型不读技能，这些变化不能归因于新增规则；也不能把比例当成固定噪声率")
        print("     上升: %s" % bup[:8])
        print("     下降: %s" % bdown[:8])

    # ---------- 9. 成绩与判定 ----------
    print()
    print("【9】成绩与预定标准")
    na, nb = summarize(new["agent"]), summarize(new["baseline"])
    oa, ob = summarize(old["agent"]), summarize(old["baseline"])
    print("  新 agent=%.4f baseline=%.4f" % (na["set_score"] or 0, nb["set_score"] or 0))
    print("  旧 agent=%.4f baseline=%.4f" % (oa["set_score"] or 0, ob["set_score"] or 0))
    d_agent = (na["set_score"] or 0) - (oa["set_score"] or 0)
    print("  agent 变化 = %+.4f" % d_agent)
    if na["total"] != oa["total"]:
        print("  ★ 两轮题数不同（%d vs %d），均分不可直接比较" % (na["total"], oa["total"]))
        warnings.append("两轮题数不同，均分比较无效")
    if d_agent > 0:
        print("  → 本轮胜出（agent %+.4f）" % d_agent)
        print("     但这只说明胜出；『成为默认版本』还需重复验证收益仍在、代价与稳定性可接受")
    elif d_agent == 0:
        print("  → 持平，不采纳")
    else:
        print("  → 未胜出（agent %+.4f），不采纳" % d_agent)

    # ---------- 结论 ----------
    print()
    print("=" * 70)
    if problems:
        print("★ 验收不通过，共 %d 项：" % len(problems))
        for p in problems:
            print("   - %s" % p)
    else:
        print("验收通过：完整性、版本、还原、空答案、耗时均已核对")
    if warnings:
        print("注意（不构成失败，但影响解读）：")
        for w in warnings:
            print("   - %s" % w)
    print("=" * 70)

    out = run / "verification.json"
    try:
        out.write_text(json.dumps(dict(
            problems=problems, warnings=warnings,
            agent_up=[list(x) for x in up_list], agent_down=[list(x) for x in down_list],
            baseline_up=bup, baseline_down=bdown,
            new_agent=na["set_score"], old_agent=oa["set_score"],
            new_baseline=nb["set_score"], old_baseline=ob["set_score"],
            delta_agent=d_agent, skills_seen=dict(seen_skills)), indent=2, ensure_ascii=False),
            encoding="utf-8")
        print("明细已写出:", out)
    except OSError as exc:
        print("写出明细失败:", exc)

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
