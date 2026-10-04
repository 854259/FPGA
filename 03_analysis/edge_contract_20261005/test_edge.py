"""Independent per-bit sampled oracle and conservative language boundary controls."""
import unittest
import edge_contract as parser
from reserved_keywords import KEYWORDS


def material(w=8,kind='any',clk='clk',signal='in',out='pulse'):
    prefix=f'I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.\n - input {clk}\n - input {signal} ({w} bits)\n - output {out} ({w} bits)\n'
    if kind=='any':body=f'Implement a module that for each bit in an {w}-bit input vector, detect when the input signal changes from one clock cycle to the next (detect any edge). The output bit of {out} should be set to 1 the cycle after the input bit has 0 to 1 or 1 to 0 transition occurs. Assume all sequential logic is triggered on the positive edge of the clock.'
    else:body=f'The module should examine each bit in an {w}-bit vector and detect when the input signal changes from 0 in one clock cycle to 1 the next (similar to positive edge detection). The output bit should be set the cycle after a 0 to 1 transition occurs.'
    return prefix+body


def bit_pulse(old,new,w,kind):
    bits=[]
    for i in range(w):
        before=(old//2**i)%2;after=(new//2**i)%2
        bits.append(int(before!=after) if kind=='any' else int(before==0 and after==1))
    return sum(b*2**i for i,b in enumerate(bits))


class Edge(unittest.TestCase):
    def test_control_software_preserves_unknown_history(self):
        from prepare_controls import prediction
        c=parser.parse(material());o=prediction(c,'extra_delay')
        self.assertIsNone(o[0]);self.assertIsNone(o[1]);self.assertIsNone(o[2])
        self.assertFalse(any(x is None for x in prediction(c,'positive')))
        p=parser.parse(material(kind='rising'))
        self.assertEqual(prediction(p,'extra_delay')[0],0)
    def test_independent_bit_oracle_for_every_width_kind_and_phase(self):
        for w in range(1,65):
            for kind in ['any','rising']:
                c=parser.parse(material(w,kind));self.assertEqual(c['status'],'supported')
                for o in c['observations']:
                    a,b=(o['older_input'],o['previous_input']) if o['phase']=='stable' else (o['previous_input'],o['input'])
                    self.assertEqual(bit_pulse(a,b,w,kind),o['expected'])
                self.assertTrue(any(o['expected'] for o in c['observations']))
    def test_omitted_edge_not_invented_explicit_positive_kept(self):
        c=parser.parse(material(kind='rising'));self.assertEqual(c['clock_edge'],'unspecified_cycle')
        self.assertFalse(any(o['phase']=='positive' for o in c['observations']))
        a=parser.parse(material());self.assertTrue(any(o['phase']=='positive' for o in a['observations']))
        self.assertFalse(any(o['step']==0 for o in a['observations']))
        self.assertFalse(any(o['step']==1 and o['phase']=='stable' for o in a['observations']))
    def test_all_reserved_words_and_case_sensitive_backreference(self):
        for word in KEYWORDS:
            for role in ['signal','out']:
                self.assertEqual(parser.parse(material(**{role:word}))['status'],'abstain')
                self.assertEqual(parser.parse(material(**{role:word.upper()}))['status'],'supported')
        text=material();self.assertEqual(parser.parse(text.replace('bit of pulse','bit of PULSE'))['status'],'abstain')
    def test_full_prose_and_exact_interface_reject_nearby_semantics(self):
        for text in [material()+' Output has a second cycle delay.',material().replace('positive edge of the clock','negative edge of the clock'),material().replace('(8 bits)','(9 bits)',1),material().replace(' - input clk',' - input reset\n - input clk'),material().replace('cycle after','same cycle as')]:
            self.assertEqual(parser.parse(text)['status'],'abstain')
        self.assertEqual(parser.parse('Implement a priority encoder.')['status'],'skip')
    def test_counterexample_factual_phase_and_fake_point_rejection(self):
        c=parser.parse(material());o=next(o for o in c['observations'] if o['expected'])
        line=f"EDGE_FIRST step={o['step']} phase={o['phase']} expected={o['expected']:x} observed=00\n"
        self.assertEqual(parser.counterexample(line,c)['previous_input'],o['previous_input'])
        for bad in [line+line,line.replace('observed=00',f"observed={o['expected']:x}"),line.replace(f"expected={o['expected']:x}",'expected=123')]:
            with self.assertRaises(ValueError):parser.counterexample(bad,c)


if __name__=='__main__':unittest.main()
