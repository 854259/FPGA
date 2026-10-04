"""Actual stage scheduling exercised with file-only fake tools; never native proof."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import calibrate

ROOT=Path(__file__).resolve().parent
FAKE = r'''
import hashlib,json
from pathlib import Path
import fsm_contract,prepare_controls
REPO=None
INHERITED_ORACLE=None
def record(kind,details):
 with (REPO/'FAKE_TOOL_CALLS.jsonl').open('a') as f:f.write(json.dumps({'kind':kind,**details})+'\n')
def check_resource(path,kit,first=False):pass
def oracle(test,solution,out):
 out.mkdir(parents=True);c=json.loads((solution.parent/'contract.json').read_text());name=solution.stem
 predicted=prepare_controls.software(c,name) if name!='candidate' else [o['expected']^1 for o in c['observations']]
 mismatches=[(o,v) for o,v in zip(c['observations'],predicted) if o['expected']!=v]
 text=''
 if mismatches:
  o,v=mismatches[0];bits=''.join(str(o['inputs'][k]) for k in c['input_names'])
  text=f'FSM_FIRST case={o["case"]} state={o["state"]:x} inputs={bits} expected={o["expected"]:x} observed={v:x}\n'
 (out/'xsim.log').write_text(text)
 record('fake_probe',{'task':test['task'],'name':name})
 return {'checks':c['checks'],'mismatches':len(mismatches),'status':'fail' if mismatches else 'pass','failure_kind':'semantic_mismatch' if mismatches else None}
def owned_command(argv,cwd,log,timeout):
 assert Path(argv[0]).name=='vivado' and argv[1:]==['-mode','batch','-source','run.tcl','-nolog','-nojournal']
 Path(log).write_text('FAKE_ONLY FSM_SYNTHESIS_PASS\n');record('fake_synth',{'argv':argv})
 return {'returncode':0,'timeout':False,'remaining_live_group':False,'launch_error':False,'argv':argv}
'''

class Schedule(unittest.TestCase):
    def run_fixture(self,damaged=False):
        with tempfile.TemporaryDirectory(prefix='fsm-pure-schedule-') as tmp:
            root=Path(tmp);shutil.copytree(ROOT/'raw_evidence/inputs',root/'raw_evidence/inputs')
            deps=root/'deps';deps.mkdir();(deps/'paired_checkpoint.py').write_text(FAKE);(deps/'probe_runner.py').write_text('# Not run\n')
            marker=root/'frozen.txt';marker.write_text('original')
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            cases=json.loads((ROOT/'CONTROL_PREPARATION.json').read_text())['cases']
            spec=dict(dependencies_cloud=str(deps),dependency_hashes={p.name:sha(p) for p in deps.iterdir()},source_hashes={'frozen.txt':sha(marker)},
                      timeout_s=1140,cases=cases,control_names=['positive','missing_hold','missing_output','wrong_condition','shifted_encoding','constant_zero'],
                      expected_natural_candidates={r['task']:'fail' for r in cases if r['archived_candidate']})
            (root/'RUN_SPEC.json').write_text(json.dumps(spec))
            if damaged:marker.write_text('changed')
            fake_cdll=type('Library',(),{'prctl':lambda *a:0})()
            with patch.object(calibrate,'ROOT',root),patch.object(calibrate.sys,'platform','linux'),patch.object(calibrate.ctypes,'CDLL',return_value=fake_cdll),patch.dict(os.environ,{'VIVADO_BIN':'/fake/bin'}),patch.object(calibrate.sys,'argv',['calibrate.py','--kit',str(root/'kit'),'--resource-check',str(root/'resource.json')]):
                rc=calibrate.main()
            report=json.loads((root/'results/summary.json').read_text())
            calls=[json.loads(s) for s in (root/'FAKE_TOOL_CALLS.jsonl').read_text().splitlines()] if (root/'FAKE_TOOL_CALLS.jsonl').exists() else []
            return rc,report,calls
    def test_actual_stage_26_fake_probes_4_fake_synth_no_model(self):
        rc,r,calls=self.run_fixture();self.assertEqual(rc,0);self.assertTrue(r['complete']);self.assertTrue(r['passed'])
        self.assertEqual(r['model_calls'],0);self.assertEqual(r['probe_executions'],26);self.assertEqual(r['synth_executions'],4)
        self.assertEqual(sum(c['kind']=='fake_probe' for c in calls),26);self.assertEqual(sum(c['kind']=='fake_synth' for c in calls),4)
        for c in r['cases'].values():self.assertIn('argv',c['synthesis']['positive'])
    def test_frozen_tamper_rejected_before_first_fake_tool(self):
        rc,r,calls=self.run_fixture(damaged=True);self.assertEqual(rc,1);self.assertFalse(r['complete']);self.assertFalse(r['passed']);self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
