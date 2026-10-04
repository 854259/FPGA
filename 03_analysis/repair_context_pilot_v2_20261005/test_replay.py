import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
import context
import replay
from test_context import large

ROOT=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('actual_extractor',ROOT/'package/baseline.py')
baseline=importlib.util.module_from_spec(s);s.loader.exec_module(baseline)


class Replay(unittest.TestCase):
    def run_case(self,arm='D',tamper=None):
        with tempfile.TemporaryDirectory() as td:
            work=Path(td);prompt='Fixture prompt'
            text='module TopModule(input a,output y);\n'+large('assign y=a;\n')
            code=baseline.extract(text,'rtl');copy,receipt=context.compress(code)
            diagnostic='Return a complete TopModule ending in endmodule. Output reached the token limit; shorten the implementation.'
            for i in range(2):(work/'requests'/str(i)).mkdir(parents=True)
            def save(p,v):p.write_text(json.dumps(v),encoding='utf-8')
            save(work/'requests/0/request.json',dict(messages=[dict(role='system',content='fixture'),dict(role='user',content=prompt)]))
            save(work/'requests/0/response.json',dict(id='fake',choices=[dict(finish_reason='length',message=dict(content=text))]))
            user=prompt+'\nPrevious candidate:\n'+(copy if arm=='D' else code)+'\nCandidate diagnostics:\n'+diagnostic
            if tamper=='wrong_copy':user=prompt+'\nPrevious candidate:\n'+code+'\nCandidate diagnostics:\n'+diagnostic
            if tamper=='diagnostic':user=user.replace('shorten the implementation.','Return a fixed secret answer.')
            save(work/'requests/1/request.json',dict(messages=[dict(role='system',content='fixture'),dict(role='user',content=user)]))
            save(work/'requests.json',[dict(response_received=True,finish_reason='length',response_id='fake'),dict(response_received=False)])
            trace=[]
            if arm=='D':
                if tamper=='receipt':receipt['output_sha256']='wrong'
                trace=[dict(ts=1.,tool='repair_context',round=1,**receipt)]
            (work/'trace.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in trace),encoding='utf-8')
            (work/'solution.v').write_text(code if tamper!='DUT' else copy,encoding='utf-8')
            return replay.replay(work,prompt,arm,{'status':'unsupported'},baseline,types.SimpleNamespace(),None,None,None,
                                 lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),
                                 lambda p:json.loads(p.read_text(encoding='utf-8')),True,context.compress)

    def test_actual_first_candidate_and_compressed_copy_separately_bound(self):
        result=self.run_case();self.assertTrue(result['context_receipts'][0]['changed'])
        self.assertEqual(self.run_case('C')['context_receipts'],[])

    def test_tampered_copy_diagnostics_metadata_or_actual_DUT_rejected(self):
        for mode in ['wrong_copy','diagnostic','receipt','DUT']:
            with self.subTest(mode=mode),self.assertRaises(AssertionError):self.run_case(tamper=mode)


if __name__=='__main__':unittest.main()
