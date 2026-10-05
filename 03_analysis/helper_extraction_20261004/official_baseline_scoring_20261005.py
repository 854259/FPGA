"""External evaluator bridge; never import this in the solver process."""
import argparse
import importlib.util
import json
from pathlib import Path

import official_baseline_arm_20261005 as arm

EVALUATOR = Path('/workspace/team/runs/fpga_owner/phase_full156_20261005_v1/official_eval_guarded.py')
EVALUATOR_SHA = '5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'
UPSTREAM_SHA = '0e47545af9001ecd884807ef6008c9c88700cf77d72f543c357103888698984b'


def eligible(solve, task, selected_arm='B'):
    solve, task = Path(solve), Path(task)
    assert selected_arm in ['A', 'P', 'B']
    if selected_arm != 'B':
        result = json.loads((solve/'worker_result.json').read_text())
        assert result['complete'] and result['arm'] == selected_arm
        requests = json.loads((solve/'requests.json').read_text())
        assert 1 <= len(requests) <= 2
        assert {p.name for p in (solve/'requests').iterdir()} == {str(i) for i in range(len(requests))}
        assert result['requests'] == result['actual_model_requests'] == len(requests)
        for index, request in enumerate(requests):
            assert request['index'] == index and request['response_received'] and not request['replayed']
            folder = solve/'requests'/str(index)
            for name in ['request', 'response']:
                assert arm.sha(folder/(name+'.json')) == request[name+'_sha256']
            payload = json.loads((folder/'request.json').read_text())
            assert (payload['model'],payload['temperature'],payload['top_p'],payload['max_tokens']) == (arm.MODEL,0,1,8192)
            assert json.loads((folder/'response.json').read_text())['choices'][0]['message']
        inputs = {p.name:arm.sha(p) for p in (solve/'prompt_only').iterdir()}
        assert inputs.get('prompt.txt') and set(inputs) <= {'prompt.txt','interface.txt'}
        assert inputs == {n:arm.sha(task/n) for n in inputs}
        assert result['solution_sha256'] == arm.sha(solve/'solution.v')
        assert (solve/'trace.jsonl').is_file()
        trace = [json.loads(line) for line in (solve/'trace.jsonl').read_text().splitlines()]
        llm = [event for event in trace if event.get('tool') == 'llm']
        assert len(llm) == len(requests) and all('error' not in event for event in llm)
        return dict(**result,input_sha256=inputs,trace_sha256=arm.sha(solve/'trace.jsonl'),
                    solution_relative='solution.v',result_relative='worker_result.json',
                    client_request_attempts=len(requests))
    result = json.loads((solve/'RESULTS.json').read_text())
    assert result['complete'] and result['transport_ok'] and result['recorder_ready']
    assert result['client_request_attempts'] == result['confirmed_model_responses'] == 1
    assert result['complete_http_bodies'] == 1 and not result['unconfirmed_call']
    assert result['solution_sha256'] == arm.sha(solve/'output/solution.v')
    assert result['trace_sha256'] == arm.sha(solve/'output/trace.jsonl')
    for name, expected in result['input_sha256'].items():
        assert arm.sha(task/name) == arm.sha(solve/'prompt_only'/name) == expected
    state = json.loads((solve/'transport/request_0/STATE.json').read_text())
    assert state == result['transport_receipts'][0] and state['response_body_complete']
    for name in ['request','response']:
        assert arm.sha(solve/'transport/request_0'/(name+'.bin')) == state[name+'_sha256']
    return dict(**result,solution_relative='output/solution.v',result_relative='RESULTS.json')


def main(args):
    # Transport/unknown calls fail before creating a judge directory or invoking
    # the official rule that would otherwise grade their empty file as L0.
    selected_arm = getattr(args, 'arm', 'B')
    original = eligible(args.solve, args.task, selected_arm)
    resource = arm.resource_module()
    resource.check_resource(args.resource_check,args.kit)
    assert arm.sha(EVALUATOR) == EVALUATOR_SHA
    meta_path=args.kit/'official_reference/UPSTREAM.json'
    assert arm.sha(meta_path) == UPSTREAM_SHA
    upstream=json.loads(meta_path.read_text())
    for name, expected in upstream['files'].items():
        assert arm.sha(args.kit/name) == expected
    assert not args.out.exists()
    args.out.mkdir(parents=True)
    spec=importlib.util.spec_from_file_location('baseline_external_judge',EVALUATOR)
    evaluator=importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluator)
    evaluator.OFFICIAL=args.kit/'official_reference'
    verdict=evaluator.judge_sample(args.task,args.solve/original['solution_relative'],args.out,args.out/'verdict.json',300)
    assert not verdict.get('tool_error') and verdict['judge_evidence_complete']
    assert verdict['task_id']==json.loads((args.task/'task.json').read_text())['task_id']
    assert eligible(args.solve,args.task,selected_arm)==original
    resource.check_resource(args.resource_check,args.kit)
    arm.save(args.out/'BOUND_VERDICT.json',dict(
        arm=selected_arm,solve_result_sha256=arm.sha(args.solve/original['result_relative']),
        solution_sha256=original['solution_sha256'],verdict_sha256=arm.sha(args.out/'verdict.json'),
        evaluator_sha256=EVALUATOR_SHA,official_upstream_commit=upstream['commit'],
        task_files={p.name:arm.sha(p) for p in args.task.iterdir() if p.is_file()},
        client_request_attempts=original['client_request_attempts'],server_received_count=None,verdict=verdict))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--arm',choices=['A','P','B'],default='B')
    for name in ['kit','solve','task','out','resource-check']:
        parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
