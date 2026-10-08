"""Wire the frozen 360-second whole native-child boundary before executing it."""
import argparse,json,sys
from pathlib import Path
import bounded_owned_exec
ROOT=Path(__file__).parent
def main():
 p=argparse.ArgumentParser();p.add_argument('--resource-check',required=True);a=p.parse_args()
 spec=json.loads((ROOT/'RUN_SPEC.json').read_bytes());assert spec['stage_cap_s']==360 and spec['guard_cap_s']==420 and spec['slot_minutes']==10
 record=bounded_owned_exec.run([sys.executable,'-B',str(ROOT/'native_compile_simulate11.py'),'--resource-check',a.resource_check],ROOT,ROOT/'ACTUAL_STAGE_PROCESS',360)
 assert record['normal_completion'] and record['returncode']==0 and record['exec_confirmed'] and record['leader_reaped'] and not record['remaining_group']
 assert json.loads((ROOT/'results/summary.json').read_bytes())['passed']
if __name__=='__main__':main()
