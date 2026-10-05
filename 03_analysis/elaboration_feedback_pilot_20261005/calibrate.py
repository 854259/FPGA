"""Two native tool controls before any model request; no task/reference inputs."""
from pathlib import Path
import elaboration_feedback
from worker import save,sha

CONTROLS = {
    'single_driver': ('module TopModule(input logic clk, output logic q);\n'
                      'always_ff @(posedge clk) q <= 1\'b1;\nendmodule\n', False),
    'multiple_driver': ('module TopModule(input logic clk, output logic q);\n'
                        'always_ff @(posedge clk) q <= 1\'b1;\n'
                        'always_comb q = 1\'b0;\nendmodule\n', True),
}

def check(out, paired, tools):
    out.mkdir(exist_ok=False)
    rows=[]
    for name,(code,should_fail) in CONTROLS.items():
        folder=out/name
        folder.mkdir()
        compile_dir=folder/'compile-0'
        compile_dir.mkdir()
        source=compile_dir/'candidate.sv'
        source.write_text(code,encoding='utf-8',newline='\n')
        argv=[str(tools/'xvlog'),'--sv',str(source)]
        log=folder/'compile.log'
        command=paired.owned_command(argv,compile_dir,log,60)
        command.update(argv=argv,source_sha256=sha(source))
        save(folder/'compile.json',command)
        assert command['returncode']==0 and not command['timeout']
        assert not command['launch_error'] and not command['remaining_live_group']
        diagnostic=elaboration_feedback.check(code,compile_dir,folder,0,
                                              paired.owned_command,str(tools/'xelab'))
        assert bool(diagnostic)==should_fail, name+' tool control failed'
        row=dict(name=name,source_sha256=sha(source),diagnostic=diagnostic,
                 detected_failure=bool(diagnostic),expected_failure=should_fail)
        save(folder/'result.json',row)
        rows.append(row)
    receipt=dict(schema='elaboration_native_controls_v1',complete=True,passed=True,
                 model_calls=0,native_compile_attempts=2,native_elaboration_attempts=2,
                 task_or_reference_inputs=False,rows=rows)
    save(out/'RESULTS.json',receipt)
    return receipt
