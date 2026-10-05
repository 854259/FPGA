"""Pure/synthetic checks only: 0 real model calls, 0 EDA, no quality qualification.

The copied original prompt and generated complete transcripts/TB remain ignored
raw evidence. No control RTL, hidden harness, answer, or task ID is parser input.
"""
import copy
import hashlib
import json
import platform
import re
import sys
import unittest
from pathlib import Path

import native_reset_contract as n
import inventory


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw_evidence"
RUN = "10501050105010501050105010501050"
PROMPT_SHA = "b55622d75576a72d6a5b321a592cc78c2a554dbc0da9e385d35b519fb6f535dc"


def original():
    prompt = (RAW / "input.prompt").read_text(encoding="utf-8")
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != PROMPT_SHA:
        raise ValueError("public prompt fixture binding changed")
    return prompt


def synthetic_trace(c, control="correct", run_id=RUN):
    """Independent discrete-event controls; never claim these are RTL execution."""
    clock, reset_n, data, memory, rise, fall = 0, 1, 0, 0, 0, 0
    delayed_rise, delayed_fall = 0, 0
    lines = [f'NRC_BEGIN {n._prefix(c, run_id)} observations={c["checks"]}']
    mismatch_count = 0
    first = None
    for row in c["observations"]:
        old_clock, old_reset = clock, reset_n
        for key, value in row["changes"].items():
            if key == "clock":
                clock = value
            elif key == "reset_n":
                reset_n = value
            elif key == "input":
                data = value
        asserted = old_reset == 1 and reset_n == 0
        positive = old_clock == 0 and clock == 1
        negative = old_clock == 1 and clock == 0
        if asserted and control not in ("reset_ignored", "synchronous_reset"):
            if control != "clear_falling_only":
                rise = 0
            if control != "clear_rising_only":
                fall = 0
            if control != "history_sync_only":
                memory = 0
            delayed_rise = delayed_fall = 0
        edge = negative if control == "falling_clock" else positive
        if edge:
            if reset_n == 0 and control != "reset_ignored":
                rise = fall = memory = delayed_rise = delayed_fall = 0
            else:
                # Bitwise identity is an alternative pure correct control.
                new_rise, new_fall = data & (1 - memory), memory & (1 - data)
                if control == "swapped":
                    new_rise, new_fall = new_fall, new_rise
                if control == "stretched_two_cycles":
                    rise, fall = new_rise | delayed_rise, new_fall | delayed_fall
                    delayed_rise, delayed_fall = new_rise, new_fall
                else:
                    rise, fall = new_rise, new_fall
                memory = data
        if control == "half_cycle" and negative:
            rise = fall = 0
        if control == "constant_zero":
            rise = fall = 0
        if control == "constant_one":
            rise = fall = 1
        observed_rise, observed_fall = str(rise), str(fall)
        if control == "unknown_x" and row["index"] == 20:
            observed_rise = "x"
        if control == "unknown_z" and row["index"] == 20:
            observed_fall = "z"
        lines.append(n._observation_prefix(row) +
                     f" observed_rising={observed_rise} observed_falling={observed_fall}")
        for role, observed in (("rising", observed_rise), ("falling", observed_fall)):
            expected = row["expected_" + role]
            if observed != str(expected):
                mismatch_count += 1
                if first is None:
                    first = dict(index=row["index"], output=c["roles"][role],
                                 expected=expected, observed=observed)
                    lines.append(f'NRC_FIRST index={row["index"]} output={c["roles"][role]} '
                                 f'expected={expected} observed={observed}')
    lines.append(f'NRC_END {n._prefix(c, run_id)} observations={c["checks"]} mismatches={mismatch_count}')
    return "\n".join(lines) + "\n"


