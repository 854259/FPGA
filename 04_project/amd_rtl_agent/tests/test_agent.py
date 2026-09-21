import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import agent


class AgentTests(unittest.TestCase):
    def test_extracts_fenced_code(self):
        text = "answer\n```systemverilog\nmodule TopModule; endmodule\n```\nend"
        self.assertEqual(agent.extract_verilog(text), "module TopModule; endmodule\n")

    def test_baseline_is_one_problem_only_call(self):
        seen = []

        def fake(messages, seed, metadata=None):
            seen.append((messages, seed))
            return "module TopModule; endmodule"

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(agent, "call_model", fake):
            result = agent.baseline_generate("ONLY THE PROBLEM", Path(temp) / "out.sv", 9)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(seen, [([{"role": "user", "content": "ONLY THE PROBLEM"}], 9)])

    def test_repair_limit_is_enforced(self):
        calls = []

        def always_bad(messages, seed, metadata=None):
            calls.append((messages, seed))
            return "not verilog"

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(agent, "call_model", always_bad):
            result = agent.generate_agent_sample(
                problem="p",
                output=Path(temp) / "candidate.sv",
                eval_dir=Path(temp) / "eval",
                seed=1,
                testbench=None,
                reference=None,
                max_repairs=2,
                skip_eda=True,
                skip_synthesis=True,
            )
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["attempts"], 3)
        self.assertFalse(result["passed"])

    def test_feedback_is_bounded(self):
        text = "\n".join(f"ERROR line {i} " + "x" * 200 for i in range(100))
        self.assertLessEqual(len(agent.compact_feedback(text)), 4096)

    def test_repair_feedback_flags_explicit_port_direction_conflict(self):
        code = "module TopModule(input q); endmodule"
        feedback = "Hint: Output 'q' has 120 mismatches"
        enriched = agent.repair_feedback(code, feedback)
        self.assertIn("端口 q", enriched)
        self.assertIn("input", enriched)

    def test_repair_feedback_does_not_guess_without_conflict(self):
        code = "module TopModule(output q); endmodule"
        feedback = "Mismatches: 2 in 20 samples"
        self.assertEqual(agent.repair_feedback(code, feedback), feedback)

    def test_basic_check_requires_topmodule(self):
        self.assertIsNotNone(agent.basic_check("module Wrong; endmodule"))
        self.assertIsNone(agent.basic_check("module TopModule; endmodule"))

    def test_mock_run_produces_baseline_and_five_samples(self):
        fixtures = ROOT / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {
            "LLM_MOCK_FILE": str(fixtures / "mock_responses.json")
        }, clear=False):
            agent._MOCK_CACHE.clear()
            args = argparse.Namespace(
                problem=str(fixtures / "problem.txt"),
                output_dir=temp,
                testbench=None,
                reference=None,
                samples=5,
                repairs=2,
                seed=1,
                skip_eda=True,
                skip_synthesis=True,
            )
            result = agent.run_problem(args)
            self.assertEqual(len(result["samples"]), 5)
            self.assertTrue((Path(temp) / "baseline.sv").exists())
            self.assertTrue((Path(temp) / "best.sv").exists())
            self.assertTrue((Path(temp) / "result.json").exists())


if __name__ == "__main__":
    unittest.main()
