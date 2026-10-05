import tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import worker,fsm_dispatch,fsm_feedback
from test_fsm_integration import material,point_line

class Boundaries(unittest.TestCase):
    def check(self,kind='semantic_mismatch',log=None,code='module TopModule;endmodule'):
        prompt=material();c=fsm_dispatch.parse(prompt)
        row=next(r for r in c['observations'] if r['expected']);calls=[]
        def oracle(test,source,out):
            calls.append(test);out.mkdir()
            (out/'xsim.log').write_text(point_line(c,row) if log is None else log)
            return dict(status='fail',failure_kind=kind,checks=c['checks'],mismatches=1)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(worker,'ROOT',root):
                text=worker.functional_feedback(prompt,code,root,0,types.SimpleNamespace(oracle=oracle),'fixture',candidate=True)
            return text,calls

    def test_tool_failure_never_becomes_model_counterexample(self):
        with self.assertRaises(RuntimeError):self.check(kind='environment_error')

    def test_missing_fabricated_or_equal_observed_counterexample_rejected(self):
        c=fsm_dispatch.parse(material());r=next(o for o in c['observations'] if o['expected'])
        for log in ['',point_line(c,dict(r,state=r['state']^1)),point_line(c,r,format(r['expected'],'x'))]:
            with self.assertRaises(ValueError):self.check(log=log)

    def test_file_access_or_includes_abstain_before_probe(self):
        for code in ['module TopModule;initial $display("x");endmodule','`include "x.sv"\nmodule TopModule;endmodule']:
            self.assertEqual(self.check(code=code),('',[]))

    def test_unknown_ambiguous_prose_retains_original_dispatch(self):
        for prompt in [material()+' Additional reset is required.',material().replace('(10 bits)','(9 bits)',1),material(True)+' Delay all output one cycle.']:
            self.assertEqual(fsm_dispatch.parse(prompt),worker.prompt_map.parse(prompt))

    def test_feedback_binds_entire_observation_and_output_order(self):
        c=fsm_dispatch.parse(material());row=next(r for r in c['observations'] if r['expected'])
        point=fsm_dispatch.counterexample(point_line(c,row),c)
        result=dict(failure_kind='semantic_mismatch',checks=c['checks'],mismatches=1)
        text=fsm_feedback.render(c,result,point)
        self.assertNotIn('assign ',text);self.assertNotIn('always ',text)
        self.assertIn('packed outputs in declaration order',text)
        for key,value in [('state',row['state']^1),('expected',row['expected']^1),('output_maps',[]),('observed_hex',format(row['expected'],'x'))]:
            with self.assertRaises(AssertionError):fsm_feedback.render(c,result,dict(point,**{key:value}))

if __name__=='__main__':unittest.main()
