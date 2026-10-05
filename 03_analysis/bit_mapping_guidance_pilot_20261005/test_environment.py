import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pilot


class Environment(unittest.TestCase):
    def check(self,missing=None,wrong=False,library=True):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);tools=root/'tools';tools.mkdir();stub=root/'stub';stub.mkdir()
            for n in ['xvlog','xelab','xsim','vivado']:
                p=tools/n;p.write_text('fixture executable');p.chmod(0o755)
            def which(name):
                if name==missing:return None
                return str(root/'other'/name) if wrong else str(tools/name)
            with patch.dict(os.environ,VIVADO_BIN=str(tools.resolve()),LD_LIBRARY_PATH=str(stub.resolve()) if library else ''),patch.object(pilot.shutil,'which',side_effect=which):
                return pilot.validate_environment(tools,stub)

    def test_available_pinned_environment_checked_without_tool_execution(self):
        result=self.check();self.assertTrue(result['verified'])
        self.assertEqual(set(result['tools']),set(['xvlog','xelab','xsim','vivado']))
        self.assertEqual(result['model_calls'],0);self.assertEqual(result['eda_calls'],0)

    def test_each_missing_tool_rejected_before_model_call(self):
        for name in ['xvlog','xelab','xsim','vivado']:
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'Missing/wrong'):
                self.check(missing=name)

    def test_wrong_tool_resolution_rejected(self):
        with self.assertRaisesRegex(AssertionError,'Missing/wrong'):self.check(wrong=True)

    def test_missing_scoped_library_path_rejected(self):
        with self.assertRaisesRegex(AssertionError,'Missing scoped'):self.check(library=False)


if __name__=='__main__':unittest.main()
