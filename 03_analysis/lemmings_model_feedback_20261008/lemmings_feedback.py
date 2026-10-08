"""Complete-prompt finite behavioural checking only; never emits a DUT.

Static draft. Runtime and all tests are AMD-only. The specification recurrence
below is a testbench oracle, not a hardware implementation or official judge.
"""
import hashlib
import re
from pathlib import Path

from reserved_keywords import KEYWORDS

HEADER = re.compile(r'\AI would like you to implement a module named TopModule with the following\s+interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*', re.S)
PORT = re.compile(r'-\s+(input|output)\s+([A-Za-z_][A-Za-z_0-9]*)\s*(?:\((1) bits\))?')
IDENT = r'[A-Za-z_][A-Za-z_0-9]*'
LABEL = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,80}')
ROLES = ('reset', 'bump_left', 'bump_right', 'ground', 'dig')
OUTPUTS = ('walk_left', 'walk_right', 'aaah', 'digging')


def body_template(names, has_dig=False, has_death=False):
    """An exact complete prose grammar; accepted names must bind to the ports."""
    if has_death and not has_dig:
        raise ValueError('death grammar includes digging')
    wl, wr = names['walk_left'], names['walk_right']
    bl, br, g = names['bump_left'], names['bump_right'], names['ground']
    text = ("The game Lemmings involves critters with fairly simple brains. So simple "
            "that we are going to model it using a finite state machine. In the "
            "Lemmings' 2D world, Lemmings can be in one of two states: walking left "
            f"({wl} is 1) or walking right ({wr} is 1). It will switch "
            "directions if it hits an obstacle. In particular, if a Lemming is bumped "
            f"on the left (by receiving a 1 on {bl}), it will walk right. If it's "
            f"bumped on the right (by receiving a 1 on {br}), it will walk left. "
            "If it's bumped on both sides at the same time, it will still switch directions. "
            "In addition to walking left and right and changing direction when bumped, "
            f'when {g}=0, the Lemming will fall and say "aaah!". When the ground '
            f"reappears ({g}=1), the Lemming will resume walking in the same "
            "direction as before the fall. Being bumped while falling does not affect "
            f"the walking direction, and being bumped in the same cycle as {g} "
            "disappears (but not yet falling), or when the ground reappears while "
            "still falling, also does not affect the walking direction.")
    if has_dig:
        d = names['dig']
        text += (" In addition to walking and falling, Lemmings can sometimes be told to do "
                 f"useful things, like dig (it starts digging when {d}=1). A Lemming can dig "
                 f"if it is currently walking on ground ({g}=1 and not falling), and will "
                 f"continue digging until it reaches the other side ({g}=0). At that "
                 "point, since there is no ground, it will fall (aaah!), then continue "
                 "walking in its original direction once it hits ground again. As with "
                 "falling, being bumped while digging has no effect, and being told to dig "
                 "when falling or when there is no ground is ignored. (In other words, a "
                 "walking Lemming can fall, dig, or switch directions. If more than one of "
                 "these conditions are satisfied, fall has higher precedence than dig, "
                 "which has higher precedence than switching directions.)")
    if has_death:
        text += (" Although Lemmings can walk, fall, and dig, Lemmings aren't invulnerable. "
                 "If a Lemming falls for too long then hits the ground, it can splatter. In "
                 "particular, if a Lemming falls for more than 20 clock cycles then hits "
                 "the ground, it will splatter and cease walking, falling, or digging (all "
                 "4 outputs become 0), forever (Or until the FSM gets reset). There is no "
                 "upper limit on how far a Lemming can fall before hitting the ground. "
                 "Lemmings only splatter when hitting the ground; they do not splatter in mid-air.")
    return (text + " Implement a Moore state machine that models this behaviour. " + names['reset'] +
            " is positive edge triggered asynchronous reseting the Lemming machine to walk "
            "left. Assume all sequential logic is triggered on the positive edge of the clock.")


def _single(pattern, text):
    matches = re.findall(pattern, text)
    return matches[0] if len(matches) == 1 else None


