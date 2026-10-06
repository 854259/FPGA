"""Terminal evidence gate only; never starts or retries an original audit."""
ORIGINAL='/workspace/team/runs/fpga_owner/serial_timer_native_20261007_v2'
SPEC='141f5ecf638751d37f77c6c72aa61cf4cdef5cc3c2948657906a880c8eafa778'
def require_terminal(ticket,report,guard,matching_original_live=False,prior_attempt=False):
    assert not matching_original_live and not prior_attempt
    assert ticket['state']=='completed' and ticket['returncode']==0 and ticket['cwd']==ORIGINAL
    assert report['schema']=='serial_timer_binary_event_native_measurement_v1'
    assert report['complete'] and report['passed'] and report['error'] is None and report['spec_sha256']==SPEC
    assert (report['actual_model_requests'],report['actual_native_commands'],report['actual_observations'],report['guard_receipts'])==(0,36,13800,73)
    assert guard['complete'] and guard['passed'] and guard['stage_rc']==0
    assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    assert guard['own_slot_released'] and guard['model_unchanged'] and guard['protected_files_unchanged']
    return dict(terminal_eligible=True,audit_executed=False,native_qualified=False,model_calls=0,eda_calls=0)
