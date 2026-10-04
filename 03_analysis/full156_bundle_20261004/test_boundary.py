"""Offline integration checks with fake model/tools; not RTL accuracy evidence."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


class Boundary(unittest.TestCase):
    def test_boundary_stop_prevents_all_admission(self):
        spec = importlib.util.spec_from_file_location("queue_test", HERE / "evaluate_batch.py")
        batch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batch)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "RUN_SPEC.json").write_text("{}", encoding="utf-8")
            (root / "STOP_AFTER_CURRENT").write_text("user stop", encoding="utf-8")
            with patch.object(batch, "ROOT", root), patch.object(batch, "frozen", return_value=(dict(task_ids=[], queue_deadline_s=30), root)), \
                patch("subprocess.Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "Boundary stop requested"):
                    batch.queue(types.SimpleNamespace())
                launch.assert_not_called()
            status = batch.read(root / "queue_status.json")
            self.assertEqual(status["completed_samples"], 0)
            self.assertFalse(status["complete"])

    def test_flock_rejection_keeps_guard_directory_uncreated(self):
        spec = importlib.util.spec_from_file_location("admission_test", HERE / "evaluate_batch.py")
        batch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batch)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "RUN_SPEC.json").write_text("{}", encoding="utf-8")
            original_exists = Path.exists

            def exists(path):
                return False if path.as_posix() == "/workspace/team/SLOT.lock" else original_exists(path)

            def launch(argv, **kwargs):
                guard = Path(argv[argv.index("--guard-out") + 1])
                self.assertFalse(guard.exists())
                self.assertFalse((root / "samples").exists())
                return types.SimpleNamespace(pid=999, wait=lambda: 1)

            with patch.object(batch, "ROOT", root), patch.object(batch, "frozen", return_value=(dict(task_ids=[], queue_deadline_s=30, model_pid=123, model="test"), root)), \
                patch("subprocess.Popen", side_effect=launch) as launcher, patch.object(Path, "exists", exists), \
                patch("time.sleep", side_effect=RuntimeError("end fake admission test")):
                with self.assertRaisesRegex(RuntimeError, "end fake admission test"):
                    batch.queue(types.SimpleNamespace())
                self.assertEqual(launcher.call_count, 1)
            self.assertEqual(batch.read(root / "queue_status.json")["completed_samples"], 0)

    def run_case(self, arm, answer, expected_requests, expected_decision):
        spec = importlib.util.spec_from_file_location("batch_test", HERE / "evaluate_batch.py")
        batch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batch)
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(HERE / "package", root / "package")
            for name in ("guarded_bundle.py", "extract_bundle.py", "lexical_mask.py"):
                shutil.copyfile(HERE / name, root / name)
            kit = root / "kit"
            task = kit / "bench/tasks_veval/task"
            task.mkdir(parents=True)
            (task / "prompt.txt").write_text("PUBLIC_AND_PROMPT", encoding="utf-8")
            (task / "ref.sv").write_text("PRIVATE_REFERENCE_SENTINEL", encoding="utf-8")
            (task / "tb.sv").write_text("PRIVATE_TB_SENTINEL", encoding="utf-8")
            (task / "task.json").write_text("PRIVATE_TASK_META_SENTINEL", encoding="utf-8")
            tool = root / "tools/xvlog"
            tool.parent.mkdir()
            tool.write_text("fake", encoding="utf-8")
            (tool.parent / "xvlog.bat").write_text("fake", encoding="utf-8")
            slot = root / "SLOT.lock"
            slot.write_text("test_owner\n", encoding="utf-8")
            check = root / "resource.json"
            check.write_text(json.dumps(dict(schema_version=1, resource_idle=True,
                slot_lock_path=str(slot), slot_lock_sha256=batch.sha(slot), slot_owner="test_owner",
                model_pid=123, model_identity={"test": True})), encoding="utf-8")
            flat = "module TopModule(input a,b,output y); assign y=a&b; endmodule"
            requests, commands = [], []

            def model(request, **kwargs):
                data = json.loads(request.data)
                serialized = json.dumps(data)
                self.assertIn("PUBLIC_AND_PROMPT", serialized)
                self.assertNotIn("PRIVATE_REFERENCE_SENTINEL", serialized)
                self.assertNotIn("PRIVATE_TB_SENTINEL", serialized)
                self.assertNotIn("PRIVATE_TASK_META_SENTINEL", serialized)
                requests.append(data)
                reply = answer if len(requests) == 1 else "```verilog\n" + flat + "\n```"
                return io.BytesIO(json.dumps(dict(id="test", choices=[dict(finish_reason="stop",
                    message=dict(content=reply))])).encode())

            def candidate_tool(argv, cwd, log, seconds):
                commands.append(Path(argv[0]).name)
                log.write_text("", encoding="utf-8")
                return dict(timeout=False, launch_error=None, remaining_live_group=[], returncode=0)

            paired = types.SimpleNamespace(model_identity=lambda pid: {"test": True},
                model_idle=lambda *args: None, owned_command=candidate_tool)
            old_read = Path.read_bytes
            old_text = Path.read_text

            def sealed_bytes(path):
                self.assertFalse(path.is_relative_to(task) and path.name in ("ref.sv", "tb.sv", "task.json"))
                return old_read(path)

            def sealed_text(path, *args, **kwargs):
                self.assertFalse(path.is_relative_to(task) and path.name in ("ref.sv", "tb.sv", "task.json"))
                return old_text(path, *args, **kwargs)

            args = types.SimpleNamespace(arm=arm, task="task", out=root / "result", resource_check=check)
            sys_path = list(__import__("sys").path)
            try:
                with patch.object(batch, "ROOT", root), patch.object(batch, "frozen", return_value=({"model": "test"}, kit)), \
                    patch.object(batch, "owned", return_value=paired), patch.dict(os.environ, MODEL_NAME="test", VIVADO_BIN=str(tool.parent), RTL_REPAIRS="1"), \
                    patch("urllib.request.urlopen", side_effect=model), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="")), \
                    patch.object(Path, "read_bytes", sealed_bytes), patch.object(Path, "read_text", sealed_text):
                    batch.worker(args)
                result = batch.read(args.out / "worker_result.json")
                self.assertEqual(result["actual_model_requests"], expected_requests)
                self.assertEqual(result["extraction"][0]["decision"], expected_decision)
                self.assertEqual(commands, ["xvlog", "xelab"] if expected_decision == "candidate_accepted" else [])
                self.assertEqual({p.name for p in (args.out / "prompt_only").iterdir()}, {"prompt.txt"})
            finally:
                os.chdir(previous)
                __import__("sys").path[:] = sys_path
                __import__("sys").modules.pop("baseline", None)

    def test_original_missing_helper_keeps_ordinary_repair(self):
        self.run_case("A", HELPER, 2, "original_baseline")

    def test_guard_restores_reply_existing_helper_without_private_inputs(self):
        self.run_case("C", HELPER, 1, "candidate_accepted")

    def test_single_top_unchanged_without_extra_tools(self):
        self.run_case("C", "```verilog\nmodule TopModule(input a,b,output y); assign y=a&b; endmodule\n```", 1, "unchanged")

    def test_duplicate_top_abstains(self):
        self.run_case("C", "```verilog\n" + "module TopModule(input a,b,output y); assign y=a&b; endmodule\n" * 2 + "```", 1, "unchanged")


HELPER = """```verilog
module TopModule(input a,b,output y);
helper u(.a(a),.b(b),.y(y));
endmodule
```
```verilog
module helper(input a,b,output y); assign y=a&b; endmodule
```
"""


if __name__ == "__main__":
    unittest.main()
