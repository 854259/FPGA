import random
import unittest
import context


def large(suffix='', newline='\n'):
    return ('// ordinary explanation ' + 'x'*90 + newline)*80 + suffix


class Context(unittest.TestCase):
    def test_large_comments_preserve_exact_code_and_line_positions(self):
        code=large('module X; assign a = 1; endmodule\n')
        result,m=context.compress(code)
        self.assertTrue(m['changed']); self.assertEqual(result,'\n'*80+'module X; assign a = 1; endmodule\n')

    def test_short_or_code_dominant_comments_are_retained(self):
        for code in ['// short\nmodule X;endmodule',large('assign y= a;\n'*1000)]:
            self.assertEqual(context.compress(code)[0],code)

    def test_literal_and_escaped_identifier_markers_remain(self):
        suffix='module X; initial $display("// /* ` \\\" marker"); wire \\//not_a_comment ; endmodule\n'
        code=large(suffix); result,m=context.compress(code)
        self.assertTrue(m['changed']);self.assertTrue(result.endswith(suffix))

    def test_crlf_and_inline_comments_remain_exact(self):
        suffix='module X; // inline\r\nendmodule\r\n'
        code=large(suffix,'\r\n');result,m=context.compress(code)
        self.assertTrue(m['changed']);self.assertEqual(result,'\r\n'*80+suffix)

    def test_directives_and_incomplete_lexical_units_abstain(self):
        for suffix in ['`define X 1\n','`__LINE__','/* explanation */',
                       '// synthesis translate_off\n','// pragma coverage_off\n',
                       '// verilator lint_off\n','// continued \\\n',
                       '"unfinished','"newline\n"','"escaped\\','\\unfinished','\\\n']:
            with self.subTest(suffix=suffix):
                code=large(suffix);result,m=context.compress(code)
                self.assertFalse(m['changed']);self.assertEqual(result,code)

    def test_comment_delimiters_and_quotes_in_comment_are_not_code(self):
        code=large()+'// ordinary quote " ` /* not directive\nmodule X;endmodule\n'
        result,m=context.compress(code);self.assertTrue(m['changed'])
        self.assertEqual(result,'\n'*81+'module X;endmodule\n')

    def test_random_compositions_keep_projection_and_idempotence(self):
        rng=random.Random(20261005)
        pieces=['assign x=1;\n','initial $display("//notcomment");\n',
                'wire \\a//b ;\n','assign y = 2; // small\n',
                '// ordinary detail\n','\t// ordinary detail\n']
        for n in range(300):
            code=large()+''.join(rng.choice(pieces) for _ in range(20))
            result,m=context.compress(code);self.assertTrue(m['changed'])
            before,_=context.comment_spans(code);after,_=context.comment_spans(result)
            self.assertEqual(context.projection(code,before),context.projection(result,after))
            self.assertEqual(context.compress(result)[0],result)


if __name__=='__main__':unittest.main()
