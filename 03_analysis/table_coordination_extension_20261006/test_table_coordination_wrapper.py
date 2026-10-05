"""Isolated observer tests: no HTTP, native tools, cloud, watcher or real ledgers."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import table_coordination_wrapper as wrapper

BASE = Path(os.environ.get("TEAM_COORDINATION_BASE_TOOL",
            str(Path(__file__).resolve().parents[3]/"04_project/amd_rtl_agent/tools/team_coordination/team_coordination.py")))


class TableObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ledger, self.runs, self.tickets = [self.base/n for n in ("ledger", "runs", "tickets")]
        self.ledger.mkdir(); self.tickets.mkdir()
        self.tool = wrapper.extend_tool(BASE)
        self.root = self.runs/"alice/table_v2"
        self.root.mkdir(parents=True)
        self.spec = dict(schema=wrapper.FROZEN_SCHEMA, expected_samples=28,
                         task_ids=[f"Prob{i:03d}_known" for i in range(1, 15)], arms=["C", "P"])
        self.tool.write(self.root/"RUN_SPEC.json", self.spec)
        digest = hashlib.sha256((self.root/"RUN_SPEC.json").read_bytes()).hexdigest()
        self.run = dict(ticket=99, root=str(self.root), expected_samples=28, spec_sha256=digest)
        self.tool.write(self.tickets/"00000099.json",
                        dict(schema="whole_task_fifo_v1", ticket=99, cwd=str(self.root), state="running"))
        self.plan = dict(owner="alice", authored_at_utc="2026-10-05T15:00:00+00:00",
                         branch="research/alice", commit="abc", summary="机械表格试验",
                         next_step="等待终态审计", changed_files=["new.py"], issues=[],
                         notices=[dict(id="handoff", revision="v1", text="请查看进度")], runs=[self.run])
        self.summary = dict(schema=wrapper.TABLE_SCHEMA, spec_sha256=digest,
                            complete=False, passed=False, rows=[], actual_model_requests=0)

    def rows(self, number):
        ordered = [(task, arm) for i, task in enumerate(self.spec["task_ids"])
                   for arm in (["C", "P"] if i % 2 == 0 else ["P", "C"])]
        return [dict(task=task, arm=arm, actual_model_requests=1 if arm == "C" else 0,
                     generation_route="model" if arm == "C" else "mechanical_table")
                for task, arm in ordered[:number]]

    def observe(self):
        self.tool.write(self.root/"results/summary.json", self.summary)
        return self.tool.observe_run(self.run, self.tickets)

    def publish(self):
        self.tool.write(self.root/"results/summary.json", self.summary)
        return self.tool.publish(self.plan, "alice", self.ledger, self.runs, self.tickets,
                                 "2026-10-05T15:00:00+00:00")

    def test_pinned_original_is_unchanged_and_only_schema_added(self):
        self.assertEqual(hashlib.sha256(BASE.read_bytes()).hexdigest(), wrapper.BASE_SHA256)
        module_spec = importlib.util.spec_from_file_location("_unchanged_base", BASE)
        original = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(original)
        self.assertEqual(self.tool.RUN_SCHEMAS, original.RUN_SCHEMAS | {wrapper.TABLE_SCHEMA})
        self.assertNotIn(wrapper.TABLE_SCHEMA, original.RUN_SCHEMAS)
        bad = self.base/"bad.py"; bad.write_text("raise AssertionError('must not execute')", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            wrapper.extend_tool(bad)

    def test_partial_calls_before_completed_row_are_visible(self):
        self.summary.update(rows=self.rows(3), actual_model_requests=2)
        result = self.observe()
        self.assertEqual((result["completed_samples"], result["expected_samples"]), (3, 28))
        self.assertEqual(result["actual_model_requests"], 2)
        self.assertEqual(result["completed_row_model_requests"], 1)
        self.assertEqual(result["unrepresented_model_requests"], 1)
        self.assertEqual(result["quality_conclusion"], "pending")
        self.assertEqual(result["model_call_evidence"], "stage_reported_not_audited")

    def test_completed_28_outputs_are_not_28_calls_or_quality_pass(self):
        self.summary.update(rows=self.rows(28), actual_model_requests=14, complete=True, passed=True,
                            screening_eligible=True, adoption=False)
        result = self.observe()
        self.assertEqual(result["status"], "completed_pending_audit")
        self.assertEqual(result["execution_state"], "terminal")
        self.assertEqual(result["actual_model_requests"], 14)
        self.assertEqual(result["quality_conclusion"], "pending_terminal_audit")
        self.assertFalse(result["terminal_quality_result_observed"])

    def test_failed_partial_retains_attempt_cost_without_full_score(self):
        self.summary.update(rows=self.rows(4), actual_model_requests=4, error="Real route validation failure")
        result = self.observe()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["unrepresented_model_requests"], 2)
        self.assertEqual(result["quality_conclusion"], "pending_terminal_audit")
        self.assertNotIn("coefficients", result)

    def test_missing_summary_queued_is_pending_and_calls_unknown(self):
        self.tool.write(self.tickets/"00000099.json",
                        dict(schema="whole_task_fifo_v1", ticket=99, cwd=str(self.root), state="queued"))
        result = self.tool.observe_run(self.run, self.tickets)
        self.assertEqual(result["execution_state"], "pending")
        self.assertIsNone(result["actual_model_requests"])
        self.assertEqual(result["model_call_evidence"], "unavailable")

    def test_invalid_accounting_and_illegal_zero_are_unknown(self):
        for mutation in ("boolean", "missing", "too_small", "model_zero", "C_mechanical", "order"):
            with self.subTest(mutation=mutation):
                self.summary.update(rows=self.rows(2), actual_model_requests=1)
                if mutation == "boolean": self.summary["actual_model_requests"] = True
                elif mutation == "missing": del self.summary["actual_model_requests"]
                elif mutation == "too_small": self.summary["actual_model_requests"] = 0
                elif mutation == "model_zero": self.summary["rows"][0]["actual_model_requests"] = 0
                elif mutation == "C_mechanical": self.summary["rows"][0]["generation_route"] = "mechanical_table"
                else: self.summary["rows"].reverse()
                result = self.observe()
                self.assertEqual(result["status"], "unknown")
                self.assertIsNone(result["actual_model_requests"])
                self.assertIsNotNone(result["observation_error"])

    def test_complete_summary_must_have_exact_cost_and_28_rows(self):
        self.summary.update(rows=self.rows(28), actual_model_requests=15, complete=True, passed=True)
        result = self.observe()
        self.assertIsNotNone(result["observation_error"])
        self.assertIsNone(result["actual_model_requests"])
        self.assertEqual(result["quality_conclusion"], "pending_terminal_audit")

    def test_ticket_and_spec_bindings_precede_extra_metadata(self):
        self.summary.update(rows=self.rows(2), actual_model_requests=1)
        self.tool.write(self.tickets/"00000099.json",
                        dict(schema="whole_task_fifo_v1", ticket=99, cwd=str(self.runs/"bob/foreign"), state="running"))
        result = self.observe()
        self.assertIsNone(result.get("actual_model_requests"))
        self.assertEqual(result["status"], "unknown")
        (self.root/"RUN_SPEC.json").write_bytes(b"wrong source")
        result = self.observe()
        self.assertNotIn("progress_schema", result)

    def test_publish_preserves_legacy_files_peer_card_and_pending_ack(self):
        peer = self.ledger/"bob"; peer.mkdir()
        (peer/"COORDINATION.json").write_bytes(b"PEER")
        own = self.ledger/"alice"; own.mkdir()
        (own/"STATUS.md").write_bytes(b"PRIMARY")
        (own/"SNAPSHOT.json").write_bytes(b"PRIMARY_SNAPSHOT")
        self.summary.update(rows=self.rows(2), actual_model_requests=1)
        card = self.publish()
        self.assertEqual(card["schema"], "team_coordination_v1")
        self.assertEqual((peer/"COORDINATION.json").read_bytes(), b"PEER")
        self.assertEqual((own/"STATUS.md").read_bytes(), b"PRIMARY")
        self.assertEqual((own/"SNAPSHOT.json").read_bytes(), b"PRIMARY_SNAPSHOT")
        self.assertIn("阶段记录的实际模型调用：1", (own/"TABLE_PROGRESS.md").read_text(encoding="utf-8"))
        self.assertIn("2/28", (own/"CURRENT_WORK.md").read_text(encoding="utf-8"))
        report = self.tool.check(self.ledger, "2026-10-05T15:00:00+00:00")
        self.assertFalse(report["reviews"][0]["acknowledged"])
        self.tool.ack("bob", "alice", "handoff", "v1", self.ledger)
        self.assertTrue(self.tool.check(self.ledger, "2026-10-05T15:00:00+00:00")["reviews"][0]["acknowledged"])
        self.plan["notices"][0]["revision"] = "v2"; self.publish()
        self.assertFalse(self.tool.check(self.ledger, "2026-10-05T15:00:00+00:00")["reviews"][0]["acknowledged"])

    def test_old_schema_card_run_stays_unchanged(self):
        self.spec = dict(frozen=True)
        self.tool.write(self.root/"RUN_SPEC.json", self.spec)
        self.run["spec_sha256"] = hashlib.sha256((self.root/"RUN_SPEC.json").read_bytes()).hexdigest()
        self.run["expected_samples"] = 2
        self.summary = dict(schema="semantic_edge_guidance_pilot_v1", spec_sha256=self.run["spec_sha256"],
                            complete=True, passed=True, rows=[{}, {}])
        result = self.observe()
        self.assertEqual(result["status"], "completed_pending_audit")
        self.assertNotIn("progress_schema", result)
        self.assertNotIn("actual_model_requests", result)
        self.publish()
        self.assertFalse((self.ledger/"alice/TABLE_PROGRESS.md").exists())

    def test_schema_and_snapshot_race_fail_closed(self):
        self.summary.update(rows=self.rows(2), actual_model_requests=1)
        self.tool.write(self.root/"results/summary.json", self.summary)
        original_read = self.tool.read
        def initial_read(path):
            value = original_read(path)
            if Path(path).name == "summary.json":
                changed = copy.deepcopy(value); changed["rows"] = self.rows(3)
                self.tool.write(path, changed)
            return value
        with mock.patch.object(self.tool, "read", side_effect=initial_read):
            result = self.tool.observe_run(self.run, self.tickets)
        self.assertEqual(result["status"], "unknown")
        self.assertIn("changed", result["observation_error"])

    def test_cli_forwards_original_actions_without_starting_watcher(self):
        with mock.patch.object(self.tool, "main", return_value="forwarded") as old_main:
            with mock.patch.object(wrapper, "extend_tool", return_value=self.tool):
                self.assertEqual(wrapper.main(["--base-tool", str(BASE), "check",
                                               "--ledger-root", str(self.ledger)]), "forwarded")
        old_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
