"""Pure synthetic binding/replay boundaries, never a real archive or quality claim."""
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import types
import unittest
import audit
import elaboration_feedback
import replay


def digest(raw):return hashlib.sha256(raw).hexdigest()
def save(path,value):path.write_text(json.dumps(value),encoding='utf-8')


class ElaborationBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'elaboration_check_0';self.folder.mkdir()
        self.code='module TopModule; endmodule\n'
        self.cloud=PurePosixPath('/synthetic-owned/worker');self.compile=self.cloud/'work/compile-0'
        self.tool=dict(path='/synthetic-tools/xelab',sha256='a'*64)
        self.runner=types.SimpleNamespace(ENVIRONMENT_ERROR=re.compile('SYNTHETIC_ENVIRONMENT_ERROR'))
        self.write_receipt()

    def write_receipt(self,rc=1,text='ERROR: [VRFC 10-3818] synthetic driver conflict\n'):
        log=self.folder/'owned_elaboration.log';log.write_text(text,encoding='utf-8')
        raw=self.code.encode();log_raw=log.read_bytes();code_sha=digest(raw);log_sha=digest(log_raw)
        for name in ['source_before.sv','source_after.sv']:(self.folder/name).write_bytes(raw)
        snapshot='own_candidate_elab_0_'+'1'*32
        argv=[self.tool['path'],'TopModule','-s',snapshot,'--nolog','-timescale','1ns/1ps']
        cloud_log=str(self.cloud/self.folder.name/'owned_elaboration.log')
        feedback=elaboration_feedback.diagnostic_text(text) if rc else ''
        self.receipt=dict(schema='candidate_elaboration_feedback_v1',complete=True,measurement_valid=True,
            error=None,native_invocation_attempted=True,model_calls=0,hidden_testbench_used=False,
            reference_used=False,candidate_only=True,official_quality_judgement=False,attempt=0,
            actualcheck_path=str(self.cloud/self.folder.name),cwd=str(self.compile),
            source_path=str(self.compile/'candidate.sv'),top='TopModule',snapshot=snapshot,
            argv=argv,native_argv_after=list(argv),executable_path=self.tool['path'],executable_unchanged=True,
            executable_before_sha256=self.tool['sha256'],executable_after_sha256=self.tool['sha256'],
            code_sha256=code_sha,source_before_sha256=code_sha,source_after_sha256=code_sha,
            source_unchanged=True,timeout_s=60,elapsed_s=1.,returncode=rc,timeout=False,
            launch_error=None,remaining_live_group=[],log_path=cloud_log,log_sha256=log_sha,
            actual_log_sha256=log_sha,log_bytes=len(log_raw),actual_log_bytes=len(log_raw),
            outcome='fail' if rc else 'pass',feedback=feedback,
            native_command=dict(timeout=False,launch_error=None,remaining_live_group=[],returncode=rc,
                                log=cloud_log,log_sha256=log_sha,log_bytes=len(log_raw),elapsed_s=.5))
        self.commit()

    def commit(self):save(self.folder/'RESULTS.json',self.receipt)
    def verify(self):
        return audit.verify_elaboration(self.folder,self.code,0,self.cloud,self.compile,self.tool,
                                        elaboration_feedback,self.runner)

    def test_normal_nonzero_facts_and_zero_pass_binding(self):
        result=self.verify();self.assertEqual(result['outcome'],'fail');self.assertEqual(result['attempt'],0)
        self.write_receipt(0,'INFO: synthetic pass\n');self.assertEqual(self.verify()['feedback'],'')

    def test_unknown_supervision_is_never_model_feedback(self):
        for key,value in [('timeout',True),('launch_error','synthetic error'),('remaining_live_group',[123]),('returncode',-9)]:
            with self.subTest(key=key):
                self.write_receipt();self.receipt['native_command'][key]=value;self.commit()
                with self.assertRaises(AssertionError):self.verify()

    def test_tool_source_and_complete_log_bound(self):
        for key,value in [('executable_after_sha256','b'*64),('code_sha256','b'*64),
                          ('log_sha256','b'*64),('actual_log_bytes',0),('source_unchanged',False)]:
            with self.subTest(key=key):
                self.write_receipt();self.receipt[key]=value;self.commit()
                with self.assertRaises(AssertionError):self.verify()
        self.write_receipt();(self.folder/'source_after.sv').write_text('modified',encoding='utf-8')
        with self.assertRaises(AssertionError):self.verify()

    def test_cwd_argv_and_candidate_only_top_are_fixed(self):
        for key,value in [('cwd','/foreign'),('top','tb'),('argv',['/synthetic-tools/xelab','tb']),
                          ('native_argv_after',[]),('source_path','/foreign/ref.sv')]:
            with self.subTest(key=key):
                self.write_receipt();self.receipt[key]=value;self.commit()
                with self.assertRaises(AssertionError):self.verify()

    def test_reference_or_pending_measurement_rejected(self):
        for key,value in [('reference_used',True),('hidden_testbench_used',True),
                          ('complete',False),('measurement_valid',False),('error','synthetic')]:
            with self.subTest(key=key):
                self.write_receipt();self.receipt[key]=value;self.commit()
                with self.assertRaises(AssertionError):self.verify()

    def test_nonzero_without_real_error_and_tampered_feedback_rejected(self):
        self.write_receipt(1,'INFO: synthetic no diagnostic\n')
        with self.assertRaises(AssertionError):self.verify()
        self.write_receipt();self.receipt['feedback']='invented expectation';self.commit()
        with self.assertRaises(AssertionError):self.verify()


class ExactReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name);self.prompt='Synthetic prompt only'
        self.codes=['module TopModule; wire a; endmodule\n','module TopModule; wire b; endmodule\n']
        self.fact='ERROR: [VRFC 10-3818] synthetic driver conflict'
        self.contract={'status':'abstain'}
        self.baseline=types.SimpleNamespace(extract=lambda text,kind:text)
        self.runtime=types.SimpleNamespace(undefined_submodules=lambda code:[],repair_ansi_declarations=lambda code,diag:None)
        self.make_replay()

    def make_replay(self):
        journal=[];compiles=[]
        for i,code in enumerate(self.codes):
            request=self.work/'requests'/str(i);request.mkdir(parents=True)
            user=self.prompt if i==0 else self.prompt+'\nPrevious candidate:\n'+self.codes[0]+'\nCandidate diagnostics:\n'+self.fact
            save(request/'request.json',dict(messages=[dict(role='system',content='synthetic'),dict(role='user',content=user)]))
            save(request/'response.json',dict(id='synthetic-'+str(i),choices=[dict(finish_reason='stop',message=dict(content=code))]))
            journal.append(dict(index=i,response_received=True,finish_reason='stop',response_id='synthetic-'+str(i)))
            folder=self.work/'compile_receipts'/str(i);folder.mkdir(parents=True)
            for n in ['source_before.sv','source_after.sv']:(folder/n).write_text(code,encoding='utf-8',newline='\n')
            log=folder/'owned_compile.log';log.write_text('INFO: synthetic compile pass\n',encoding='utf-8')
            compiles.append(dict(argv=['/synthetic-tools/xvlog','--sv','/synthetic-owned/work/compile-'+str(i)+'/candidate.sv'],
                returncode=0,timeout=False,launch_error=None,remaining_live_group=[],log_sha256=audit.sha(log),
                log_bytes=log.stat().st_size,source_sha256=digest(code.encode()),source_before_sha256=digest(code.encode()),
                source_after_sha256=digest(code.encode())))
            (self.work/('elaboration_check_'+str(i))).mkdir()
        save(self.work/'requests.json',journal);save(self.work/'compile_journal.json',compiles)
        (self.work/'solution.v').write_text(self.codes[-1],encoding='utf-8',newline='\n')
        trace=dict(tool='map_feedback',round=0,excerpt=self.fact,repair_available=True)
        (self.work/'trace.jsonl').write_text(json.dumps(trace)+'\n',encoding='utf-8')

    def elaborate(self,folder,code,attempt):
        self.assertEqual(code,self.codes[attempt])
        return dict(attempt=attempt,outcome='fail' if attempt==0 else 'pass',returncode=1 if attempt==0 else 0,
                    complete=True,measurement_valid=True,feedback=self.fact if attempt==0 else '')

    def run_replay(self,arm='P'):
        def no_probe(*args):self.fail('Unsupported contract must not execute a semantic probe')
        return replay.replay(self.work,self.prompt,arm,self.contract,self.baseline,self.runtime,None,None,
                             no_probe,audit.sha,audit.read,False,self.elaborate)

    def test_exact_native_feedback_in_unique_repair_and_pass_chain(self):
        result=self.run_replay()
        self.assertTrue(result['elaboration_repair_feedback_bound'])
        self.assertEqual([r['outcome'] for r in result['elaboration_checks']],['fail','pass'])

    def test_invented_repair_payload_rejected(self):
        path=self.work/'requests/1/request.json';body=audit.read(path)
        body['messages'][1]['content']+=' fabricated extra hint';save(path,body)
        with self.assertRaises(AssertionError):self.run_replay()

    def test_control_arm_cannot_claim_candidate_elaboration(self):
        with self.assertRaises(AssertionError):self.run_replay('C')

    def test_missing_or_orphan_candidate_check_rejected(self):
        (self.work/'elaboration_check_0').rmdir()
        with self.assertRaises(AssertionError):self.run_replay()
        (self.work/'elaboration_check_0').mkdir();(self.work/'elaboration_check_9').mkdir()
        with self.assertRaises(AssertionError):self.run_replay()

    def test_successful_ansi_patch_preserves_early_return_without_xelab(self):
        # Independent shape fixture: successful declaration repair never calls callback.
        for n in ['elaboration_check_0','elaboration_check_1']:(self.work/n).rmdir()
        journal=audit.read(self.work/'requests.json')[:1];save(self.work/'requests.json',journal)
        compiles=audit.read(self.work/'compile_journal.json');compiles[0]['returncode']=1
        compiles[1]['argv']=compiles[0]['argv'];save(self.work/'compile_journal.json',compiles)
        self.runtime.repair_ansi_declarations=lambda code,diag:self.codes[1]
        (self.work/'trace.jsonl').write_text('',encoding='utf-8')
        result=self.run_replay();self.assertEqual(result['declaration_patches'],1)
        self.assertEqual(result['elaboration_checks'],[])
        self.assertFalse(result['elaboration_repair_feedback_bound'])


if __name__=='__main__':unittest.main()
