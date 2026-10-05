"""Owned AMD supervisor probe: spawn one child in this exact owned process group.

Not run during preparation/pure tests. Writes only the given owned scratch path.
The pinned paired runner must timeout, kill and reap both original identities.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def identity(pid):
    fields = (Path("/proc")/str(pid)/"stat").read_text().rsplit(")", 1)[1].split()
    return dict(pid=pid, starttime=fields[19], pgid=int(fields[2]))


def main(args):
    target = args.identity.resolve()
    if sys.platform != "linux" or target.parent != Path.cwd().resolve():
        raise ValueError("owned AMD Linux scratch identity only")
    owner = identity(os.getpid())
    child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(10)"],
                             stdin=subprocess.DEVNULL)
    descendant = identity(child.pid)
    if owner["pgid"] != owner["pid"] or descendant["pgid"] != owner["pgid"]:
        raise ValueError("probe not in one owned session/process group")
    payload = dict(schema="fsm_owned_supervisor_probe_identity_v2", owner=owner, child=descendant,
                   child_argv=[sys.executable, "-B", "-c", "import time; time.sleep(10)"])
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
    print("FSM_SUPERVISOR_IDENTITIES owner="+str(owner["pid"])+" child="+str(descendant["pid"]), flush=True)
    time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, required=True)
    main(parser.parse_args())
