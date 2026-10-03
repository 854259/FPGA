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
import os
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_SCORE = ROOT / "official_reference/selftest/score.py"
QUALITY = ROOT / "bench/five_sample_quality.py"
ENDURANCE = ROOT / "bench/http_endurance.py"

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


class JudgeInvocationTests(unittest.TestCase):
    """Quality runs delegate to the single evidence-preserving judge adapter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.solution = self.root / 'solution.v'
        self.solution.write_text('module TopModule; endmodule\n', encoding='utf-8')
        self.adapter = mock.Mock()
        self.patch = mock.patch.object(quality, 'load_evaluation', return_value=self.adapter)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_missing_judge_stops_the_batch_instead_of_inventing_l0(self):
        self.adapter.judge_sample.side_effect = RuntimeError('judge produced no verdict')
        with self.assertRaises(RuntimeError):
            quality.run_judge(self.root, self.solution, self.root / 'judge')

    def test_stale_verdict_is_preserved_and_the_run_is_rejected(self):
        outdir = self.root / 'judge'
        outdir.mkdir()
        stale = outdir / 'verdict.json'
        stale.write_text('{"level":3}', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            quality.run_judge(self.root, self.solution, outdir)
        self.adapter.judge_sample.assert_not_called()
        self.assertEqual(stale.read_text(), '{"level":3}')

    def test_unreadable_verdict_failure_is_not_swallowed(self):
        self.adapter.judge_sample.side_effect = RuntimeError('unreadable verdict')
        with self.assertRaisesRegex(RuntimeError, 'unreadable'):
            quality.run_judge(self.root, self.solution, self.root / 'judge')

    def test_official_tool_error_is_returned_unchanged(self):
        result = {'task_id': 't', 'level': 0, 'coefficient': 0, 'tool_error': 'LICENSE_ERROR'}
        self.adapter.judge_sample.return_value = result
        self.assertIs(quality.run_judge(self.root, self.solution, self.root / 'judge'), result)


class CompletenessLedgerTests(unittest.TestCase):
    """完整性台账：预期 vs 实际，缺题目/缺采样都要看得出来。"""

    def test_ledger_counts_missing_tasks(self):
        ledger = dict(expected_tasks=3, missing_tasks=["ProbNope"],
                      expected_cells=3 * 2 * 5, attempted=2 * 2 * 5,
                      empty=0, tool_error=0, graded=20)
        complete = (ledger["attempted"] == ledger["expected_cells"]
                    and not ledger["missing_tasks"])
        self.assertFalse(complete)                  # 少了一题，不能算完整

    def test_ledger_flags_short_sampling(self):
        # 题都在，但总采样数不足（例如中途中断），也必须算不完整
        ledger = dict(expected_tasks=2, missing_tasks=[],
                      expected_cells=2 * 2 * 5, attempted=2 * 2 * 3,
                      empty=0, tool_error=0, graded=12)
        complete = (ledger["attempted"] == ledger["expected_cells"]
                    and not ledger["missing_tasks"])
        self.assertFalse(complete)

    def test_ledger_complete_only_when_everything_ran(self):
        ledger = dict(expected_tasks=2, missing_tasks=[],
                      expected_cells=2 * 2 * 5, attempted=20,
                      empty=0, tool_error=0, graded=20)
        complete = (ledger["attempted"] == ledger["expected_cells"]
                    and not ledger["missing_tasks"])
        self.assertTrue(complete)

    def test_script_reports_the_whole_ledger(self):
        text = QUALITY.read_text(encoding="utf-8")
        for field in ("expected_tasks", "missing_tasks", "expected_cells",
                      "attempted", "tool_error", "graded", "complete"):
            self.assertIn(field, text)


class EnduranceAssertionTests(unittest.TestCase):
    """耐久测试的并发断言不能在 codes 含 None 时抛异常。"""

    def test_none_in_codes_does_not_raise_and_fails(self):
        codes = [200, None, 200]
        # 旧写法 sorted(codes) 在 Python 3 里会因 None 与 int 不可比而抛 TypeError
        with self.assertRaises(TypeError):
            sorted(codes)
        ok = len(codes) == 3 and all(c == 200 for c in codes)
        self.assertFalse(ok)

    def test_all_200_passes(self):
        codes = [200, 200, 200]
        self.assertTrue(len(codes) == 3 and all(c == 200 for c in codes))

    def test_script_uses_all_not_sorted(self):
        """只检查代码行，不看注释——注释里提到旧写法是允许的（那是解释）。"""
        lines = [ln for ln in ENDURANCE.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        code = "\n".join(lines)
        self.assertIn("all(c == 200 for c in codes)", code)
        self.assertNotIn("sorted(codes)", code)


class JudgeNonZeroExitTests(unittest.TestCase):
    """The shared adapter's failure and evidence survive the quality wrapper."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.solution = self.root / 'solution.v'
        self.solution.write_text('module TopModule; endmodule\n', encoding='utf-8')
        self.adapter = mock.Mock()
        patch = mock.patch.object(quality, 'load_evaluation', return_value=self.adapter)
        patch.start()
        self.addCleanup(patch.stop)

    def failed_adapter(self, task, solution, dst, verdict, deadline):
        (dst / 'judge_receipt.json').write_text('{"judge_rc":1}', encoding='utf-8')
        (dst / 'raw.json').write_text('{"level":3}', encoding='utf-8')
        raise RuntimeError('judge did not exit successfully')

    def test_valid_verdict_with_nonzero_exit_stops_the_batch(self):
        self.adapter.judge_sample.side_effect = self.failed_adapter
        with self.assertRaises(RuntimeError):
            quality.run_judge(self.root, self.solution, self.root / 'judge')

    def test_the_shared_raw_verdict_and_receipt_are_not_removed(self):
        self.adapter.judge_sample.side_effect = self.failed_adapter
        out = self.root / 'judge'
        with self.assertRaises(RuntimeError):
            quality.run_judge(self.root, self.solution, out)
        self.assertEqual((out / 'judge_receipt.json').read_text(), '{"judge_rc":1}')
        self.assertEqual((out / 'raw.json').read_text(), '{"level":3}')

    def test_zero_exit_result_is_forwarded_without_recalculation(self):
        result = {'task_id': 't', 'level': 3, 'coefficient': 1.0}
        self.adapter.judge_sample.return_value = result
        out = self.root / 'judge'
        self.assertIs(quality.run_judge(self.root, self.solution, out), result)
        self.adapter.judge_sample.assert_called_once_with(
            self.root, self.solution, out, out / 'verdict.json', 600)


