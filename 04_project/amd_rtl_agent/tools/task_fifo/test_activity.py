import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import activity


class ActivityTests(unittest.TestCase):
    def test_repeat_sync_deduplicates_and_keeps_private_text_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "run"
            worker = run / "samples/A/demo/worker"
            request = worker / "requests/0"
            request.mkdir(parents=True)
            def save(path, data):
                path.write_text(json.dumps(data), encoding="utf-8")
            save(request / "request.json", dict(model="fake", messages=[dict(content="PRIVATE_PROMPT_SENTINEL")]))
            save(request / "response.json", dict(choices=[dict(message=dict(content="PRIVATE_SOLUTION_SENTINEL"))], usage=dict(prompt_tokens=5, completion_tokens=6)))
            digest = hashlib.sha256((request / "response.json").read_bytes()).hexdigest()
            save(worker / "requests.json", [dict(index=0, response_received=True, elapsed_s=.2, finish_reason="stop", response_sha256=digest)])
            save(run / "queue_status.json", dict(state="running", complete=False, completed_samples=0, current_task="demo", current_arm="A", source_spec_sha256="a"*64))
            ledger = root / "ledger"
            first = activity.sync(run, ledger)
            second = activity.sync(run, ledger)
            self.assertEqual(first["calls_received"], 1)
            self.assertEqual(second["calls_received"], 1)
            self.assertEqual(len((ledger / "calls.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            self.assertFalse(second["final_score_audited"])
            for path in ledger.iterdir():
                if path.suffix in (".json", ".jsonl", ".md"):
                    text = path.read_text(encoding="utf-8")
                    self.assertNotIn("PRIVATE_PROMPT_SENTINEL", text)
                    self.assertNotIn("PRIVATE_SOLUTION_SENTINEL", text)

    def test_change_and_conclusion_events_are_separate_and_append_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            activity.append(root, "changes", "commit:test", "Added isolated FIFO", {"commit": "test"})
            activity.append(root, "changes", "commit:test", "Duplicate", {})
            activity.append(root, "conclusions", "result:test", "Small sample only", {"adoption": False})
            self.assertEqual(len((root / "changes.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(len((root / "conclusions.jsonl").read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
