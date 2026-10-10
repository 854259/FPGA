"""New variable request-budget receipt boundary; no model, EDA or native job."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'submission/agent/shared_budget.py'
SPEC = importlib.util.spec_from_file_location('request_shared_budget', SOURCE)
budget_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(budget_module)


class RequestBudgetTests(unittest.TestCase):
    def test_non300_expiry_uses_actual_inherited_parent_clock(self):
        with tempfile.TemporaryDirectory(prefix='request-budget-cpu-') as tmp:
            requests = Path(tmp) / 'requests.json'
            origin = time.monotonic()
            requests.write_text(json.dumps([]))
            with patch.dict(os.environ, {budget_module.PARENT_STARTED_ENV: str(origin)}):
                budget = budget_module.SolveBudget(
                    .025, parent_started=budget_module.parent_started_from_environment())
            self.assertEqual(budget.started, origin)
            self.assertEqual(budget.end, origin + .025)
            time.sleep(max(0., budget.end - time.monotonic()) + .002)
            with self.assertRaises(budget_module.BudgetExpired):
                budget.remaining()
            receipt = budget.exit_receipt(requests, SOURCE)
            self.assertEqual(receipt['budget_s'], .025)
            self.assertEqual(receipt['started_monotonic'], origin)
            self.assertGreaterEqual(receipt['elapsed_s'], .025)
            self.assertAlmostEqual(receipt['elapsed_s'],
                                   receipt['observed_monotonic'] - origin, places=9)
            self.assertFalse(receipt['complete'])
            self.assertFalse(receipt['score_eligible'])
            self.assertIsNone(receipt['grade'])
            self.assertIsNone(receipt['actual_calls'])
            self.assertIsNone(receipt['unconfirmed_calls'])

    def test_active_non300_request_cannot_write_an_expiry_receipt(self):
        with tempfile.TemporaryDirectory(prefix='request-budget-cpu-') as tmp:
            requests = Path(tmp) / 'requests.json'
            requests.write_text('[]')
            origin = time.monotonic()
            budget = budget_module.SolveBudget(60, parent_started=origin)
            with self.assertRaises(AssertionError):
                budget.exit_receipt(requests, SOURCE)
            self.assertEqual(budget.end, origin + 60)


if __name__ == '__main__':
    unittest.main()