class CompletionVersusComparabilityTests(unittest.TestCase):
    """残余一：尝试齐全 ≠ 可比较。直接测 main 用的纯函数，不重写公式。"""

    def _summary(self, agent_scored, agent_tasks, base_scored, base_tasks):
        return {"agent": {"scored_tasks": agent_scored, "tasks": agent_tasks},
                "baseline": {"scored_tasks": base_scored, "tasks": base_tasks}}

    def test_all_environment_failures_are_attempts_complete_but_not_comparable(self):
        # 评审的静态构造：80 格全部尝试，但全部环境失败 -> 两个模式都没有有效成绩
        state = quality.evaluate_state(
            attempted=80, expected_cells=80, missing_tasks=[],
            summary=self._summary(0, 8, 0, 8))
        self.assertTrue(state["attempts_complete"])       # 尝试确实齐全
        self.assertFalse(state["comparable"])             # 但不能用来比较
        self.assertEqual(state["scored_coverage"], {"agent": 0.0, "baseline": 0.0})
        self.assertEqual(quality.exit_code_for(state), 3)  # 不是 0

    def test_short_attempts_are_not_complete(self):
        state = quality.evaluate_state(
            attempted=60, expected_cells=80, missing_tasks=[],
            summary=self._summary(8, 8, 8, 8))
        self.assertFalse(state["attempts_complete"])
        self.assertEqual(quality.exit_code_for(state), 2)

    def test_missing_task_is_not_complete(self):
        state = quality.evaluate_state(
            attempted=80, expected_cells=80, missing_tasks=["ProbNope"],
            summary=self._summary(8, 8, 8, 8))
        self.assertFalse(state["attempts_complete"])

    def test_partial_environment_failures_block_paired_experiment_claim(self):
        # 官方可以汇总有效成绩，但两侧少了不同题，不能宣称配对协议完成。
        state = quality.evaluate_state(
            attempted=80, expected_cells=80, missing_tasks=[],
            summary=self._summary(6, 8, 7, 8))
        self.assertTrue(state["attempts_complete"])
        self.assertFalse(state["comparable"])
        self.assertEqual(quality.exit_code_for(state), 3)
        self.assertEqual(state["scored_coverage"], {"agent": 0.75, "baseline": 0.875})

    def test_one_failed_sample_blocks_complete_five_sample_claim(self):
        summary = self._summary(8, 8, 8, 8)
        summary["agent"]["tool_errors"] = 1
        state = quality.evaluate_state(80, 80, [], summary)
        self.assertTrue(state["attempts_complete"])
        self.assertFalse(state["comparable"])

    def test_same_task_count_with_wrong_identity_is_not_comparable(self):
        summary = self._summary(1, 1, 1, 1)
        summary["agent"]["per_task"] = [dict(task_id="A", samples=5, scored_samples=5)]
        summary["baseline"]["per_task"] = [dict(task_id="B", samples=5, scored_samples=5)]
        state = quality.evaluate_state(10, 10, [], summary, ["A"], 5)
        self.assertFalse(state["comparable"])

    def test_complete_paired_zero_scores_are_valid(self):
        summary = self._summary(1, 1, 1, 1)
        for mode in ("agent", "baseline"):
            summary[mode].update(set_score=0.0, tool_errors=0,
                                 per_task=[dict(task_id="A", samples=5, scored_samples=5)])
        state = quality.evaluate_state(10, 10, [], summary, ["A"], 5)
        self.assertTrue(state["comparable"])
        self.assertEqual(quality.exit_code_for(state), 0)

    def test_one_mode_without_any_score_blocks_comparison(self):
        state = quality.evaluate_state(
            attempted=80, expected_cells=80, missing_tasks=[],
            summary=self._summary(8, 8, 0, 8))
        self.assertFalse(state["comparable"])
        self.assertIn("baseline 没有任何有效成绩", state["incomparable_reasons"])

    def test_main_uses_the_shared_functions(self):
        text = QUALITY.read_text(encoding="utf-8")
        self.assertIn("state = evaluate_state(", text)
        self.assertIn("return exit_code_for(state)", text)


if __name__ == "__main__":
    unittest.main()
