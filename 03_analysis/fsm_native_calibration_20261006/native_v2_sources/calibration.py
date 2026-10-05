"""Unfrozen v2 measurement recipe. Execute/import/tests only on AMD.

This is a new evidence standard, not a relaxation or retry of native71. The
old native71 fatal-returncode gate remains rejected. No model quality is claimed.
"""
import hashlib
import json
import re
import sys
import types
from pathlib import Path, PurePosixPath

TOOLS = ("xvlog", "xelab", "xsim")
PRODUCTION_HASHES = {
    "synthesis.py": "0bddeb3480e260bcd9f23e68e215510c9894e4d56e1ae3cb99662312b7b2160d",
    "narrative_spec.py": "648f550d72c89f5997be322660ef17e7ae59261b2a388df36ff8e9d68d6c9898",
    "narrative_keywords.py": "b2d174387bd14c9c9e59432331ae52c66de5f6bf00fb6c417a31f8e2d60cd6f2",
}
PREPARATION_BINDING_SHA = "fc1de2ebb005880e229d1076c7200b4faeef1fdc6e66426d5d161801ec1f1a9b"
NATIVE_RECIPE_SHA = "826cd483d0f417f0a36399c45ec3a076836cea1388106264c5161334c6081650"
PAIRED_SHA = "78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c"
PROTECTED_HELPER_SHA = "53507373aa69e54ccd083a6452fb7acaa0cdbc144d2bdf0e01710b21cfd5ed1a"
CASE_NAMES = ("walking_falling", "walking_falling_digging")
TRANSPORTS = ("pass_then_fatal", "finish_without_pass", "wrong_pass_count",
              "duplicate_pass", "owned_scratch_source_mutation")
MUTATION_BYTES = b"\n// owned-scratch-only deliberate post-xsim calibration mutation\n"
EXPECTED_NATIVE_BY_TOOL = dict(xvlog=36, xelab=35, xsim=34)
PLANNED = dict(semantic_variants=24, transport_variants=10, eda_failure_variants=2,
               supervisor_probes=2, total_controls=38, native_variants=36,
               native_commands=105, owned_supervisor_commands=2,
               semantic_observations=2160, transport_observations=850,
               full_trace_observations=3010)
EXPECTED_GUARDS = 2*(PLANNED["native_commands"]+PLANNED["owned_supervisor_commands"])+2
ENV_ERROR = re.compile(r"error while loading shared libraries|cannot open shared object|"
                       r"license checkout failed|no valid license|failed to initialize.*(?:license|runtime)|"
                       r"segmentation fault|symbol lookup error", re.I)
FATAL = re.compile(r"\bfatal\b|\$fatal|FSM_TRANSPORT_FATAL_AFTER_PASS", re.I)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def file_sha(path):
    return sha(Path(path).read_bytes())


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    """Exclusive immutable evidence files; caller never resamples an existing run."""
    with Path(path).open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2)+"\n").encode())


def contained(root, relative):
    require(type(relative) is str and "\\" not in relative, "POSIX relative asset name required")
    rel = PurePosixPath(relative)
    require(not rel.is_absolute() and rel.parts and all(x not in ("..", ".", "") for x in rel.parts)
            and ":" not in relative, "unsafe relative asset")
    root = Path(root).resolve()
    path = root
    for part in rel.parts:
        path = path/part
        require(not path.is_symlink(), "symlink asset forbidden")
        require(not hasattr(path, "is_junction") or not path.is_junction(), "junction asset forbidden")
    require(path.resolve().is_relative_to(root), "asset escaped packet")
    return path


