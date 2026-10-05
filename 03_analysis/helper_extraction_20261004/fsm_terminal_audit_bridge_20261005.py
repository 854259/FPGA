"""AMD-only resource-guard bridge to the unchanged frozen FSM auditor."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def main(a):
    assert sys.platform == 'linux'
    paired = Path('/workspace/team/runs/fpga_teammate/diagnostic_Q5_20261005_865876a/source/03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    assert hashlib.sha256(paired.read_bytes()).hexdigest() == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    spec = importlib.util.spec_from_file_location('fsm_audit_resource', paired)
    resource = importlib.util.module_from_spec(spec); spec.loader.exec_module(resource)
    kit = Path('/workspace/team/tasks/autodl-rtl-kit/project')
    resource.check_resource(a.resource_check, kit, first=True)
    root = Path(__file__).resolve().parent
    auditor = root/'auditor/audit.py'
    assert hashlib.sha256(auditor.read_bytes()).hexdigest() == 'f5ec7199716c9bdd9a0dc8e39a45fb941c0a9fe19d93c27b2e9c51d563988284'
    cmd = [sys.executable, '-B', str(auditor), '--archive', str(root/'INPUT.zip'),
           '--out', str(root/'results'), '--spec-sha',
           '09f06455ed3fbc4601f90a3c673c3c12acfadf377309f51565dac1eeeb2e87f9']
    receipt = resource.owned_command(cmd, root, root/'audit.log', 100)
    (root/'AUDIT_EXECUTION.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert receipt['returncode'] == 0 and not receipt['timeout'] and not receipt['remaining_live_group'], receipt
    resource.check_resource(a.resource_check, kit)
    print((root/'results/RESULTS.json').read_text(), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--resource-check', type=Path, required=True)
    main(p.parse_args())
