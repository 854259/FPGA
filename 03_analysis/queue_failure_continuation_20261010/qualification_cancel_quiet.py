"""New cancellation-poll boundary on AMD, not model or seal qualification."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import failure_continuation as failure

SERVER_QUEUE_SHA = '0e196113d16f130230d2cc0b232915e1f5b4f1dda184790afbfdc4986dd1fd58'


def function(text, prefix):
    start = text.index(prefix)
    body = text.index('{', start)
    depth = 1
    end = body+1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    root = Path(__file__).resolve().parent
    out = root/'quiet_results';assert not out.exists();out.mkdir()
    queue = Path('/workspace/team/tools/llama-src/tools/server/server-queue.cpp')
    raw = queue.read_bytes();assert hashlib.sha256(raw).hexdigest() == SERVER_QUEUE_SHA
    recv = function(raw.decode(), 'server_task_result_ptr server_response::recv_with_timeout(')
    send = function(raw.decode(), 'void server_response::send(')
    # Compile the exact pinned functions in a minimal CPU harness. Only the
    # supporting types are reduced; neither function body is rewritten.
    header = r'''
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <memory>
#include <mutex>
#include <thread>
#include <unordered_set>
#include <vector>
#define RES_DBG(...) ((void)0)
struct result { int id; };
using server_task_result_ptr = std::unique_ptr<result>;
struct server_response {
 std::mutex mutex_results;
 std::condition_variable condition_results;
 std::vector<server_task_result_ptr> queue_results;
 std::unordered_set<int> waiting_task_ids{42,99};
 bool running=true;
 server_task_result_ptr recv_with_timeout(const std::unordered_set<int>&,int);
 void send(server_task_result_ptr&&);
};
'''
    main_cpp = r'''
double observe(bool noisy) {
 server_response response;
 auto start=std::chrono::steady_clock::now();
 std::thread notifications([&]() {
  if(noisy) {
   for(int i=0;i<15;i++) {
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    response.send(std::make_unique<result>(result{99}));
   }
  } else {
   std::this_thread::sleep_for(std::chrono::milliseconds(100));
   response.send(std::make_unique<result>(result{99}));
   // This gap matches the proposed helper and permits the one-second poll.
   std::this_thread::sleep_for(std::chrono::milliseconds(1250));
   response.send(std::make_unique<result>(result{99}));
  }
 });
 auto result=response.recv_with_timeout({42},1);
 auto elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
 notifications.join();
 if(result) std::terminate();
 return elapsed;
}
int main() {
 auto noisy=observe(true),quiet=observe(false);
 std::printf("{\"noisy_elapsed_s\":%.9f,\"quiet_elapsed_s\":%.9f}\n",noisy,quiet);
 return noisy>2.3 && noisy<3.5 && quiet>1.0 && quiet<1.3 ? 0 : 1;
}
'''
    source = header+'\n'+recv+'\n'+send+'\n'+main_cpp
    cpp=out/'pinned_queue.cpp';cpp.write_text(source)
    compile_result = subprocess.run(['g++','-std=c++17','-O0','-pthread',str(cpp),'-o',str(out/'queue_probe')],capture_output=True,timeout=20)
    (out/'COMPILE_STDOUT.bin').write_bytes(compile_result.stdout)
    (out/'COMPILE_STDERR.bin').write_bytes(compile_result.stderr)
    assert compile_result.returncode == 0, compile_result.stderr.decode()
    run=subprocess.run([str(out/'queue_probe')],capture_output=True,timeout=10)
    (out/'PROBE_STDOUT.bin').write_bytes(run.stdout);(out/'PROBE_STDERR.bin').write_bytes(run.stderr)
    assert run.returncode == 0, run.stderr.decode()
    measured=json.loads(run.stdout)
    parent=time.monotonic()-300
    (out/'SOLVE_CLOCK.json').write_text(json.dumps(dict(schema='parent_solve_clock_v1',budget_s=300,started_monotonic=parent)))
    polls=[]
    class Resource:
        @staticmethod
        def model_idle(endpoint,model):
            polls.append(time.monotonic())
            if len(polls)==1:
                raise RuntimeError('shared model slots are busy or idle telemetry is unavailable')
            return dict(model=model,processing_slots=0,health_status='ok')
    _,proof=failure.idle_after_failed_solver(out,dict(allow_shared_budget_failure=True,solve_supervisor_s=310),Resource,
        dict(llm_base_url='SIMULATED',model_name='SIMULATED'))
    assert len(polls)==2 and 1.2<=polls[1]-polls[0]<2
    assert proof['deadline_monotonic']==parent+310
    result=dict(schema='cancel_poll_quiet_pinned_queue_delta_v1',passed=True,
        server_queue_sha256=SERVER_QUEUE_SHA,
        extracted_recv_function_sha256=hashlib.sha256(recv.encode()).hexdigest(),
        extracted_send_function_sha256=hashlib.sha256(send.encode()).hexdigest(),
        exact_function_bodies_compiled=True,CPU_supporting_types_reduced=True,
        current_failure_source_sha256=hashlib.sha256(Path(failure.__file__).read_bytes()).hexdigest(),
        pinned_queue_measurement=measured,helper_quiet_gap_s=polls[1]-polls[0],helper_wait=proof,
        parent_age_and_resource_simulated=True,new_model_calls=0,new_EDA=0,new_FIFO=0,
        real_model_cancellation_qualified=False,real_seal_continuation_qualified=False,
        full_goal_complete=False)
    (out/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
