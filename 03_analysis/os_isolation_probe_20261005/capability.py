"""Read-only Linux kernel feature queries, not a sandbox or native IO admission."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys


def query():
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise PermissionError('probe only implements the observed Linux x86_64 ABI')
    # Read the installed kernel userspace header; do not guess syscall numbers.
    header = Path('/usr/include/asm-generic/unistd.h')
    raw = header.read_bytes()
    matches = re.findall(rb'^#define\s+__NR_landlock_create_ruleset\s+(\d+)\s*$', raw, re.M)
    if len(matches) != 1:
        raise ValueError('installed header does not contain one literal Landlock syscall number')
    number = int(matches[0])
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    result = libc.syscall(ctypes.c_long(number), ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    observed_errno = ctypes.get_errno()
    # GET operations only. This process installs no policy or no_new_privs flag.
    seccomp = libc.prctl(21, 0, 0, 0, 0)
    no_new_privs = libc.prctl(39, 0, 0, 0, 0)
    stat = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
    return dict(schema='os_isolation_backend_capability_query_v1', pid=os.getpid(), starttime=stat[19],
                kernel=platform.release(), machine=platform.machine(), python=platform.python_version(),
                header=str(header), header_sha256=hashlib.sha256(raw).hexdigest(),
                syscall_number=number, syscall_args=[0, 0, 1], query_returncode=result,
                observed_errno=observed_errno, observed_errno_text=os.strerror(observed_errno),
                landlock_query_available=result >= 1, landlock_abi=result if result >= 1 else None,
                seccomp_mode_query=seccomp, no_new_privs_query=no_new_privs,
                installed_policy=False, namespace_created=False, network_requests=0,
                actual_model_calls=0, actual_eda_calls=0, sandbox_verified=False,
                real_execution_admitted=False, offline_target32GB_verified=False,
                scope='Observed query only; denial may be kernel or outer policy. No global unsupported claim.')


if __name__ == '__main__':
    print(json.dumps(query()))
