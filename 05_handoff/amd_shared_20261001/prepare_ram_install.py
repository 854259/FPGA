"""Verify our slim TAR, stage in tmpfs and optionally remove its cloud upload copy.
The original and verified slim package remain on the owner's local computer.
"""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, time

ap=argparse.ArgumentParser()
ap.add_argument('--remove-upload-copy',action='store_true')
ap.add_argument('--wait-for-upload',action='store_true')
args=ap.parse_args()
archive=pathlib.Path('/workspace/Vivado-2026.1-Linux-ZynqMP-minimal.tar')
stage=pathlib.Path('/dev/shm/vivado-stage-20261001')
bootstrap=pathlib.Path('/workspace/vivado-installer-20261001')
expected_size=26371880960
expected_sha='dae39976c08a6ef559a25306cc8005616f2952c60ec03183f250772b7ba92708'
tree_bytes=26368561948
expanded=69099630929
def check(ok,message):
    if not ok: raise SystemExit('STOP: '+message)
def digest(path,algorithm):
    h=hashlib.new(algorithm)
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''): h.update(block)
    return h.hexdigest()
check(sys.platform=='linux','Linux only')
if args.wait_for_upload:
    deadline=time.monotonic()+12*3600
    while not archive.exists() or archive.stat().st_size<expected_size:
        check(time.monotonic()<deadline,'upload timeout after 12 hours')
        time.sleep(15)
    # Jupyter's final chunk must be flushed before hashing.
    time.sleep(5)
check(archive.is_file() and archive.stat().st_size==expected_size,'upload incomplete or unexpected file')
check(not stage.exists(),'staging directory already exists; inspect before resuming')
check(not bootstrap.exists(),'bootstrap directory already exists')
limit=pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()
used=int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text())
check(limit.isdigit(),'finite cgroup memory limit must be known')
check(int(limit)-used>tree_bytes+16*1024**3,'need component size plus 16 GiB memory headroom')
check(shutil.disk_usage('/dev/shm').free>tree_bytes+1024**3,'tmpfs free space insufficient')
check(shutil.disk_usage('/workspace').free+expected_size>expanded+8*1024**3,'disk would remain too small after upload cleanup')
print('Checking uploaded SHA-256...',flush=True)
check(digest(archive,'sha256')==expected_sha,'TAR digest mismatch')
stage.mkdir(mode=0o700)
print('Extracting verified TAR into RAM...',flush=True)
subprocess.run(['tar','-xf',str(archive),'-C',str(stage)],check=True)
root=stage/'FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700'
bom=json.loads((stage/'deployment/linux-vivado-bom.json').read_text())
for i,a in enumerate(bom['archives'],1):
    p=root/'payload'/(a['archive']+'.xz')
    check(p.is_file() and p.stat().st_size==a['compressed_bytes'],'payload size: '+p.name)
    check(digest(p,'md5')==a['md5'],'payload checksum: '+p.name)
    if i%100==0: print('Checked',i,'payloads',flush=True)
check(len(bom['archives'])==902,'unexpected component count')
# tmpfs may be noexec: execute only the small bootstrap from the normal disk.
shutil.copytree(root,bootstrap,symlinks=True,ignore=shutil.ignore_patterns('payload'))
(bootstrap/'payload').symlink_to(root/'payload',target_is_directory=True)
record={'stage':str(stage),'executable_installer':str(bootstrap),'archive_sha256':expected_sha,'payloads_verified':902,'installed':False,'upload_copy_removed':False}
if args.remove_upload_copy:
    # Exact generated upload only; never remove arbitrary user paths.
    check(archive.parent==pathlib.Path('/workspace') and not archive.is_symlink(),'unexpected upload location')
    archive.unlink()
    record['upload_copy_removed']=True
record['workspace_free_bytes']=shutil.disk_usage('/workspace').free
record['memory_current_bytes']=int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text())
pathlib.Path('/workspace/ram-stage-verification.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2),flush=True)
check(record['workspace_free_bytes']>=expanded+8*1024**3,'disk check after cleanup failed')
print('RAM_STAGE_READY; installation has NOT run.',flush=True)
