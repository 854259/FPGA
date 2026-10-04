"""Owned network-namespace capability probe; never changes host networking."""
import hashlib,json,os,shutil,signal,subprocess,time
from pathlib import Path
assert os.name=='posix'
host=os.readlink('/proc/self/ns/net')
payload="import os,json; print(json.dumps({'own_netns':os.readlink('/proc/self/ns/net'),'uid':os.getuid()}))"
argv=['unshare','--user','--map-root-user','--net','/usr/bin/python3','-c',payload]
out={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'host_netns':host,'uid':os.getuid(),'tools':{n:shutil.which(n) for n in ['unshare','ip','docker','podman','strace']},'model_calls':0,'eda_calls':0,'host_network_changed':False,'offline_verified':False,'target_single32gb_verified':False}
p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',start_new_session=True)
timeout=False
try:stdout,stderr=p.communicate(timeout=8)
except subprocess.TimeoutExpired:
    timeout=True
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    stdout,stderr=p.communicate(timeout=5)
finally:
    # Select only this newly created group; no model, teammate or host service.
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
assert os.readlink('/proc/self/ns/net')==host
try:os.killpg(p.pid,0);group_gone=False
except ProcessLookupError:group_gone=True
out['namespace_probe']={'argv':argv,'pid':p.pid,'returncode':p.returncode,'timeout':timeout,'stdout':stdout,'stderr':stderr,'owned_group_gone':group_gone}
out['isolated_namespace_created']=p.returncode==0 and not timeout and json.loads(stdout)['own_netns']!=host
print(json.dumps(out,ensure_ascii=False))
