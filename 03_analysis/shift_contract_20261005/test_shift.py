"""Independent bit-array state oracle and ambiguity controls; no model/EDA."""
import unittest
import shift_contract as parser


def material(width=64,clock='clk',load='load',enable='ena',amount='amount',data='data',out='q'):
    return (f'I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.\n'
        f' - input {clock}\n - input {load}\n - input {enable}\n - input {amount} (2 bits)\n - input {data} ({width} bits)\n - output {out} ({width} bits)\n'
        f'The module should implement a {width}-bit arithmetic shift register, with synchronous load. '
        f'The shifter can shift both left and right, and by 1 or 8 bit positions, selected by "{amount}." '
        'Assume the right shift is an arithmetic right shift. Signals are defined as below: '
        f'(1) {load}: Loads shift register with {data}[{width-1}:0] instead of shifting. Active high. '
        f'(2) {enable}: Chooses whether to shift. Active high. '
        f'(3) {amount}: Chooses which direction and how much to shift. '
        "(a) 2'b00: shift left by 1 bit. (b) 2'b01: shift left by 8 bits. "
        "(c) 2'b10: shift right by 1 bit. (d) 2'b11: shift right by 8 bits. "
        f'(4) {out}: The contents of the shifter.\n')


def bit_state(c):
    """Separate implementation: per-bit moves, no signed integer or >>."""
    r=c['roles'];w=c['width'];bits=None;observed=[]
    for step in c['steps']:
        d=step['inputs'];previous=None if bits is None else sum(b*(2**i) for i,b in enumerate(bits))
        if previous is not None:observed.append(previous)
        if d[r['load']]:bits=[(d[r['data']]//(2**i))%2 for i in range(w)]
        elif d[r['enable']]:
            count=1 if d[r['amount']] in (0,2) else 8
            bits=([0]*count+bits[:-count]) if d[r['amount']]<2 else (bits[count:]+[bits[-1]]*count)
        observed.append(sum(b*(2**i) for i,b in enumerate(bits)))
    return observed


class Shift(unittest.TestCase):
    def test_independent_bit_state_matches_every_sampled_observation(self):
        for width in [8,9,16,32,63,64]:
            c=parser.parse(material(width));self.assertEqual(c['status'],'supported')
            self.assertEqual(bit_state(c),[o['expected'] for o in c['observations']])
            self.assertEqual(c['checks'],len(c['steps'])*2-1)

    def test_exact_roles_and_widths(self):
        c=parser.parse(material(16,'clock','capture','run','mode','payload','state'))
        self.assertEqual(c['status'],'supported');self.assertEqual(c['roles']['data'],'payload')
        base=material()
        for text in [base.replace('data (64 bits)','data (63 bits)'),base.replace('amount (2 bits)','amount (3 bits)'),
                     base.replace('input clk','input reset'),base.replace(' - output',' - input reset\n - output'),
                     base.replace('data[63:0]','data[62:0]'),material(7)]:
            self.assertEqual(parser.parse(text)['status'],'abstain')

    def test_unknown_or_contradictory_semantics_abstain(self):
        base=material()
        for text in [base+'Reset asynchronously.',base+'Shift on both clock edges.',base.replace('instead of shifting','after shifting'),
                     base.replace('Active high.','Active low.'),base.replace('right by 8','right by 7'),
                     base.replace('synchronous load','asynchronous load')]:
            self.assertEqual(parser.parse(text)['status'],'abstain')

    def test_tb_full_cycles_stable_checks_no_edge_polarity_assumption(self):
        c=parser.parse(material(64));tb=parser.render_tb(c,'shift_case')
        self.assertEqual(tb.count('_shiftcheck_checks=_shiftcheck_checks+1'),c['checks'])
        self.assertEqual(tb.count('clk=1; #1;'),len(c['steps']))
        self.assertEqual(tb.count('clk=0; #1;'),len(c['steps']))
        self.assertIn("data=64'h8000000000000000",tb)
        self.assertNotIn('posedge',tb);self.assertNotIn('module TopModule',tb)

    def test_counterexample_binds_state_and_rejects_fake_points(self):
        c=parser.parse(material(8));o=next(o for o in c['observations'] if o['expected'])
        msg=f"SHIFT_FIRST step={o['step']} phase={o['phase']} expected={o['expected']:x} observed=00"
        p=parser.counterexample(msg,c);self.assertEqual(p['inputs'],o['inputs']);self.assertEqual(p['previous'],o['previous'])
        for text in [msg+'\n'+msg,msg.replace('expected=', 'expected=ff'),msg.replace('observed=00','observed=100'),msg.replace('step='+str(o['step']),'step=9999')]:
            with self.assertRaises(ValueError):parser.counterexample(text,c)

    def test_load_enable_hold_and_both_signs_are_present(self):
        c=parser.parse(material(64));r=c['roles']
        self.assertTrue(any(s['inputs'][r['load']] and s['inputs'][r['enable']] for s in c['steps']))
        for amount in range(4):
            shifted=[s for s in c['steps'] if not s['inputs'][r['load']] and s['inputs'][r['enable']] and s['inputs'][r['amount']]==amount]
            self.assertTrue(any(s['previous']&(1<<63) for s in shifted));self.assertTrue(any(not(s['previous']&(1<<63)) for s in shifted))

    def test_non_shift_skips(self):self.assertEqual(parser.parse('Implement a mux.')['status'],'skip')


if __name__=='__main__':unittest.main()
