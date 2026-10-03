"""Controlled local compiler process; no RTL correctness claims or real EDA."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

source = Path(sys.argv[-1]).read_text(encoding='utf-8')
record = {'pid': os.getpid(), 'source': str(Path(sys.argv[-1]).resolve()),
          'parent_pid': os.getppid(), 'cwd': str(Path.cwd())}
if 'FAKE_COMPILE_SPAWN_CHILD' in source:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    record['child_pid'] = child.pid
with Path(os.environ['FAKE_COMPILER_LOG']).open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(record) + '\n')
if 'FAKE_COMPILE_SLEEP' in source:
    time.sleep(30)
if 'FAKE_COMPILE_FAIL' in source:
    print('ERROR: controlled candidate compiler failure')
    raise SystemExit(1)
if ('FAKE_DECLARATION_CASE' in source
        and re.search(r'output\s+(?:wire\s+)?\[7:0\]\s+q\b', source)):
    print('ERROR: [VRFC 10-1280] procedural assignment to a non-register q')
    raise SystemExit(1)
print('Controlled fake compiler accepted; this is not a functional verdict.')
