"""verify_full156.py 的行为测试 —— 不需要 GPU、不需要云端。

为什么单独写
------------
这个脚本的第一版宣称做了六项检查，实际都没做；第二版又因为一个推导式写错，
**把正常成绩全部算成 0**（评审复现：一题 L3 应得 1.0，脚本给 0.0）。
其他脚本的 22 个测试通过，不能替代这个脚本自己的验证。

所以这里用**合成 run 目录**端到端跑脚本，覆盖评审点名的四类实际行为：
  1. 正常成绩（含空答案留在分母、环境失败单列）
  2. 错误技能哈希 —— 必须阻止验收通过
  3. 混用技能 —— 必须阻止"有效对照实验"的结论
  4. 不可比题集 —— 必须给"暂不可判定"，而不是胜出/持平
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bench/verify_full156.py"

VARIANT = "8fb63de303486c9e" + "0" * 48
STABLE = "f4c4c8e2d97ec476" + "0" * 48
RUNTIME = "cea6479c6364fbfc" + "0" * 48
BASELINE = "537783e39db22079" + "0" * 48
UPSTREAM = "afd135e7ba5f6ec4c6d77e7c927c894327537801"


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def make_run(root, tasks_levels, skills=None, samples=1, runtimes=None):
    """tasks_levels: {task: level}（agent）；baseline 一律 L1。

    skills: {task: sha} 指定该题 agent 样本用的技能哈希，默认全部用 VARIANT。
    """
    run = pathlib.Path(root)
    for task, level in tasks_levels.items():
        coeff = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}[level]
        write_json(run / "full/results" / ("agent.%s.s0.json" % task),
                   dict(task_id=task, level=level, coefficient=coeff, tool_error=None, elapsed_s=30.0))
        write_json(run / "full/results" / ("baseline.%s.s0.json" % task),
                   dict(task_id=task, level=1, coefficient=0.2, tool_error=None, elapsed_s=29.0))
        sha = (skills or {}).get(task, VARIANT)
        (run / "full/agent" / task / "s0").mkdir(parents=True, exist_ok=True)
        (run / "full/agent" / task / "s0/trace.jsonl").write_text(
            json.dumps({"ts": 1.0, "tool": "agent_meta", "skill_sha256": sha,
                        "repair_skill_sha256": "a" * 64, "repairs": 0}) + "\n"
            + json.dumps({"ts": 3.5, "tool": "lint", "rc": 0}) + "\n", encoding="utf-8")
        (run / "full/agent" / task / "s0/solution.v").write_text(
            "module TopModule; endmodule\n" if level > 0 else "", encoding="utf-8")
    # 对照 run（旧）
    return run


def make_experiment(run, task_ids, samples=1, submission=None, upstream=UPSTREAM):
    ss = submission if submission is not None else {
        "agent/runtime.py": RUNTIME, "baseline.py": BASELINE}
    write_json(run / "full/experiment.json", dict(
        upstream_commit=upstream, samples=samples, task_ids=sorted(task_ids),
        modes=["agent", "baseline"], submission_sha256=ss))


class HarnessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="verify-behavior-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.new = pathlib.Path(self.tmp) / "new"
        self.old = pathlib.Path(self.tmp) / "old"
        self.skill = pathlib.Path(self.tmp) / "SKILL.md"
        self.skill_sha = self.set_skill("# stable skill\n")

    def set_skill(self, content):
        """写入 SKILL.md 并返回它的真实 SHA-256。

        用 write_bytes 而不是 write_text：后者在 Windows 上会把 \\n 转成 \\r\\n，
        于是"哈希字符串"和"哈希文件"结果不同，测试会永远对不上。
        这里直接哈希落盘后的字节，与脚本读文件的方式一致。
        """
        self.skill.write_bytes(content.encode("utf-8"))
        return hashlib.sha256(self.skill.read_bytes()).hexdigest()

    def run_script(self, extra=()):
        cmd = [sys.executable, str(SCRIPT),
               "--new", str(self.new), "--old", str(self.old),
               "--deployed-skill-file", str(self.skill),
               "--expect-runtime", RUNTIME[:16],
               "--expect-baseline", BASELINE[:16],
               "--expect-generation-skill", self.skill_sha[:16],
               "--variant-skill", VARIANT[:16],
               "--expect-upstream", UPSTREAM] + list(extra)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        p = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", env=env)
        raw = (p.stdout or "") + (p.stderr or "")
        # 把连续空格压成一个，断言就不必数对齐用的空格了
        return p.returncode, raw, re.sub(r"[ \t]+", " ", raw)

    def build_pair(self, new_levels, old_levels, new_skills=None, same_tasks=True):
        make_run(self.new, new_levels, skills=new_skills)
        make_experiment(self.new, new_levels.keys())
        make_run(self.old, old_levels)
        make_experiment(self.old, old_levels.keys())
        # 部署现场：实验已结束，技能已还原（内容变了，哈希随之变）
        self.skill_sha = self.set_skill("# stable skill restored\n")


class NormalScoreTests(HarnessCase):
    """1) 正常成绩：必须算对，不能像第二版那样全变 0。"""

    def test_scores_are_computed_and_not_zero(self):
        # {ProbA: L3, ProbB: L1} -> (1.0 + 0.2)/2 = 0.6；baseline 全 L1 -> 0.2
        self.build_pair({"ProbA": 3, "ProbB": 1}, {"ProbA": 3, "ProbB": 1})
        rc, out, flat = self.run_script()
        self.assertIn("新 agent set=0.6000", flat)
        self.assertIn("新 baseline set=0.2000", flat)
        self.assertNotIn("set=0.0000", out)

    def test_empty_solution_is_l0_and_stays_in_denominator(self):
        # ProbB 的 level=0 且 solution.v 为空 -> 空答案计数应为 1，但仍计入分母
        self.build_pair({"ProbA": 3, "ProbB": 0}, {"ProbA": 3, "ProbB": 0})
        rc, out, flat = self.run_script()
        self.assertIn("新 agent set=0.5000", flat)     # (1.0 + 0.0)/2
        self.assertIn("空 solution 1", flat)

    def test_normal_run_passes(self):
        self.build_pair({"ProbA": 3}, {"ProbA": 3})
        rc, out, flat = self.run_script()
        self.assertEqual(rc, 0, out[-800:])


class SkillGateTests(HarnessCase):
    """2) 错误技能哈希：必须阻止验收通过。"""

    def test_all_wrong_skill_hash_fails_acceptance(self):
        wrong = "deadbeefdeadbeef" + "0" * 48
        self.build_pair({"ProbA": 3}, {"ProbA": 3}, new_skills={"ProbA": wrong})
        rc, out, flat = self.run_script()
        self.assertNotEqual(rc, 0, "技能哈希全错时必须验收失败")
        self.assertIn("不是预定变体", out)

    def test_missing_skill_metadata_fails_acceptance(self):
        self.build_pair({"ProbA": 3}, {"ProbA": 3})
        (self.new / "full/agent/ProbA/s0/trace.jsonl").write_text(
            json.dumps({"ts": 1.0, "tool": "lint", "rc": 0}) + "\n", encoding="utf-8")
        rc, out, flat = self.run_script()
        self.assertNotEqual(rc, 0, "缺 agent_meta 时必须验收失败")
        self.assertIn("缺 agent_meta", out)


class MixedSkillTests(HarnessCase):
    """3) 混用技能：必须阻止"有效对照实验"的结论。"""

    def test_mixed_skills_block_the_experiment_conclusion(self):
        other = "1111222233334444" + "0" * 48
        self.build_pair({"ProbA": 3, "ProbB": 3},
                        {"ProbA": 3, "ProbB": 3},
                        new_skills={"ProbA": VARIANT, "ProbB": other})
        rc, out, flat = self.run_script()
        self.assertNotEqual(rc, 0)
        self.assertIn("不是预定变体", out)
        self.assertIn("有效对照实验", out)


class ComparabilityTests(HarnessCase):
    """4) 不可比题集：必须给"暂不可判定"，不是胜出/持平。"""

    def test_different_task_counts_yield_undecidable(self):
        make_run(self.new, {"ProbA": 3, "ProbB": 3})
        make_experiment(self.new, ["ProbA", "ProbB"])
        make_run(self.old, {"ProbA": 3})
        make_experiment(self.old, ["ProbA"])
        self.skill_sha = self.set_skill("# stable skill restored\n")
        rc, out, flat = self.run_script()
        self.assertIn("暂不可判定", out)
        self.assertIn("两轮评测题数不同", out)
        self.assertNotIn("→ 持平，不采纳", out)

    def test_identical_pairs_are_comparable_and_decide(self):
        self.build_pair({"ProbA": 3}, {"ProbA": 3})
        rc, out, flat = self.run_script()
        self.assertIn("可比: 是", out)
        self.assertIn("→ 持平，不采纳", out)

    def test_a_real_improvement_is_reported_as_a_win(self):
        self.build_pair({"ProbA": 3}, {"ProbA": 1})
        rc, out, flat = self.run_script()
        self.assertIn("可比: 是", out)
        self.assertIn("本轮胜出", out)


class RegressionOnTheExactBugTests(unittest.TestCase):
    """把那个推导式错误本身钉住：形状转换必须真的把 verdict 提出来。"""

    def test_shape_conversion_unwraps_the_sample_dict(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vf_shapes", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        sys.argv = ["x", "--new", "/nonexistent"]
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
        shaped = m.to_official_shape({"A": {0: {"level": 3, "coefficient": 1.0}}})
        self.assertEqual(shaped, {"A": [{"level": 3, "coefficient": 1.0}]})
        # 关键：列表元素必须就是 verdict 本身，而不是再包一层 {idx: verdict}
        self.assertIn("level", shaped["A"][0])

    def test_scores_match_the_official_examples(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vf_scores", SCRIPT)
        m = importlib.util.module_from_spec(spec)
        sys.argv = ["x", "--new", "/nonexistent"]
        try:
            spec.loader.exec_module(m)
        except SystemExit:
            pass
        off = m.load_official_score()

        def score(x):
            return off.summarize(m.to_official_shape(x))["set_score"]

        self.assertAlmostEqual(score({"A": {0: {"task_id": "A", "level": 3, "coefficient": 1.0}}}), 1.0, places=4)
        self.assertAlmostEqual(score({"A": {0: {"task_id": "A", "level": 3, "coefficient": 1.0}},
                                      "B": {0: {"task_id": "B", "level": 1, "coefficient": 0.2}}}), 0.6, places=4)
        mixed = {i: {"task_id": "A", "level": 0, "coefficient": 0.0} for i in range(1, 5)}
        mixed[0] = {"task_id": "A", "level": 3, "coefficient": 1.0}
        self.assertAlmostEqual(score({"A": mixed}), 0.2, places=4)


if __name__ == "__main__":
    unittest.main()
