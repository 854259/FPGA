import re
import unittest

from priority import prioritize_stdout


def old_feedback(stdout):
    lines = [line for line in stdout.splitlines() if re.search('ERROR|WARNING|FATAL', line)]
    return '\n'.join(lines)[:2048] or stdout[-2048:]


class PriorityTests(unittest.TestCase):
    def test_warning_only_is_unchanged(self):
        for text in ['', 'banner\r\nWARNING: width\r\n', 'INFO: ERROR label mentioned\n']:
            self.assertEqual(prioritize_stdout(text), text)

    def test_repeated_errors_cannot_hide_distinct_variable(self):
        warnings = ['WARNING: width ' + 'w' * 340] * 5
        repeated = ['ERROR: [VRFC 10-1280] non-register alpha [/owned/candidate.sv:' + str(i) + ']' for i in range(11)]
        hidden = 'ERROR: [VRFC 10-1280] non-register beta [/owned/candidate.sv:40]'
        raw = '\n'.join(warnings + repeated + [hidden])
        self.assertNotIn(hidden, old_feedback(raw))
        result = prioritize_stdout(raw)
        self.assertEqual(result.splitlines()[:2], [repeated[0], hidden])
        self.assertIn(hidden, old_feedback(result))
        self.assertLessEqual(len(old_feedback(result)), 2048)

    def test_distinct_file_code_message_and_variable_remain(self):
        lines = [
            'ERROR: [VRFC 10-1280] non-register alpha [a.sv:1]',
            'ERROR: [VRFC 10-1280] non-register alpha [b.sv:2]',
            'ERROR: [VRFC 10-9999] non-register alpha [a.sv:3]',
            'ERROR: [VRFC 10-1280] other alpha [a.sv:4]',
            'ERROR: [VRFC 10-1280] non-register beta [a.sv:5]',
        ]
        self.assertEqual(prioritize_stdout('\n'.join(lines)).splitlines(), lines)

    def test_unknown_location_and_bit_range_are_not_erased(self):
        lines = ['ERROR: array [3:0]', 'ERROR: array [7:0]',
                 'ERROR: bad [candidate.txt:1]', 'ERROR: bad [candidate.txt:2]']
        self.assertEqual(prioritize_stdout('\n'.join(lines)).splitlines(), lines)

    def test_native_locations_never_rewrite_retained_lines(self):
        first = '  ERROR: [VRFC 10-1] assignment [C:\\owned\\candidate.sv:7:3]'
        second = '  ERROR: [VRFC 10-1] assignment [C:\\owned\\candidate.sv:9:2]'
        self.assertEqual(prioritize_stdout(first + '\n' + second), first)

    def test_fatal_and_nonsevere_keep_original_relative_order(self):
        fatal = 'FATAL: native failed [a.v:2]'
        error = 'ERROR: invalid [a.v:1]'
        self.assertEqual(prioritize_stdout('banner\n' + fatal + '\nWARNING: width\n' + error),
                         fatal + '\n' + error + '\nbanner\nWARNING: width')

    def test_large_unique_errors_still_use_original_cap(self):
        text = '\n'.join('ERROR: [VRFC 10-1] unique ' + str(i) + ' ' + 'x' * 90 for i in range(40))
        self.assertEqual(prioritize_stdout(text), text)
        self.assertEqual(len(old_feedback(prioritize_stdout(text))), 2048)

    def test_reapplication_and_nontext(self):
        text = 'WARNING: x\nERROR: invalid [a.v:1]\nERROR: invalid [a.v:2]'
        once = prioritize_stdout(text)
        self.assertEqual(prioritize_stdout(once), once)
        with self.assertRaises(TypeError):
            prioritize_stdout(None)


if __name__ == '__main__':
    unittest.main()
