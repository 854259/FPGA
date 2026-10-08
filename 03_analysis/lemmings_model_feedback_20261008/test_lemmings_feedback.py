"""Draft AMD-only controls; artificial logs are not native execution evidence."""
import json
from pathlib import Path
import re
import unittest

import lemmings_feedback as lf

HERE = Path(__file__).resolve().parent


def prompt(variant):
    return (HERE / 'prompts' / (variant + '.txt')).read_text(encoding='utf-8')


def simulated_log(parsed, bad_event=None, output='xxxx'):
    """Only a labelled protocol control. Never use as real model/EDA evidence."""
    lines = ['SIMULATED_PROTOCOL_CONTROL_NOT_NATIVE']
    for row in parsed['rows']:
        observed = output if row['event'] == bad_event else row['expected']
        lines.append(f"LEMMINGS_STEP event={row['event']} kind={row['kind']} clock={row['clock']} "
                     f"reset={row['reset']} left={row['bump_left']} right={row['bump_right']} "
                     f"ground={row['ground']} dig={row['dig']} outputs={observed}")
        if row['event'] == bad_event:
            lines.append(f'LEMMINGS_FIRST event={bad_event}')
    return '\n'.join(lines) + '\n'


class CompleteContractControls(unittest.TestCase):
    def test_three_complete_contracts(self):
        for variant, dig, death in (('walk_fall', False, False), ('dig', True, False), ('death', True, True)):
            with self.subTest(variant=variant):
                parsed = lf.parse(prompt(variant))
                self.assertIsNotNone(parsed)
                self.assertEqual((parsed['contract']['has_dig'], parsed['contract']['has_death']), (dig, death))
                self.assertTrue(parsed['contract']['all_prompt_consumed'])
                self.assertEqual(parsed['checks'], len(parsed['rows']))

    def test_semantically_bound_port_renaming(self):
        text = prompt('death')
        mapping = dict(clk='clock_x', areset='reset_x', bump_left='hit_l', bump_right='hit_r',
                       ground='floor_x', dig='excavate_x', walk_left='moving_l', walk_right='moving_r')
        # Rename identifiers wherever used as identifiers, leaving English words
        # like "dig" and "ground" untouched except their actual port references.
        for old, new in mapping.items():
            if old in ('ground', 'dig'):
                text = re.sub(r'(?m)(- input\s+)' + old + r'\b', lambda m: m[1] + new, text)
                text = re.sub(r'\b' + old + r'(?==)', new, text)
                if old == 'ground':
                    text = re.sub(r'\bground(?=\s+disappears)', new, text)
            else:
                text = re.sub(r'\b' + old + r'\b', new, text)
        parsed = lf.parse(text)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['contract']['clock'], 'clock_x')
        self.assertEqual(parsed['contract']['ground'], 'floor_x')
        self.assertEqual(parsed['contract']['dig'], 'excavate_x')

    def test_reject_ambiguous_or_changed_contracts(self):
        original = prompt('death')
        changes = [
            original + '\nAlso output a pulse before landing.',
            original.replace('more than 20', 'at least 20'),
            original.replace('more than 20', 'more than 19'),
            original.replace('Moore', 'Mealy'),
            original.replace('asynchronous', 'synchronous'),
            original.replace('positive edge triggered asynchronous', 'negative edge triggered asynchronous'),
            original.replace('positive edge of', 'negative edge of'),
            original.replace('fall has higher precedence than dig', 'dig has higher precedence than fall'),
            original.replace('they do not splatter in', 'they splatter in'),
            original.replace('- output aaah', '- output falling'),
            original.replace('- output digging', '- output excavation'),
            original.replace('- input  ground', '- input  ground (2 bits)'),
            original.replace('- input  ground', '- output ground'),
            original.replace('- input  dig', '- input  dig\n - input extra'),
            original.replace('- input  dig', '- input  ground'),
            original.replace('If it\'s bumped on both sides at the same time, it will still switch\ndirections.', ''),
            original.replace('There is no\nupper limit on how far a Lemming can fall before hitting the ground.', ''),
        ]
        # Normalize line wrapping here only to make mutation controls explicit.
        offset = original.index('The game Lemmings')
        body = original[:offset] + ' '.join(original[offset:].split())
        changes.extend([
            body.replace("If it's bumped on both sides at the same time, it will still switch directions.", ''),
            body.replace('Lemmings only splatter when hitting the ground; they do not splatter in mid-air.', ''),
            body.replace('forever (Or until the FSM gets reset).', ''),
        ])
        for i, text in enumerate(changes):
            with self.subTest(change=i):
                self.assertNotEqual(text, original, 'control mutation must actually change the source')
                self.assertIsNone(lf.parse(text))
        self.assertIsNone(lf.parse(None))
        self.assertIsNone(lf.parse('A serial or truth-table prompt, not the complete supported text.'))

    def test_hand_calculated_collisions_and_reset(self):
        for variant in ('walk_fall', 'dig', 'death'):
            parsed = lf.parse(prompt(variant))
            rows = parsed['rows']
            self.assertEqual(rows[0]['kind'], 'async_assert')
            self.assertEqual(rows[0]['clock'], 0)
            self.assertEqual(rows[0]['expected'], '1000')
            collisions = [r['expected'] for r in rows if r['tag'] == 'walking_bump']
            self.assertEqual(collisions, ['1000', '0100', '0100', '1000', '0100', '1000', '0100'])
            for row in rows:
                if row['tag'] in ('reset_release_moore_hold', 'reset_dominates_clock'):
                    self.assertEqual(row['expected'], '1000')

    def test_hand_calculated_complete_interval_boundaries(self):
        for variant in ('walk_fall', 'dig', 'death'):
            rows = lf.parse(prompt(variant))['rows']
            for duration in (1, 19, 20, 21, 31, 32, 40, 64):
                landings = [r['expected'] for r in rows if r['tag'] == f'fall_{duration}_E{duration}_landing']
                wanted = ['0000', '0000'] if variant == 'death' and duration > 20 else ['1000', '0100']
                self.assertEqual(landings, wanted)
                airborne = [r for r in rows if re.fullmatch(f'fall_{duration}_E[0-9]+', r['tag'])]
                self.assertEqual(len(airborne), duration * 2)
                self.assertTrue(all(r['expected'] == '0010' for r in airborne))
            self.assertEqual([r['expected'] for r in rows if re.fullmatch('separate_[12]_landing', r['tag'])],
                             ['1000', '1000'])

    def test_simulated_protocol_exactness(self):
        parsed = lf.parse(prompt('death'))
        log = simulated_log(parsed)
        self.assertIsNone(lf.measured_trace(log, parsed, 0))
        event = next(r['event'] for r in parsed['rows'] if r['tag'] == 'fall_21_E21_landing')
        wrong = simulated_log(parsed, event, '1000')
        point = lf.measured_trace(wrong, parsed, 1)
        self.assertEqual(point['event'], event)
        self.assertEqual(point['expected_outputs'], '0000')
        self.assertEqual(point['observed_outputs'], '1000')
        self.assertIn('each event', lf.feedback_text(point))
        self.assertEqual(point['actual_trace_since_reset'][0]['kind'], 'async_assert')
        for bad in (wrong + 'LEMMINGS_FIRST event=9\n',
                    wrong + 'LEMMINGS_STEP invalid\n',
                    wrong.replace('kind=async_assert', 'kind=posedge', 1),
                    wrong.replace('event=0 ', 'event=1 ', 1),
                    wrong.replace('reset=1 ', 'reset=0 ', 1),
                    wrong.replace('outputs=1000', 'outputs=100', 1)):
            with self.assertRaises(RuntimeError):
                lf.measured_trace(bad, parsed, 1)
        unknown = lf.measured_trace(simulated_log(parsed, 0, 'x000'), parsed, 1)
        self.assertEqual(unknown['observed_outputs'], 'x000')

    def test_tb_is_only_observer_and_instantiation(self):
        for variant in ('walk_fall', 'dig', 'death'):
            parsed = lf.parse(prompt(variant))
            tb = lf.render_tb(parsed, 'SyntheticQualification')
            self.assertIn('module R2Probe;', tb)
            self.assertNotIn('module TopModule', tb)
            self.assertEqual(tb.count('LEMMINGS_STEP event='), parsed['checks'])
            self.assertEqual('.dig(_lf_dig)' in tb, variant != 'walk_fall')
        with self.assertRaises(ValueError):
            lf.render_tb(parsed, 'unsafe " label')


if __name__ == '__main__':
    unittest.main()
