"""Changed request-boundary and score-selection checks. AMD only, no real model/EDA."""
import copy,json,unittest
import fsm_guidance as b
class Boundary(unittest.TestCase):
 def raw(self,p,index=0):
  user=b.combined(p,'') if not index else b.combined(p,'')+'\nPrevious candidate:\nmodule TopModule; endmodule\nCandidate diagnostics:\nERROR mock'
  return json.dumps(dict(model='mock',messages=[dict(role='system',content='fixed generation'),dict(role='user',content=user)],temperature=0.,top_p=1.,max_tokens=8192)).encode()
 def test_first_user_only(self):
  p='Design a serial state machine from the following specification.';raw=self.raw(p);after,r=b.transform(raw,p,'','P',0);b.verify(raw,after,p,'','P',0,r)
  j=json.loads(raw);k=json.loads(after);self.assertTrue(r['changed']);self.assertEqual(j['messages'][0],k['messages'][0]);self.assertIn(b.GUIDANCE,k['messages'][1]['content'])
 def test_control_unchanged(self):
  p='serial state machine';raw=self.raw(p);after,r=b.transform(raw,p,'','C',0);self.assertEqual(raw,after);b.verify(raw,after,p,'','C',0,r)
 def test_repair_unchanged(self):
  p='serial state machine';raw=self.raw(p,1);after,r=b.transform(raw,p,'','P',1);self.assertEqual(raw,after);b.verify(raw,after,p,'','P',1,r)
 def test_nonsequential_unchanged(self):
  p='Build a combinational AND gate.';raw=self.raw(p);after,r=b.transform(raw,p,'','P',0);self.assertEqual(raw,after);self.assertFalse(r['changed'])
 def test_reject_system_tampering(self):
  p='counter state';raw=self.raw(p);after,r=b.transform(raw,p,'','P',0);j=json.loads(after);j['messages'][0]['content']='changed'
  with self.assertRaises(AssertionError):b.verify(raw,json.dumps(j).encode(),p,'','P',0,r)
 def test_reject_budget_or_prompt(self):
  p='counter state';raw=self.raw(p)
  for key,value in [('max_tokens',8193),('temperature',1)]:
   j=json.loads(raw);j[key]=value
   with self.assertRaises(AssertionError):b.transform(json.dumps(j).encode(),p,'','P',0)
  with self.assertRaises(AssertionError):b.transform(raw,'another specification','','P',0)
 def test_guidance_has_no_RTL_or_task_dispatch(self):
  self.assertNotIn('Prob',b.GUIDANCE);self.assertNotIn('endmodule',b.GUIDANCE);self.assertNotIn('always @',b.GUIDANCE)
if __name__=='__main__':unittest.main()
