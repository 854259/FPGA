"""AMD-only owner adapter delta; shared PR199's 16 controls are not repeated."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    if sys.platform != 'linux':
        raise RuntimeError('AMD Linux only')
    root = Path('/workspace/team/runs/fpga_owner/fifo_unstarted_wait_recovery135136_20261009_v1')
    spec = importlib.util.spec_from_file_location('owned_wait_adapter',
        root / 'fifo_wait_recovery_owned_135136_20261009.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    plan = json.loads((root / 'PLAN.json').read_bytes())
    fifo = Path(plan['fifo_root'])
    targets = [fifo / 'tickets' / ('%08d.json' % n) for n in range(132, 137)]
    before = {str(p): p.read_bytes() for p in targets}
    core = adapter.validate_plan(plan, root)
    outcomes = []
    with patch.object(core.subprocess, 'Popen', side_effect=AssertionError('no launch in qualification')):
        for entry in plan['entries']:
            monitor = core.proc_record(entry['monitor']['pid'])
            assert monitor and monitor['state'] not in ('Z', 'X')
            assert all(monitor[k] == entry['monitor'][k] for k in entry['monitor'])
            result = core.recover(plan, entry, root)
            assert result == {'outcome': 'waiting_original'}
            outcomes.append(dict(ticket=entry['queued']['ticket'], outcome=result['outcome']))
    cases = [dict(case='exact_owned_binding_live_waiting_read_only', passed=True,
                  outcomes=outcomes)]
    for name in ('foreign_ticket_133', 'changed_original_command', 'missing_frozen_source'):
        altered = copy.deepcopy(plan)
        if name == 'foreign_ticket_133':
            altered['entries'][0]['queued']['ticket'] = 133
        elif name == 'changed_original_command':
            altered['entries'][0]['queued']['command'] = ['FORBIDDEN_CHANGED_COMMAND']
        else:
            altered['entries'][0]['frozen_files'].pop(next(iter(altered['entries'][0]['frozen_files'])))
        try:
            adapter.validate_plan(altered, root)
        except RuntimeError:
            cases.append(dict(case=name, refused=True))
        else:
            raise AssertionError('owner adapter accepted ' + name)
    assert all(Path(p).read_bytes() == b for p, b in before.items())
    assert not (root / 'WATCH_INTENT.json').exists()
    assert not list(root.glob('RECOVERY_*'))
    result = dict(passed=True, cases=cases, original_tickets_132_136_unchanged=True,
                  watcher_started=False, recovery_triggered=False, model_calls=0,
                  eda_commands=0, new_fifo_tickets=0, shared_16_controls_repeated=False)
    Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
