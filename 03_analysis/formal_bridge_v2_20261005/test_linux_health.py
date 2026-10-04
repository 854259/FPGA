"""Linux-only owned version-command timeout and recovery, fake executable."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_health import hp

@unittest.skipUnless(sys.platform=='linux','Queued Linux process supervision check')
class LinuxHealth(unittest.TestCase):
    def test_version_timeout_removes_owned_descendant_and_next_check_recovers(self):
        hp.VERSIONS.clear()
        with tempfile.TemporaryDirectory(prefix='bridge-version-owned-') as td:
            root=Path(td);tool=root/'vivado';record=root/'owned.json'
            tool.write_text('''#!/usr/bin/env python3
import json,os,pathlib,subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
def identity(pid):return {'pid':pid,'starttime':pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
pathlib.Path(os.environ['OWN_VERSION_PIDFILE']).write_text(json.dumps({'parent':identity(os.getpid()),'child':identity(child.pid)}))
time.sleep(60)
''');tool.chmod(0o700)
            with patch.dict(os.environ,OWN_VERSION_PIDFILE=str(record)),patch.object(hp,'VERSION_TIMEOUT',.5):
                started=time.monotonic();self.assertIsNone(hp.vivado_version(str(tool)));self.assertLess(time.monotonic()-started,4)
            self.assertTrue(record.exists(),'Must reach the spawned tool and child, not merely time out beforehand')
            identities=json.loads(record.read_text())
            def live(row):
                try:
                    fields=(Path('/proc')/str(row['pid'])/'stat').read_text().rsplit(')',1)[1].split()
                    return fields[19]==row['starttime'] and fields[0] not in ['Z','X']
                except FileNotFoundError:return False
            until=time.monotonic()+3
            while any(live(row) for row in identities.values()) and time.monotonic()<until:time.sleep(.05)
            for row in identities.values():
                stat=Path('/proc')/str(row['pid'])/'stat'
                if stat.exists():
                    fields=stat.read_text().rsplit(')',1)[1].split()
                    self.assertFalse(fields[19]==row['starttime'] and fields[0] not in ['Z','X'])
            tool.write_text('#!/usr/bin/env python3\nprint("vivado v2026.1 (64-bit)")\n')
            self.assertEqual(hp.vivado_version(str(tool)),'2026.1')

if __name__=='__main__':unittest.main()
