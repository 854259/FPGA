"""Independent scan semantics and ambiguous-prose controls; no model/EDA."""
import math
import unittest
import priority_contract as contract


def material(width,signal='data',out='index',illustrated=False):
    ow=math.ceil(math.log2(width))
    prefix='I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.\n'
    prefix+=f' - input {signal} ({width} bits)\n - output {out} ({ow} bits)\n'
    if illustrated:
        body="The module should implement a priority encoder. A priority encoder is a combinational circuit that, when given an input bit vector, outputs the position of the first 1 bit in the vector. For example, a 8-bit priority encoder given the input 8'b10010000 would output 3'd4, because bit[4] is first bit that is high. "
        body+=f'Build a {width}-bit priority encoder. For this problem, if none of the input bits are high (i.e., input is zero), output zero. Note that a {width}-bit number has {2**width} possible combinations.'
    else:
        value=(1<<(width-1))|1
        body=f'The module should implement a priority encoder for an {width}-bit input. Given an {width}-bit vector, the output should report the first (least significant) bit in the vector that is 1. Report zero if the input vector has no bits that are high. '
        body+=f"For example, the input {width}'b{value:0{width}b} should output {ow}'d0, because bit[0] is first bit that is high."
    return prefix+body+'\n'


class Priority(unittest.TestCase):
    def test_all_domain_matches_independent_bit_scan(self):
        for width in range(2,9):
            for illustrated in [False,True]:
                parsed=contract.parse(material(width,illustrated=illustrated))
                self.assertEqual(parsed['status'],'supported');self.assertEqual(parsed['checks'],2**width)
                for case in parsed['cases']:
                    value=case['inputs']['data'];expected=0
                    for bit in range(width):
                        if (value>>bit)&1:expected=bit;break
                    self.assertEqual(case['expected'],expected)

    def test_extra_prose_abstains_at_any_location(self):
        base=material(4)
        for extra in ['Hold index when data is zero.','Use a flip-flop.','Swap input bits before encoding.','Negate the result.','Output index must be registered.']:
            for text in [extra+'\n'+base,base+'\n'+extra,base.replace('The module',extra+' The module')]:
                self.assertEqual(contract.parse(text)['status'],'abstain')

    def test_wrong_width_and_ambiguous_example_rejected(self):
        base=material(4,illustrated=True)
        for text in [base.replace('input data (4 bits)','input data (5 bits)'),
                     base.replace('output index (2 bits)','output index (3 bits)'),
                     base.replace('10010000','00010000'),base.replace("3'd4","3'd7"),
                     base.replace('has 16 possible','has 15 possible'),base.replace('output zero','output one')]:
            self.assertEqual(contract.parse(text)['status'],'abstain')

    def test_names_and_complete_single_interface(self):
        for signal,out in [('in','pos'),('vector','result'),('checks','mismatches')]:
            parsed=contract.parse(material(3,signal,out));self.assertEqual(parsed['status'],'supported')
            tb=contract.render_tb(parsed,'renamed_priority')
            self.assertIn('.'+signal+'('+signal+')',tb)
            self.assertIn('_prioritycheck_checks',tb)
        for text in [material(4).replace(' - output',' - input other (4 bits)\n - output'),
                     material(4,'data','data'),material(4,'input','out')]:
            self.assertEqual(contract.parse(text)['status'],'abstain')

    def test_counterexample_matches_full_domain_and_rejects_spoof(self):
        parsed=contract.parse(material(4))
        message='PRIORITY_FIRST value=3 expected=0 observed=1'
        self.assertEqual(contract.counterexample(message,parsed)['inputs'],{'data':3})
        for log in [message+'\n'+message,message.replace('expected=0','expected=1'),
                    message.replace('value=3','value=16'),message.replace('observed=1','observed=0'),
                    message.replace('observed=1','observed=4')]:
            with self.assertRaises(ValueError):contract.counterexample(log,parsed)

    def test_testbench_only_and_exhaustive_count(self):
        parsed=contract.parse(material(8));tb=contract.render_tb(parsed,'priority_control')
        self.assertEqual(tb.count('R2_PROBE_RESULT'),1)
        self.assertEqual(tb.count('_prioritycheck_checks=_prioritycheck_checks+1'),256)
        self.assertNotIn('module TopModule',tb)
        with self.assertRaises(AssertionError):contract.render_tb(parsed,'bad"id')

    def test_non_priority_is_skip(self):self.assertEqual(contract.parse('Implement a mux.')['status'],'skip')


if __name__=='__main__':unittest.main()
