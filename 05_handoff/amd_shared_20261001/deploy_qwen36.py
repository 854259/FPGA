"""Download the pinned Q4_K_M model, build HIP llama.cpp, start localhost service."""
import hashlib,json,os,pathlib,shutil,subprocess,tarfile,time,traceback,urllib.request
root=pathlib.Path('/workspace/team'); logs=root/'model-deployment'; logs.mkdir(exist_ok=True)
state={'phase':'preparing','complete':False}
def save(**items):
    state.update(items); temp=logs/'status.tmp'; temp.write_text(json.dumps(state,indent=2)); temp.replace(logs/'status.json'); print(json.dumps(state),flush=True)
env=os.environ.copy()
for item in pathlib.Path('/proc/1/environ').read_bytes().split(b'\0'):
    key,sep,value=item.partition(b'=')
    if sep and key.decode(errors='ignore') in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy']:
        env[key.decode()]=value.decode()
env['NO_PROXY']=env['no_proxy']='127.0.0.1,localhost'
env['LD_LIBRARY_PATH']='/opt/rocm/lib:/opt/rocm/lib64'
env['PATH']='/opt/rocm/bin:/opt/rocm/llvm/bin:'+env['PATH']
model=root/'models/Qwen3.6-27B-Q4_K_M.gguf'; partial=model.with_suffix('.gguf.partial')
size=19095766304; sha='65b753ea835627f7b511143c6ceb976525c7f21f5df8c664bc0a9c23d1c49921'
url='https://hf-mirror.com/ggml-org/Qwen3.6-27B-GGUF/resolve/8a7ee08e8b9bfb857107ecc25a5599d2f38b76f8/Qwen3.6-27B-Q4_K_M.gguf?download=true'
src=root/'tools/llama-src'; build=root/'tools/llama-build'
def run(cmd,name):
    with (logs/(name+'.log')).open('w') as f:
        subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
download=None
try:
    needed=0 if model.exists() else size-(partial.stat().st_size if partial.exists() else 0)
    assert shutil.disk_usage('/workspace').free>needed+10*1024**3,'Need model remainder plus 10 GiB for build and tests'
    if not model.exists():
        save(phase='downloading_model_and_building_backend',expected_model_bytes=size)
        dl=(logs/'download.log').open('w')
        download=subprocess.Popen(['/usr/bin/curl','-L','--fail','--retry','6','--retry-delay','10','--connect-timeout','25','--speed-limit','1024','--speed-time','120','-C','-','-o',str(partial),url],env=env,stdout=dl,stderr=subprocess.STDOUT)
    if not src.exists():
        src.mkdir()
        subprocess.run(['tar','-xzf','/workspace/llama-v0.5.0-source.tar.gz','--strip-components=1','-C',str(src)],check=True)
    run(['cmake','-S',str(src),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DLLAMA_BUILD_COMMIT=c13fcbf','-DGGML_HIP=ON','-DAMDGPU_TARGETS=gfx1100','-DCMAKE_HIP_ARCHITECTURES=gfx1100','-DGGML_NATIVE=OFF','-DLLAMA_BUILD_TESTS=OFF','-DLLAMA_BUILD_EXAMPLES=OFF','-DLLAMA_BUILD_APP=OFF','-DLLAMA_USE_PREBUILT_UI=OFF','-DLLAMA_BUILD_UI=OFF','-DLLAMA_OPENSSL=OFF'],'configure')
    run(['cmake','--build',str(build),'--target','llama-server','-j','8'],'build')
    save(phase='waiting_for_model',backend_built=True)
    if download:
        assert download.wait()==0,'Model download failed; see download.log'
        dl.close()
    candidate=model if model.exists() else partial
    assert candidate.stat().st_size==size,'Downloaded model size mismatch'
    save(phase='checking_model_sha256')
    with candidate.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
    assert actual==sha,'Model SHA-256 mismatch'
    if candidate==partial: partial.rename(model)
    model.chmod(0o644)
    lock={'repository':'ggml-org/Qwen3.6-27B-GGUF','revision':'8a7ee08e8b9bfb857107ecc25a5599d2f38b76f8','quantization':'Q4_K_M','bytes':size,'sha256':actual}
    (root/'models/model-lock.json').write_text(json.dumps(lock,indent=2))
    save(phase='loading_gpu_model',model_sha256_verified=True)
    cmd=[str(build/'bin/llama-server'),'-m',str(model),'--alias','Qwen3.6-27B-Q4_K_M','--host','127.0.0.1','--port','8000','-ngl','99','-c','16384','-np','1','-t','8','--reasoning','off']
    serverlog=(logs/'server.log').open('a')
    server=subprocess.Popen(cmd,env=env,stdout=serverlog,stderr=subprocess.STDOUT,start_new_session=True)
    (logs/'server.pid').write_text(str(server.pid))
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+600
    while True:
        assert server.poll() is None,'Model server exited; see server.log'
        try:
            with opener.open('http://127.0.0.1:8000/health',timeout=5) as r:
                if r.status==200: break
        except Exception: pass
        assert time.monotonic()<deadline,'Model startup timeout'; time.sleep(5)
    payload={'model':'Qwen3.6-27B-Q4_K_M','messages':[{'role':'user','content':'Return only synthesizable Verilog for module top_module(input a,input b,output y); y is a XOR b. No explanation.'}],'max_tokens':256,'temperature':0}
    req=urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=120) as r: answer=json.load(r)
    (logs/'model-response-smoke.json').write_text(json.dumps(answer,indent=2))
    text=answer['choices'][0]['message']['content']; assert text and 'module' in text,'Model response smoke failed'
    save(phase='model_ready_rtl_evaluation_pending',complete=True,server_pid=server.pid,response_smoke_passed=True,workspace_free_bytes=shutil.disk_usage('/workspace').free)
except BaseException as e:
    save(phase='needs_attention',error=str(e)); traceback.print_exc()
    # Keep an independent resumable download alive if a build fails.
    raise
