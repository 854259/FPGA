# Draft per-solve Linux supervision

`supervisor.py` is a direct-function component for the new natural integration
factor. It is frozen in the engineering TOOLS_SPEC only, without actual IO
authorization or production deployment. Importing
it starts no process, network request, or EDA command.

The guarded main stage captures `started = time.monotonic()` before reading the
public solve input or checking the full qualification gates, then calls
`run_supervised(argv, evidence_dir, ROOT, started_monotonic=started)`. An omitted
start defaults to the supervisor's own entry time. An explicit start must be a
finite numeric value, must not be a Boolean or future time, and must still have
remaining work time. Parent preparation therefore consumes the existing budget;
it never starts a new child or supervisor budget. The
single total budget is 300 seconds: the child must finish work before second
272, leaving 24 seconds for owned process cleanup and 4 for receipt sealing.
The same absolute start/work/cleanup/total deadlines travel in an inherited
one-shot pipe, rather than starting a fresh child budget. There is no retry.

Required frozen specification additions:

```python
spec['source_hashes']['supervisor.py'] = exact_supervisor_sha256
spec['source_hashes']['guard_wrapper.py'] = exact_own_guard_sha256
spec['source_hashes'][child_entry] = exact_own_child_source_sha256
spec['supervisor'] = {
    'child_entry': 'solve_child.py',  # relative own frozen Python source
    'python_executable': fixed_resolved_python_path,
    'python_sha256': exact_interpreter_sha256,
}
```

Every path must be physical, absolute where required, and contain no symlink or
junction. Resolve the interpreter path before freezing; `/usr/bin/python3` can
be a symlink. The actual wrapper command must contain the own frozen
`ROOT/guard_wrapper.py` and exactly one `--guard-out ROOT/guard`.

The inherited token binds actual stage, wrapper and child PID/starttime/process
group/session identity; the wrapper's actual command digest; RUN_SPEC,
resource and active status digests; the owned cooperative lock digest; the
durable authorization file and nonce; and the absolute deadlines. The child
must be the actual direct independently grouped child of that stage. A missing
or temporarily incomplete JSON publication is waited for at most five seconds
within the existing budget. A missing/None stage PID is waited for only in the
explicit pending shape `complete=False, passed=False, phase='resource_guard'`
with no error. A completed/failed status or different published PID is rejected
immediately. Scheduling state is excluded from identity so that a sleeping parent
and a running parent compare correctly.

Child integration:

```python
# Do this before any model, EDA, or runtime IO admission.
supervisor_grant = supervisor.child_admission(ROOT)
admission = supervisor.verify_child_admission(supervisor_grant, ROOT)
solve_started = admission['started_monotonic']
work_deadline = admission['work_deadline_monotonic']

# Existing runtime qualification/resource/source gates still run. If the
# current PID differs from guard.status.stage_pid, accept only this actual
# inherited grant, and require admission['stage']['pid'] == stage_pid.
# Never turn this into a caller-provided `admitted=True` flag.

# Every actual transport/native callback caps its remaining time against
# work_deadline - time.monotonic(). The worker must inherit solve_started;
# reading public inputs and creating clients must not restart the clock.
```

`verify_child_admission` only accepts the same in-process grant object returned
from `child_admission`, checks its canonical contents and then rechecks the
actual live identities/guard/lock. The grant always reports
`real_io_admitted=False`: runtime still needs complete quality, original
harness, generated native, physical dependency, resource and isolation gates.
The handshake is an ownership/provenance check among trusted own frozen
processes. It is not a security boundary against a hostile process with the
same operating-system credentials.

Cleanup requires a single-threaded main stage with no existing children and
Linux subreaper plus `pidfd_open`/`pidfd_send_signal` support. It captures child
descendants across all threads, including detached sessions and children
adopted when a parent exits. Each process is pinned to a PID file descriptor
after checking PID/starttime/group/session. Signals use that descriptor; this
module never uses `killpg` or numeric-PID signalling. The stage, actual wrapper
parent, and explicit shared model PID are protected. Any conflicting identity
or unverifiable ownership fails closed. TERM is followed by KILL and reaping
within the cleanup deadline. Failure must stop the enclosing stage for the
outer guard to inspect; do not begin another solve or release the shared slot.

The durable receipt preserves the launch attempt before Popen, confirmed
actual child identity, authorization digest, actual command, full child log
digest/bytes, return code, observed cleanup identities, signal/reap records and
elapsed/commit timing. Actual model and EDA counts are `None` in this receipt:
they must come from runtime's actual durable attempt/confirmation receipts.
A child return code of zero is not proof of solver quality or those counts.
Partial runtime evidence stays in the owned directory.

Client termination never proves server-side model cancellation. The receipt
always reports `server_job_cancellation_confirmed=False`; an HTTP timeout may
leave the shared model processing, and the outer guard must keep its existing
idle/slot-release gate. This component never manages the model or instance.

Local verification on Windows Python 3.12.14: **27 methods, 25 passed, 2 Linux
methods skipped, zero failures/errors**. Two actual own Python dummy child
controls passed: normal exit and hanging child followed by cleanup via the own
Popen process handle. Pure controls reject forged Booleans, changed identities,
changed stage/lock/guard namespaces, altered deadlines, malformed inherited
pipes and protected-process signalling; parent prechecks retain the original
absolute budget, and pending PID publication waits without accepting
contradictory status. These are engineering controls,
**0 actual model, EDA, cloud or FIFO calls**.

The explicit opt-in command `python test_supervisor.py --linux-owned-controls`
adds a normal Linux full-supervisor/pipe control under a fabricated own guard,
and actual own hanging-parent/detached-grandchild cleanup using PID descriptors.
Those tests **passed on Linux Python 3.12.3 in the isolated engineering namespace**,
as part of all 177 engineering methods with zero skips/errors. The four actual
own Python controls and 76 fake HTTP subchecks are recorded in `LINUX_CHECKS.json`.
They made zero actual model/EDA calls. Their
guard/resource documents are explicitly synthetic; they never admit real model
or EDA IO. The dummy fixture's wrapper is different from the production guard.
The full actual 300-second timeout, real AMD Linux
integration, sandbox, ROCm, production guard ancestry and solver qualification
remain separately unverified.

The supervisor checks the absolute deadline and withdraws `passed` when
observed finalization exceeds it. A userspace deadline does not prove a hard
real-time bound for blocked kernel/filesystem IO in the supervisor itself;
the external stage guard remains necessary. The 28-second reserve changes the
available child work time, so this factor cannot inherit earlier C/P effect
claims without a new same-budget evaluation.
