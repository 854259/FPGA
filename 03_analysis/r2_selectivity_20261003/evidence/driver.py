from pathlib import Path
import subprocess,sys,json,hashlib,time
root=Path(__file__).resolve().parent;src=root/'src';manifest=json.loads((src/'source_manifest.json').read_text());out=root/'results';out.mkdir(exist_ok=False)
lock=Path('/workspace/team/SLOT.lock').read_bytes();assert lock.decode().splitlines()[0]=='codex_r2b_20261003'
def check():
 assert Path('/workspace/team/SLOT.lock').read_bytes()==lock
 for name,h in manifest.items():assert hashlib.sha256((src/name).read_bytes()).hexdigest()==h,name
commands=[('fixtures',[str(src/'r2_selectivity/fixtures/probe_runner.py'),'--selector',str(src/'signedness_selector.py'),'--out',str(out/'fixtures')]),('guards',[str(src/'r2_selectivity/guards/probe_runner.py'),'validate-guards','--out',str(out/'guards')]),('lfsr',[str(src/'r3_lfsr/probes/run_probe.py'),'--out',str(out/'lfsr')])]
rows=[]
for stage,args in commands:
 check();start=time.time()
 with (root/(stage+'.log')).open('xb') as log:
  rc=subprocess.call([sys.executable,'-B',*args],stdout=log,stderr=subprocess.STDOUT)
 check();rows.append(dict(stage=stage,rc=rc,started=start,ended=time.time()))
 (root/'driver_status.json').write_text(json.dumps(rows,indent=2)+'\n')
 print(stage,rc,flush=True)
sys.exit(0 if all(x['rc']==0 for x in rows) else 1)
