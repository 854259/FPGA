"""Frozen real native trace integrity and exact stimulus preservation; no EDA/model."""
import json,re,unittest
from pathlib import Path
import edge_contract,edge_dispatch,phase_feedback,phase_context
R=Path(__file__).resolve().parent
class Phase(unittest.TestCase):
    def data(self):return json.loads((R/'raw_evidence/test_fixtures/phase_observation.json').read_bytes())
    def test_actual_native_group_matches_point_and_has_multiple_phases(self):
        d=self.data();c=d['contract'];p=edge_dispatch.counterexample(d['log'],c)
        self.assertGreaterEqual(len(p['phase_context']['observations']),2)
        text=phase_feedback.render(c,dict(mismatches=p['phase_context']['mismatches'],checks=c['checks'],failure_kind='semantic_mismatch'),p)
        self.assertIn('Related observations at the same sequence step',text)
        self.assertNotIn('assign ',text);self.assertNotIn('always ',text)
    def test_original_stimulus_and_obligations_remain_exact_bytes(self):
        c=self.data()['contract'];tb=edge_contract.render_tb(c,'Constructed_W5_rising_R0');full=edge_dispatch.render_tb(c,'Constructed_W5_rising_R0')
        self.assertEqual(''.join(s for s in full.splitlines(keepends=True) if not s.startswith('$display("EDGE_TRACE ')),tb)
    def test_missing_duplicate_reordered_fabricated_and_out_of_range_trace_rejected(self):
        d=self.data();c,log=d['contract'],d['log'];traces=[s for s in log.splitlines() if s.startswith('EDGE_TRACE')];a,b=traces[:2]
        bad=[log.replace(a+'\n','',1),log.replace(a,a+'\n'+a,1),log.replace(a,'SWAP_TOKEN',1).replace(b,a,1).replace('SWAP_TOKEN',b,1),log.replace(a,re.sub(r'expected=\w+','expected=ffffff',a),1),log.replace(a,re.sub(r'observed=\w+','observed=ffffff',a),1),re.sub(r'EDGE_FIRST step=\d+','EDGE_FIRST step=999',log,count=1),re.sub(r'(R2_PROBE_RESULT .* mismatches=)\d+',r'\g<1>99999',log,count=1)]
        for altered in bad:
            with self.subTest(trace_sha=hash(altered)),self.assertRaises((AssertionError,ValueError)):phase_context.context(altered,c,edge_contract)
if __name__=='__main__':unittest.main()