def parse(prompt):
    """No task ID is accepted. Unknown or partially consumed contracts abstain."""
    if not isinstance(prompt, str):
        return None
    try:
        prompt_sha = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        return None
    text = prompt.replace('\r\n', '\n').replace('\r', '\n')
    header = HEADER.match(text)
    if header is None:
        return None
    lines = text[header.end():].splitlines()
    ports, body = [], None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = PORT.fullmatch(line.strip())
        if match is None:
            body = ' '.join('\n'.join(lines[index:]).split())
            break
        ports.append(dict(direction=match[1], name=match[2], width=1))
    if body is None or not ports or len({p['name'] for p in ports}) != len(ports):
        return None
    if any(p['name'] in KEYWORDS for p in ports):
        return None
    # Only the observed doubled quotation spelling has equivalent syntax.
    body = body.replace('say ""aaah!"".', 'say "aaah!".')
    names = dict(
        walk_left=_single(r'walking left \((' + IDENT + r') is 1\)', body),
        walk_right=_single(r'walking right \((' + IDENT + r') is 1\)', body),
        bump_left=_single(r'on the left \(by receiving a 1 on (' + IDENT + r')\)', body),
        bump_right=_single(r'on the right \(by receiving a 1 on (' + IDENT + r')\)', body),
        ground=_single(r'when (' + IDENT + r')=0, the Lemming will fall', body),
        reset=_single(r'behaviour\. (' + IDENT + r') is positive edge triggered asynchronous', body),
        dig=_single(r'it starts digging when (' + IDENT + r')=1', body),
        aaah='aaah', digging='digging')
    if any(names[x] is None for x in ('walk_left', 'walk_right', 'bump_left', 'bump_right', 'ground', 'reset')):
        return None
    matches = [(d, death) for d, death in ((False, False), (True, False), (True, True))
               if (not d or names['dig'] is not None) and body == body_template(names, d, death)]
    if len(matches) != 1:
        return None
    has_dig, has_death = matches[0]
    input_roles = ('reset', 'bump_left', 'bump_right', 'ground') + (('dig',) if has_dig else ())
    output_roles = ('walk_left', 'walk_right', 'aaah') + (('digging',) if has_dig else ())
    used = [names[x] for x in input_roles + output_roles]
    if len(set(used)) != len(used):
        return None
    by_name = {p['name']: p for p in ports}
    if any(name not in by_name for name in used):
        return None
    if any(by_name[names[x]]['direction'] != 'input' for x in input_roles):
        return None
    if any(by_name[names[x]]['direction'] != 'output' for x in output_roles):
        return None
    remaining = [p for p in ports if p['name'] not in used]
    if len(remaining) != 1 or remaining[0]['direction'] != 'input':
        return None
    names['clock'] = remaining[0]['name']
    if not has_dig:
        names['dig'] = names['digging'] = None
    contract = dict(ports=ports, **names, has_dig=has_dig, has_death=has_death,
                    death_threshold=20 if has_death else None,
                    all_prompt_consumed=True, reset_kind='active_high_asynchronous',
                    clock_edge='positive', model_kind='Moore',
                    priority='fall_then_dig_then_bump',
                    fall_duration='complete_intervals_between_entry_and_landing_edges',
                    observation='settled_after_explicit_event')
    rows = trace(contract)
    return dict(prompt_sha256=prompt_sha, contract=contract, rows=rows, checks=len(rows))


