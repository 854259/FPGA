"""Synthetic pure positive/negative controls; no model, EDA or corpus access."""
import ast
import inspect
import itertools
import re
import unittest
from unittest.mock import patch

import synthesis

PREAMBLE = ("I would like you to implement a module named TopModule with the following\n"
            "interface. All input and output ports are one bit unless otherwise\n"
            "specified.\n\n")
KMAP = "The module should implement the Karnaugh map below.\n\n"
COMB = ("The module should implement a combinational circuit. Read the simulation\n"
        "waveforms to determine what the circuit does, then implement it.\n\n")
OBSERVATION = "The module can be described by the following simulation waveform:\n\n"
DC = ("The module should implement the Karnaugh map below. d is don't-care,\n"
      "which means you may choose to output whatever value is convenient.\n\n")


def ports(names="abcd", output="out", declaration_order=None):
    decls = [("input", name) for name in names] + [("output", output)]
    if declaration_order is not None:
        decls = [decls[i] for i in declaration_order]
    return "".join(f" - {direction} {name}\n" for direction, name in decls) + "\n"


def map_prompt(order="abcd", columns=("00", "01", "11", "10"),
               row_labels=("00", "01", "11", "10")):
    text = "ab\ncd " + " ".join(columns) + "\n"
    for row in row_labels:
        values = []
        for col in columns:
            a, b, c, d = map(int, col + row)
            values.append(str((a & c) ^ b ^ d))
        text += row + " | " + " | ".join(values) + " |\n"
    return PREAMBLE + ports(order) + KMAP + text


def waveform(statement=COMB):
    text = "time p r answer\n"
    for index, (p, r) in enumerate(itertools.product((0, 1), repeat=2)):
        text += f"{index * 5}ns {p} {r} {p ^ r}\n"
    return PREAMBLE + ports("pr", "answer") + statement + text


def emitted_cases(rtl):
    cases = re.findall(r"([1-4])'b([01]+): ([A-Za-z_][A-Za-z_0-9]*) = 1'b([01]);", rtl)
    return {label: (name, int(value)) for width, label, name, value in cases}


