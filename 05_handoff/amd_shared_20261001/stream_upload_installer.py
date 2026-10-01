"""Stream a local tar over existing SSH into a NEW remote directory.
Never stores a second tar copy on the remote workspace. Keeps normal SSH
host-key verification and authentication; no credentials are stored here.
"""
import argparse
import pathlib
import shlex
import subprocess

ap=argparse.ArgumentParser()
ap.add_argument('archive',type=pathlib.Path)
ap.add_argument('--host',required=True,help='Existing user@host or SSH config alias')
ap.add_argument('--port',type=int,default=22)
ap.add_argument('--remote-dir',default='/workspace/vivado-offline-stage')
ap.add_argument('--identity',type=pathlib.Path)
ap.add_argument('--bom',type=pathlib.Path,default=pathlib.Path(__file__).with_name('linux-vivado-bom.json'))
args=ap.parse_args()
if args.host.startswith('-') or not 0 < args.port < 65536:
    raise SystemExit('Invalid SSH destination')
remote=pathlib.PurePosixPath(args.remote_dir)
if not str(remote).startswith('/workspace/') or '..' in remote.parts:
    raise SystemExit('Destination must be a new directory under /workspace/')
cmd=['ssh','-o','StrictHostKeyChecking=yes','-p',str(args.port)]
if args.identity: cmd+=['-i',str(args.identity)]
q=shlex.quote(str(remote))
import json
bom=json.loads(args.bom.read_text())
required=args.archive.stat().st_size+sum(a['expanded_bytes'] for a in bom['archives'])+8*1024**3
check="import shutil,sys; n=shutil.disk_usage('/workspace').free; print('Available bytes:',n,'Required bytes:',"+str(required)+"); sys.exit(0 if n >= "+str(required)+" else 2)"
cmd += [args.host, f'python3 -c {shlex.quote(check)} && mkdir -- {q} && tar -xf - -C {q}']
with args.archive.open('rb') as src:
    result=subprocess.run(cmd,stdin=src,check=False)
raise SystemExit(result.returncode)
