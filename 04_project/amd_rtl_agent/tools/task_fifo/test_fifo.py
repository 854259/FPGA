"""Actual CPU subprocess FIFO checks in private temp roots; no model or EDA."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import task_fifo as fifo


class QueueTests(unittest.TestCase):
    def fixture(self, root, name, fail=False):
        receipt = root / (name + ".json")
        events = root / "events.txt"
        start_line = name + "_start\n"
        finish_line = name + "_finish\n"
        code = (
            "import json,time;from pathlib import Path;"
            f"p=Path({str(events)!r});"
            f"p.open('a').write({start_line!r});"
            "time.sleep(.08);"
            f"p.open('a').write({finish_line!r});"
            f"Path({str(receipt)!r}).write_text(json.dumps(dict(complete={not fail!r})));"
            f"raise SystemExit({int(fail)})"
        )
        return fifo.register(root / "queue", name, [sys.executable, "-c", code], root, receipt, name + "_")

    def test_fifo_whole_task_with_reversed_monitor_start_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tickets = [self.fixture(root, name) for name in ("one", "two", "three")]
            errors = []

            def run(ticket):
                try:
                    fifo.execute(root / "queue", ticket["ticket"], check=lambda _: True, poll_s=.01, lifetime_s=5)
                except Exception as error:
                    errors.append(error)

            threads = [threading.Thread(target=run, args=(ticket,)) for ticket in reversed(tickets)]
            for thread in threads:
                thread.start()
                time.sleep(.02)
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual((root / "events.txt").read_text().splitlines(),
                ["one_start", "one_finish", "two_start", "two_finish", "three_start", "three_finish"])
            self.assertTrue(all(item["state"] == "completed" for item in fifo.entries(root / "queue")))

    def test_failed_task_keeps_head_and_blocks_next(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.fixture(root, "failed", fail=True)
            second = self.fixture(root, "later")
            with self.assertRaises(RuntimeError):
                fifo.execute(root / "queue", first["ticket"], check=lambda _: True, poll_s=.01, lifetime_s=2)
            self.assertEqual(fifo.head(root / "queue")["ticket"], first["ticket"])
            with self.assertRaises(TimeoutError):
                fifo.execute(root / "queue", second["ticket"], check=lambda _: True, poll_s=.01, lifetime_s=.05)
            self.assertEqual((root / "events.txt").read_text().splitlines(), ["failed_start", "failed_finish"])

    def test_cancelled_before_start_never_launches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = self.fixture(root, "cancelled")
            with fifo.registry(root / "queue"):
                item["state"] = "cancelled_before_start"
                fifo.save(fifo.ticket_path(root / "queue", item["ticket"]), item)
            # Cancellation can race a waiting monitor, but a fresh invocation
            # of an already-final ticket is never treated as a new execution.
            with self.assertRaises(RuntimeError):
                fifo.execute(root / "queue", item["ticket"], check=lambda _: True, poll_s=.01)
            self.assertFalse((root / "events.txt").exists())

    def test_adopt_never_restarts_or_interrupts_existing_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completion = root / "completion.json"
            command = [sys.executable, "-c", "import json,time;from pathlib import Path;time.sleep(.1);"
                f"Path({str(completion)!r}).write_text(json.dumps(dict(complete=True)))"]
            existing = subprocess.Popen(command)
            initial_identity = fifo.identity(existing.pid)
            item = fifo.register(root / "queue", "adopted", [], root, completion, "own_", initial_identity)
            fifo.execute(root / "queue", item["ticket"], check=lambda _: True, poll_s=.01)
            self.assertEqual(existing.wait(), 0)
            self.assertEqual(fifo.read(fifo.ticket_path(root / "queue", item["ticket"]))["state"], "completed")


if __name__ == "__main__":
    unittest.main()
