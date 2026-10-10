"""Linux real-clock/socket controls for the new HTTP-only absolute deadline."""
import hashlib,http.server,json,signal,sys,threading,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
assert sys.platform=='linux' and sys.dont_write_bytecode
import shared_budget
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
observed=[]
class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200)
        data=b'complete' if self.path=='/fast' else b' '*40
        self.send_header('Content-Length',str(len(data)));self.end_headers()
        item=dict(path=self.path,sent=0,closed=False);observed.append(item)
        try:
            if self.path=='/fast':self.wfile.write(data);self.wfile.flush();item['sent']=len(data)
            else:
                for byte in data:
                    self.wfile.write(bytes([byte]));self.wfile.flush();item['sent']+=1;time.sleep(.025)
        except (BrokenPipeError,ConnectionResetError):item['closed']=True
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Fixture)
server.daemon_threads=True
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='http://127.0.0.1:'+str(server.server_port)
initial_handler=signal.getsignal(signal.SIGALRM);initial_mask=signal.pthread_sigmask(signal.SIG_BLOCK,set())
assert signal.getitimer(signal.ITIMER_REAL)==(0.,0.)
def consume(budget,path):
    with budget.http_deadline():
        with opener.open(url+path,timeout=budget.remaining()) as response:return response.read()
def restored():
    assert signal.getsignal(signal.SIGALRM)==initial_handler
    assert signal.getitimer(signal.ITIMER_REAL)==(0.,0.)
    assert signal.pthread_sigmask(signal.SIG_BLOCK,set())==initial_mask
reports=[]
try:
    tick=time.monotonic();assert consume(shared_budget.SolveBudget(.5),'/fast')==b'complete';restored()
    reports.append(dict(case='real_http_fast_complete',passed=True,elapsed_s=time.monotonic()-tick))
    budget=shared_budget.SolveBudget(.2);tick=time.monotonic()
    try:consume(budget,'/trickle');raise AssertionError('Continuous body exceeded deadline')
    except shared_budget.BudgetExpired:pass
    elapsed=time.monotonic()-tick;assert .18<=elapsed<.4 and budget.expired();restored()
    item=next(r for r in observed if r['path']=='/trickle');assert item['sent']>=5
    reports.append(dict(case='real_continuous_body_absolute_deadline',passed=True,budget_s=.2,elapsed_s=elapsed,bytes_sent_before_interrupt=item['sent']))
    budget=shared_budget.SolveBudget(.28);tick=time.monotonic()
    assert consume(budget,'/fast')==b'complete';time.sleep(.09)
    remaining=budget.remaining();assert remaining<.21
    try:consume(budget,'/second');raise AssertionError('Second request reset the budget')
    except shared_budget.BudgetExpired:pass
    elapsed=time.monotonic()-tick;assert .26<=elapsed<.48;restored()
    reports.append(dict(case='real_second_http_uses_shared_remainder',passed=True,budget_s=.28,second_remainder_s=remaining,elapsed_s=elapsed))
    handler=lambda *a:None
    signal.signal(signal.SIGALRM,handler)
    try:
        try:
            with shared_budget.SolveBudget(.5).http_deadline():raise AssertionError('Foreign handler overwritten')
        except RuntimeError as e:assert 'handler already owned' in str(e)
        assert signal.getsignal(signal.SIGALRM) is handler
    finally:signal.signal(signal.SIGALRM,initial_handler)
    restored();reports.append(dict(case='refuse_foreign_signal_handler',passed=True))
    signal.signal(signal.SIGALRM,signal.SIG_IGN);signal.setitimer(signal.ITIMER_REAL,5)
    try:
        try:
            with shared_budget.SolveBudget(.5).http_deadline():raise AssertionError('Foreign timer overwritten')
        except RuntimeError as e:assert 'timer already owned' in str(e)
        assert signal.getitimer(signal.ITIMER_REAL)[0]>4
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,initial_handler)
    restored();reports.append(dict(case='refuse_foreign_timer',passed=True))
    before=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
    try:
        try:
            with shared_budget.SolveBudget(.5).http_deadline():raise AssertionError('Blocked deadline accepted')
        except RuntimeError as e:assert 'signal already blocked' in str(e)
        assert signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK,set())
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,before)
    restored();reports.append(dict(case='refuse_blocked_alarm_preserve_mask',passed=True))
    errors=[]
    def outside_main():
        try:
            with shared_budget.SolveBudget(.5).http_deadline():errors.append('incorrectly accepted')
        except RuntimeError as e:errors.append(str(e))
    t=threading.Thread(target=outside_main);t.start();t.join(2)
    assert not t.is_alive() and errors==['HTTP deadline requires the owned Linux main thread'];restored()
    reports.append(dict(case='refuse_non_main_thread',passed=True))
finally:
    server.shutdown();server.server_close();thread.join(2)
assert not thread.is_alive() and all(sha(ROOT/n)==h for n,h in manifest.items())
result=dict(schema='absolute_http_deadline_real_socket_delta_v1',passed=True,cases=reports,observed=observed,
 qualification_only=True,real_clock=True,real_http_fixture=True,HTTP_fixture_calls=len(observed),
 new_model_calls=0,new_eda_calls=0,new_FIFO=0,existing_cases_rerun=0)
(ROOT/'QUICK_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(passed=True,cases=len(reports),HTTP_fixture_calls=len(observed))))