class SynthesisControls(unittest.TestCase):
    def generated(self, prompt):
        result = synthesis.synthesize(prompt)
        self.assertTrue(result["emitted"], result)
        self.assertEqual((result["actual_model_requests"], result["actual_eda_calls"],
                          result["external_io_calls"]), (0, 0, 0))
        self.assertEqual(result["rtl"].count("module TopModule ("), 1)
        self.assertEqual(result["rtl"].count("endmodule"), 1)
        self.assertNotIn("casex", result["rtl"])
        self.assertNotIn("casez", result["rtl"])
        self.assertIn("default: ", result["rtl"])
        return result

    def rejected(self, prompt, reason=None, interface=""):
        result = synthesis.synthesize(prompt, interface)
        self.assertFalse(result["emitted"], result)
        self.assertEqual(result["rtl"], "")
        if reason is not None:
            self.assertEqual(result["reason"], reason)
        return result

    def test_all_declaration_permutations_bind_case_bits(self):
        for permutation in itertools.permutations("abcd"):
            with self.subTest(order=permutation):
                result = self.generated(map_prompt("".join(permutation)))
                self.assertEqual(result["input_bit_order"], list(permutation))
                cases = emitted_cases(result["rtl"])
                self.assertEqual(len(cases), 16)
                for label, (output, value) in cases.items():
                    bits = dict(zip(permutation, map(int, label), strict=True))
                    self.assertEqual(output, "out")
                    self.assertEqual(value, (bits["a"] & bits["c"]) ^ bits["b"] ^ bits["d"])

    def test_all_column_and_row_label_permutations(self):
        for columns in itertools.permutations(("00", "01", "11", "10")):
            for rows in itertools.permutations(("00", "01", "11", "10")):
                with self.subTest(columns=columns, rows=rows):
                    result = self.generated(map_prompt(columns=columns, row_labels=rows))
                    for label, (_, value) in emitted_cases(result["rtl"]).items():
                        a, b, c, d = map(int, label)
                        self.assertEqual(value, (a & c) ^ b ^ d)

    def test_vector_bit_order_and_ansi_width_exact(self):
        prompt = (PREAMBLE + " - input x (4 bits)\n - output f\n\n" + KMAP
                  + "x[0]x[2]\nx[3]x[1] 00 01 11 10\n"
                  + "00 | 0 | 1 | 0 | 1 |\n01 | 1 | 0 | 1 | 0 |\n"
                  + "11 | 0 | 1 | 0 | 1 |\n10 | 1 | 0 | 1 | 0 |\n")
        result = self.generated(prompt)
        self.assertEqual(result["input_bit_order"], ["x[3]", "x[2]", "x[1]", "x[0]"])
        self.assertIn("input [3:0] x", result["rtl"])
        self.assertIn("case ({x[3], x[2], x[1], x[0]})", result["rtl"])
        for label, (_, value) in emitted_cases(result["rtl"]).items():
            x3, x2, x1, x0 = map(int, label)
            self.assertEqual(value, x0 ^ x2 ^ x3 ^ x1)

    def test_output_declaration_position_not_lost(self):
        prompt = waveform().replace(ports("pr", "answer"),
                                   ports("pr", "answer", (2, 1, 0)))
        result = self.generated(prompt)
        self.assertEqual([p["name"] for p in result["interface_ports"]], ["answer", "r", "p"])
        declaration = result["rtl"].split(");", 1)[0]
        self.assertLess(declaration.index("answer"), declaration.index(" r,"))
        self.assertLess(declaration.index(" r,"), declaration.index(" p\n"))
        self.assertEqual(result["input_bit_order"], ["r", "p"])

    def test_explicit_combinational_complete_waveform_and_repeat(self):
        prompt = waveform() + "20ns 0 0 0\n"
        result = self.generated(prompt)
        self.assertEqual(result["complete_assignment_count"], 4)
        self.assertEqual({k: v for k, (_, v) in emitted_cases(result["rtl"]).items()},
                         {"00": 0, "01": 1, "10": 1, "11": 0})

    def test_observation_only_waveform_abstains_despite_parser_admission(self):
        result = self.rejected(waveform(OBSERVATION),
                               "waveform_has_no_explicit_combinational_contract")
        self.assertTrue(result["parser_admitted"])

    def test_explicit_dontcare_only_is_selected_zero(self):
        prompt = (PREAMBLE + ports("ab") + DC
                  + "a\nb 0 1\n0 | d | 1 |\n1 | 0 | d |\n")
        result = self.generated(prompt)
        self.assertEqual(result["care_assignment_count"], 2)
        self.assertEqual(result["dontcare_assignment_count"], 2)
        self.assertEqual({k: v for k, (_, v) in emitted_cases(result["rtl"]).items()},
                         {"00": 0, "01": 0, "10": 1, "11": 0})
        self.assertIn("default: out = 1'bx;", result["rtl"])
        self.rejected(prompt.replace(DC, KMAP))
        self.rejected(prompt.replace("| 1 |", "| d |").replace("| 0 |", "| d |"),
                      "missing_or_inconsistent_care_obligations")

    def test_nonbinary_care_and_unknown_waveform_abstain(self):
        for value in ("x", "z", "?", "2"):
            with self.subTest(value=value):
                self.rejected(map_prompt().replace("| 0 |", f"| {value} |", 1))
                self.rejected(waveform().replace("0ns 0 0 0", f"0ns 0 0 {value}"))

    def test_extra_output_input_and_duplicate_names_abstain(self):
        self.rejected(map_prompt().replace(" - output out", " - output extra\n - output out"))
        self.rejected(map_prompt().replace(" - output out", " - input extra\n - output out"))
        self.rejected(map_prompt().replace(" - input b", " - input a"))
        self.rejected(map_prompt().replace(" - output out", " - output out (2 bits)"))

    def test_missing_duplicate_overlapping_and_out_of_range_axes_abstain(self):
        prompt = map_prompt()
        for bad in (prompt.replace("cd 00", "ad 00"), prompt.replace("ab\ncd", "aa\ncd"),
                    prompt.replace("cd 00 01 11 10", "cd 00 01 11 11"),
                    prompt.replace("10 |", "11 |"), prompt.replace("10 |", "XX |")):
            self.rejected(bad)
        self.rejected((PREAMBLE + " - input x (4 bits)\n - output f\n\n" + KMAP
                       + "x[1]x[2]\nx[3]x[4] 00 01 11 10\n"
                       + "00 | 0 | 1 | 0 | 1 |\n01 | 1 | 0 | 1 | 0 |\n"
                       + "11 | 0 | 1 | 0 | 1 |\n10 | 1 | 0 | 1 | 0 |\n"))

    def test_incomplete_conflicting_or_unconsumed_waveform_abstains(self):
        self.rejected(waveform().replace("15ns 1 1 0\n", ""))
        self.rejected(waveform() + "20ns 0 0 1\n")
        self.rejected(waveform() + "The output is registered.\n")
        self.rejected(waveform().replace("p", "clk"))
        self.rejected(map_prompt() + "Also reset the output on a clock edge.\n")

    def test_reserved_names_and_separate_interface_abstain(self):
        self.rejected(waveform().replace("answer", "always"), "invalid_or_reserved_port_name")
        self.rejected(waveform(), "separate_interface_not_supported",
                      interface="input p; input r; output [1:0] answer;")
        self.rejected(waveform(), "interface_must_be_string", interface=None)
        self.rejected(None)

    def test_raw_prompt_and_interface_hashes_bind_emit_and_abstention(self):
        import hashlib
        prompt = waveform()
        empty = self.generated(prompt)
        whitespace = synthesis.synthesize(prompt, " \n\t")
        self.assertTrue(whitespace["emitted"])
        self.assertEqual(empty["rtl_sha256"], whitespace["rtl_sha256"])
        self.assertNotEqual(empty["interface_sha256"], whitespace["interface_sha256"])
        self.assertEqual(empty["prompt_sha256"], hashlib.sha256(prompt.encode()).hexdigest())
        abstained = self.rejected(prompt, "separate_interface_not_supported", interface="extra")
        self.assertEqual(abstained["prompt_sha256"], empty["prompt_sha256"])
        self.assertEqual(abstained["interface_sha256"], hashlib.sha256(b"extra").hexdigest())
        unsupported = self.rejected(prompt + "Extra text.")
        self.assertEqual(unsupported["prompt_sha256"],
                         hashlib.sha256((prompt + "Extra text.").encode()).hexdigest())

    def test_public_entry_has_no_oracle_parameters_or_external_operations(self):
        self.assertEqual(list(inspect.signature(synthesis.synthesize).parameters),
                         ["prompt", "interface"])
        tree = ast.parse(inspect.getsource(synthesis))
        imports = {n.module if isinstance(n, ast.ImportFrom) else n.names[0].name
                   for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))}
        self.assertTrue(imports <= {"hashlib", "itertools", "json", "re", "contract", "reserved_keywords"})
        with patch("builtins.open", side_effect=AssertionError("unexpected IO")):
            self.generated(waveform())
            self.rejected(waveform(OBSERVATION))


if __name__ == "__main__":
    unittest.main()
