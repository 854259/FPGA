"""AMD CPU replay of the newly observed disconnect-to-idle boundary only."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import failure_continuation as failure


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--inspection',type=Path,required=True)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    assert sys.platform=='linux' and sys.dont_write_bytecode
    report=json.loads(args.inspection.read_bytes())
    raw=args.trace.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==report['observer_result']['observations_sha256']
    events=[json.loads(x) for x in raw.splitlines()]
    assert events and report['real_budget_interrupt_then_slot_idle_observed']
    delay=report['idle_delay_after_budget_exit_s']
    assert 0<delay<10
    out=args.out;out.mkdir(exist_ok=False)
    admission=dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='Qwen3.6-27B-Q4_K_M')
    plan=dict(allow_shared_budget_failure=True,solve_supervisor_s=310)
    result=[]
    for name,age in [('observed_delay_replay',300),('still_busy_at_cleanup_end',309.8),('identity_alias_change',300)]:
        folder=out/name;folder.mkdir()
        now=time.monotonic();origin=now-age
        (folder/'SOLVE_CLOCK.json').write_text(json.dumps(dict(schema='parent_solve_clock_v1',budget_s=300,started_monotonic=origin)))
        class Resource:
            polls=0
            def model_idle(self,endpoint,model):
                self.polls+=1
                assert endpoint==admission['llm_base_url'] and model==admission['model_name']
                if name=='identity_alias_change':
                    raise RuntimeError('shared model health or model alias changed')
                if name=='still_busy_at_cleanup_end' or time.monotonic()-now<delay:
                    raise RuntimeError('shared model slots are busy or idle telemetry is unavailable')
                return dict(model=model,health_status='ok',processing_slots=0,slot_count=1)
        resource=Resource();error=None;idle=None;wait=None
        try:idle,wait=failure.idle_after_failed_solver(folder,plan,resource,admission)
        except RuntimeError as exc:error=str(exc)
        elapsed=time.monotonic()-now
        if name=='observed_delay_replay':
            assert error is None and idle['processing_slots']==0 and wait['polls']>1
            assert wait['deadline_monotonic']==origin+310 and wait['returned_monotonic']<=origin+310
        elif name=='still_busy_at_cleanup_end':
            assert error=='Shared model did not become idle within original parent310 cleanup end'
            assert elapsed<1 and idle is None
        else:
            assert error=='shared model health or model alias changed' and resource.polls==1 and idle is None
        record=dict(name=name,passed=True,polls=resource.polls,elapsed_s=elapsed,error=error,idle_wait=wait,
                    parent_age_simulated=True,resource_and_model_idle_simulated=True)
        (folder/'RESULT.json').write_text(json.dumps(record,indent=2)+'\n');result.append(record)
    evidence=dict(schema='failed_idle_wait_trace_delta_CPU_qualification_v1',complete=True,passed=True,cases=result,
        source_sha256=hashlib.sha256(Path(failure.__file__).read_bytes()).hexdigest(),
        fixture_original_trace_sha256=hashlib.sha256(raw).hexdigest(),observed_original_delay_s=delay,
        scope='New idle-wait helper with recorded139 delay replay and two refusal boundaries. All parent/resource/model observations in this replay are simulated; no production seal or shared-model request is repeated.',
        real_model_continuation_qualified=False,new_model_calls=0,new_EDA=0,new_FIFO=0,full_goal_complete=False)
    (out/'QUALIFICATION_RESULT.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))


if __name__=='__main__':
    main()
