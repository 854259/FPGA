"""Control-wrapper behavior without model calls or EDA execution."""
import argparse
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location('r3_validate_controls_test', HERE / 'validate_controls.py')
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


class ControlWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.helper = self.root / 'probe_runner.py'
        shutil.copyfile(REPO / '03_analysis/r3_lfsr_20261003/probes/probe_runner.py', self.helper)
        self.args = argparse.Namespace(probes=self.helper, probe_root=self.root, out=self.root / 'out')
        self.tools = {name: dict(path='/mock/' + name, sha256=name) for name in ('xvlog', 'xelab', 'xsim')}

    def invoke(self, valid=True, after=None):
        fake = types.SimpleNamespace()

        def run(out):
            self.assertEqual(fake.ROOT, self.root)
            self.assertEqual(fake.TASK_CHECKS, {'Prob086_lfsr5': 269, 'Prob085_shift4': 209,
                                             'Prob033_ece241_2014_q1c': 65536})
            out.mkdir()
            result = dict(complete=True, valid=valid, assets_unchanged=True, tasks={})
            (out / 'controls_validation.json').write_text(json.dumps(result))
            return result

        fake.validate_controls = run
        mock_spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda module: None))
        with ExitStack() as stack:
            stack.enter_context(patch.object(controls.importlib.util, 'spec_from_file_location', return_value=mock_spec))
            stack.enter_context(patch.object(controls.importlib.util, 'module_from_spec', return_value=fake))
            stack.enter_context(patch.object(controls, 'tool_ids', side_effect=[self.tools, self.tools if after is None else after]))
            stack.enter_context(patch('builtins.print'))
            return controls.validate(self.args)

    def test_valid_controls_record_current_tools_and_wrapper_identity(self):
        self.assertEqual(self.invoke(), 0)
        result = json.loads((self.args.out / 'controls_validation.json').read_text())
        self.assertEqual(result['tools_before'], result['tools_after'])
        self.assertTrue(result['tools_unchanged'])
        self.assertEqual(result['validator_sha256'], controls.digest(HERE / 'validate_controls.py'))

    def test_invalid_controls_return_failure(self):
        self.assertEqual(self.invoke(valid=False), 1)

    def test_changed_tools_invalidate_an_otherwise_positive_result(self):
        after = dict(self.tools, xsim={'path': '/other/xsim', 'sha256': 'changed'})
        self.assertEqual(self.invoke(after=after), 1)
        result = json.loads((self.args.out / 'controls_validation.json').read_text())
        self.assertFalse(result['valid'])
        self.assertFalse(result['tools_unchanged'])

    def test_changed_bottom_level_helper_rejected_before_controls(self):
        self.helper.write_text('changed helper\n')
        with self.assertRaisesRegex(ValueError, 'bottom-level probe runner changed'):
            controls.validate(self.args)
        self.assertFalse(self.args.out.exists())

    def test_missing_tool_rejected_before_execution(self):
        with patch.object(controls.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'three EDA executables'):
                controls.tool_ids()


if __name__ == '__main__':
    unittest.main()
