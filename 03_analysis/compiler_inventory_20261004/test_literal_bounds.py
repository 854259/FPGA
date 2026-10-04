import importlib.util
from pathlib import Path
import unittest

from literal_bounds import inspect

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("inventory_mask", ROOT / "lexical_mask.py")
mask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mask)


def check(body):
    return inspect("module TopModule;\n" + body + "\nendmodule", mask._strip_noncode)


class BoundsTests(unittest.TestCase):
    def test_direct_high_select(self):
        r = check("logic [7:0] carry;\nassign q=carry[8];")
        self.assertEqual([(h["index"], h["line"]) for h in r["hints"]], [(8, 3)])

    def test_valid_extremes(self):
        self.assertEqual(check("reg [7:0] q;\nassign y=q[0]^q[7];")["hints"], [])

    def test_ascending_range(self):
        r = check("wire [0:3] q;\nassign y=q[4];")
        self.assertEqual(r["hints"][0]["range_high"], 3)

    def test_negative_range(self):
        self.assertEqual(check("wire [-1:-4] q;\nassign y=q[0];")["hints"][0]["index"], 0)

    def test_comments_and_strings_are_not_selects(self):
        self.assertEqual(check('wire [1:0] q;\n// q[9]\n/* q[8] */\ninitial $display("q[7]");')["hints"], [])

    def test_dynamic_and_part_selects_unsupported(self):
        self.assertEqual(check("wire [7:0] q;\nassign y=q[i+1]^q[9:8];")["hints"], [])

    def test_ports_are_not_internal_declarations(self):
        self.assertEqual(check("output logic [1:0] q;\nassign y=q[5];")["declarations"], 0)

    def test_duplicate_names_are_ambiguous(self):
        self.assertEqual(check("wire [1:0] q;\nbegin wire [9:0] q; end\nassign y=q[5];")["hints"], [])

    def test_hierarchical_reference_is_not_local(self):
        self.assertEqual(check("wire [1:0] q;\nassign y=child.q[5];")["hints"], [])

    def test_multiple_modules_keep_separate_ranges(self):
        r = inspect("module TopModule;\nwire [1:0] q;\nassign y=q[5];\nendmodule\nmodule H;\nwire [9:0] q;\nassign y=q[5];\nendmodule", mask._strip_noncode)
        self.assertEqual([h["module"] for h in r["hints"]], ["TopModule"])

    def test_signed_internal_vector(self):
        self.assertEqual(check("reg signed [7:0] q;\nassign y=q[8];")["hints"][0]["signal"], "q")

    def test_parameterized_range_unsupported(self):
        self.assertEqual(check("wire [W-1:0] q;\nassign y=q[8];")["declarations"], 0)

    def test_nested_function_scope_skipped(self):
        r = check("wire [1:0] q;\nfunction f; f=q[9]; endfunction")
        self.assertEqual(r["skipped_scopes"], 1)
        self.assertEqual(r["hints"], [])

    def test_unclosed_comment_refused(self):
        self.assertEqual(check("wire [1:0] q; /*")["status"], "unclosed_noncode")

    def test_directives_refused(self):
        self.assertEqual(check("`define W 8\nwire [7:0] q;\nassign y=q[8];")["status"], "unsupported_directive")

    def test_unpaired_module_refused(self):
        self.assertEqual(inspect("module TopModule; wire q;", mask._strip_noncode)["status"], "unpaired_modules")


if __name__ == "__main__":
    unittest.main()