def trace(contract):
    """Finite stimulus with expected external behaviour; no synthesizable RTL."""
    stimuli = []
    digging = contract['has_dig']

    def add(kind='posedge', reset=0, left=0, right=0, ground=1, dig=0, tag=''):
        stimuli.append(dict(kind=kind, reset=reset, bump_left=left, bump_right=right,
                            ground=ground, dig=dig if digging else 0, tag=tag))

    def reset():
        # Previous event may leave reset high: always deassert then reassert.
        # The unobserved low preparation phase occurs in render_tb; assertion
        # itself is an explicitly observed event and creates no clock edge.
        add('async_assert', reset=1, tag='async_reset_without_clock')
        add('posedge', reset=1, ground=0, left=1, right=1, dig=1, tag='reset_dominates_clock')
        add('hold', ground=0, left=1, right=1, dig=1, tag='reset_release_moore_hold')
        add('posedge', tag='resume_ground')

    reset()
    # Single and simultaneous bumps from both remembered directions.
    for left, right in ((0, 1), (1, 0), (1, 0), (1, 1), (1, 1), (0, 1), (1, 1)):
        add(left=left, right=right, tag='walking_bump')
        add('hold', left=1-left, right=1-right, ground=0, dig=1, tag='Moore_input_hold')
    # Exercise entry, air, landing and direction preservation from both sides.
    for direction in ('left', 'right'):
        reset()
        if direction == 'right':
            add(left=1, tag='turn_right')
            add(tag='right_walk_no_bump')
        add(ground=0, left=1, right=1, dig=1, tag='fall_beats_dig_and_bump')
        add('hold', ground=1, left=1, right=1, dig=1, tag='fall_Moore_hold')
        add(ground=0, left=1, dig=1, tag='air_ignores_bumps')
        add(ground=1, left=1, right=1, dig=1, tag='landing_ignores_dig_and_bumps')
        if digging:
            add(left=1, right=1, dig=1, tag='dig_beats_bump')
            add('hold', ground=0, tag='dig_Moore_hold')
            add(left=1, right=1, dig=0, tag='dig_persists_without_request')
            add(left=1, dig=1, tag='dig_ignores_bumps')
            add(ground=0, right=1, tag='dig_to_fall')
            add(ground=1, left=1, right=1, dig=1, tag='dig_episode_landing')
    # Hand calibrated boundary convention: entry E0, landing EN, N intervals.
    # Non-death contracts must survive these same long episodes.
    for direction in ('left', 'right'):
        for duration in (1, 19, 20, 21, 31, 32, 40, 64):
            reset()
            if direction == 'right':
                add(left=1, tag='turn_right')
            add(ground=0, left=1, right=1, dig=1, tag=f'fall_{duration}_E0')
            for edge in range(1, duration):
                add(ground=0, left=1, right=1, dig=1, tag=f'fall_{duration}_E{edge}')
            add(ground=1, left=1, right=1, dig=1, tag=f'fall_{duration}_E{duration}_landing')
            # Dead must absorb varied inputs; living variants continue normally.
            for left, right, ground, dig in ((0, 0, 0, 1), (1, 1, 1, 1), (0, 1, 1, 0)):
                add(left=left, right=right, ground=ground, dig=dig, tag='after_landing')
    if digging:
        # Also calibrate long falls entered from DIG in both directions.
        for direction in ('left', 'right'):
            for duration in (20, 21, 40):
                reset()
                if direction == 'right':
                    add(left=1, tag='turn_right')
                add(dig=1, tag='dig_before_boundary')
                add(ground=0, tag=f'dig_fall_{duration}_E0')
                for edge in range(1, duration):
                    add(ground=0, tag=f'dig_fall_{duration}_E{edge}')
                add(ground=1, tag=f'dig_fall_{duration}_E{duration}_landing')
    # A second safe fall must start its own age, not accumulate the first one.
    reset()
    for episode in (1, 2):
        add(ground=0, tag=f'separate_{episode}_E0')
        for edge in range(1, 12):
            add(ground=0, tag=f'separate_{episode}_E{edge}')
        add(ground=1, tag=f'separate_{episode}_landing')
    # Reset in FALL and DIG tests asynchronous recovery outside WALK/DEAD.
    add(ground=0, tag='reset_during_fall_setup')
    reset()
    if digging:
        add(dig=1, tag='reset_during_dig_setup')
        reset()

    activity, direction, age, last_reset = 'walk', 'left', 0, 0
    rows = []
    for event, stimulus in enumerate(stimuli):
        if stimulus['kind'] == 'async_assert':
            activity, direction, age, last_reset = 'walk', 'left', 0, event
        elif stimulus['reset']:
            activity, direction, age = 'walk', 'left', 0
        elif stimulus['kind'] == 'posedge':
            if activity == 'walk':
                if not stimulus['ground']:
                    activity, age = 'fall', 0
                elif digging and stimulus['dig']:
                    activity = 'dig'
                elif stimulus['bump_' + direction]:
                    direction = 'right' if direction == 'left' else 'left'
            elif activity == 'dig':
                if not stimulus['ground']:
                    activity, age = 'fall', 0
            elif activity == 'fall':
                completed = age + 1
                if stimulus['ground']:
                    activity = ('dead' if contract['has_death'] and completed > 20 else 'walk')
                    age = 0
                else:
                    age = completed
        expected = ''.join(str(int(value)) for value in
                           (activity == 'walk' and direction == 'left',
                            activity == 'walk' and direction == 'right',
                            activity == 'fall', activity == 'dig'))
        rows.append(dict(event=event, **stimulus, clock=int(stimulus['kind'] == 'posedge'),
                         expected=expected, last_reset=last_reset))
    return rows


