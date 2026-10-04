"""Check care-only model information against an independent boolean function."""
import unittest
import prompt_map
import table_feedback
from test_prompt_map import prompt


class FeedbackInformation(unittest.TestCase):
    def test_complete_care_domain_no_design_or_dontcare_guess(self):
        function=lambda b:b['j']^(b['k']&b['l'])^b['n']
        absent={(0,0,0,0),(1,1,1,1)}
        text=prompt('jkln','nk','lj',['01','11','10','00'],['11','00','01','10'],function,absent)
        contract=prompt_map.parse(text)
        case=next(c for c in contract['cases'] if c['expected'] is not None)
        point=dict(inputs=case['inputs'],output='result',expected=case['expected'],observed=str(1-case['expected']))
        info=table_feedback.render(contract,dict(failure_kind='semantic_mismatch',checks=14,mismatches=1),point)
        table=info.split('Required truth table:\n',1)[1].splitlines()
        self.assertEqual(table[0],'j k l n | result')
        self.assertEqual(len(table)-1,14)
        observed={}
        for line in table[1:]:
            left,right=line.split('|');bits=tuple(map(int,left.split()))
            self.assertNotIn(bits,absent)
            self.assertEqual(int(right),function(dict(zip('jkln',bits))))
            self.assertNotIn(bits,observed);observed[bits]=int(right)
        self.assertNotIn('module TopModule',info)
        self.assertNotIn('assign ',info)
        self.assertNotIn('R2Probe',info)


if __name__=='__main__':unittest.main()
