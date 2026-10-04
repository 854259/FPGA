import unittest
from feedback import normalize,messages


def trace(previous=1,data=0,time_ps=5000,bit=0):
    return f"FIRST_MISMATCH time_ps={time_ps} load=0 data={data:0128x} previous_q={previous:0128x} bit={bit} expected_q_bit=0 observed_q_bit=1"


class FeedbackTests(unittest.TestCase):
    def test_zero_and_low_bit_round_trip(self):
        r=normalize(trace());self.assertEqual(r["data_set_bits"],[]);self.assertEqual(r["previous_set_bits"],[0]);self.assertEqual(r["time_ns"],"5")

    def test_high_bit_not_dropped(self):
        r=normalize(trace((1<<511)|(1<<17),data=1<<510,bit=511))
        self.assertEqual(r["previous_set_bits"],[17,511]);self.assertEqual(r["data_set_bits"],[510])

    def test_fractional_time_is_exact(self):
        self.assertEqual(normalize(trace(time_ps=1501))["time_ns"],"1.501")

    def test_unknown_vector_does_not_become_zero(self):
        with self.assertRaises(ValueError):normalize(trace().replace("data="+"0"*128,"data="+"0"*127+"x"))

    def test_width_and_index_changes_are_rejected(self):
        with self.assertRaises(ValueError):normalize(trace(bit=512))
        with self.assertRaises(ValueError):normalize(trace().replace("previous_q="+"0"*127+"1","previous_q=1"))

    def test_pass_has_no_invented_failure(self):
        r=messages(1085440,0,None);self.assertEqual(r["A"],r["B"]);self.assertIsNone(r["normalized"])
        with self.assertRaises(ValueError):messages(1085440,0,trace())


if __name__=="__main__":unittest.main()
