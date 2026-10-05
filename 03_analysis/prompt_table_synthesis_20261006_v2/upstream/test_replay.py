"""Synthetic trace integrity, not a model/EDA run or grade claim."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import edge_dispatch
import phase_feedback as edge_feedback
import replay
from test_edge_integration import material,trace_log

ROOT=Path(__file__).resolve().parent
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
baseline=module('edge_replay_extract',ROOT/'package/baseline.py')
runtime=module('edge_replay_original_functions',ROOT/'package/agent/runtime.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d),encoding='utf-8')


class Replay(unittest.TestCase):
    def run_case(self,tamper=None):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td);prompt=material();c=edge_dispatch.parse(prompt)
            first='module TopModule(input clk,input [7:0] in,output [7:0] pulse);assign pulse=0;endmodule'
            second='module TopModule(input clk,input [7:0] in,output [7:0] pulse);assign pulse=1;endmodule'
            first=baseline.extract(first,'rtl');second=baseline.extract(second,'rtl')
            # Replies and probe grades here are intentionally synthetic integrity fixtures.
            row=next(o for o in c['observations'] if o['expected'])
            log=trace_log(c,True)
            point=edge_dispatch.counterexample(log,c)
            result=dict(status='fail',failure_kind='semantic_mismatch',checks=c['checks'],mismatches=1)
            diagnostic=edge_feedback.render(c,result,point)
            journal=[];compiles=[]
            for i,code in enumerate([first,second]):
                req=work/'requests'/str(i);req.mkdir(parents=True)
                user=prompt if i==0 else prompt+'\nPrevious candidate:\n'+first+'\nCandidate diagnostics:\n'+diagnostic
                if tamper=='diagnostic' and i==1:user+='changed'
                save(req/'request.json',dict(messages=[dict(role='system',content='fixture'),dict(role='user',content=user)]))
                save(req/'response.json',dict(id=str(i),choices=[dict(finish_reason='stop',message=dict(content=code))]))
                journal.append(dict(response_received=True,finish_reason='stop',response_id=str(i)))
                receipt=work/'compile_receipts'/str(i);receipt.mkdir(parents=True)
                for n in ['source_before.sv','source_after.sv']:(receipt/n).write_text(code,encoding='utf-8')
                (receipt/'owned_compile.log').write_text('',encoding='utf-8')
                h=sha(receipt/'source_before.sv')
                compiles.append(dict(argv=['/fake/xvlog','--sv',f'/fixture/compile-{i}/candidate.sv'],returncode=0,
                                     launch_error=None,remaining_live_group=[],timeout=False,log_sha256=sha(receipt/'owned_compile.log'),
                                     log_bytes=0,source_sha256=h,source_before_sha256=h,source_after_sha256=h))
                check=work/f'map_check_{i}';check.mkdir()
                save(check/'contract.json',c);(check/'input.sv').write_text(code,encoding='utf-8')
                if i==0:save(check/'feedback.json',dict(text=diagnostic))
            save(work/'requests.json',journal);save(work/'compile_journal.json',compiles)
            (work/'trace.jsonl').write_text('',encoding='utf-8');(work/'solution.v').write_text(second,encoding='utf-8')
            if tamper=='source':(work/'map_check_0/input.sv').write_text(second,encoding='utf-8')
            if tamper=='DUT':(work/'solution.v').write_text(first,encoding='utf-8')
            if tamper=='compile':(work/'compile_receipts/0/source_before.sv').write_text(second,encoding='utf-8')
            if tamper=='contract':save(work/'map_check_0/contract.json',dict(c,width=9))
            if tamper=='compression':(work/'trace.jsonl').write_text(json.dumps(dict(tool='repair_context',changed=False)),encoding='utf-8')
            def probe(check,contract):
                if check.name=='map_check_0':
                    self.assertEqual(read(check/'feedback.json')['text'],edge_feedback.render(contract,result,point))
                    return result
                return dict(status='pass',failure_kind=None,checks=c['checks'],mismatches=0)
            return replay.replay(work,prompt,'P',c,baseline,runtime,edge_dispatch,edge_feedback,probe,sha,read,False)

    def test_original_source_messages_and_repair_feedback_bound(self):
        result=self.run_case()
        self.assertTrue(result['original_repair_feedback_bound'])
        self.assertEqual(result['declaration_patches'],0)

    def test_diagnostic_actual_source_compiler_contract_dut_or_extra_factor_rejected(self):
        for mode in ['diagnostic','source','compile','contract','DUT','compression']:
            with self.subTest(mode=mode),self.assertRaises(AssertionError):self.run_case(mode)


if __name__=='__main__':unittest.main()
