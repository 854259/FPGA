"""AMD-only isolated pure checker controls; native adapter remains unqualified."""
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.request


def forbidden(*a,**k):raise RuntimeError('pure stage forbids process/network operations')


assert sys.platform=='linux' and sys.dont_write_bytecode
root=Path(__file__).resolve().parent
out=root/'results';out.mkdir(exist_ok=False)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((root/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(root/n)==h for n,h in manifest.items())
stream=io.StringIO()
with patch.object(subprocess,'Popen',forbidden),patch.object(subprocess,'run',forbidden),patch.object(socket,'socket',forbidden),patch.object(urllib.request,'urlopen',forbidden):
 import test_adapter
 tests=unittest.defaultTestLoader.loadTestsFromModule(test_adapter)
 result=unittest.TextTestRunner(stream=stream,verbosity=2).run(tests)
assert all(sha(root/n)==h for n,h in manifest.items())
(out/'CONTROLS_LOG.txt').write_text(stream.getvalue(),encoding='utf-8')
summary=dict(passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
 source_hashes_held=True,new_model_calls=0,new_eda_calls=0,new_fifo_tickets=0,
 native_adapter_qualified=False,worker_integrated=False,score_measured=False,
 scope='New simulated native-adapter trust-boundary controls; no native correctness or model gain.')
(out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary))
raise SystemExit(0 if result.wasSuccessful() else 1)
