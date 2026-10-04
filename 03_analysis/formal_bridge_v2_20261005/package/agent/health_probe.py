"""Read-only endpoint/card attribution for health, separate from solving.

Counts the model server's one AMD card, not all GPUs or a guessed busiest card.
This instantaneous card counter does not certify target hardware or peak use.
"""
import ipaddress
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
from urllib.parse import urlparse

VERSIONS={}
VERSION_TIMEOUT=30

def _stop_owned(proc):
    if os.name=='nt':
        if proc.poll() is None:proc.kill()
    else:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass

def vivado_version(tool):
    if not tool:return None
    if tool in VERSIONS:return VERSIONS[tool]
    try:
        with tempfile.TemporaryDirectory(prefix='rtl-health-version-') as td:
            with subprocess.Popen([tool,'-version'],cwd=td,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',start_new_session=os.name!='nt') as proc:
                try:output,_=proc.communicate(timeout=VERSION_TIMEOUT)
                finally:
                    _stop_owned(proc)
                    if proc.poll() is None:proc.wait(timeout=5)
                rc=proc.returncode
        match=re.search(r'Vivado\s+v?(\d{4}\.\d+)',output,re.I)
        if rc==0 and match:
            VERSIONS[tool]=match[1]
            return match[1]
    except (OSError,subprocess.SubprocessError):pass
    # An unavailable/transient version check must recover on the next request.
    return None

def _address(hexaddr):
    raw=bytes.fromhex(hexaddr)
    if len(raw)==4:raw=raw[::-1]
    elif len(raw)==16:raw=b''.join(raw[i:i+4][::-1] for i in range(0,16,4))
    return ipaddress.ip_address(raw)

def _identity(pid):
    fields=(pid/'stat').read_text().rsplit(')',1)[1].split()
    if fields[0] in ['Z','X']:raise ValueError('not a live endpoint owner')
    return fields[19]

def _fds(pid):
    values=[]
    for fd in (pid/'fd').iterdir():
        try:values.append(os.readlink(fd))
        except FileNotFoundError:continue
    return values

def observe(base,proc=Path('/proc'),drm=Path('/sys/class/drm')):
    """Return a measured single card or None if attribution is ambiguous."""
    try:
        parsed=urlparse(base)
        if parsed.scheme not in ['http','https'] or parsed.hostname not in ['localhost','127.0.0.1','::1'] or parsed.username or parsed.password:return None
        port=parsed.port or (443 if parsed.scheme=='https' else 80)
        wanted={ipaddress.ip_address('127.0.0.1'),ipaddress.ip_address('::1')} if parsed.hostname=='localhost' else {ipaddress.ip_address(parsed.hostname)}
        inodes=set()
        for table in ['tcp','tcp6']:
            file=proc/'net'/table
            if not file.exists():continue
            for line in file.read_text().splitlines()[1:]:
                fields=line.split()
                if len(fields)<10 or fields[3]!='0A':continue
                address,hexport=fields[1].split(':')
                if int(hexport,16)!=port:continue
                ip=_address(address)
                if ip in wanted or ip.is_unspecified and any(x.version==ip.version for x in wanted):inodes.add(fields[9])
        if not inodes:return None
        owners=[]
        for pid in proc.glob('[0-9]*'):
            try:
                links=_fds(pid)
                if any('socket:['+inode+']' in links for inode in inodes):owners.append(pid)
            except (OSError,ValueError):continue
        if len(owners)!=1:return None
        owner=owners[0];start=_identity(owner);links=_fds(owner)
        nodes={Path(link).name for link in links if re.fullmatch(r'/dev/dri/renderD\d+',link)}
        if len(nodes)!=1:return None
        node=nodes.pop();device=drm/node/'device'
        if (device/'vendor').read_text().strip()!='0x1002':return None
        used=int((device/'mem_info_vram_used').read_text().strip());total=int((device/'mem_info_vram_total').read_text().strip())
        if not 0<=used<=total:return None
        after=_fds(owner)
        if _identity(owner)!=start or not any('socket:['+inode+']' in after for inode in inodes):return None
        if {Path(link).name for link in after if re.fullmatch(r'/dev/dri/renderD\d+',link)}!={node}:return None
        return {'model_pid':int(owner.name),'model_starttime':start,'render_node':node,'card_vram_used_bytes':used,'card_vram_total_bytes':total,'vram_gb':used/1024**3,'scope':'model endpoint owner single AMD card counter; instantaneous, not target/peak certification'}
    except (OSError,ValueError,IndexError,TypeError):return None

def vram_gb(base):
    result=observe(base)
    return result['vram_gb'] if result else None
