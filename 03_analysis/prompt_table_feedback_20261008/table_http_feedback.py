"""Run the scored feedback functions inside the existing HTTP worker deadline."""
from pathlib import Path
import sys

import baseline_worker as base
import table_feedback

BRIDGE = None
sha = base.sha
save = base.save


def oracle(case, source, out):
    # Both scored checkers stage only a prompt-derived TB here. Keep the original
    # probe runner, but inherit the HTTP worker's supervised process group.
    out = Path(out)
    inputs = out.parent / 'inputs'
    runner_file = inputs / 'probe_runner.py'
    runner_file.write_bytes((BRIDGE.ROOT / 'probe_runner.py').read_bytes())
    runner = base.load('http_prompt_probe', runner_file)
    runner.TASK_CHECKS = {case['task']: case['checks']}

    def stage(name, argv, directory):
        tool = BRIDGE.core.vivado_tool(name)
        argv = [tool or str(inputs / 'unavailable' / name), *argv[1:]]
        return BRIDGE.native_contract.run_stage(name, argv, directory)

    runner._run_stage = stage
    result = runner.probe_candidate(case['task'], source, out)
    for record in result.get('stages', []):
        BRIDGE.core.trace(out.parent.parent, record['name'], rc=record['returncode'],
                          timeout=record['timeout'],
                          excerpt=Path(record['log']).read_text(errors='replace')[-2048:])
    return result


def feedback(prompt, code, out, attempt):
    out = Path(out).resolve()
    # The research function uses ROOT only to express its generated TB path.
    # HTTP workers are separate processes; restore this binding on every exit.
    previous = base.ROOT
    base.ROOT = out
    try:
        tools = sys.modules[__name__]
        measured = table_feedback.check(prompt, code, out, attempt, tools,
                                        'TableProbe', out)
        if measured is not None:
            return measured
        return base.functional_feedback(prompt, code, out, attempt, tools,
                                        'ContractProbe', candidate=True)
    finally:
        base.ROOT = previous
