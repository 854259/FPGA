"""五样本统计口径的回归测试 —— 不需要 GPU、不需要模型。

为什么需要
----------
我自己写的第二版质量评测把两处统计算错了，评审给出的反例在官方函数上核对过：

    1xL3 + 4x空答  ->  官方 pass@1 = 0.2   （我算成 1.0，因为把空答案排出了分母）
    5xL2           ->  官方 pass@5 = 0.7   （我算成 0，因为我按"是否出现 L3"判）

所以现在**不再自己算**，而是把判定器的 verdict 交给官方 `score.summarize()`。
本文件把官方口径**钉成测试**：哪天有人改了统计方式，这里会立刻红。

另一件事：缺判定结果必须表现为"环境失败"而不是静默当成 L0——
否则工具问题会被算成模型失分，把成绩做低而不自知。
"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SCORE = ROOT / "official_reference/selftest/score.py"
QUALITY = ROOT / "bench/five_sample_quality.py"

COEFF = {0: 0.0, 1: 0.2, 2: 0.7, 3: 1.0}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(value)
    except SystemExit:
        pass
    return value


official = load("official_score_pinned", OFFICIAL_SCORE)
quality = load("five_sample_quality", QUALITY)


def sample(level, tool_error=None):
    s = {"task_id": "t", "level": level, "coefficient": COEFF[level]}
    if tool_error:
        s["tool_error"] = tool_error
    return s


class OfficialConventionTests(unittest.TestCase):
    """把官方口径钉死，防止有人"顺手改一改"统计方式。"""

    def test_empty_solution_counts_as_l0_and_stays_in_the_denominator(self):
        # 1 次 L3 + 4 次空答（空答 = level 0），pass@1 必须是 0.2 而不是 1.0
        r = official.summarize({"t": [sample(3), sample(0), sample(0), sample(0), sample(0)]})
        self.assertAlmostEqual(r["pass@1"], 0.2, places=4)
        self.assertAlmostEqual(r["set_score"], 0.2, places=4)
        self.assertAlmostEqual(r["pass@5"], 1.0, places=4)

    def test_pass_at_5_is_the_best_coefficient_not_an_l3_flag(self):
        # 5 次都是 L2：pass@5 必须是 0.7，不是 0
        r = official.summarize({"t": [sample(2)] * 5})
        self.assertAlmostEqual(r["pass@5"], 0.7, places=4)
        self.assertAlmostEqual(r["pass@1"], 0.7, places=4)

    def test_mixed_levels(self):
        r = official.summarize({"t": [sample(1), sample(3), sample(0), sample(2), sample(1)]})
        mean = (0.2 + 1.0 + 0.0 + 0.7 + 0.2) / 5
        self.assertAlmostEqual(r["pass@1"], round(mean, 4), places=4)
        self.assertAlmostEqual(r["pass@5"], 1.0, places=4)

    def test_tool_error_samples_are_excluded_from_the_mean(self):
        r = official.summarize({"t": [sample(3), sample(1, tool_error="LICENSE_ERROR")]})
        # 环境失败被排除，均值只由留下的那个 L3 决定
        self.assertAlmostEqual(r["pass@1"], 1.0, places=4)
        self.assertEqual(r["tool_errors"], 1)
        self.assertEqual(r["per_task"][0]["excluded_samples"], 1)

    def test_all_tool_errors_marks_the_task_unscored(self):
        r = official.summarize({"t": [sample(0, tool_error="X"), sample(0, tool_error="Y")]})
        self.assertEqual(r["scored_tasks"], 0)
        self.assertEqual(r["tool_errors"], 2)
        # 官方注释说该题不计入题集得分；算术上却是 0.0。
        # 这里只钉住"scored_tasks 会暴露不完整"这一点，不改官方行为。
        self.assertNotEqual(r["scored_tasks"], r["tasks"])

    def test_gain_score_matches_the_documented_formula(self):
        import math
        gain, score = official.gain_score(2.0, 1.0)
        self.assertAlmostEqual(gain, 2.0, places=6)
        self.assertAlmostEqual(score, 40.0 * math.log(2.0) / math.log(official.GAIN_FULL_MARK), places=4)

    def test_gain_score_is_zero_when_not_better(self):
        gain, score = official.gain_score(0.9, 1.0)
        self.assertAlmostEqual(gain, 0.9, places=6)
        self.assertEqual(score, 0.0)


class HarnessWiringTests(unittest.TestCase):
    """我自己脚本的接线：必须复用官方函数，且缺结果不能静默当 L0。"""

    def test_script_loads_the_official_summarize(self):
        module = quality.load_official_score()
        self.assertTrue(hasattr(module, "summarize"))
        self.assertIsNotNone(module.summarize)

    def test_script_does_not_reimplement_the_statistics(self):
        """脚本里不该再出现自己的系数求和 / max 逻辑。"""
        text = QUALITY.read_text(encoding="utf-8")
        self.assertIn("official.summarize", text)
        # 旧版用过这些名字做自算，出现了就说明又开始自己算了
        self.assertNotIn("statistics.mean(COEFF", text)
        self.assertNotIn("pass_at_1=", text)

    def test_missing_verdict_becomes_a_tool_error_not_a_silent_l0(self):
        """判定没产出结果时，脚本把它标成 tool_error；官方汇总会单列，不拉低均分。"""
        text = QUALITY.read_text(encoding="utf-8")
        self.assertIn("tool_error", text)
        self.assertIn("judge produced no verdict", text)
        # 反证：如果缺结果被当成 L0，就会看到显式构造 level 0 的兜底
        self.assertNotIn('{"task_id": task, "level": 0}', text)

    def test_reports_incompleteness(self):
        """必须把 scored_tasks 与 tasks 一起报，否则"评测不完整"会被静默吞掉。"""
        text = QUALITY.read_text(encoding="utf-8")
        self.assertIn("scored_tasks", text)
        self.assertIn("评测不完整", text)


if __name__ == "__main__":
    unittest.main()
