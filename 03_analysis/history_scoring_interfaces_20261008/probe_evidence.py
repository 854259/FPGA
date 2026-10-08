"""Original read-only common functional probe evidence; never runs EDA."""
import hashlib,json
from pathlib import Path,PurePosixPath
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def verify(check,task,c,parser,feedback,runner,shared,dependencies,phase_context,edge_contract):
    assert (check/'inputs'/task/'tb.sv').read_text(encoding='utf-8')==parser.render_tb(c,task)
    raw=read(check/'probe/result.json');adapter=read(check/'probe/adapter_receipt.json')
    assert all(adapter[k]==v for k,v in raw.items()) and adapter['inherited_result_sha256']==sha(check/'probe/result.json')
    assert adapter['inherited_runner_sha256']==sha(dependencies/'probe_runner.py')
    assert adapter['oracle_adapter_sha256']==sha(dependencies/'paired_checkpoint.py')
    assert raw['runner_sha256']==sha(dependencies/'probe_runner.py') and raw['inputs_unchanged']
    assert raw['solution_sha256']==sha(check/'input.sv')==sha(check/'probe/dut.sv')
    assert raw['tb_sha256']==sha(check/'inputs'/task/'tb.sv')==sha(check/'probe/tb.sv')
    assert raw['task']==task and len(raw['stages'])==3
    for stage,name in zip(raw['stages'],['xvlog','xelab','xsim']):
        assert stage['name']==name and PurePosixPath(stage['argv'][0]).name==name
        shared.command(stage,check/'probe'/(name+'.log'))
        assert not runner.ENVIRONMENT_ERROR.search((check/'probe'/(name+'.log')).read_text(encoding='utf-8',errors='replace'))
    runner.TASK_CHECKS[task]=c['checks'];log=(check/'probe/xsim.log').read_text(encoding='utf-8')
    count,mismatches=runner._parse_summary(log,task)
    assert raw['checks']==count==c['checks'] and raw['mismatches']==mismatches
    assert raw['status']==('pass' if mismatches==0 else 'fail') and raw['failure_kind']==(None if mismatches==0 else 'semantic_mismatch')
    if c.get('family')=='edge':
        observed,bound=phase_context.context(log,c,edge_contract)
        assert (bound is None)==(mismatches==0)
    if mismatches:
        point=parser.counterexample(log,c);assert read(check/'counterexample.json')==point
        assert read(check/'feedback.json')['text']==feedback.render(c,adapter,point)
    return raw
