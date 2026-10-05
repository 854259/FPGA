import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import team_coordination as tool


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.ledger, self.runs, self.tickets = base / "activity", base / "runs", base / "tickets"
        self.ledger.mkdir(); self.tickets.mkdir()
        self.plan = dict(owner="alice", authored_at_utc="2026-10-05T15:00:00+00:00", branch="research/alice",
                         commit="abc", summary="正在测试时序", next_step="等待原始审计", changed_files=["new.py"],
                         issues=[dict(issue_key="veval:edge", experiment_key="baseline:suffix:one", status="completed_pending_audit",
                                      evidence=["run/results/summary.json"], limits=["已见题，尚未审计"])],
                         notices=[dict(id="handoff", text="请复用统计工具", revision="v1")], runs=[])

    def publish(self, plan=None, observed="2026-10-05T15:00:00+00:00"):
        p = plan or self.plan
        return tool.publish(p, p["owner"], self.ledger, self.runs, self.tickets, observed)

    def test_freshness_audit_state_and_same_direction_different_experiment(self):
        self.publish()
        peer = copy.deepcopy(self.plan); peer.update(owner="bob", branch="research/bob")
        peer["issues"][0].update(experiment_key="baseline:different:five", status="verified_bounded")
        self.publish(peer, "2026-10-05T14:44:59+00:00")
        report = tool.check(self.ledger, "2026-10-05T15:00:00+00:00")
        entries = report["repeated_directions"]["veval:edge"]
        self.assertEqual([r["freshness"] for r in entries], ["fresh", "stale"])
        self.assertTrue(all(not r["verified"] for r in entries))
        self.assertFalse(report["stale_ownership_released"])
        self.assertNotEqual(entries[0]["experiment_key"], entries[1]["experiment_key"])

    def test_owned_publish_preserves_peer_and_primary_status_and_chinese(self):
        peer = self.ledger / "bob"; peer.mkdir()
        (peer / "COORDINATION.json").write_bytes(b"PEER_CARD")
        own = self.ledger / "alice"; own.mkdir()
        (own / "STATUS.md").write_bytes(b"AUTOMATIC_STATUS")
        (own / "SNAPSHOT.json").write_bytes(b"AUTOMATIC_SNAPSHOT")
        self.publish()
        self.assertEqual((peer / "COORDINATION.json").read_bytes(), b"PEER_CARD")
        self.assertEqual((own / "STATUS.md").read_bytes(), b"AUTOMATIC_STATUS")
        self.assertEqual((own / "SNAPSHOT.json").read_bytes(), b"AUTOMATIC_SNAPSHOT")
        self.assertIn("正在测试时序", (own / "CURRENT_WORK.md").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            tool.publish(self.plan, "bob", self.ledger, self.runs, self.tickets)

    def test_ack_requires_current_revision_and_writes_reviewer_only(self):
        self.publish()
        peer = copy.deepcopy(self.plan); peer.update(owner="bob", notices=[])
        self.publish(peer)
        original = (self.ledger / "alice/COORDINATION.json").read_bytes()
        with self.assertRaises(ValueError):
            tool.ack("bob", "alice", "handoff", "v0", self.ledger)
        tool.ack("bob", "alice", "handoff", "v1", self.ledger)
        self.assertEqual((self.ledger / "alice/COORDINATION.json").read_bytes(), original)
        self.assertTrue(tool.check(self.ledger, "2026-10-05T15:00:00+00:00")["reviews"][0]["acknowledged"])
        self.plan["notices"][0]["revision"] = "v2"; self.publish()
        self.assertFalse(tool.check(self.ledger, "2026-10-05T15:00:00+00:00")["reviews"][0]["acknowledged"])

    def test_owned_run_progress_is_not_quality_and_unknown_or_failed_preserved(self):
        root = self.runs / "alice/example_v1"; root.mkdir(parents=True)
        spec = b'{"frozen":true}\n'; (root / "RUN_SPEC.json").write_bytes(spec)
        digest = hashlib.sha256(spec).hexdigest()
        self.plan["runs"] = [dict(ticket=80, root=str(root), expected_samples=2, spec_sha256=digest)]
        tool.write(self.tickets / "00000080.json", dict(schema="whole_task_fifo_v1", ticket=80, cwd=str(root), state="running"))
        self.assertEqual(self.publish()["runs"][0]["status"], "unknown")
        summary = dict(schema="phaseP_stability156x5_v1", spec_sha256=digest, complete=True, passed=True, rows=[{}, {}])
        tool.write(root / "results/summary.json", summary)
        self.assertEqual(self.publish()["runs"][0]["status"], "completed_pending_audit")
        summary.update(complete=False, passed=False, error="original failure", rows=[{}])
        tool.write(root / "results/summary.json", summary)
        self.assertEqual(self.publish()["runs"][0]["status"], "failed")
        summary.update(schema="unknown-schema", error=None)
        tool.write(root / "results/summary.json", summary)
        self.assertEqual(self.publish()["runs"][0]["status"], "unknown")
        self.plan["runs"][0]["root"] = str(self.runs / "bob/foreign")
        with self.assertRaises(ValueError):
            self.publish()

    def test_ack_without_reviewer_card_is_visible_with_unknown_activity(self):
        self.publish()
        tool.ack("bob", "alice", "handoff", "v1", self.ledger)
        report = tool.check(self.ledger, "2026-10-05T15:00:00+00:00")
        self.assertEqual(report["unknown_members"][0]["owner"], "bob")
        self.assertEqual(report["unknown_members"][0]["freshness"], "unknown")
        self.assertTrue(report["reviews"][0]["acknowledged"])
        self.assertEqual(report["unregistered_reviews"], [])

    def test_future_card_is_unknown_and_unbounded_verification_rejected(self):
        self.publish(observed="2026-10-05T15:00:01+00:00")
        self.assertEqual(tool.check(self.ledger, "2026-10-05T15:00:00+00:00")["members"][0]["freshness"], "unknown")
        self.plan["issues"][0].update(status="verified_bounded", evidence=[])
        with self.assertRaises(ValueError):
            self.publish()


if __name__ == "__main__":
    unittest.main()
