#!/usr/bin/python3
"""Transparent owned native-tool journal; do not alter RTL/test/tool arguments."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,time,uuid

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    name=Path(sys.argv[0]).name
    assert name in ('iverilog','vvp')
    root=Path(os.environ['OWN_CALIBRATION_ROOT']).resolve()
    directory=Path(os.environ['OWN_NATIVE_JOURNAL']).resolve()
    assert directory.is_relative_to(root/'results')
    spec=json.loads((root/'RUN_SPEC.json').read_text())
    binding=spec['real_tools'][name];real=Path(binding['path'])
    assert sha(real)==binding['sha256']
    assert Path(sys.argv[0]).resolve().is_relative_to(root/'tools')
    assert sha(sys.argv[0])==spec['source_hashes']['tool_journal.py']
    cwd=Path.cwd().resolve();assert cwd.is_relative_to(root/'results')
    argv=[str(real),*sys.argv[1:]];output=None
    if name=='iverilog' and '-o' in argv:
        output=Path(argv[argv.index('-o')+1]);output=output if output.is_absolute() else cwd/output
        assert output.resolve().is_relative_to(root/'results')
    inputs={}
    for i,arg in enumerate(argv[1:],1):
        if i and argv[i-1]=='-o':continue
        p=Path(arg);p=p if p.is_absolute() else cwd/p
        if p.is_file() and p.resolve().is_relative_to(root/'results'):
            inputs[str(p.resolve())]=sha(p)
    directory.mkdir(parents=True,exist_ok=True)
    token=str(time.time_ns())+'-'+uuid.uuid4().hex
    before_xml={str(p.resolve()):p.stat().st_mtime_ns for p in cwd.glob('*.xml')}
    started_ns=time.time_ns();tick=time.monotonic();process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    stdout,stderr=process.communicate()
    Path(directory/(token+'.stdout')).write_bytes(stdout);Path(directory/(token+'.stderr')).write_bytes(stderr)
    artifacts={}
    if output is not None and output.is_file():
        target=directory/(token+'.compiled.vvp');target.write_bytes(output.read_bytes())
        artifacts['compiled']=dict(path=target.name,sha256=sha(target),original_path=str(output.resolve()))
    xmls=[]
    if name=='vvp':
        for i,p in enumerate(sorted(cwd.glob('*.xml'))):
            target=directory/(token+'.'+str(i)+'.xml');target.write_bytes(p.read_bytes())
            xmls.append(dict(path=target.name,sha256=sha(target),original_path=str(p.resolve()),
                mtime_ns=p.stat().st_mtime_ns,before_mtime_ns=before_xml.get(str(p.resolve()))))
    receipt=dict(schema='owned_native_journal_v1',name=name,argv=argv,cwd=str(cwd),
        executable_sha256=binding['sha256'],returncode=process.returncode,child_pid=process.pid,
        elapsed_s=time.monotonic()-tick,started_ns=started_ns,source_input_sha256=inputs,artifacts=artifacts,xmls=xmls,
        stdout=dict(path=token+'.stdout',sha256=hashlib.sha256(stdout).hexdigest(),bytes=len(stdout)),
        stderr=dict(path=token+'.stderr',sha256=hashlib.sha256(stderr).hexdigest(),bytes=len(stderr)))
    (directory/(token+'.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    sys.stdout.buffer.write(stdout);sys.stdout.buffer.flush();sys.stderr.buffer.write(stderr);sys.stderr.buffer.flush()
    return process.returncode

if __name__=='__main__':raise SystemExit(main())
