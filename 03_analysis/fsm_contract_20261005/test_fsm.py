import itertools
import re
import unittest
import fsm_contract as f
import templates
import prepare_controls as controls
from reserved_keywords import KEYWORDS

class FSM(unittest.TestCase):
    def test_full_domain_independent_truth_all_widths(self):
        for n in range(5,13):
            prompt,truth=templates.full(n);c=f.parse(prompt);self.assertEqual(c['status'],'supported')
            self.assertEqual(c['checks'],(1<<n)*2)
            for row in c['observations']:
                values=[t for t in truth if row['state']>>t[0]&1 and t[1]==row['inputs']['sense']]
                targets=set(t[2] for t in values);a=any(t[3][0] for t in values);b=any(t[3][1] for t in values)
                wanted=sum(1<<i for i in targets)*4+int(a)*2+int(b)
                self.assertEqual(row['expected'],wanted)
    def test_partial_domain_independent_truth_and_encoding(self):
        for n in range(4,13):
            for explicit in [True,False]:
                prompt,truth=templates.partial(n,explicit=explicit);c=f.parse(prompt);self.assertEqual(c['status'],'supported')
                self.assertEqual(c['checks'],n*8)
                for row in c['observations']:
                    self.assertEqual(row['state'].bit_count(),1)
                    index=row['state'].bit_length()-1
                    t=next(t for t in truth if t[0]==index and row['inputs'][t[1]]==t[2])
                    wanted=int(t[3]==0)*8+int(t[3]==n-1)*4+t[4][0]*2+t[4][1]
                    self.assertEqual(row['expected'],wanted)
    def test_reserved_port_and_legal_uppercase_case_sensitive_roles(self):
        for word in KEYWORDS:
            p=templates.full(names=(word,'phase','future','lit','ready'))[0]
            self.assertNotEqual(f.parse(p)['status'],'supported')
            p=templates.partial(names=('trigger','finish','accept','active',word,'last_next','busy','done'))[0]
            self.assertNotEqual(f.parse(p)['status'],'supported')
        c=f.parse(templates.full(names=('Sense','Phase','Future','Lit','Ready'))[0]);self.assertEqual(c['status'],'supported')
        p=templates.partial(names=('Trigger','Finish','Accept','Active','First','Last','Busy','Done'))[0]
        self.assertEqual(f.parse(p)['status'],'supported')
        self.assertNotEqual(f.parse(p.replace('--Trigger=','--trigger='))['status'],'supported')
        self.assertNotEqual(f.parse(p.replace('- First --','- first --'))['status'],'supported')
    def test_unknown_semantics_and_interface_abstain(self):
        for p in [templates.full()[0],templates.partial()[0]]:
            for extra in [' Hold the outputs for an extra cycle.',' Reset overrides all outputs.',' Swap the input roles.',' Use priority among simultaneous active states.']:
                self.assertNotEqual(f.parse(p+extra)['status'],'supported')
                self.assertNotEqual(f.parse(extra+p)['status'],'supported')
            self.assertNotEqual(f.parse(p.replace('All input and output ports are one bit','All input and output ports are active-low'))['status'],'supported')
            self.assertNotEqual(f.parse(p.replace('- input','- output',1))['status'],'supported')
    def test_missing_duplicate_overlapping_and_ambiguous_table(self):
        p=templates.partial()[0];line='Node0 () --trigger=0--> Node0'
        for bad in [p.replace(line,''),p.replace(line,line+'\n'+line),p.replace('--trigger=0-->','--(always go to next cycle)-->'),p.replace("5'b00010","5'b00100"),p.replace('--trigger=0--> Node0','--trigger=0--> BadState')]:
            self.assertNotEqual(f.parse(bad)['status'],'supported')
        p=templates.full()[0]
        self.assertNotEqual(f.parse(p.replace('Q0 (0, 0) --1-->','Q0 (1, 0) --1-->'))['status'],'supported')
        self.assertNotEqual(f.parse(p.replace('Q0 (0, 0) --1--> Q1',''))['status'],'supported')
    def test_control_independent_predictions_and_expected_modes(self):
        for prompt in [templates.full()[0],templates.partial()[0]]:
            c=f.parse(prompt)
            for name in controls.NAMES:
                rows=controls.software(c,name);self.assertEqual(len(rows),c['checks'])
                mismatches=sum(v!=o['expected'] for v,o in zip(rows,c['observations']))
                self.assertEqual(mismatches==0,name=='positive')
                self.assertIn('module TopModule(',controls.control(c,name))
            tb=f.render_tb(c,'Synthetic');self.assertEqual(tb.count('_fsmcheck_checks=_fsmcheck_checks+1;'),c['checks'])
    def test_factual_counterexample_and_reject_fake(self):
        c=f.parse(templates.partial()[0]);o=c['observations'][0]
        bits=''.join(str(o['inputs'][k]) for k in c['input_names'])
        line=f'FSM_FIRST case=0 state={o["state"]:x} inputs={bits} expected={o["expected"]:x} observed=0'
        self.assertEqual(f.counterexample(line,c)['case'],0)
        for bad in [line+'\n'+line,line.replace('state=1','state=2'),line.replace('expected=8','expected=9'),line.replace('observed=0',f'observed={o["expected"]:x}'),line.replace('inputs=000','inputs=001'),line.replace('observed=0','observed=ff')]:
            with self.assertRaises(ValueError):f.counterexample(bad,c)
        self.assertEqual(f.counterexample(line.replace('observed=0','observed=x'),c)['observed_hex'],'x')
    def test_constructed_rename_width_not_task_number(self):
        p=templates.full(7,names=('data','present','next_bits','alarm','flag'),label='Mode')[0]
        c=f.parse(p);self.assertEqual(c['status'],'supported');self.assertEqual(c['states'],[f'Mode{i}' for i in range(7)])
        self.assertNotEqual(f.parse('Prob143_fsm_onehot')['status'],'supported')

if __name__=='__main__':unittest.main()