def render_tb(parsed, task):
    if not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('unsafe probe label')
    c = parsed['contract']
    lines = ['`timescale 1ns/1ps', 'module R2Probe;',
             'reg _lf_clk=0, _lf_reset=0, _lf_bl=0, _lf_br=0, _lf_ground=1, _lf_dig=0;',
             'wire _lf_wl, _lf_wr, _lf_aaah, _lf_digging;',
             'integer _lf_checks=0, _lf_bad=0;']
    signals = dict(clock='_lf_clk', reset='_lf_reset', bump_left='_lf_bl', bump_right='_lf_br',
                   ground='_lf_ground', dig='_lf_dig', walk_left='_lf_wl', walk_right='_lf_wr',
                   aaah='_lf_aaah', digging='_lf_digging')
    connections = [f'.{c[role]}({signal})' for role, signal in signals.items() if c[role] is not None]
    if not c['has_dig']:
        lines.append("assign _lf_digging=1'b0;")
    lines += ['TopModule _lf_dut(' + ','.join(connections) + ');', 'initial begin']
    for row in parsed['rows']:
        # A low phase and reset deassertion precede every event. The following
        # #2 ensures an async assertion is a real 0->1 transition, not a race.
        preparation_reset = 0 if row['kind'] == 'async_assert' else row['reset']
        lines += [f"_lf_clk=0; _lf_reset=1'b{preparation_reset};",
                  f"_lf_bl=1'b{row['bump_left']}; _lf_br=1'b{row['bump_right']}; "
                  f"_lf_ground=1'b{row['ground']}; _lf_dig=1'b{row['dig']};", '#2;']
        if row['kind'] == 'async_assert':
            lines.append("_lf_reset=1; #1;")
        elif row['kind'] == 'posedge':
            lines.append('_lf_clk=1; #1;')
        else:
            lines.append('#1;')
        lines += [f'$display("LEMMINGS_STEP event={row["event"]} kind={row["kind"]} clock=%b reset=%b left=%b right=%b ground=%b dig=%b outputs=%b%b%b%b",'
                  '_lf_clk,_lf_reset,_lf_bl,_lf_br,_lf_ground,_lf_dig,_lf_wl,_lf_wr,_lf_aaah,_lf_digging);',
                  '_lf_checks=_lf_checks+1;',
                  f"if ({{_lf_wl,_lf_wr,_lf_aaah,_lf_digging}} !== 4'b{row['expected']}) begin",
                  f'if(_lf_bad==0) $display("LEMMINGS_FIRST event={row["event"]}");',
                  '_lf_bad=_lf_bad+1; end', '#1;']
    lines += [f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_lf_checks,_lf_bad);',
              f'if(_lf_checks!={parsed["checks"]}) $fatal(1,"CHECK_COUNT_INVALID");',
              '$finish; end', f'initial begin #{4 * parsed["checks"] + 100}; $fatal(1,"WATCHDOG_EXPIRED"); end',
              'endmodule', '']
    return '\n'.join(lines)


