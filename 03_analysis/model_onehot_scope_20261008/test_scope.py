"""New semantic scope checks only; original boundary controls are not replayed."""
import json,sys,unittest
import fsm_guidance as b
assert sys.platform=='linux' and sys.dont_write_bytecode
class Scope(unittest.TestCase):
 def raw(self,p):
  return json.dumps(dict(model='mock',messages=[dict(role='system',content='fixed generation'),dict(role='user',content=b.combined(p,''))],temperature=0.,top_p=1.,max_tokens=8192)).encode()
 def test_onehot_only_selects_by_prompt(self):
  for p in ['A one-hot encoded state machine.', 'Use ONE HOT encoding.', 'The state uses onehot encoding.']:
   raw=self.raw(p);forwarded,r=b.transform(raw,p,'','P',0);self.assertTrue(r['changed']);b.verify(raw,forwarded,p,'','P',0,r)
   self.assertEqual(json.loads(forwarded)['messages'][1]['content'],p+b.SUFFIX+b.GUIDANCE)
 def test_other_protocols_are_byte_unchanged(self):
  for p in ['A serial state machine.', 'A timer controlling four shift cycles.', 'A counter state machine.', 'A combinational AND gate.']:
   raw=self.raw(p);forwarded,r=b.transform(raw,p,'','P',0);self.assertEqual(raw,forwarded);self.assertFalse(r['changed']);b.verify(raw,forwarded,p,'','P',0,r)
 def test_scope_does_not_consume_task_or_interface_labels(self):
  p='Use binary state encoding.';raw=self.raw(p);forwarded,r=b.transform(raw,p,'','P',0);self.assertEqual(forwarded,raw)
  self.assertEqual(b.clarification(p,'one-hot')[0],'');self.assertEqual(b.clarification('one-hot', '')[0],b.GUIDANCE)
if __name__=='__main__':unittest.main()
