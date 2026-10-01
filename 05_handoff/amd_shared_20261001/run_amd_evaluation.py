"""Run pinned development evaluator: reference3, model smoke3, reference156, full156."""
import datetime,hashlib,json,os,pathlib,shutil,signal,subprocess,time,traceback
team=pathlib.Path('/workspace/team')
kit=team/'tasks/autodl-rtl-kit'; project=kit/'project'
runroot=team/'runs/fpga_owner'/('amd156_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
runroot.mkdir(exist_ok=False)
scratch=runroot/'scratch'; scratch.mkdir()
state={'phase':'reference3','complete':False,'profile':'development','not_final_isolated_evaluation':True,'samples':1,'max_agent_repairs':1,'source_lock':json.loads((kit/'source-lock.json').read_text()),'stages':{}}
env=os.environ.copy()
env.update(PATH='/workspace/AMD/2026.1/Vivado/bin:'+env['PATH'],LD_LIBRARY_PATH='/workspace/team/udev-stub',XILINXD_LICENSE_FILE='/workspace/team/Xilinx.lic',XILINX_VIVADO='/workspace/AMD/2026.1/Vivado',LLM_BASE_URL='http://127.0.0.1:8000/v1',MODEL_NAME='Qwen3.6-27B-Q4_K_M',RTL_PROFILE='development',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',EDA_TMP=str(scratch),SELFTEST_TMP=str(scratch),NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')
def save(**items):
    state.update(items); p=runroot/'status.tmp'; p.write_text(json.dumps(state,indent=2)); p.replace(runroot/'status.json'); print(json.dumps({k:state[k] for k in ['phase','complete']}),flush=True)
def stage(name,tasks,reference=False):
    save(phase=name)
    out=runroot/name
    args=['python3','-B',str(project/'official_eval.py'),'--tasks',str(project/tasks),'--out',str(out),'--samples','1','--deadline','300']
    if reference: args.append('--reference')
    with (runroot/(name+'.log')).open('w') as log:
        p=subprocess.Popen(args,cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while p.poll() is None:
                if shutil.disk_usage('/workspace').free<8*1024**3: raise RuntimeError('Space below 8 GiB; evaluation stopped and evidence retained')
                time.sleep(10)
            assert p.returncode==0,name+' failed; inspect '+str(runroot/(name+'.log'))
        except BaseException:
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try: p.wait(timeout=20)
                except subprocess.TimeoutExpired: os.killpg(p.pid,signal.SIGKILL); p.wait()
            raise
    meta=json.loads((out/'experiment.json').read_text()); assert meta['complete']
    records=[json.loads(f.read_text()) for f in (out/'results').glob('*.json')]
    summary={'count':len(records),'L3':sum(r.get('level')==3 and not r.get('tool_error') for r in records),'tool_errors':sum(bool(r.get('tool_error')) for r in records)}
    state['stages'][name]=summary; save()
    return summary
try:
    save()
    a=stage('reference3','official_reference/tasks',True)
    assert a['count']==3 and a['L3']==3 and a['tool_errors']==0,'Reference fixtures did not all pass'
    save(phase='waiting_for_model')
    deadline=time.monotonic()+6*3600
    while True:
        model=json.loads((team/'model-deployment/status.json').read_text())
        if model.get('complete'): break
        assert model.get('phase')!='needs_attention','Model deployment needs attention'
        assert time.monotonic()<deadline,'Model wait timed out'; time.sleep(20)
    state['model_lock']=json.loads((team/'models/model-lock.json').read_text())
    a=stage('smoke3','official_reference/tasks')
    assert a['count']==6 and a['tool_errors']==0 and a['L3']>0,'Model pair smoke is not ready for full run'
    stage('reference156','bench/tasks_veval',True)
    stage('full156','bench/tasks_veval')
    save(phase='complete',complete=True,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
except BaseException as e:
    save(phase='needs_attention',error=str(e)); traceback.print_exc(); raise