def measured_trace(log, parsed, mismatches):
    """Reject incomplete/forged-looking protocol instead of fabricating feedback."""
    pattern = re.compile(r'^LEMMINGS_STEP event=(\d+) kind=(async_assert|posedge|hold) clock=([01]) reset=([01]) left=([01]) right=([01]) ground=([01]) dig=([01]) outputs=([01xz]{4})\s*$', re.M)
    found = pattern.findall(log)
    if len(found) != parsed['checks'] or len(re.findall(r'^LEMMINGS_STEP\b', log, re.M)) != len(found):
        raise RuntimeError('missing/ambiguous Lemmings observations')
    observations, failures = [], []
    for row, values in zip(parsed['rows'], found):
        event, kind, clock, reset, left, right, ground, dig, outputs = values
        actual = (int(event), kind, int(clock), int(reset), int(left), int(right), int(ground), int(dig))
        expected = tuple(row[k] for k in ('event', 'kind', 'clock', 'reset', 'bump_left', 'bump_right', 'ground', 'dig'))
        if actual != expected:
            raise RuntimeError('Lemmings observations contradict the executed event trace')
        observations.append(dict(event=int(event), kind=kind, clock=int(clock), reset=int(reset),
                                 bump_left=int(left), bump_right=int(right), ground=int(ground),
                                 dig=int(dig), outputs=outputs))
        if outputs != row['expected']:
            failures.append(row['event'])
    first = re.findall(r'^LEMMINGS_FIRST event=(\d+)\s*$', log, re.M)
    if (len(re.findall(r'^LEMMINGS_FIRST\b', log, re.M)) != len(first) or
            len(failures) != mismatches or first != ([str(failures[0])] if failures else [])):
        raise RuntimeError('Lemmings mismatch count/first observation unconfirmed')
    if not failures:
        return None
    row = parsed['rows'][failures[0]]
    c = parsed['contract']
    return dict(event=row['event'], event_kind=row['kind'], clock_port=c['clock'],
                input_ports={role: c[role] for role in ROLES if c[role] is not None},
                output_ports={role: c[role] for role in OUTPUTS if c[role] is not None},
                expected_outputs=row['expected'], observed_outputs=observations[row['event']]['outputs'],
                actual_trace_since_reset=observations[row['last_reset']:row['event'] + 1])


def feedback_text(point):
    """Losslessly compress repeated identical measured events; never add RTL."""
    roles = tuple(point['input_ports'])
    chunks = []
    for row in point['actual_trace_since_reset']:
        value = (row['kind'], row['clock'], *(row[role] for role in roles), row['outputs'])
        if chunks and value == chunks[-1]['value'] and row['event'] == chunks[-1]['end'] + 1:
            chunks[-1]['end'] = row['event']
        else:
            chunks.append(dict(start=row['event'], end=row['event'], value=value))
    samples = []
    for chunk in chunks:
        where = str(chunk['start']) if chunk['start'] == chunk['end'] else f"{chunk['start']}..{chunk['end']} (each event)"
        samples.append(where + ':' + str(chunk['value']))
    output_names = [point['output_ports'][role] for role in OUTPUTS if role in point['output_ports']]
    size = len(output_names)
    return ("A simulation check derived only from the complete behaviour in the prompt found a mismatch. "
            "Events below distinguish asynchronous reset assertion, positive clock edges, and input changes "
            "without a positive clock edge; outputs were observed after settling. "
            f"Actual event:(kind,{point['clock_port']}," + ','.join(point['input_ports'][r] for r in roles) +
            ",outputs) since the most recent reset: [" + '; '.join(samples) + "]. "
            f"Output order is ({','.join(output_names)}); the trace's final unused output slot is zero when digging is absent. "
            f"At event {point['event']} ({point['event_kind']}), expected "
            f"{point['expected_outputs'][:size]}, observed {point['observed_outputs'][:size]}. "
            "Fix the implementation to satisfy the prompt while retaining its interface.")


