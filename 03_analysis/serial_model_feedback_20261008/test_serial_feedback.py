"""AMD-only pure checker tests; synthetic log fixtures are not native evidence."""
from pathlib import Path
import types
import unittest

import serial_feedback as sf


def prompt(width=3, data=True):
    ports = '- input clock\n- input rst\n- input rx\n- output received\n'
    if data:
        ports += f'- output payload ({width} bits)\n'
    return ('I would like you to implement a module named TopModule with the following\n'
            'interface. All input and output ports are one bit unless otherwise\nspecified.\n\n'
            + ports + '\n' + sf.body_template(width, data, 'payload', 'received', 'word'))


def simulated_log(parsed, bad_cycle=None, bad_done=None, bad_data=None):
    """Deliberately artificial oracle output for parser validation only."""
    lines = []
    n = parsed['contract']['payload_bits']
    for row in parsed['rows']:
        done = str(row['expected_done'])
        data = format(row['expected_data'] or 0, f'0{n}b')
        if row['cycle'] == bad_cycle:
            done = done if bad_done is None else bad_done
            data = data if bad_data is None else bad_data
        lines.append(f"SERIAL_STEP cycle={row['cycle']} reset={row['reset']} input={row['serial_input']} done={done} data={data}")
        if row['cycle'] == bad_cycle:
            lines.append(f"SERIAL_FIRST cycle={row['cycle']}")
    return '\n'.join(lines) + '\n'


class SerialFeedbackTests(unittest.TestCase):
    def test_exact_grammar_and_widths(self):
        for n in (2, 3, 8, 16):
            for data in (False, True):
                p = sf.parse(prompt(n, data))
                self.assertEqual(p['contract']['payload_bits'], n)
                self.assertEqual(bool(p['contract']['data_output']), data)
                self.assertTrue(p['contract']['all_prompt_consumed'])
        self.assertIsNotNone(sf.parse(prompt().replace('Include a active-high', 'Include an active-high')))

    def test_added_or_unsupported_obligations_abstain(self):
        p = prompt()
        for changed in (p + ' Also check parity.', p.replace('3 data bits', '4 data bits'),
                        p.replace('synchronous reset', 'asynchronous reset'),
                        p.replace('least significant bit first', 'most significant bit first'),
                        p.replace('1 stop bit (1)', '2 stop bits (1)'),
                        p.replace('- input rx', '- input rx (2 bits)'),
                        p.replace('- input rx', '- input wire'),
                        p.replace('- input rst', '- input clear'),
                        p.replace('- output received', '- output clock'),
                        p.replace('- input rx', '- input rx\n- input enable'),
                        p.replace('- input rx', '- input clock'), ''):
            self.assertIsNone(sf.parse(changed))

    def test_trace_has_hand_checked_three_bit_protocol_results(self):
        parsed = sf.parse(prompt())
        successes = [(r['cycle'], r['expected_data']) for r in parsed['rows'] if r['expected_done']]
        self.assertEqual(parsed['checks'], 69)
        self.assertEqual(successes, [(8, 0), (13, 7), (18, 1), (23, 4), (28, 5), (45, 6), (54, 1), (66, 4)])
        self.assertEqual(parsed['rows'][40]['serial_input'], 1)
        self.assertEqual(parsed['rows'][40]['expected_done'], 0)
        self.assertEqual(parsed['rows'][48]['reset'], 1)
        self.assertEqual(parsed['rows'][48]['expected_done'], 0)

    def test_measured_late_stop_trace_and_data_mismatch(self):
        parsed = sf.parse(prompt())
        point = sf.measured_trace(simulated_log(parsed, 40, bad_done='1'), parsed, 1)
        self.assertEqual(point['actual_trace_since_reset'][0]['cycle'], 1)
        self.assertEqual(point['actual_trace_since_reset'][-1]['cycle'], 40)
        self.assertEqual(point['expected_done'], 0)
        self.assertIn('observed 1', sf.feedback_text(point))
        data_point = sf.measured_trace(simulated_log(parsed, 18, bad_data='100'), parsed, 1)
        self.assertEqual(data_point['expected_data'], 1)
        self.assertIn('payload=0b001, observed 0b100', sf.feedback_text(data_point))

    def test_unknown_outputs_fail_but_uncared_data_does_not(self):
        parsed = sf.parse(prompt())
        point = sf.measured_trace(simulated_log(parsed, 8, bad_data='xxx'), parsed, 1)
        self.assertEqual(point['observed_data'], 'xxx')
        log = simulated_log(parsed).replace('cycle=2 reset=0 input=1 done=0 data=000',
                                            'cycle=2 reset=0 input=1 done=0 data=xxx')
        self.assertIsNone(sf.measured_trace(log, parsed, 0))

    def test_incomplete_fabricated_or_changed_observations_rejected(self):
        parsed = sf.parse(prompt())
        log = simulated_log(parsed, 40, bad_done='1')
        for changed, count in ((log.replace('cycle=40 reset=0 input=1', 'cycle=40 reset=0 input=0'), 1),
                               ('\n'.join(log.splitlines()[1:]), 1),
                               (log + 'SERIAL_FIRST cycle=40\n', 1), (log, 0),
                               (log.replace('SERIAL_FIRST cycle=40', 'SERIAL_FIRST cycle=39'), 1)):
            with self.assertRaises(RuntimeError):
                sf.measured_trace(changed, parsed, count)

    def test_label_is_not_selection_and_paths_are_guarded(self):
        parsed = sf.parse(prompt())
        a, b = sf.render_tb(parsed, 'ProbeAlpha'), sf.render_tb(parsed, 'ProbeBeta')
        self.assertEqual(a.replace('ProbeAlpha', 'LABEL'), b.replace('ProbeBeta', 'LABEL'))
        for bad in ('../unsafe', 'A"', 'A/b', '1start'):
            with self.assertRaises(ValueError):
                sf.render_tb(parsed, bad)
        for code in ('$display("fake");', '`include "other.sv"', 'module R2Probe; endmodule'):
            self.assertIsNone(sf.check(prompt(), code, Path('unused'), 0, None, 'ProbeAlpha', Path('.')))

    def test_c_keeps_original_and_p_restores_hook_on_failure(self):
        original = lambda *a, **k: 'old feedback'
        def run(args, paired):
            if args.arm == 'C':
                self.assertIs(base.functional_feedback, original)
                return 'original result'
            self.assertIsNot(base.functional_feedback, original)
            self.assertEqual(base.functional_feedback('unsupported', 'RTL', '.', 0, None, 'Safe'), 'old feedback')
            raise RuntimeError('injected worker failure')
        base = types.SimpleNamespace(functional_feedback=original, run_worker=run, ROOT=Path('.'))
        self.assertEqual(sf.run_worker(base, types.SimpleNamespace(arm='C'), None), 'original result')
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            sf.run_worker(base, types.SimpleNamespace(arm='P'), None)
        self.assertIs(base.functional_feedback, original)


if __name__ == '__main__':
    unittest.main()
