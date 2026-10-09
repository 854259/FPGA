"""Simulated oracle receipts test adapter trust boundaries, not native correctness."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import onehot_feedback as f
from native_material_fixture import fixture

CODE = 'module TopModule; /* synthetic adapter byte-identity marker, not EDA-qualified */ endmodule\n'


class SimulatedOracle:
    def __init__(self, root, fault=None, bad=1):
        self.root,self.fault,self.bad,self.calls=Path(root),fault,bad,0

    @staticmethod
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @staticmethod
    def save(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

    def oracle(self, task, source, out):
        self.calls+=1;out.mkdir()
        if self.fault=='raise':raise RuntimeError('simulated native launch failure')
        tb=self.root/task['tb']
        result=dict(schema_version=1,task=task['task'],outdir=str(out),
            status='fail' if self.bad else 'pass',failure_kind='semantic_mismatch' if self.bad else None,
            checks=task['checks'],mismatches=self.bad,solution_sha256=self.sha(source),tb_sha256=self.sha(tb),
            inputs_unchanged=True,stages=[])
        log_task='Other' if self.fault=='summary_task' else task['task']
        observed='00000' if self.fault=='not_counterexample' else '00010'
        body=(f'ONEHOT_FIRST input=0 state=000 observed={observed}\n' if self.bad else '')
        body+=f'R2_PROBE_RESULT task={log_task} checks={task["checks"]} mismatches={self.bad}\n'
        for name in ('xvlog','xelab','xsim'):
            log=out/(name+'.log');log.write_text(body if name=='xsim' else 'simulated tool receipt\n')
            result['stages'].append(dict(name=name,returncode=0,timeout=False,launch_error=None,
                remaining_live_group=[],log=str(log),log_sha256=self.sha(log),log_bytes=log.stat().st_size))
        if self.fault=='source':source.write_text(source.read_text()+'// changed\n')
        if self.fault=='tb':tb.write_text(tb.read_text()+'// changed\n')
        if self.fault=='inputs':result['inputs_unchanged']=False
        if self.fault=='source_receipt':result['solution_sha256']='0'*64
        if self.fault=='tool':result.update(status='fail',failure_kind='tool_failure')
        if self.fault=='count_bool':result['mismatches']=True
        if self.fault=='log_hash':result['stages'][-1]['log_sha256']='0'*64
        if self.fault=='log_path':result['stages'][-1]['log']=str(out/'Other.log')
        if self.fault=='stages':result['stages'].reverse()
        if self.fault=='timeout':result['stages'][-1]['timeout']=True
        if self.fault=='remaining':result['stages'][-1]['remaining_live_group']=[123456]
        original=copy.deepcopy(result)
        self.save(out/'result.json',original)
        result.update(inherited_result_path=str(out/'result.json'),inherited_result_sha256=self.sha(out/'result.json'),
            inherited_runner_path='simulated-only',inherited_runner_sha256='simulated-only',
            oracle_adapter_path='simulated-only',oracle_adapter_sha256='simulated-only')
        self.save(out/'adapter_receipt.json',result)
        if self.fault=='stored_result':
            original['mismatches']=2;self.save(out/'result.json',original)
        if self.fault=='stored_adapter':
            alternate=copy.deepcopy(result);alternate['mismatches']=2;self.save(out/'adapter_receipt.json',alternate)
        return result


class AdapterControls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.out=self.root/'out';self.out.mkdir()
        p,i,_=fixture(n=3,module='TopModule')
        self.prompt=p+'\n\nInterface:\n'+i

    def run_check(self,fault=None,bad=1,attempt=0,code=CODE):
        oracle=SimulatedOracle(self.root,fault,bad)
        return f.check(self.prompt,code,self.out,attempt,oracle,'Synthetic',self.root),oracle

    def rejected(self,fault,error=RuntimeError):
        with self.assertRaises(error):self.run_check(fault)
        self.assertFalse((self.out/'onehot_check_0/feedback.txt').exists())

    def test_stored_native_receipt_must_match_returned(self):self.rejected('stored_result')
    def test_stored_adapter_receipt_must_match_returned(self):self.rejected('stored_adapter')

    def test_positive_feedback_preserves_candidate_and_real_field_bindings(self):
        text,oracle=self.run_check();folder=self.out/'onehot_check_0'
        self.assertEqual(oracle.calls,1);self.assertEqual((folder/'input.sv').read_bytes(),CODE.encode())
        self.assertIn("state=3'b000",text)
        self.assertEqual((folder/'feedback.txt').read_text(),text)
        binding=json.loads((folder/'measurement_binding.json').read_text())
        self.assertEqual(binding['result_sha256'],oracle.sha(folder/'probe/result.json'))

    def test_measured_pass_is_empty_feedback(self):
        text,oracle=self.run_check(bad=0)
        self.assertEqual(text,'');self.assertEqual(oracle.calls,1)
        self.assertFalse((self.out/'onehot_check_0/feedback.txt').exists())

    def test_mutated_candidate_or_tb_is_not_feedback(self):
        for fault in ('source','tb'):
            with self.subTest(fault=fault):
                with tempfile.TemporaryDirectory() as td:
                    root=Path(td);out=root/'out';out.mkdir();oracle=SimulatedOracle(root,fault)
                    with self.assertRaises(RuntimeError):f.check(self.prompt,CODE,out,0,oracle,'Synthetic',root)

    def test_input_receipt_rejected(self):self.rejected('inputs')
    def test_source_digest_rejected(self):self.rejected('source_receipt')
    def test_native_tool_failure_not_semantic_feedback(self):self.rejected('tool')
    def test_boolean_mismatch_count_rejected(self):self.rejected('count_bool')
    def test_native_log_hash_and_path_rejected(self):
        self.rejected('log_hash')
        self.out=self.root/'other';self.out.mkdir();self.rejected('log_path')
    def test_out_of_order_stages_rejected(self):self.rejected('stages')
    def test_timeout_or_live_process_not_success(self):
        self.rejected('timeout')
        self.out=self.root/'other';self.out.mkdir();self.rejected('remaining')
    def test_wrong_summary_identity_rejected(self):self.rejected('summary_task',ValueError)
    def test_expected_output_is_not_a_counterexample(self):self.rejected('not_counterexample',ValueError)
    def test_launch_exception_propagates_without_feedback(self):self.rejected('raise')

    def test_retained_attempt_folder_is_never_overwritten(self):
        self.run_check();source=self.out/'onehot_check_0/input.sv';before=source.read_bytes()
        with self.assertRaises(FileExistsError):self.run_check()
        self.assertEqual(source.read_bytes(),before)

    def test_unsupported_prompt_candidate_or_attempt_never_calls_oracle(self):
        oracle=SimulatedOracle(self.root)
        self.assertIsNone(f.check('unknown prompt',CODE,self.out,0,oracle,'Synthetic',self.root))
        self.assertIsNone(f.check(self.prompt,CODE+'$display("x");',self.out,0,oracle,'Synthetic',self.root))
        with self.assertRaises(ValueError):f.check(self.prompt,CODE,self.out,2,oracle,'Synthetic',self.root)
        self.assertEqual(oracle.calls,0)


if __name__=='__main__':unittest.main()
