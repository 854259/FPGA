"""Pure text-factor boundaries; no model, tool, network or archive execution."""
import unittest
import guidance


ERROR = "ERROR: [VRFC 10-3818] variable 'observed_signal' is driven by invalid combination of procedural drivers [/owned/candidate.sv:7]"


class GuidanceTests(unittest.TestCase):
    def test_real_error_appends_once_and_preserves_every_original_character(self):
        original='prefix\r\n'+ERROR+'\r\nERROR: [XSIM 43-3322] Static elaboration failed.\r\n'
        result=guidance.augment_diagnostics(original)
        self.assertEqual(result,original+guidance.APPENDIX)
        self.assertTrue(result.startswith(original))

    def test_repeated_application_is_idempotent(self):
        first=guidance.augment_diagnostics(ERROR)
        self.assertEqual(guidance.augment_diagnostics(first),first)
        self.assertEqual(first.count(guidance.APPENDIX),1)

    def test_multiple_actual_signal_errors_get_one_generic_hint(self):
        original=ERROR+'\n'+ERROR.replace('observed_signal','second_observed')
        result=guidance.augment_diagnostics(original)
        self.assertEqual(result.count(guidance.APPENDIX),1)
        self.assertIn("'observed_signal'",result)
        self.assertIn("'second_observed'",result)
        self.assertNotIn('observed_signal',guidance.APPENDIX)
        self.assertNotIn('second_observed',guidance.APPENDIX)

    def test_warning_info_fatal_and_plain_prose_are_unchanged(self):
        for severity in ['WARNING','INFO','FATAL','FATAL_ERROR','']:
            with self.subTest(severity=severity):
                original=ERROR.replace('ERROR:',severity+':' if severity else '')
                self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_other_error_codes_are_unchanged(self):
        for code in ['10-1280','10-38180','10-9336','43-3322']:
            with self.subTest(code=code):
                original=ERROR.replace('10-3818',code)
                self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_same_code_without_required_message_is_unchanged(self):
        for text in ['synthetic unrelated native issue','invalid combination of drivers',
                     'procedural drivers are mentioned only']:
            original='ERROR: [VRFC 10-3818] '+text
            self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_code_and_message_on_different_lines_do_not_trigger(self):
        original='ERROR: [VRFC 10-3818] unrelated\nWARNING: invalid combination of procedural drivers'
        self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_inline_quoted_error_is_not_a_native_error_line(self):
        for prefix in ['assign x = "','// ','example: ']:
            original=prefix+ERROR
            self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_empty_and_no_error_text_are_unchanged(self):
        for original in ['', ' \t\r\n','INFO: successful candidate elaboration\n']:
            self.assertEqual(guidance.augment_diagnostics(original),original)

    def test_whitespace_in_actual_severity_and_code_is_supported(self):
        original=ERROR.replace('ERROR: [VRFC ','\t ERROR:\t[VRFC\t')
        self.assertEqual(guidance.augment_diagnostics(original),original+guidance.APPENDIX)

    def test_long_original_diagnostics_are_never_deleted_or_truncated(self):
        original=('WARNING: retained noise\n'*3000)+ERROR+'\n'+'retained tail'*1000
        result=guidance.augment_diagnostics(original)
        self.assertEqual(result[:len(original)],original)
        self.assertEqual(len(result),len(original)+len(guidance.APPENDIX))

    def test_partial_guidance_marker_cannot_suppress_the_actual_hint(self):
        original=ERROR+'\n[Procedural-writer repair guidance]'
        self.assertEqual(guidance.augment_diagnostics(original),original+guidance.APPENDIX)

    def test_non_text_input_rejected_without_guessing(self):
        for value in [None, b'ERROR', [], {}]:
            with self.subTest(type=type(value).__name__):
                with self.assertRaises(TypeError):guidance.augment_diagnostics(value)


if __name__=='__main__':unittest.main()
