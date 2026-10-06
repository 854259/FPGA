"""Linux direct-child birth gate; preserve leader unreaped until owned cleanup."""
import ctypes,hashlib,json,os,signal,sys,time
from pathlib import Path
def sha(b):return hashlib.sha256(b).hexdigest()
def save(p,j):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
def snapshot(pid):
 p=Path('/proc')/str(pid);stat=(p/'stat').read_bytes();cmd=(p/'cmdline').read_bytes();v=stat.decode().rsplit(')',1)[1].split()
 return dict(pid=pid,state=v[0],starttime=v[19],pgid=int(v[2]),sid=int(v[3]),command_sha256=sha(cmd)),stat,cmd
def group(pgid):
 rows=[]
 for p in Path('/proc').glob('[0-9]*/stat'):
  try:
   r,_,_=snapshot(int(p.parent.name))
   if r['pgid']==pgid:rows.append(r)
  except (FileNotFoundError,ProcessLookupError):pass
 return sorted(rows,key=lambda r:r['pid'])
def bound(now,birth):return now['pid']==birth['pid'] and now['starttime']==birth['starttime'] and now['pgid']==now['sid']==birth['pid']
def run(argv,cwd,out,cap_s):
 assert sys.platform=='linux' and sys.dont_write_bytecode and isinstance(argv,list) and argv and all(isinstance(a,str) and a for a in argv) and 0<cap_s<=450
 assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
 out=Path(out);out.mkdir(exist_ok=False);cwd=Path(cwd).resolve();assert cwd.is_dir()
 start=time.monotonic();deadline=start+cap_s;pid=None;birth=None;reaped=False;status=None;err=None
 record=dict(schema='owned_preexec_birth_gate_v1',argv=argv,cwd=str(cwd),cap_s=cap_s,timeout=False,signals=[],exec_error=None,error=None,child_identity=None,exec_confirmed=False,returncode=None,remaining_group=[])
 def cancelled(sig,frame):raise InterruptedError('owned command interrupted '+str(sig))
 handlers={s:signal.signal(s,cancelled) for s in (signal.SIGTERM,signal.SIGINT)}
 fd=os.open(out/'stdout.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);rd,wr=os.pipe2(os.O_CLOEXEC|os.O_NONBLOCK)
 save(out/'ATTEMPT.json',dict(argv=argv,cwd=str(cwd),cap_s=cap_s,at_epoch=time.time()))
 try:
  pid=os.fork()
  if pid==0:
   try:
    os.close(rd);os.setsid();os.chdir(cwd);null=os.open('/dev/null',os.O_RDONLY);os.dup2(null,0);os.dup2(fd,1);os.dup2(fd,2);os.close(null);os.close(fd)
    os.kill(os.getpid(),signal.SIGSTOP)
    os.execvpe(argv[0],argv,os.environ.copy())
   except BaseException as e:
    try:os.write(wr,json.dumps(dict(type=type(e).__name__,text=str(e)[:500])).encode())
    except OSError:pass
    os._exit(127)
  os.close(wr);wr=None;os.close(fd);fd=None
  gate_deadline=min(deadline,start+.8)
  while True:
   got,state=os.waitpid(pid,os.WNOHANG|os.WUNTRACED)
   if got:
    if os.WIFSTOPPED(state) and os.WSTOPSIG(state)==signal.SIGSTOP:break
    reaped=True;status=state;raise RuntimeError('child exited before physical birth gate')
   if time.monotonic()>=gate_deadline:raise TimeoutError('physical birth gate not confirmed')
   time.sleep(.002)
  birth,stat,cmd=snapshot(pid);assert birth['state']=='T' and bound(birth,birth) and cmd
  (out/'birth_stat.bin').write_bytes(stat);(out/'birth_cmdline.bin').write_bytes(cmd)
  record['child_identity']=birth;save(out/'CHILD_IDENTITY.json',dict(identity=birth,stat_sha256=sha(stat),cmdline_sha256=sha(cmd),gate='SIGSTOP before exec',planned_argv=argv))
  now,_,_=snapshot(pid);assert now==birth
  os.kill(pid,signal.SIGCONT);record['signals'].append('SIGCONT_bound_preexec_child')
  while True:
   observed=os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
   if observed is not None:break
   if time.monotonic()>=deadline:record['timeout']=True;break
   time.sleep(.005)
 except BaseException as e:record['error']=type(e).__name__+': '+str(e)
 finally:
  if pid is not None and not reaped:
   try:
    now,_,_=snapshot(pid)
    terminal=now['state'] in ('Z','X')
    members=group(pid) if birth is not None else []
    live_members=[r for r in members if r['state'] not in ('Z','X')]
    if not terminal or live_members:
     if birth is not None:
      assert bound(now,birth);os.killpg(pid,signal.SIGKILL);record['signals'].append('SIGKILL_bound_unreaped_group')
     else:
      # PID cannot be reused: this exact direct child has not been reaped.
      os.kill(pid,signal.SIGKILL);record['signals'].append('SIGKILL_unreaped_direct_child_only')
    cleanup_deadline=time.monotonic()+5
    while True:
     got,state=os.waitpid(pid,os.WNOHANG)
     if got:status=state;reaped=True;break
     if time.monotonic()>=cleanup_deadline:raise TimeoutError('owned leader not reaped')
     time.sleep(.005)
   except BaseException as e:record['error']=(record['error']+'; ' if record['error'] else '')+type(e).__name__+': '+str(e)
  if pid is not None and reaped:
   cleanup_deadline=time.monotonic()+5
   while True:
    try:
     while os.waitpid(-pid,os.WNOHANG)[0]:pass
    except ChildProcessError:pass
    record['remaining_group']=group(pid)
    if not record['remaining_group'] or time.monotonic()>=cleanup_deadline:break
    time.sleep(.01)
  try:
   raw=os.read(rd,4096)
   if raw:record['exec_error']=json.loads(raw)
   elif birth is not None and reaped and status is not None:
    record['exec_confirmed']=True
  except (BlockingIOError,ValueError) as e:record['exec_error']=dict(type=type(e).__name__,text=str(e))
  os.close(rd)
  if wr is not None:os.close(wr)
  if fd is not None:os.close(fd)
  for s,h in handlers.items():signal.signal(s,h)
  record['returncode']=os.waitstatus_to_exitcode(status) if status is not None else None
  record.update(elapsed_s=time.monotonic()-start,leader_reaped=reaped,stdout_sha256=sha((out/'stdout.bin').read_bytes()),stdout_bytes=(out/'stdout.bin').stat().st_size)
  record['normal_completion']=bool(record['exec_confirmed'] and not record['timeout'] and record['error'] is None and record['exec_error'] is None and record['signals']==['SIGCONT_bound_preexec_child'] and not record['remaining_group'] and record['returncode'] is not None)
  save(out/'COMPLETE.json',record)
 return record
