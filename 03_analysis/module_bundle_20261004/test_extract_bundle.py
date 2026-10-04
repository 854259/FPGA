"""Observable format preservation and refusal boundaries for helper recovery."""
import importlib.util
from pathlib import Path
import unittest

from extract_bundle import extract_bundle


def load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


ROOT = Path(__file__).resolve().parent.parent
baseline = load("frozen_baseline", ROOT / "ross_diagnostic_repair_20261004/baseline_extract.py")
selector = load("lexical_mask", ROOT / "natural_coverage_20261004/signedness_selector.py")
TOP = "module TopModule(input a, output y); Helper h(.a(a),.y(y)); endmodule"
HELPER = "module Helper(input a,output y); assign y=a; endmodule"


class BundleTests(unittest.TestCase):
    def run_reply(self, text):
        return extract_bundle(text, baseline, selector._strip_noncode)

    def refused(self, text, reason):
        source, receipt = self.run_reply(text)
        self.assertEqual(source, baseline.extract(text, "rtl"))
        self.assertFalse(receipt["changed"])
        self.assertEqual(receipt["reason"], reason)

    def test_unfenced_helpers_preserved(self):
        source, receipt = self.run_reply(TOP + "\n" + HELPER)
        self.assertIn(TOP, source)
        self.assertIn(HELPER, source)
        self.assertTrue(receipt["changed"])

    def test_separate_fences_helper_first(self):
        source, receipt = self.run_reply("```sv\n" + HELPER + "\n```\nThen:\n```verilog\n" + TOP + "\n```")
        self.assertTrue(source.startswith("module TopModule"))
        self.assertIn(HELPER, source)
        self.assertEqual(receipt["dependency_edges"]["TopModule"], ["Helper"])

    def test_nested_parameter_expression_and_instance_array(self):
        top = "module TopModule(input a,output y); Helper #(.W((1+1))) h[0:0](.a(a),.y(y)); endmodule"
        helper = "module Helper #(parameter W=2)(input a,output y);assign y=a;endmodule"
        source, receipt = self.run_reply(top + "\n" + helper)
        self.assertIn(helper, source)
        self.assertTrue(receipt["changed"])

    def test_comment_keywords_do_not_create_modules(self):
        source, receipt = self.run_reply("/* module Fake endmodule */" + TOP + "// endmodule\n" + HELPER)
        self.assertTrue(receipt["changed"])
        self.assertIn(HELPER, source)

    def test_string_keywords_do_not_create_modules(self):
        helper = 'module Helper(input a,output y);assign y=a; localparam NOTE="module endmodule";endmodule'
        self.assertTrue(self.run_reply(TOP + "\n" + helper)[1]["changed"])

    def test_single_top_byte_behavior_unchanged(self):
        text = "```sv\n// lead\nmodule TopModule(input a,output y);assign y=a;endmodule\n```"
        self.refused(text, "single_top_baseline_preserved")

    def test_duplicate_top_abstains(self):
        self.refused(TOP + "\n" + TOP + "\n" + HELPER, "top_module_not_unique")

    def test_duplicate_helper_abstains(self):
        self.refused(TOP + "\n" + HELPER + "\n" + HELPER, "duplicate_helper_name")

    def test_unlinked_module_abstains(self):
        self.refused(TOP + "\n" + HELPER + "\nmodule Alternative();endmodule", "unreferenced_helper_or_alternative")

    def test_recursive_bundle_abstains(self):
        helper = "module Helper(input a,output y); TopModule loop(.a(a),.y(y));endmodule"
        self.refused(TOP + "\n" + helper, "recursive_module_bundle")

    def test_incomplete_module_abstains(self):
        self.refused(TOP + "module Helper(input a);", "incomplete_module")

    def test_nested_module_abstains(self):
        self.refused("module TopModule(); module Helper();endmodule endmodule", "nested_or_unpaired_module")

    def test_unclosed_comment_abstains(self):
        self.refused(TOP + HELPER + "/*", "unclosed_comment_or_string")

    def test_unclosed_string_abstains(self):
        self.refused(TOP + 'module Helper();initial $display("oops);endmodule', "unclosed_comment_or_string")

    def test_unclosed_fence_abstains(self):
        self.refused("```sv\n" + TOP + HELPER, "unclosed_fence")

    def test_fragment_in_another_fence_abstains(self):
        self.refused("```sv\nassign x=y;\n```\n```sv\n" + TOP + HELPER + "\n```", "code_outside_complete_modules")

    def test_macro_scope_abstains(self):
        self.refused('`define WIDTH 1\n' + TOP + HELPER, "unsupported_scope_or_directive")

    def test_other_language_fence_abstains(self):
        self.refused("```python\nprint(1)\n```\n```sv\n" + TOP + HELPER + "\n```", "unsupported_fence_language")

    def test_automatic_module_abstains(self):
        self.refused(TOP + "\nmodule automatic Helper(input a,output y);assign y=a;endmodule", "unsupported_module_declaration")


if __name__ == "__main__":
    unittest.main()