def _load_recipe(case_root):
    """Compile pinned source bytes only on AMD; no path-based dependency guessing."""
    names = ("narrative_keywords", "narrative_spec", "synthesis", "native_fixtures")
    hashes = PRODUCTION_HASHES | {"native_fixtures.py": NATIVE_RECIPE_SHA}
    prior = {name: sys.modules.get(name) for name in names}
    modules = {}
    try:
        for name in names:
            path = contained(case_root, name+".py")
            data = path.read_bytes()
            require(sha(data) == hashes[name+".py"], "pinned recipe changed: "+name)
            module = types.ModuleType(name)
            module.__file__ = str(path)
            sys.modules[name] = module
            exec(compile(data, str(path), "exec"), module.__dict__)
            modules[name] = module
        return modules
    finally:
        for name in names:
            if prior[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior[name]


def _extra_steps(has_dig):
    """Literal reset obligations, independent of the production transition code."""
    left, right, falling = ("1000", "0100", "0010") if has_dig else ("100", "010", "001")
    steps = [("tick", left, falling, (0, 0, 0, 0), "enter reachable left FALL before reset"),
             ("reset", "asynchronous reset from left FALL")]
    if has_dig:
        steps += [("tick", left, left, (0, 0, 1, 0), "restore shared walking context after left FALL reset"),
                  ("tick", left, "0001", (0, 0, 1, 1), "enter reachable left DIG before reset"),
                  ("reset", "asynchronous reset from left DIG"),
                  ("tick", left, falling, (0, 0, 0, 0), "force shared FALL recovery after left DIG reset check"),
                  ("tick", falling, left, (0, 0, 1, 0), "land in shared WALK before right FALL reset")]
    else:
        steps += [("tick", left, left, (0, 0, 1, 0), "restore shared WALK after left FALL reset check")]
    steps += [("tick", left, right, (1, 0, 1, 0), "reach WALK right before right FALL reset"),
              ("tick", right, falling, (0, 0, 0, 0), "enter reachable right FALL before reset"),
              ("reset", "asynchronous reset from right FALL must clear direction")]
    if has_dig:
        steps += [("tick", left, left, (0, 0, 1, 0), "recover WALK after right FALL reset check"),
                  ("reset", "synchronize WALK direction before independent right DIG check"),
                  ("tick", left, right, (1, 0, 1, 0), "reach WALK right before right DIG reset"),
                  ("tick", right, "0001", (0, 0, 1, 1), "enter reachable right DIG before reset"),
                  ("reset", "asynchronous reset from right DIG must clear direction")]
    return steps


def _expected_rows(control, roles, count):
    """Expand literal old clause trajectories, not producer transition/output code."""
    has_dig = bool(roles["dig"])
    left = "1000" if has_dig else "100"
    falling = "0010" if has_dig else "001"
    digging = "0001"
    rows = []
    def observation(expected, phase, clause, clock, reset, bl, br, ground, dig):
        rows.append(dict(index=len(rows)+1, expected=expected, phase=phase, clause=clause,
                         inputs=dict(clock=clock, reset=reset, bump_left=bl, bump_right=br,
                                     ground=ground, dig=dig if has_dig else 0)))
    def reset_block(clause):
        for phase, clock, reset in [("async_assert_clock_low", 0, 1),
                                    ("reset_dominates_positive_edge", 1, 1),
                                    ("reset_release_no_clock_edge", 1, 0),
                                    ("negative_edge_no_advance", 0, 0)]:
            observation(left, phase, clause, clock, reset, 1, 1, 0, 1 if has_dig else 0)
    def tick(before, after, values, clause):
        observation(before, "before_positive_edge", clause, 0, 0, *values)
        observation(after, "after_positive_edge", clause, 1, 0, *values)
        observation(after, "after_negative_edge", clause, 0, 0, *values)
    reset_block("initial complete asynchronous reset")
    previous = left
    for row in control["clause_obligations"]:
        bits = row["inputs"]
        values = (bits["bump_left"], bits["bump_right"], bits["ground"], bits["dig"] or 0)
        tick(previous, row["packed_expected"], values, row["clause"])
        previous = row["packed_expected"]
    reset_block("old final walking reset preserved")
    require(len(rows) == control["expected_check_count"], "old observation expansion changed")
    for step in _extra_steps(has_dig):
        if step[0] == "reset":
            reset_block(step[1])
        else:
            tick(*step[1:])
    require(len(rows) == count, "new full trajectory count mismatch")
    return rows


def _measurement_tb(control, roles, rows):
    """Derive v2 TB transparently; old frozen fixture bytes stay untouched."""
    old = control["fixture_sv"]
    width = len(rows[0]["expected"])
    outputs = [roles["left"], roles["right"], roles["fall_output"]]+([roles["digging"]] if roles["dig"] else [])
    packed = "{"+", ".join(outputs)+"}"
    # Original declaration order in both pinned original fixtures is bound below.
    require(packed in old, "original output packing not bound")
    start = old.index("task check_outputs;")
    end = old.index("endtask", start)+len("endtask")
    old_task = old[start:end]
    require(old_task.count("$fatal(") == 1 and "checks = checks + 1;" in old_task,
            "old observation procedure shape changed")
    dig = roles["dig"] if roles["dig"] else "1'b0"
    args = ", ".join(["checks", "expected", packed, roles["clock"], roles["reset"],
                     roles["bump_left"], roles["bump_right"], roles["ground"], dig])
    task = (
        "task check_outputs;\n    input ["+str(width-1)+":0] expected;\n    begin\n"
        "        checks = checks + 1;\n"
        '        $display("FSM_TRACE check=%0d expected=%b actual=%b clock=%b reset=%b bump_left=%b bump_right=%b ground=%b dig=%b", '+args+");\n"
        "        if ("+packed+" !== expected) begin\n"
        "            mismatches = mismatches + 1;\n"
        '            $display("FSM_FAIL check=%0d expected=%b actual=%b", checks, expected, '+packed+");\n"
        "        end\n    end\nendtask")
    tb = old[:start]+task+old[end:]
    require(tb.count("integer checks = 0;") == 1, "old check declaration changed")
    tb = tb.replace("integer checks = 0;", "integer checks = 0;\ninteger mismatches = 0;")
    old_tail = '    $display("NARRATIVE_CONTROL_PASS checks=%0d", checks);\n    $finish;'
    require(tb.count(old_tail) == 1, "old terminal procedure changed")
    extra = []
    for step in _extra_steps(bool(roles["dig"])):
        extra.append("    // v2: "+step[-1])
        if step[0] == "reset":
            extra.append("    asynchronous_reset;")
        else:
            _, before, after, values, clause = step
            extra.append("    tick("+", ".join(map(str, values))+", "+str(width)+"'b"+before+", "+str(width)+"'b"+after+");")
    extra += [
        '    $display("FSM_DONE checks=%0d mismatches=%0d", checks, mismatches);',
        '    if (mismatches == 0) $display("FSM_PASS checks=%0d", checks);',
        "    $finish;",
    ]
    return tb.replace(old_tail, "\n".join(extra))


def _ignore_reset_source(positive, reset_name, activity):
    needle = "    if ("+reset_name+") begin _nfc_activity <= WALK; _nfc_right <= 0; end"
    require(positive.count(needle) == 1, "independent sentinel reset source changed")
    replacement = ("    if ("+reset_name+") begin\n"
                   "        if (!(_nfc_activity === "+activity+")) begin\n"
                   "            _nfc_activity <= WALK; _nfc_right <= 0;\n"
                   "        end\n    end")
    return positive.replace(needle, replacement)


def _retain_reset_direction_source(positive, reset_name, activity):
    """Independent fault: clear activity on reset, but wrongly keep right memory."""
    needle = "    if ("+reset_name+") begin _nfc_activity <= WALK; _nfc_right <= 0; end"
    require(positive.count(needle) == 1, "independent reset-direction source changed")
    replacement = ("    if ("+reset_name+") begin\n"
                   "        _nfc_activity <= WALK;\n"
                   "        if (!(_nfc_activity === "+activity+")) _nfc_right <= 0;\n"
                   "    end")
    return positive.replace(needle, replacement)


def describe_cases(case_root):
    """Replay pinned old preparation; create only new generic-root v2 recipes."""
    case_root = Path(case_root)
    binding = read(contained(case_root, "PREPARATION_BINDING.json"))
    require(file_sha(contained(case_root, "PREPARATION_BINDING.json")) == PREPARATION_BINDING_SHA,
            "old 44-file binding changed")
    require(len(binding["private_files"]) == 44, "old preparation inventory changed")
    for name, value in binding["private_files"].items():
        require(file_sha(contained(case_root, name)) == value["sha256"], "old input bytes changed: "+name)
    modules = _load_recipe(case_root)
    emission = modules["synthesis"]
    fixture_recipe = modules["native_fixtures"]
    descriptions = []
    for case, prompt_name, checks in [
        (CASE_NAMES[0], "Prob142_lemmings2.prompt.txt", 55),
        (CASE_NAMES[1], "Prob152_lemmings3.prompt.txt", 115),
    ]:
        prompt = contained(case_root, "fixtures/"+prompt_name).read_bytes().decode("utf-8")
        receipt = emission.synthesize(prompt, "")
        original_receipt = read(contained(case_root, "prepared/"+case+"/synthesis_receipt.json"))
        require(receipt == original_receipt and receipt["emitted"], "exact production emission replay")
        control = fixture_recipe.prepare(prompt, "")
        original_control = read(contained(case_root, "prepared/"+case+"/native_control_preparation.json"))
        require(control == original_control and control["prepared"], "exact independent control replay")
        roles = receipt["contract"]["roles"]
        expected = _expected_rows(control, roles, checks)
        tb = _measurement_tb(control, roles, expected)
        source_map = {"producer": receipt["rtl"]} | control["controls"]
        extra = {"ignore_reset_while_falling": ("FALL", [39, 52] if not roles["dig"] else [69, 95])}
        if roles["dig"]:
            extra["ignore_reset_while_digging"] = ("DIG", [79, 112])
        for name, (activity, indices) in extra.items():
            source_map[name] = _ignore_reset_source(control["controls"]["positive"], roles["reset"], activity)
        directions = {"retain_direction_on_fall_reset": ("FALL", [52] if not roles["dig"] else [95])}
        if roles["dig"]:
            directions["retain_direction_on_dig_reset"] = ("DIG", [112])
        for name, (activity, indices) in directions.items():
            source_map[name] = _retain_reset_direction_source(control["controls"]["positive"], roles["reset"], activity)
        required = dict(stuck_zero=[1], wrong_front_bump=[6], lost_fall_direction=[21],
                        landing_bump=[21], synchronous_reset=[1], negative_clock_edge=[4],
                        bump_before_dig=[33], dig_not_sticky=[36])
        required.update({name: values[1] for name, values in extra.items()})
        required.update({name: values[1] for name, values in directions.items()})
        for variant, source in source_map.items():
            kind = "producer_positive" if variant == "producer" else "sentinel_positive" if variant == "positive" else "semantic_negative"
            descriptions.append(dict(label=case+"__"+variant, case=case, variant=variant, kind=kind,
                                     source=source, tb=tb, expected_observations=expected,
                                     required_mismatch_indices=required.get(variant, []),
                                     prompt_sha256=receipt["prompt_sha256"], expected_native_tools=list(TOOLS)))
        for transport in TRANSPORTS:
            altered = tb
            pass_line = '    if (mismatches == 0) $display("FSM_PASS checks=%0d", checks);'
            require(altered.count(pass_line) == 1, "measurement PASS source not unique")
            if transport == "pass_then_fatal":
                altered = altered.replace("    $finish;", '    $display("FSM_TRANSPORT_FATAL_AFTER_PASS");\n    $fatal(1, "FSM_TRANSPORT_FATAL_AFTER_PASS");')
            elif transport == "finish_without_pass":
                altered = altered.replace(pass_line, "    // deliberately finish without PASS")
            elif transport == "wrong_pass_count":
                altered = altered.replace(pass_line, '    if (mismatches == 0) $display("FSM_PASS checks=%0d", checks + 1);')
            elif transport == "duplicate_pass":
                altered = altered.replace(pass_line, pass_line+"\n"+pass_line)
            descriptions.append(dict(label=case+"__"+transport, case=case, variant=transport, kind="transport_refusal",
                                     source=receipt["rtl"], tb=altered, expected_observations=expected,
                                     required_mismatch_indices=[], prompt_sha256=receipt["prompt_sha256"],
                                     expected_native_tools=list(TOOLS)))
    base = descriptions[0]
    descriptions += [
        dict(label="eda_compile_error", case="tool_failure", variant="compile_error", kind="eda_failure",
             source="module TopModule( ;\n", tb=base["tb"], expected_observations=[],
             required_mismatch_indices=[], expected_native_tools=["xvlog"]),
        dict(label="eda_missing_module", case="tool_failure", variant="missing_module", kind="eda_failure",
             source=base["source"], tb=base["tb"], expected_observations=[],
             required_mismatch_indices=[], expected_native_tools=["xvlog", "xelab"]),
        dict(label="supervisor_timeout", case="supervision", variant="timeout", kind="supervisor_probe",
             source="", tb="", expected_observations=[], required_mismatch_indices=[], expected_native_tools=[]),
        dict(label="supervisor_launch_error", case="supervision", variant="launch_error", kind="supervisor_probe",
             source="", tb="", expected_observations=[], required_mismatch_indices=[], expected_native_tools=[]),
    ]
    require(len(descriptions) == PLANNED["total_controls"], "fixed38-control recipe")
    for index, item in enumerate(descriptions):
        item["index"] = index
        item["source_sha256"] = sha(item["source"].encode())
        item["tb_sha256"] = sha(item["tb"].encode())
        item["expected_observations_sha256"] = sha(canonical(item["expected_observations"]).encode())
    require(sum(len(i["expected_observations"]) for i in descriptions) == PLANNED["full_trace_observations"],
            "planned observation count")
    return descriptions


def plan(descriptions):
    rows = [{k: v for k, v in item.items() if k not in ("source", "tb")} for item in descriptions]
    return dict(schema="fsm_native_calibration_case_plan_v2", planned=PLANNED,
                expected_native_by_tool=EXPECTED_NATIVE_BY_TOOL, rows=rows,
                production_hashes=PRODUCTION_HASHES, old_preparation_binding_sha256=PREPARATION_BINDING_SHA,
                legacy_native71_gate_failure_preserved=True,
                legacy_native71_assertion_kind="policy_reference_only_not_reaudit",
                legacy_native71_spec_sha256="cc1abf90fc1e38fbfcaf51df53eab0b47572c532dd8bcc91a334ed4cbfde9d74",
                evidence_standard="full independently bound trace plus physical tool/supervisor/source receipts",
                original_harness=False, model_calls=0, score_gain_measured=False)


TRACE = re.compile(r"FSM_TRACE check=(\d+) expected=([01xz]+) actual=([01xz]+) "
                   r"clock=([01xz]) reset=([01xz]) bump_left=([01xz]) bump_right=([01xz]) ground=([01xz]) dig=([01xz])", re.I)
FAIL = re.compile(r"FSM_FAIL check=(\d+) expected=([01xz]+) actual=([01xz]+)", re.I)
DONE = re.compile(r"FSM_DONE checks=(\d+) mismatches=(\d+)")
PASS = re.compile(r"FSM_PASS checks=(\d+)")


def measure(log, expected):
    """Always retain actual partial counts; completeness never follows rc alone."""
    rows, failures, dones, passes, errors = [], [], [], [], []
    positions = dict(trace=[], failure=[], done=[], passed=[])
    for position, line in enumerate(log.splitlines()):
        line = line.strip()
        if line.startswith("FSM_TRACE"):
            m = TRACE.fullmatch(line)
            if not m:
                errors.append("malformed_trace")
                continue
            n = int(m[1]); want = m[2].lower(); actual = m[3].lower()
            data = dict(zip(("clock", "reset", "bump_left", "bump_right", "ground", "dig"), m.groups()[3:]))
            observed = dict(index=n, logged_expected=want, actual=actual, logged_inputs=data)
            if 1 <= n <= len(expected):
                independent = expected[n-1]
                observed["expected"] = independent["expected"]
                observed["mismatch"] = actual != independent["expected"]
                if want != independent["expected"]:
                    errors.append("logged_expected_not_independent")
                if len(actual) != len(want) or len(actual) != len(independent["expected"]):
                    errors.append("trace_width")
                if data != {k: str(v) for k, v in independent["inputs"].items()}:
                    errors.append("physical_stimulus_not_expected")
            else:
                errors.append("trace_index_outside_plan")
                observed["mismatch"] = None
            rows.append(observed); positions["trace"].append(position)
        elif line.startswith("FSM_FAIL"):
            m = FAIL.fullmatch(line)
            if m:
                failures.append(dict(index=int(m[1]), expected=m[2].lower(), actual=m[3].lower()))
                positions["failure"].append(position)
            else:
                errors.append("malformed_fail")
        elif line.startswith("FSM_DONE"):
            m = DONE.fullmatch(line)
            if m:
                dones.append(dict(checks=int(m[1]), mismatches=int(m[2])))
                positions["done"].append(position)
            else:
                errors.append("malformed_done")
        elif line.startswith("FSM_PASS"):
            m = PASS.fullmatch(line)
            if m:
                passes.append(int(m[1])); positions["passed"].append(position)
            else:
                errors.append("malformed_pass")
    mismatched = [r for r in rows if r.get("mismatch") is True]
    indices = [r["index"] for r in mismatched]
    if [r["index"] for r in rows] != list(range(1, len(expected)+1)):
        errors.append("partial_repeated_or_reordered_trace")
    exact_failures = [dict(index=r["index"], expected=r["expected"], actual=r["actual"]) for r in mismatched]
    if failures != exact_failures:
        errors.append("FAIL_not_exact_actual_mismatches")
    trace_positions = {row["index"]: position for row, position in zip(rows, positions["trace"])}
    for failed, position in zip(failures, positions["failure"]):
        at = trace_positions.get(failed["index"])
        following = [p for p in positions["trace"]+positions["done"] if at is not None and p > at]
        if at is None or not at < position < min(following, default=len(log.splitlines())):
            errors.append("FAIL_not_immediately_after_own_trace")
    if dones != [dict(checks=len(expected), mismatches=len(mismatched))]:
        errors.append("DONE_not_unique_exact_count")
    if positions["trace"] and positions["done"] and max(positions["trace"]) >= positions["done"][0]:
        errors.append("DONE_before_trace_end")
    if positions["passed"] and positions["done"] and min(positions["passed"]) <= positions["done"][0]:
        errors.append("PASS_before_DONE")
    fatal = bool(FATAL.search(log))
    generic_failure = bool(re.search(r"\bfail(?:ed|ure)?\b|^\s*ERROR\s*:", log, re.I | re.M))
    env_error = bool(ENV_ERROR.search(log))
    complete = not errors and not env_error
    return dict(schema="fsm_native_full_trace_measurement_v2", observations=rows,
                actual_trace_count=len(rows), expected_trace_count=len(expected),
                actual_mismatch_count=len(mismatched), mismatch_indices=indices,
                first_mismatch=mismatched[0] if mismatched else None, observed_FAIL=failures,
                DONE=dones, PASS=passes, fatal_found=fatal, environment_error=env_error,
                generic_failure_found=generic_failure,
                transport_fatal_markers=sum(line.strip() == "FSM_TRANSPORT_FATAL_AFTER_PASS" for line in log.splitlines()),
                errors=errors, measurement_complete=complete,
                positive_log_admissible=complete and not indices and passes == [len(expected)] and not fatal and not generic_failure,
                negative_log_admissible=complete and bool(indices) and not passes and not fatal and not generic_failure)


def clean_command(command):
    return (type(command.get("returncode")) is int and 0 <= command["returncode"] <= 255 and command.get("timeout") is False
            and command.get("launch_error") is None and command.get("remaining_live_group") == [])


def probe_identity_valid(identity):
    if type(identity) is not dict or identity.get("schema") != "fsm_owned_supervisor_probe_identity_v2":
        return False
    values = [identity.get(key) for key in ("owner", "child")]
    if any(type(value) is not dict or set(value) != {"pid", "starttime", "pgid"} for value in values):
        return False
    for value in values:
        if not (type(value["pid"]) is int and value["pid"] > 1 and type(value["pgid"]) is int
                and type(value["starttime"]) is str and value["starttime"].isdigit()):
            return False
    owner, child = values
    return owner["pid"] != child["pid"] and owner["pid"] == owner["pgid"] == child["pgid"]


def probe_cleanup_valid(evidence):
    if type(evidence) is not dict or not probe_identity_valid(evidence.get("identity")):
        return False
    after = evidence.get("after")
    if not (type(evidence.get("identity_sha256")) is str and re.fullmatch("[0-9a-f]{64}", evidence["identity_sha256"])
            and type(after) is dict and set(after) == {"owner", "child"}
            and evidence.get("both_original_processes_absent") is True):
        return False
    for key, value in after.items():
        if not (type(value) is dict and set(value) == {"original_process_absent", "observed"}
                and value["original_process_absent"] is True):
            return False
        observed = value["observed"]
        if observed is not None and not (
                type(observed) is dict and set(observed) == {"state", "starttime", "pgid"}
                and type(observed["state"]) is str and len(observed["state"]) == 1
                and type(observed["starttime"]) is str and observed["starttime"].isdigit()
                and observed["starttime"] != evidence["identity"][key]["starttime"]
                and type(observed["pgid"]) is int and observed["pgid"] > 0):
            return False
    return True


def classify(item, commands, log, source_before, source_after):
    expected = item["expected_observations"]
    kind, variant = item["kind"], item["variant"]
    result = dict(schema="fsm_native_calibration_row_classification_v2", control_matched=False,
                  evidence_complete=False, positive_admission=False, measurement=None, refusal_reasons=[])
    if kind == "supervisor_probe":
        require(len(commands) == 1, "one supervisor probe only")
        command = commands[0]
        matched = (command["timeout"] is True and command["launch_error"] is None
                   and command["remaining_live_group"] == [] and command["returncode"] == -9
                   and "SIGKILL" in command.get("group_signals", [])
                   and probe_cleanup_valid(command.get("probe_evidence"))) if variant == "timeout" else (
                   command["timeout"] is False and type(command["launch_error"]) is str
                   and bool(re.search(r"\[Errno 2\].*No such file or directory", command["launch_error"]))
                   and command["returncode"] is None
                   and command["remaining_live_group"] == [])
        complete = (probe_cleanup_valid(command.get("probe_evidence")) if variant == "timeout" else
                    command["timeout"] is False and type(command["launch_error"]) is str
                    and bool(re.search(r"\[Errno 2\].*No such file or directory", command["launch_error"]))
                    and command["returncode"] is None and command["remaining_live_group"] == [])
        return result | dict(control_matched=bool(matched), evidence_complete=bool(complete),
                             supervision_failure_correctly_refused=bool(matched))
    require(len(commands) == len(item["expected_native_tools"]), "exact fixed tool sequence")
    require(all(clean_command(x) for x in commands), "launch/timeout/group/unknown-rc is tool failure")
    require(source_before == {"candidate.sv": item["source_sha256"], "tb.sv": item["tb_sha256"]},
            "scratch input before hashes")
    unchanged = source_before == source_after
    if kind == "eda_failure":
        require(unchanged, "EDA failure source mutation")
        if variant == "compile_error":
            match = commands[0]["returncode"] != 0 and bool(re.search(r"syntax error|unexpected token", log, re.I))
        else:
            match = (commands[0]["returncode"] == 0 and commands[1]["returncode"] != 0
                     and bool(re.search(r"top level.*not found|cannot find|could not find|not found in library|unresolved.*module", log, re.I)))
        require(not ENV_ERROR.search(log), "environment failure is not EDA sentinel success")
        return result | dict(control_matched=bool(match), evidence_complete=True,
                             expected_EDA_failure_observed=bool(match))
    require(commands[0]["returncode"] == commands[1]["returncode"] == 0,
            "compile/elaboration failure is not semantic-negative success")
    measurement = measure(log, expected)
    result["measurement"] = measurement
    result["evidence_complete"] = measurement["measurement_complete"]
    if not unchanged:
        result["refusal_reasons"].append("scratch_source_changed")
    if not measurement["positive_log_admissible"]:
        result["refusal_reasons"].append("positive_trace_or_terminal_refused")
    if commands[-1]["returncode"] != 0:
        result["refusal_reasons"].append("nonzero_xsim_rc")
    admitted = unchanged and measurement["positive_log_admissible"] and commands[-1]["returncode"] == 0
    result["positive_admission"] = admitted
    if kind in ("producer_positive", "sentinel_positive"):
        result["control_matched"] = admitted
    elif kind == "semantic_negative":
        result["control_matched"] = (unchanged and measurement["negative_log_admissible"]
                                     and commands[-1]["returncode"] == 0
                                     and set(item["required_mismatch_indices"]) <= set(measurement["mismatch_indices"]))
    else:
        require(kind == "transport_refusal", "unknown case kind")
        base = (measurement["measurement_complete"] and measurement["actual_mismatch_count"] == 0
                and not measurement["environment_error"]
                and (not measurement["generic_failure_found"] or variant == "pass_then_fatal"))
        passes = measurement["PASS"]
        count = len(expected)
        if variant == "pass_then_fatal":
            matched = (base and passes == [count] and measurement["fatal_found"] and unchanged
                       and measurement["transport_fatal_markers"] == 1)
        elif variant == "finish_without_pass":
            matched = base and passes == [] and not measurement["fatal_found"] and unchanged and commands[-1]["returncode"] == 0
        elif variant == "wrong_pass_count":
            matched = base and passes == [count+1] and not measurement["fatal_found"] and unchanged and commands[-1]["returncode"] == 0
        elif variant == "duplicate_pass":
            matched = base and passes == [count, count] and not measurement["fatal_found"] and unchanged and commands[-1]["returncode"] == 0
        else:
            require(variant == "owned_scratch_source_mutation", "unknown transport variant")
            matched = (measurement["positive_log_admissible"] and commands[-1]["returncode"] == 0
                       and not unchanged and source_after["tb.sv"] == item["tb_sha256"]
                       and source_after["candidate.sv"] == sha(item["source"].encode()+MUTATION_BYTES))
        result["control_matched"] = bool(matched and not admitted)
        result["positive_refusal_correctly_detected"] = result["control_matched"]
    return result


def command_plan(item, spec):
    folder = spec["cloud_root"]+"/results/"+item["label"]
    tools = spec["compiler_tools"]
    top = "fsm_deliberately_missing_module" if item["variant"] == "missing_module" else "tb_narrative_contract"
    argv = {
        "xvlog": [tools["xvlog"]["path"], "-sv", "--nolog", "candidate.sv", "tb.sv"],
        "xelab": [tools["xelab"]["path"], top, "-s", "narrative_calibration_snapshot", "--nolog", "-timescale", "1ns/1ps"],
        "xsim": [tools["xsim"]["path"], "narrative_calibration_snapshot", "-runall", "-nolog"],
    }
    if item["kind"] == "supervisor_probe":
        probe = ([spec["python_runtime"]["path"], "-B", spec["cloud_root"]+"/"+spec["supervisor_probe_relative"],
                  "--identity", folder+"/PROBE_IDENTITY.json"] if item["variant"] == "timeout"
                 else [folder+"/.deliberately_missing_launcher"])
        return [dict(tool="owned_supervisor", argv=probe, cwd=folder, cap_s=spec["supervisor_probe_timeout_s"])]
    return [dict(tool=name, argv=argv[name], cwd=folder, cap_s=spec["native_command_timeout_s"])
            for name in item["expected_native_tools"]]
