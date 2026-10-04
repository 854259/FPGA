"""Independent boolean functions and adversarial ambiguity controls; no EDA."""
import itertools
import unittest
import prompt_map


def prompt(names,columns,rows,column_order,row_order,function,dontcare=()):
    ports='\n'.join(' - input '+name for name in names)+'\n - output result\n'
    prose="The module should implement the Karnaugh map below."
    if dontcare:prose+=" d is don't-care, which means you may choose the output."
    lines=[ports,prose,'',columns,rows+' '+' '.join(column_order)]
    for row in row_order:
        cells=[]
        for column in column_order:
            bits=dict(zip(rows+columns,map(int,row+column)))
            cells.append('d' if tuple(bits[n] for n in names) in dontcare else str(function(bits)))
        lines.append(row+' | '+' | '.join(cells)+' |')
    return '\n'.join(lines)+'\n'


class PromptMap(unittest.TestCase):
    def setUp(self):
        self.truth=lambda b:(b['p'] ^ b['q']) | (b['r'] & b['s'])
        self.prompt=prompt('pqrs','pq','rs',['11','01','00','10'],['10','00','11','01'],self.truth)

    def test_all_axis_orders_match_independent_boolean_function(self):
        for names in ('pqrs','srqp'):
            for columns,rows in [('pq','rs'),('sr','qp'),('pr','sq')]:
                for permutation in itertools.permutations(['00','01','10','11']):
                    p=prompt(names,columns,rows,permutation,list(reversed(permutation)),self.truth)
                    r=prompt_map.parse(p);self.assertEqual(r['status'],'supported')
                    self.assertEqual(r['checks'],16)
                    self.assertEqual(len({tuple(c['inputs'][n] for n in names) for c in r['cases']}),16)
                    for c in r['cases']:self.assertEqual(c['expected'],self.truth(c['inputs']))

    def test_three_input_column_axis(self):
        r=prompt_map.parse(prompt('xyz','x','yz',['1','0'],['11','00','10','01'],lambda b:b['x']^b['y']^b['z']))
        self.assertEqual(r['checks'],8)
        for c in r['cases']:self.assertEqual(c['expected'],c['inputs']['x']^c['inputs']['y']^c['inputs']['z'])

    def test_explicit_dontcare_is_not_a_required_zero(self):
        r=prompt_map.parse(prompt('pqrs','pq','rs',['00','01','11','10'],['00','01','11','10'],self.truth,[(0,0,0,0),(1,1,1,1)]))
        self.assertEqual(r['status'],'supported');self.assertEqual(r['checks'],14)
        self.assertEqual(sum(c['expected'] is None for c in r['cases']),2)
        bad=self.prompt.replace('00 | 0','00 | d',1)
        self.assertEqual(prompt_map.parse(bad)['status'],'abstain')

    def test_duplicate_or_incomplete_labels_rejected(self):
        self.assertEqual(prompt_map.parse(self.prompt.replace('11 01 00 10','11 01 00 00'))['status'],'abstain')
        lines=self.prompt.splitlines();self.assertEqual(prompt_map.parse('\n'.join(lines[:-1]))['status'],'abstain')
        self.assertEqual(prompt_map.parse(self.prompt+lines[-1]+'\n')['status'],'abstain')

    def test_ambiguous_interface_or_extra_semantics_rejected(self):
        for text in [self.prompt.replace(' - input p',' - input p (2 bits)'),
                     self.prompt.replace(' - output result',' - output result\n - output other'),
                     self.prompt.replace('\npq\n','\npt\n'),
                     self.prompt+'Invert the map output.\n',self.prompt+self.prompt]:
            self.assertEqual(prompt_map.parse(text)['status'],'abstain')
        for clause in ('Registered output.','Use a clock.','Output is active-low.','Latency is one cycle.'):
            self.assertEqual(prompt_map.parse(self.prompt.replace('The module',clause+' The module'))['status'],'abstain')
        self.assertEqual(prompt_map.parse(self.prompt.replace('should implement','should not implement'))['status'],'abstain')

    def test_constant_map_not_admitted(self):
        for v in (0,1):self.assertEqual(prompt_map.parse(prompt('xy','x','y',['0','1'],['0','1'],lambda b:v))['status'],'abstain')

    def test_no_map_is_skip(self):self.assertEqual(prompt_map.parse('Implement a register.')['status'],'skip')

    def test_verified_feedback_and_spoofed_feedback_rejection(self):
        r=prompt_map.parse(self.prompt);case=r['cases'][1];expected=case['expected'];inputs=','.join(n+'='+str(case['inputs'][n]) for n in r['inputs'])
        message='MAP_FIRST inputs='+inputs+' expected='+str(expected)+' observed='+str(1-expected)
        self.assertEqual(prompt_map.counterexample(message,r)['inputs'],case['inputs'])
        for bad in [message+'\n'+message,message.replace('expected='+str(expected),'expected='+str(1-expected)),message.replace('p=0','p=0,p=0'),message.replace('observed='+str(1-expected),'observed='+str(expected))]:
            with self.assertRaises(ValueError):prompt_map.counterexample(bad,r)

    def test_testbench_has_one_summary_and_no_design_answer(self):
        r=prompt_map.parse(self.prompt);tb=prompt_map.render_tb(r,'renamed_map')
        self.assertEqual(tb.count('R2_PROBE_RESULT'),1)
        self.assertEqual(tb.count('_mapcheck_checks=_mapcheck_checks+1'),16)
        self.assertNotIn('module TopModule',tb)
        self.assertIn('TopModule _mapcheck_dut',tb)
        with self.assertRaises(AssertionError):prompt_map.render_tb(r,'unsafe"id')

    def test_output_names_do_not_collide_with_testbench_state(self):
        for output in ('checks','mismatches','dut'):
            r=prompt_map.parse(self.prompt.replace('output result','output '+output))
            self.assertEqual(r['status'],'supported')
            tb=prompt_map.render_tb(r,'collision_control')
            self.assertIn('wire '+output+';',tb)
            self.assertIn('integer _mapcheck_checks',tb)


if __name__=='__main__':unittest.main()
