"""AMD-only FAKE metadata gates. No watcher, cloud, model, EDA or real ledger.

All ticket99 references are synthetic test identities, not a future FIFO vote.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import fsm_coordination_wrapper as w

BASE = None
TABLE = None


class FsmObserverTests(unittest.TestCase):
    def setUp(self):
        w.require(sys.platform == "linux" and BASE is not None and TABLE is not None, "AMD-only explicit test dependencies")
        self.temp = tempfile.TemporaryDirectory(prefix="FAKE_FSM_OBSERVER_")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.ledger, self.runs, self.tickets = [self.base/name for name in ("ledger", "runs", "tickets")]
        self.ledger.mkdir(); self.tickets.mkdir()
        self.tool = w.extend_tool(TABLE, BASE)
        self.root = self.runs/"alice/fsm_FAKE"; self.root.mkdir(parents=True)
        kinds = ["producer_positive"]*2+["sentinel_positive"]*2+["semantic_negative"]*20+["transport_refusal"]*10+["eda_failure"]*2+["supervisor_probe"]*2
        self.items = [dict(index=i, label="FAKE_control_"+str(i), kind=kind,
                           expected_native_tools=["xvlog", "xelab", "xsim"] if i < 34 else ["xvlog"] if i == 34 else ["xvlog", "xelab"] if i == 35 else [])
                      for i, kind in enumerate(kinds)]
        self.commands = [tool for row in self.items for tool in (row["expected_native_tools"] or ["owned_supervisor"])]
        self.case_plan = dict(schema=w.CASE_SCHEMA, planned=w.PLANNED, expected_native_by_tool=w.NATIVE_BY_TOOL, rows=self.items)
        self.tool.write(self.root/"CASE_PLAN.json", self.case_plan)
        self.spec = dict(schema=w.FROZEN_SCHEMA, cloud_root=str(self.root), planned=w.PLANNED,
                         expected_native_by_tool=w.NATIVE_BY_TOOL, model_requests_max=0,
                         source_hashes={"CASE_PLAN.json": hashlib.sha256((self.root/"CASE_PLAN.json").read_bytes()).hexdigest()})
        self.rebind_spec()
        self.run_card = dict(ticket=99, root=str(self.root), expected_samples=38, spec_sha256=self.digest)
        self.ticket("running")
        self.plan = dict(owner="alice", authored_at_utc="2026-10-06T02:00:00+00:00", branch="FAKE/research",
            commit="FAKE", summary="仅观察校准", next_step="等待原档案审计", changed_files=[], issues=[],
            notices=[dict(id="review", revision="v1", text="请查看已绑定进度")], runs=[self.run_card])

    def rebind_spec(self):
        self.tool.write(self.root/"RUN_SPEC.json", self.spec)
        self.digest = hashlib.sha256((self.root/"RUN_SPEC.json").read_bytes()).hexdigest()
        if hasattr(self, "run_card"): self.run_card["spec_sha256"] = self.digest

    def ticket(self, state, foreign=False):
        self.tool.write(self.tickets/"00000099.json", dict(schema="whole_task_fifo_v1", ticket=99,
            cwd=str(self.runs/"bob/foreign") if foreign else str(self.root), state=state))

    def counts(self, confirmed, attempted=None):
        attempted = confirmed if attempted is None else attempted
        native = {tool: self.commands[:confirmed].count(tool) for tool in w.NATIVE_BY_TOOL}
        return dict(model_calls=0, attempted_owned_commands=attempted, confirmed_owned_commands=confirmed,
                    unconfirmed_owned_attempts=attempted-confirmed, actual_native_by_tool=native,
                    actual_native_commands=sum(native.values()), actual_owned_supervisor_commands=self.commands[:confirmed].count("owned_supervisor"), inventory_errors=[])

    def rows(self, number):
        return [dict(index=i["index"], label=i["label"], kind=i["kind"], error=None) for i in self.items[:number]]

    def live(self, confirmed=3, completed=1):
        for row in self.rows(completed):
            self.tool.write(self.root/"results"/row["label"]/"ROW.json", row)
        for index in range(confirmed):
            control = index//3 if index < 102 else 34 if index == 102 else 35 if index < 105 else index-69
            self.tool.write(self.root/"results/progress"/(str(index).zfill(4)+".json"), dict(
                schema="fsm_native_progress_v2", label=self.items[control]["label"], completed_rows=control, **self.counts(index+1)))

    def terminal(self, qualified=True, error=None, number=38, confirmed=107):
        summary = dict(schema=w.SUMMARY_SCHEMA, spec_sha256=self.digest, planned=w.PLANNED,
                       complete=number == 38 and error is None, evidence_complete=qualified, native_qualified=qualified,
                       error=error, rows=self.rows(number), guard_receipts=216, **self.counts(confirmed))
        self.tool.write(self.root/"results/summary.json", summary)
        return summary

    def observe(self):
        return self.tool.observe_run(self.run_card, self.tickets)

    def test_01_pins_precede_loading(self):
        self.assertEqual(hashlib.sha256(TABLE.read_bytes()).hexdigest(), w.TABLE_WRAPPER_SHA256)
        self.assertEqual(hashlib.sha256(BASE.read_bytes()).hexdigest(), w.BASE_SHA256)
        bad = self.base/"bad.py"; bad.write_text("raise AssertionError('must not execute')", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "table wrapper SHA256"): w.extend_tool(bad, BASE)
        with self.assertRaisesRegex(ValueError, "base tool SHA256"): w.extend_tool(TABLE, bad)

    def test_02_queued_unknown_cost_not_fabricated_zero(self):
        self.ticket("queued")
        result = self.observe()
        self.assertEqual(result["execution_state"], "pending")
        self.assertEqual(result["completed_samples"], 0)
        self.assertIsNone(result["actual_model_requests"])
        self.assertIsNone(result["actual_native_commands"])

    def test_03_live_rows_native_and_model_separate(self):
        self.live(3, 1)
        result = self.observe()
        self.assertEqual((result["completed_samples"], result["actual_native_commands"], result["actual_owned_supervisor_commands"], result["actual_model_requests"]), (1, 3, 0, 0))
        self.assertEqual(result["count_evidence"], "stage_reported_not_audited")
        self.assertEqual(result["native_qualification"], "pending")

    def test_04_progress_may_precede_current_row(self):
        self.live(3, 0)
        result = self.observe()
        self.assertEqual((result["completed_samples"], result["actual_native_commands"]), (0, 3))
        self.assertEqual(result["status"], "running")

    def test_05_terminal_claim_remains_pending_archive(self):
        self.terminal()
        result = self.observe()
        self.assertEqual(result["status"], "completed_pending_audit")
        self.assertEqual((result["completed_samples"], result["actual_native_commands"], result["actual_owned_supervisor_commands"]), (38, 105, 2))
        self.assertTrue(result["reported_stage_native_qualified"])
        self.assertEqual(result["native_qualification"], "pending_terminal_audit")
        self.assertFalse(result["terminal_quality_result_observed"])
        self.assertNotIn("grade", result)

    def test_06_failed_partial_attempts_remain_visible(self):
        summary = self.terminal(False, "FAKE supervision error", 1, 3)
        summary.update(self.counts(3, 4)); self.tool.write(self.root/"results/summary.json", summary)
        result = self.observe()
        self.assertEqual((result["status"], result["actual_native_commands"], result["unconfirmed_owned_attempts"]), ("failed", 3, 1))
        self.assertEqual(result["quality_conclusion"], "pending_terminal_audit")

    def test_07_invalid_native_probe_or_model_count_is_unknown(self):
        original = self.terminal()
        for field, value in [("actual_model_requests", 1), ("model_calls", True), ("actual_native_commands", 107), ("actual_owned_supervisor_commands", 0), ("confirmed_owned_commands", 106)]:
            with self.subTest(field=field):
                summary = copy.deepcopy(original); summary[field] = value
                if field == "actual_model_requests": summary["model_calls"] = value
                self.tool.write(self.root/"results/summary.json", summary)
                result = self.observe(); self.assertIsNotNone(result["observation_error"])
                self.assertIsNone(result["actual_native_commands"])

    def test_08_nonprefix_rows_and_unfrozen_case_plan_refused(self):
        summary = self.terminal(); summary["rows"][0], summary["rows"][1] = summary["rows"][1], summary["rows"][0]
        self.tool.write(self.root/"results/summary.json", summary)
        self.assertIsNotNone(self.observe()["observation_error"])
        self.terminal(); (self.root/"CASE_PLAN.json").write_bytes(b"{}")
        self.assertIsNotNone(self.observe()["observation_error"])

    def test_09_foreign_ticket_and_spec_root_fail_before_counts(self):
        self.terminal(); self.ticket("running", True)
        self.assertIsNone(self.observe()["actual_native_commands"])
        self.ticket("running"); self.spec["cloud_root"] = str(self.runs/"bob/foreign"); self.rebind_spec(); self.terminal()
        self.assertIsNotNone(self.observe()["observation_error"])

    def test_10_snapshot_race_refuses_cost(self):
        self.terminal()
        original = w.snapshot
        def change(path):
            value = original(path)
            if Path(path).name == "summary.json":
                altered = copy.deepcopy(value[1]); altered["native_qualified"] = False
                self.tool.write(path, altered)
            return value
        with mock.patch.object(w, "snapshot", side_effect=change): result = self.observe()
        self.assertIn("changed", result["observation_error"])
        self.assertIsNone(result["actual_native_commands"])
        self.assertFalse(result["terminal_quality_result_observed"])
        self.assertIsNone(result["reported_stage_native_qualified"])
        self.assertNotIn("observed_summary_sha256", result)

    def test_11_publish_preserves_peer_primary_and_pending_ack(self):
        peer = self.ledger/"bob"; peer.mkdir(); (peer/"COORDINATION.json").write_bytes(b"PEER")
        own = self.ledger/"alice"; own.mkdir(); (own/"STATUS.md").write_bytes(b"PRIMARY"); (own/"SNAPSHOT.json").write_bytes(b"PRIMARY_SNAPSHOT")
        self.live()
        card = self.tool.publish(self.plan, "alice", self.ledger, self.runs, self.tickets, "2026-10-06T02:00:00+00:00")
        self.assertEqual(card["schema"], "team_coordination_v1")
        self.assertEqual((peer/"COORDINATION.json").read_bytes(), b"PEER")
        self.assertEqual((own/"STATUS.md").read_bytes(), b"PRIMARY")
        self.assertEqual((own/"SNAPSHOT.json").read_bytes(), b"PRIMARY_SNAPSHOT")
        self.assertIn("1/38", (own/"CURRENT_WORK.md").read_text(encoding="utf-8"))
        self.assertIn("native 3/105", (own/"FSM_NATIVE_PROGRESS.md").read_text(encoding="utf-8"))
        self.assertFalse(self.tool.check(self.ledger, "2026-10-06T02:00:00+00:00")["reviews"][0]["acknowledged"])
        self.assertFalse((peer/"reviews").exists())

    def test_12_table_and_stability_observations_delegate_exactly(self):
        loader = importlib.util.spec_from_file_location("_FAKE_unchanged_table", TABLE)
        table = importlib.util.module_from_spec(loader); loader.loader.exec_module(table)
        old_tool = table.extend_tool(BASE)
        for schema, frozen, size in [("phaseP_stability156x5_v1", {"frozen": True}, 780),
                                     ("table_synthesis_pilot_v1", dict(schema="table_synthesis_pilot_frozen_v1", expected_samples=28, task_ids=["FAKE_Task"+str(i) for i in range(14)], arms=["C", "P"]), 28)]:
            with self.subTest(schema=schema):
                self.spec = frozen; self.rebind_spec(); self.run_card["expected_samples"] = size
                self.tool.write(self.root/"results/summary.json", dict(schema=schema, spec_sha256=self.digest, complete=False, passed=False, rows=[], actual_model_requests=0))
                self.assertEqual(self.observe(), old_tool.observe_run(self.run_card, self.tickets))

    def test_13_terminal_ticket_without_summary_is_pending_audit(self):
        self.ticket("held_for_inspection")
        result = self.observe()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["native_qualification"], "pending_terminal_audit")
        self.assertIsNone(result["actual_native_commands"])

    def test_14_cli_preserves_actions_without_starting_watcher(self):
        with mock.patch.object(self.tool, "main", return_value="forwarded") as old_main:
            with mock.patch.object(w, "extend_tool", return_value=self.tool):
                self.assertEqual(w.main(["--table-wrapper", str(TABLE), "--base-tool", str(BASE), "check", "--ledger-root", str(self.ledger)]), "forwarded")
        old_main.assert_called_once()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-tool", required=True, type=Path)
    parser.add_argument("--table-wrapper", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    BASE, TABLE = args.base_tool.resolve(), args.table_wrapper.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
