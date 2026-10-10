"""Only the newly identified pre300 parent-origin compatibility boundary."""
import hashlib
import json
from pathlib import Path
import sys
import time
import failure_continuation as failure


def main():
    assert sys.platform=='linux' and sys.dont_write_bytecode
    root=Path(__file__).resolve().parent
    out=root/'early_results';out.mkdir(exist_ok=False)
    origin=time.monotonic()
    (out/'SOLVE_CLOCK.json').write_text(json.dumps(dict(schema='parent_solve_clock_v1',budget_s=300,started_monotonic=origin)))
    class Resource:
        polls=0
        def model_idle(self,endpoint,model):
            self.polls+=1
            return dict(model=model,health_status='ok',processing_slots=0,slot_count=1)
    resource=Resource()
    idle,wait=failure.idle_after_failed_solver(out,dict(allow_shared_budget_failure=True,solve_supervisor_s=310),resource,
       dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='Qwen3.6-27B-Q4_K_M'))
    assert idle['processing_slots']==0 and resource.polls==1
    assert wait['deadline_monotonic']==origin+310
    assert wait['started_monotonic']<origin+300 and wait['returned_monotonic']<=origin+310
    result=dict(schema='failed_idle_wait_early_parent_origin_delta_v1',complete=True,passed=True,
        source_sha256=hashlib.sha256(Path(failure.__file__).read_bytes()).hexdigest(),
        real_parent_clock=True,resource_and_idle_simulated=True,
        pre300_failure_path_no_future_parent_origin=True,idle_wait=wait,
        scope='Only new early-failure helper boundary. Source below300 now constructs a valid budget from real parent origin; model/resource are simulated. No seal or production CLI/model request is exercised; old four controls retain original47bed source binding.',
        real_model_continuation_qualified=False,new_model_calls=0,new_EDA=0,new_FIFO=0,full_goal_complete=False)
    (out/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