def check(prompt, code, out, attempt, paired, task, root):
    """None=abstain; ''=finite trace passed; text=actual measured counterexample."""
    parsed = parse(prompt)
    if parsed is None or not isinstance(code, str) or re.search(r'\$[A-Za-z_]|`(?:include|define)|\bR2Probe\b', code):
        return None
    if not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('unsafe probe label')
    if type(attempt) is not int or attempt not in (0, 1):
        raise ValueError('Lemmings feedback retains only initial and one repair attempt')
    folder = Path(out) / ('lemmings_check_' + str(attempt))
    inputs = folder / 'inputs' / task
    inputs.mkdir(parents=True, exist_ok=False)
    source, tb = folder / 'input.sv', inputs / 'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(render_tb(parsed, task), encoding='utf-8', newline='\n')
    paired.save(folder / 'contract.json', parsed)
    source_sha, tb_sha = paired.sha(source), paired.sha(tb)
    result = paired.oracle(dict(task=task, checks=parsed['checks'], tb=str(tb.relative_to(root))),
                           source, folder / 'probe')
    if paired.sha(source) != source_sha or paired.sha(tb) != tb_sha:
        raise RuntimeError('Lemmings check inputs changed')
    if result.get('inputs_unchanged') is not True or result.get('checks') != parsed['checks']:
        raise RuntimeError('unconfirmed Lemmings check; no fabricated feedback')
    mismatches = result.get('mismatches')
    if type(mismatches) is not int or not 0 <= mismatches <= parsed['checks']:
        raise RuntimeError('unconfirmed Lemmings mismatch count')
    if not ((result.get('status') == 'pass' and mismatches == 0) or
            (result.get('status') == 'fail' and result.get('failure_kind') == 'semantic_mismatch' and mismatches > 0)):
        raise RuntimeError('Lemmings tool/protocol failure; no fabricated feedback')
    if result.get('solution_sha256') != source_sha or result.get('tb_sha256') != tb_sha:
        raise RuntimeError('Lemmings oracle receipt names different source inputs')
    stages = result.get('stages')
    if not isinstance(stages, list) or [s.get('name') for s in stages] != ['xvlog', 'xelab', 'xsim']:
        raise RuntimeError('Lemmings native stage receipts incomplete')
    for stage in stages:
        stage_log = folder / 'probe' / (stage['name'] + '.log')
        if (stage.get('returncode') != 0 or stage.get('timeout') is not False or
                stage.get('launch_error') is not None or stage.get('remaining_live_group') != [] or
                Path(stage.get('log', '')).resolve() != stage_log.resolve() or
                stage.get('log_sha256') != paired.sha(stage_log) or
                stage.get('log_bytes') != stage_log.stat().st_size):
            raise RuntimeError('Lemmings native stage/log binding unconfirmed')
    log = folder / 'probe/xsim.log'
    log_sha = paired.sha(log)
    point = measured_trace(log.read_text(encoding='utf-8', errors='replace'), parsed, mismatches)
    paired.save(folder / 'trace_binding.json', dict(prompt_sha256=parsed['prompt_sha256'],
                source_sha256=source_sha, tb_sha256=tb_sha, log_sha256=log_sha,
                result_path='probe/result.json', result_sha256=paired.sha(folder / 'probe/result.json'),
                checks=parsed['checks'], mismatches=mismatches))
    if paired.sha(log) != log_sha:
        raise RuntimeError('Lemmings measurement log changed')
    if point is None:
        return ''
    paired.save(folder / 'counterexample.json', point)
    text = feedback_text(point)
    (folder / 'feedback.txt').write_text(text, encoding='utf-8', newline='\n')
    return text


def run_worker(base, args, paired):
    if args.arm == 'C':
        return base.run_worker(args, paired)
    if args.arm != 'P':
        raise ValueError('Lemmings feedback comparison requires C or P')
    original = base.functional_feedback

    def feedback(prompt, code, out, attempt, tools, task, candidate=False):
        result = check(prompt, code, out, attempt, tools, task, base.ROOT)
        if result is not None:
            return result
        return original(prompt, code, out, attempt, tools, task, candidate=candidate)

    base.functional_feedback = feedback
    try:
        return base.run_worker(args, paired)
    finally:
        base.functional_feedback = original
