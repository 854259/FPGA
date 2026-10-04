import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_context import large

HERE=Path(__file__).resolve().parent


def load(name):
    spec=importlib.util.spec_from_file_location('context_'+name,HERE/'package/agent'/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Integration(unittest.TestCase):
    def run_case(self,filename,code,compile_ok=True,functional=False):
        runtime=load(filename); calls=[]; sources=[]; probes=[]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);task=root/'task';task.mkdir();out=root/'out';out.mkdir()
            (out/'trace.jsonl').write_text('');(task/'prompt.txt').write_text('Fixture prompt')
            tool=root/'xvlog';tool.write_text('fixture')
            good='module TopModule(input a,output y); assign y=a; endmodule'
            def model(req,**kwargs):
                calls.append(json.loads(req.data))
                body=dict(choices=[dict(finish_reason='stop',message=dict(content=code if len(calls)==1 else good))])
                return io.BytesIO(json.dumps(body).encode())
            def native(argv,**kwargs):
                sources.append(Path(argv[-1]).read_text(encoding='utf-8'))
                rc=0 if compile_ok or len(sources)>1 else 1
                import subprocess
                return subprocess.CompletedProcess(argv,rc,'ERROR: fixture syntax' if rc else '')
            def feedback(prompt,code,out,attempt):
                probes.append(code);return 'Observed mismatch at fixture input.' if functional and attempt==0 else ''
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ,MODEL_NAME='fake',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'),patch.object(runtime,'vivado_tool',return_value=str(tool)),patch.object(runtime,'map_feedback',side_effect=feedback,create=True),patch('urllib.request.urlopen',side_effect=model),patch('subprocess.run',side_effect=native):
                    runtime.worker(task,out)
            finally:
                os.chdir(previous)
            trace=[json.loads(x) for x in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            return calls,sources,probes,trace,(out/'solution.v').read_text(encoding='utf-8')

    def test_compiler_failure_changes_only_second_prompt_copy(self):
        code='module TopModule(input a,output y);\n'+large('assign y=a;endmodule\n')
        control=self.run_case('map_runtime.py',code,False)
        candidate=self.run_case('d_runtime.py',code,False)
        self.assertEqual(control[0][0],candidate[0][0]);self.assertEqual(control[1],candidate[1])
        self.assertEqual(control[4],candidate[4]);self.assertEqual(len(candidate[0]),2)
        self.assertLess(len(candidate[0][1]['messages'][1]['content']),len(control[0][1]['messages'][1]['content']))
        self.assertIn('ERROR: fixture syntax',candidate[0][1]['messages'][1]['content'])
        self.assertEqual(control[0][1]['messages'][0],candidate[0][1]['messages'][0])
        receipts=[r for r in candidate[3] if r['tool']=='repair_context'];self.assertTrue(receipts[0]['changed'])

    def test_correct_first_candidate_and_actual_native_source_untouched(self):
        code='module TopModule(input a,output y);\n'+large('assign y=a;endmodule\n')
        control=self.run_case('map_runtime.py',code);candidate=self.run_case('d_runtime.py',code)
        self.assertEqual(control[:3],candidate[:3]);self.assertEqual(control[4],code)
        self.assertEqual(candidate[1],[code]);self.assertEqual(len(candidate[0]),1)
        self.assertFalse(any(r['tool']=='repair_context' for r in candidate[3]))

    def test_original_functional_feedback_is_retained(self):
        code='module TopModule(input a,output y);\n'+large('assign y=a;endmodule\n')
        candidate=self.run_case('d_runtime.py',code,functional=True)
        self.assertEqual(candidate[2][0],code);self.assertEqual(len(candidate[0]),2)
        self.assertIn('Observed mismatch at fixture input.',candidate[0][1]['messages'][1]['content'])

    def test_incomplete_candidate_check_keeps_original_diagnostic(self):
        code=large('module TopModule(input a,output y);')
        candidate=self.run_case('d_runtime.py',code)
        self.assertEqual(len(candidate[0]),2)
        self.assertIn('Return a complete TopModule ending in endmodule.',candidate[0][1]['messages'][1]['content'])
        self.assertEqual(len(candidate[1]),1)

    def test_directive_abstention_is_identical_to_control(self):
        code=large('`define X 1\nmodule TopModule;endmodule')
        control=self.run_case('map_runtime.py',code,False);candidate=self.run_case('d_runtime.py',code,False)
        self.assertEqual(control[:3],candidate[:3]);self.assertEqual(control[4],candidate[4])
        self.assertFalse(next(r for r in candidate[3] if r['tool']=='repair_context')['changed'])


if __name__=='__main__':unittest.main()