class NativeResetDraft(unittest.TestCase):
    """All methods and subtests are pure/synthetic, 0 model/0 EDA."""
    def setUp(self):
        self.prompt = original()
        self.c = n.parse(self.prompt)
        self.assertEqual(self.c["status"], "supported")

    def reject_prompt(self, prompt):
        self.assertEqual(n.parse(prompt)["status"], "abstain")

    def reject_log(self, log):
        with self.assertRaises(ValueError):
            n.observations(log, self.c, RUN)

    def test_original_complete_roles_and_semantics(self):
        self.assertEqual(self.c["module"], "sync_pos_neg_edge_detector")
        self.assertEqual(self.c["roles"], dict(clock="i_clk", reset="i_rstb", data="i_detection_signal",
                                             rising="o_positive_edge_detected", falling="o_negative_edge_detected"))
        self.assertEqual({key: self.c[key] for key in n.SEMANTICS}, n.SEMANTICS)
        self.assertEqual(self.c["prompt_sha256"], PROMPT_SHA)

    def test_names_renamed_from_meaning_and_preserved_case(self):
        renamed = self.prompt
        names = dict(sync_pos_neg_edge_detector="PulseTracker", i_clk="SampleClock",
                     i_rstb="ClearLow", i_detection_signal="CleanData",
                     o_positive_edge_detected="WentHigh", o_negative_edge_detected="WentLow")
        for old, new in names.items():
            renamed = renamed.replace(old, new)
        c = n.parse(renamed)
        self.assertEqual(c["status"], "supported")
        self.assertEqual(c["module"], "PulseTracker")
        self.assertEqual(c["roles"], dict(clock="SampleClock", reset="ClearLow", data="CleanData",
                                         rising="WentHigh", falling="WentLow"))
        tb = n.render_tb(c, RUN)
        self.assertIn("PulseTracker _nrc_dut(.SampleClock(_nrc_clock),.ClearLow(_nrc_reset_n)", tb)
        self.assertNotIn("TopModule", tb)
        self.assertEqual(n.observations(synthetic_trace(c), c, RUN)["status"], "semantic_pass")
        ce = n.counterexample(synthetic_trace(c, "swapped"), c, RUN)
        self.assertIn(ce["first_output"], ("WentHigh", "WentLow"))
        self.assertEqual((ce["rising_output"], ce["falling_output"]), ("WentHigh", "WentLow"))

    def test_reordered_ports_and_behavior_keep_meaning(self):
        lines = self.prompt.splitlines()
        a = next(i for i, x in enumerate(lines) if x.startswith("- `i_clk`"))
        lines[a:a + 3] = list(reversed(lines[a:a + 3]))
        b = next(i for i, x in enumerate(lines) if x.startswith("- `o_positive"))
        lines[b:b + 2] = list(reversed(lines[b:b + 2]))
        c = next(i for i, x in enumerate(lines) if x.startswith("- When the module detects"))
        lines[c:c + 2] = list(reversed(lines[c:c + 2]))
        parsed = n.parse("\n".join(lines))
        self.assertEqual(parsed["roles"], self.c["roles"])
        self.assertEqual(parsed["observations"], self.c["observations"])

    def test_scalar_explicit_wording_and_markdown_whitespace(self):
        variants = [self.prompt.replace("Glitch-free, debounced signal", f"Glitch-free, debounced {word} signal")
                    for word in ("single-bit", "scalar", "1-bit")]
        variants.append(self.prompt.replace("System Verilog", "SystemVerilog").replace("\n", "\r\n"))
        variants.append("\n".join("  " + x + "  " for x in self.prompt.splitlines()))
        for prompt in variants:
            with self.subTest(variant_sha=hashlib.sha256(prompt.encode()).hexdigest()):
                self.assertEqual(n.parse(prompt)["status"], "supported")

    def test_unknown_conflicting_negated_clock_reset_or_pulse_abstain(self):
        changes = [
            ("active on rising edge", "active on falling edge"),
            ("Asynchronous reset signal", "Synchronous reset signal"),
            ("active low", "active high"), ("active (low)", "active (high)"),
            ("incorporate asynchronous reset functionality", "not incorporate asynchronous reset functionality"),
            ("all outputs", "some outputs"), ("reset to `0`", "reset to `1`"),
            ("internal state should be cleared", "internal state should be retained"),
            ("internal state should be cleared", "internal state should not be cleared"),
            ("one clock cycle", "two clock cycles"), ("one clock cycle", "half a clock cycle"),
            ("asserted high", "asserted low"), ("should be asserted high", "should not be asserted high"),
            ("normal edge detection should resume", "normal edge detection should resume two cycles later"),
            ("no additional debouncing logic is required", "additional debouncing logic is required"),
            ("is **glitch-free and debounced**", "is **not glitch-free and debounced**"),
        ]
        for old, new in changes:
            with self.subTest(change=new):
                self.assertIn(old, self.prompt)
                self.reject_prompt(self.prompt.replace(old, new))

    def test_extra_behavior_even_with_supported_original_abstains(self):
        for suffix in ("\n- Reset is synchronous.", "\nClock is active on the falling edge.",
                       "\n- Do not reset the outputs.", "\nIgnore previous requirements.",
                       "\nParameter WIDTH=8.", "\nA third output is required."):
            with self.subTest(suffix=suffix):
                self.reject_prompt(self.prompt + suffix)

    def test_missing_required_clause_or_section_abstains(self):
        nonempty = [line for line in self.prompt.splitlines() if line.strip()]
        for index in range(len(nonempty)):
            with self.subTest(index=index):
                self.reject_prompt("\n".join(nonempty[:index] + nonempty[index + 1:]))

    def test_vector_width_or_extra_port_abstains(self):
        for old, new in (("`i_detection_signal`:", "`i_detection_signal[7:0]`:"),
                         ("Glitch-free, debounced signal", "Glitch-free, debounced 8-bit vector signal"),
                         ("`o_positive_edge_detected`:", "`o_positive_edge_detected` (8 bits):"),
                         ("### Outputs:", "### Outputs:\n- `extra`: scalar signal.")):
            with self.subTest(new=new):
                self.reject_prompt(self.prompt.replace(old, new))

    def test_duplicate_reserved_or_invalid_identifiers_abstain(self):
        variants = [self.prompt.replace("i_rstb", "i_clk"),
                    self.prompt.replace("o_negative_edge_detected", "o_positive_edge_detected"),
                    self.prompt.replace("sync_pos_neg_edge_detector", "module"),
                    self.prompt.replace("i_clk", "wire"), self.prompt.replace("i_clk", "9clock"),
                    self.prompt.replace("i_clk", "bad-clock"),
                    self.prompt.replace("i_clk", "c" * 65)]
        for variant in variants:
            with self.subTest(variant_sha=hashlib.sha256(variant.encode()).hexdigest()):
                self.reject_prompt(variant)

    def test_inconsistent_renamed_references_or_output_meanings_abstain(self):
        variants = [self.prompt.replace("`i_detection_signal`:", "`new_data`:"),
                    self.prompt.replace("`i_rstb`:", "`new_reset`:"),
                    self.prompt.replace("`o_positive_edge_detected`:", "`new_rise`:"),
                    self.prompt.replace("output `o_positive_edge_detected`", "output `o_negative_edge_detected`"),
                    self.prompt.replace("`i_detection_signal`, the output", "`I_detection_signal`, the output"),
                    self.prompt.replace("positive edge is detected on", "negative edge is detected on")]
        for variant in variants:
            with self.subTest(variant_sha=hashlib.sha256(variant.encode()).hexdigest()):
                self.reject_prompt(variant)

    def test_unbalanced_or_interior_markup_never_changes_native_names(self):
        variants = [self.prompt.replace("`i_clk`", "i_`clk`"),
                    self.prompt.replace("`i_clk`", "`i_`clk"),
                    self.prompt.replace("asynchronous reset functionality", "**asy**nchronous reset functionality"),
                    self.prompt.replace("**one clock cycle**", "**one clock cycle", 1),
                    self.prompt.replace("`i_detection_signal`", "`i_detection_signal", 1),
                    self.prompt.replace("`i_rstb`", "i_**rstb**")]
        for variant in variants:
            with self.subTest(variant_sha=hashlib.sha256(variant.encode()).hexdigest()):
                self.reject_prompt(variant)

    def test_module_quote_forms_preserve_original_quirk_and_reject_other_mismatches(self):
        original_token = '"`' + self.c["module"] + '`'
        for token in (self.c["module"], '`' + self.c["module"] + '`',
                      '"' + self.c["module"] + '"', "'" + self.c["module"] + "'",
                      original_token + '"'):
            with self.subTest(token=token):
                self.assertEqual(n.parse(self.prompt.replace(original_token, token))["status"], "supported")
        for token in ('"' + self.c["module"], self.c["module"] + '"',
                      "'" + self.c["module"] + '"', '"' + self.c["module"] + "'",
                      "'`" + self.c["module"] + '`'):
            with self.subTest(token=token):
                self.reject_prompt(self.prompt.replace(original_token, token))

    def test_skip_non_edge_and_refuse_nontext_or_oversize(self):
        self.assertEqual(n.parse("A two-input Boolean gate.")["status"], "skip")
        with self.assertRaises(TypeError):
            n.parse({"prompt": self.prompt})
        self.reject_prompt(self.prompt + "\x00")
        self.reject_prompt(self.prompt + " " * 32769)

    def test_zero_release_only_and_two_prime_edges(self):
        rows = self.c["observations"]
        releases = [i for i, row in enumerate(rows) if row["changes"].get("reset_n") == 1]
        self.assertEqual(len(releases), 3)
        for i in releases:
            with self.subTest(release=i):
                self.assertEqual((rows[i]["input"], rows[i]["clock"]), (0, 0))
                self.assertEqual([row["clock"] for row in rows[i + 1:i + 5]], [1, 0, 1, 0])
                self.assertTrue(all(row["input"] == 0 for row in rows[i + 1:i + 5]))

    def test_both_high_pulses_get_async_low_clock_reset(self):
        rows = self.c["observations"]
        for role in ("rising", "falling"):
            with self.subTest(role=role):
                i = next(i for i, row in enumerate(rows) if row["phase"] == f"async_reset_during_{role}_pulse")
                self.assertEqual(rows[i - 1]["expected_" + role], 1)
                self.assertEqual((rows[i - 1]["clock"], rows[i]["clock"]), (0, 0))
                self.assertEqual(rows[i]["changes"], {"reset_n": 0})
                self.assertEqual((rows[i]["expected_rising"], rows[i]["expected_falling"]), (0, 0))

    def test_high_memory_is_reset_without_active_reset_clock(self):
        rows = self.c["observations"]
        i = next(i for i, row in enumerate(rows) if row["phase"] == "async_reset_during_rising_pulse")
        self.assertEqual(rows[i - 1]["remembered_input"], 1)
        self.assertEqual(rows[i]["remembered_input"], 0)
        self.assertTrue(all(row["clock"] == 0 for row in rows[i:i + 3]))
        self.assertEqual(rows[i + 3]["expected_falling"], 0)

    def test_every_transition_has_setup_posedge_negedge_and_both_outputs(self):
        rows = [row for row in self.c["observations"] if row["phase"].startswith("transition_")]
        self.assertEqual(len(rows), 36)
        for index in range(12):
            with self.subTest(step=index):
                group = rows[index * 3:index * 3 + 3]
                self.assertEqual([row["phase"] for row in group], [f"transition_{index}_{p}" for p in ("setup", "posedge", "negedge")])
                self.assertEqual([row["clock"] for row in group], [0, 1, 0])
                self.assertTrue(all("expected_rising" in row and "expected_falling" in row for row in group))

    def test_native_tb_matches_every_bound_observation(self):
        tb = n.render_tb(self.c, RUN)
        self.assertEqual(tb.count('$display("NRC_OBS '), self.c["checks"])
        self.assertEqual(tb.count("_nrc_checks=_nrc_checks+1;"), self.c["checks"])
        self.assertIn("sync_pos_neg_edge_detector _nrc_dut(", tb)
        self.assertIn("observed_rising=%b observed_falling=%b", tb)
        self.assertIn('if(_nrc_mismatches!=0) $fatal(1,"SEMANTIC_MISMATCH");', tb)
        self.assertIn('WATCHDOG_EXPIRED', tb)
        self.assertNotIn("TopModule", tb)
        (RAW / "generated_tb.sv").write_bytes(tb.encode("utf-8"))

    def test_probe_signal_names_do_not_alias_native_port_names(self):
        prompt = self.prompt
        for old, new in zip(self.c["roles"].values(), ("_nrc_clock", "_nrc_checks", "_nrc_data", "_nrc_rise", "_nrc_fall")):
            prompt = prompt.replace(old, new)
        c = n.parse(prompt)
        self.assertEqual(c["status"], "supported")
        tb = n.render_tb(c, RUN)
        self.assertIn("._nrc_checks(_nrc_reset_n)", tb)

    def test_native_module_name_may_equal_legal_port_name(self):
        for role in n.ROLE_NAMES:
            with self.subTest(role=role):
                prompt = self.prompt.replace(self.c["module"], self.c["roles"][role])
                c = n.parse(prompt)
                self.assertEqual(c["status"], "supported")
                self.assertEqual(c["module"], c["roles"][role])
                self.assertIn(c["module"] + " _nrc_dut(", n.render_tb(c, RUN))
                self.assertEqual(n.observations(synthetic_trace(c), c, RUN)["status"], "semantic_pass")

    def test_all_schedule_data_assignments_low_and_both_actuals_retained(self):
        check = inventory.schedule_binding(self.c)
        self.assertEqual(check["observations"], 69)
        self.assertEqual(check["retained_scalar_actual_values"], 138)
        self.assertTrue(check["all_data_assignments_clock_low"])
        self.assertTrue(check["all_data_changes_clock_low"])
        self.assertTrue(check["both_actual_outputs_retained"])
        result = n.observations(synthetic_trace(self.c), self.c, RUN)
        previous_data = 0
        for expected, actual in zip(self.c["observations"], result["observations"]):
            with self.subTest(index=expected["index"]):
                if "input" in expected["changes"] or expected["input"] != previous_data:
                    self.assertEqual(expected["clock"], 0)
                previous_data = expected["input"]
                self.assertEqual(actual["observed_rising"], str(expected["expected_rising"]))
                self.assertEqual(actual["observed_falling"], str(expected["expected_falling"]))
                self.assertEqual(actual["rising_output"], self.c["roles"]["rising"])
                self.assertEqual(actual["falling_output"], self.c["roles"]["falling"])

    def test_inventory_passes_only_prompt_and_metadata_cannot_decide_support(self):
        calls = []

        def watched(prompt):
            self.assertIs(type(prompt), str)
            calls.append(prompt)
            return n.parse(prompt)

        records = [dict(id=identifier, input=dict(prompt=self.prompt, context=object()),
                        output=object(), hidden_harness=object(), answer=object())
                   for identifier in ("arbitrary_metadata_A", "unrelated_metadata_B")]
        bindings = inventory.inspect_records(records, parse_fn=watched)
        self.assertEqual(calls, [self.prompt, self.prompt])
        self.assertEqual([b["status"] for b in bindings], ["supported", "supported"])
        self.assertEqual(bindings[0]["roles"], bindings[1]["roles"])
        self.assertEqual(bindings[0]["module"], bindings[1]["module"])
        self.assertNotIn("hidden_harness", bindings[0])
        self.assertNotIn("answer", bindings[0])
        self.assertNotIn("context", bindings[0])
        self.assertNotIn("prompt", bindings[0])

    def test_inventory_refuses_duplicate_json_and_wrong_prompt_result_binding(self):
        with self.assertRaises(ValueError):
            json.loads('{"key":1,"key":2}', object_pairs_hook=inventory.unique_object)
        with self.assertRaises(ValueError):
            inventory.inspect_records([dict(id="binding_only", input=dict(prompt=None))])
        with self.assertRaises(ValueError):
            inventory.inspect_records([dict(id="binding_only", input=dict(prompt="A different edge prompt."))],
                                      parse_fn=lambda prompt: self.c)

    def test_correct_synthetic_trace_and_no_counterexample(self):
        log = synthetic_trace(self.c)
        result = n.observations("Simulator banner\n" + log + "finish status\n", self.c, RUN)
        self.assertEqual(result["status"], "semantic_pass")
        self.assertEqual(result["mismatches"], 0)
        self.assertEqual(len(result["observations"]), self.c["checks"])
        self.assertIsNone(result["first"])
        with self.assertRaises(ValueError):
            n.counterexample(log, self.c, RUN)
        (RAW / "synthetic_correct.trace.txt").write_bytes(log.encode("utf-8"))
        (RAW / "synthetic_correct.observations.json").write_text(json.dumps(
            dict(synthetic_only=True, actual_model_calls=0, actual_eda_calls=0,
                 quality_qualification=False, parsed=result), indent=2), encoding="utf-8")

    def test_all_meaningful_negative_synthetic_controls_detected(self):
        controls = ("reset_ignored", "synchronous_reset", "history_sync_only", "clear_rising_only",
                    "clear_falling_only", "swapped", "constant_zero", "constant_one",
                    "stretched_two_cycles", "half_cycle", "falling_clock")
        evidence = []
        for control in controls:
            with self.subTest(control=control):
                log = synthetic_trace(self.c, control)
                result = n.observations(log, self.c, RUN)
                ce = n.counterexample(log, self.c, RUN)
                self.assertGreater(result["mismatches"], 0)
                self.assertEqual(result["status"], "semantic_mismatch")
                self.assertEqual(ce["complete_observations"], result["observations"])
                self.assertEqual(ce["checks"], self.c["checks"])
                self.assertEqual(ce["mismatches"], result["mismatches"])
                self.assertIn(ce["first_output"], ce["mismatched_outputs"])
                self.assertNotEqual(str(ce["first_expected"]), ce["first_observed"])
                (RAW / f"synthetic_{control}.trace.txt").write_bytes(log.encode("utf-8"))
                (RAW / f"synthetic_{control}.counterexample.json").write_text(json.dumps(
                    dict(synthetic_only=True, actual_model_calls=0, actual_eda_calls=0,
                         quality_qualification=False, control=control, parsed=ce), indent=2), encoding="utf-8")
                evidence.append(dict(control=control, mismatches=result["mismatches"], first=result["first"],
                                     trace_sha256=result["transcript_sha256"], checks=result["checks"]))
        (RAW / "SYNTHETIC_CONTROL_RESULTS.json").write_text(json.dumps(dict(synthetic_only=True, actual_model_calls=0,
             actual_eda_calls=0, quality_qualification=False, controls=evidence), indent=2), encoding="utf-8")

    def test_unknown_values_retained_as_per_output_mismatches(self):
        for control, role, value in (("unknown_x", "rising", "x"), ("unknown_z", "falling", "z")):
            with self.subTest(control=control):
                ce = n.counterexample(synthetic_trace(self.c, control), self.c, RUN)
                self.assertEqual(ce["first_observed"], value)
                self.assertEqual(ce["observed_" + role], value)
                self.assertEqual(ce["first_output"], self.c["roles"][role])
                self.assertEqual(ce["mismatches"], 1)

    def test_full_ordered_observation_removal_duplication_or_reorder_rejected(self):
        log = synthetic_trace(self.c)
        rows = log.splitlines(keepends=True)
        for altered in ("".join(rows[:5] + rows[6:]), "".join(rows[:5] + [rows[5]] + rows[5:]),
                        "".join(rows[:5] + [rows[6], rows[5]] + rows[7:]), log[:log.index("NRC_END")],
                        "".join(rows[:-1]), "".join(rows[1:])):
            with self.subTest(log_sha=hashlib.sha256(altered.encode()).hexdigest()):
                self.reject_log(altered)

    def test_all_expected_metadata_fields_are_bound(self):
        log = synthetic_trace(self.c)
        first = next(line for line in log.splitlines() if line.startswith("NRC_OBS"))
        fields = dict(index="99", phase="invented", time_ns="999", cycle="999", clock="1", reset_n="1", input="1",
                      previous_input="1", remembered_input="1", expected_rising="1", expected_falling="1")
        for field, value in fields.items():
            with self.subTest(field=field):
                changed = re.sub(rf"\b{field}=\S+", field + "=" + value, first)
                self.assertNotEqual(changed, first)
                self.reject_log(log.replace(first, changed, 1))

    def test_invalid_scalar_actual_values_or_marker_format_rejected(self):
        log = synthetic_trace(self.c)
        for value in ("00", "01", "2", "ff", "X", "Z", "1x", "", "nan", "x0"):
            with self.subTest(value=value):
                self.reject_log(log.replace("observed_rising=0", "observed_rising=" + value, 1))
        self.reject_log(log.replace("NRC_OBS ", "Prefix NRC_OBS ", 1))
        self.reject_log(log + "NRC_UNKNOWN ignored\n")

    def test_spoofed_passing_summary_or_unmarked_mismatch_rejected(self):
        failing = synthetic_trace(self.c, "swapped")
        self.reject_log(re.sub(r"mismatches=\d+", "mismatches=0", failing))
        passing = synthetic_trace(self.c)
        self.reject_log(passing.replace("observed_rising=0", "observed_rising=1", 1))
        first = next(line for line in failing.splitlines() if line.startswith("NRC_FIRST"))
        self.reject_log(failing.replace(first + "\n", ""))

    def test_forged_duplicate_or_misplaced_first_marker_rejected(self):
        log = synthetic_trace(self.c, "swapped")
        first = next(line for line in log.splitlines() if line.startswith("NRC_FIRST"))
        altered = [log.replace(first, first + "\n" + first, 1),
                   log.replace(first, first.replace("index=11", "index=999"), 1),
                   log.replace(first, re.sub(r"output=\S+", "output=wrong_port", first), 1),
                   log.replace(first, re.sub(r"expected=[01]", "expected=7", first), 1),
                   log.replace(first, re.sub(r"observed=[01xz]", "observed=7", first), 1),
                   first + "\n" + log.replace(first + "\n", "", 1)]
        for bad in altered:
            with self.subTest(log_sha=hashlib.sha256(bad.encode()).hexdigest()):
                self.assertNotEqual(bad, log)
                self.reject_log(bad)

    def test_run_prompt_binding_duplicate_end_and_wrong_counts_rejected(self):
        log = synthetic_trace(self.c)
        end = log.splitlines()[-1]
        variants = [log.replace(RUN, "f" * 32, 1), log.replace(PROMPT_SHA, "f" * 64, 1),
                    log.replace("observations=" + str(self.c["checks"]), "observations=999", 1),
                    log.replace(end, end.replace("observations=" + str(self.c["checks"]), "observations=999")),
                    log.replace(end, end.replace("mismatches=0", "mismatches=999")), log + end + "\n"]
        for bad in variants:
            with self.subTest(log_sha=hashlib.sha256(bad.encode()).hexdigest()):
                self.reject_log(bad)

    def test_mutated_contract_or_invalid_run_refused(self):
        for mutate in (lambda c: c["roles"].update(reset=c["roles"]["clock"]),
                       lambda c: c.update(module="module"), lambda c: c.update(reset_kind="synchronous"),
                       lambda c: c.update(pulse_cycles=2), lambda c: c.update(checks=0),
                       lambda c: c["observations"].pop(),
                       lambda c: c["observations"][0].update(expected_rising=1),
                       lambda c: c.update(prompt_sha256="wrong"), lambda c: c.update(width=True),
                       lambda c: c.update(pulse_cycles=1.0),
                       lambda c: c["observations"][0].update(clock=False),
                       lambda c: c["observations"][0].update(time_ns=2.0),
                       lambda c: c["observations"][0]["changes"].update(reset_n=False)):
            changed = copy.deepcopy(self.c)
            mutate(changed)
            with self.subTest(mutation=repr(mutate)), self.assertRaises(ValueError):
                n.render_tb(changed, RUN)
        for run_id in ("", "../../escape", "x" * 32, "A" * 32, "a" * 31, "a" * 65, None):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                n.render_tb(self.c, run_id)

    def test_nontext_or_oversize_transcript_refused(self):
        for log in (None, {}, " " * (1024 * 1024 + 1)):
            with self.subTest(log_type=type(log).__name__), self.assertRaises(ValueError):
                n.observations(log, self.c, RUN)

    def test_counterexample_does_not_drop_sibling_output_or_reset_context(self):
        ce = n.counterexample(synthetic_trace(self.c, "synchronous_reset"), self.c, RUN)
        self.assertEqual(ce["phase"], "async_reset_during_rising_pulse")
        self.assertEqual((ce["clock"], ce["reset_n"], ce["input"]), (0, 0, 1))
        self.assertEqual((ce["expected_rising"], ce["expected_falling"]), (0, 0))
        self.assertEqual((ce["observed_rising"], ce["observed_falling"]), ("1", "0"))
        self.assertEqual(ce["checks"], len(ce["complete_observations"]))
        self.assertIn("native provenance requires external receipts", ce["integrity_scope"])


class CountResult(unittest.TextTestResult):
    subtests_run = 0

    def addSubTest(self, test, subtest, outcome):
        self.subtests_run += 1
        super().addSubTest(test, subtest, outcome)


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeResetDraft)
    result = unittest.TextTestRunner(verbosity=2, resultclass=CountResult).run(suite)
    receipt = dict(status="passed" if result.wasSuccessful() else "failed",
                   tests=result.testsRun, subtests=result.subtests_run,
                   failures=len(result.failures), errors=len(result.errors),
                   python=platform.python_version(), synthetic_only=True,
                   actual_model_calls=0, actual_eda_calls=0, fifo_submitted=False,
                   independent_quality_admitted=0, quality_qualification=False, adoption=False,
                   files_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                 for name in ("native_reset_contract.py", "test_native_reset_contract.py", "inventory.py")})
    c = n.parse(original())
    receipt.update(observations_per_trace=c["checks"], scalar_outputs=2,
                   actual_values_per_complete_trace=2 * c["checks"],
                   negative_synthetic_controls=11, unknown_value_controls=2,
                   native_compilation_verified=False)
    (ROOT / "LOCAL_CHECKS.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
