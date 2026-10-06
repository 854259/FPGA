"""FAKE terminal metadata controls; no audit/EDA/model/FIFO execution."""
import copy,unittest
import terminal_gate as g
def fixture():
    return (dict(state='completed',returncode=0,cwd=g.ORIGINAL),dict(schema='serial_timer_binary_event_native_measurement_v1',complete=True,passed=True,error=None,spec_sha256=g.SPEC,actual_model_requests=0,actual_native_commands=36,actual_observations=13800,guard_receipts=73),dict(complete=True,passed=True,stage_rc=0,owned_cleanup=dict(verified=True,remaining=[]),own_slot_released=True,model_unchanged=True,protected_files_unchanged=True))
class TerminalGateControls(unittest.TestCase):
    def test_complete_metadata_admits_only_audit_eligibility_not_qualification(self):
        r=g.require_terminal(*fixture());self.assertTrue(r['terminal_eligible']);self.assertFalse(r['audit_executed']);self.assertFalse(r['native_qualified'])
    def test_queued_running_and_failed_original_cannot_admit(self):
        for state in ('queued','running','failed','failed_released_after_inspection'):
            t,r,b=fixture();t['state']=state
            with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
        t,r,b=fixture();t['returncode']=1
        with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
    def test_missing_or_failed_report_or_wrong_original_spec_refuses(self):
        for key,value in [('complete',False),('passed',False),('error','FAKE failure'),('spec_sha256','0'*64),('schema','unrecognized')]:
            t,r,b=fixture();r[key]=value
            with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
        t,r,b=fixture();t['cwd']='/FAKE/other'
        with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
    def test_native_counts_cannot_substitute_old_onehot_qualification(self):
        for key,value in [('actual_model_requests',1),('actual_native_commands',24),('actual_observations',14144),('guard_receipts',49)]:
            t,r,b=fixture();r[key]=value
            with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
    def test_cleanup_release_or_source_model_drift_refuses(self):
        for key in ('complete','passed','own_slot_released','model_unchanged','protected_files_unchanged'):
            t,r,b=fixture();b[key]=False
            with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
        for value in (dict(verified=False,remaining=[]),dict(verified=True,remaining=[99999])):
            t,r,b=fixture();b['owned_cleanup']=value
            with self.assertRaises(AssertionError):g.require_terminal(t,r,b)
    def test_live_original_or_unknown_prior_audit_never_restarts(self):
        for flags in (dict(matching_original_live=True),dict(prior_attempt=True)):
            with self.assertRaises(AssertionError):g.require_terminal(*fixture(),**flags)
if __name__=='__main__':unittest.main(verbosity=2)
