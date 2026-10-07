# Candidate-side static elaboration — preparation only

Status: source patch prepared on 2026-10-07. Not deployed, not a scoring run, not native-qualified.

The completed A114 development screen produced C4/P4 L3 out of15, weighted .40/.40, with19/19 requests. It is rejected under its original screen. A retained failure passed candidate xvlog but failed judge elaboration due to incompatible procedural drivers. That diagnosis identifies a general gap; it does not authorize reading judge material in production or establish the new mechanism's accuracy.

## Exact patch inputs

Apply only to a fresh copy of the two original A114 source files after SHA-256 verification:

| File | Required SHA-256 |
| --- | --- |
| package/agent/map_runtime.py | 2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba |
| baseline_worker.py | b1f396a3a54b065ef2e0b19fc3aa54973aea41a6b82577a51b4cfc2e32876852 |

The patch uses zero-context hunks: `git apply --unidiff-zero static_elaboration.patch`.
The two hashes are mandatory preconditions, not a suggestion to patch the original run in place.
Do not use the old A114 worker.py wrapper: it appends the rejected system factor.
The next isolated C/P harness must call the patched baseline_worker directly and freeze all required unchanged support files.
The patch removes the A system validation/import, keeps the original C/P generation messages, enables STATIC_ELABORATION only for P, and requires a frozen activity_root owned by the executing task.
A new RUN_SPEC and source/dependency inventory are required; the historical A114 spec is not a valid launch spec for the changed source.

## Mechanism and existing behavior

Both xvlog success exits enter candidate-only xelab on TopModule from the current compile directory.
Only candidate.sv is compiled; no testbench, private reference, judge logs or new simulation is supplied.
A native nonzero elaboration exit supplies that call's diagnostics to the existing repair loop.
The maximum model calls and repairs stay at the newly frozen common2/1 limits; this patch does not increase either limit.
The declaration repair path retains the corrected candidate as the next repair input; if its elaboration passes, its previous immediate-return behavior is retained.
The ordinary success path continues to the original map feedback.
C retains both original success exits and never runs this new elaboration step.

The existing owned_command supervises xelab with its original60-second single-command cap; the outer worker/judge/supervisor limits must stay at300/300/360 in a later paired run.
Separate elaboration receipts record input before/after, log hash, command, actual result and owned process cleanup.
A timeout, launch error, surviving owned group or missing tool is an execution failure, not a repaired design.
The current patch is a reviewable proposal: support for candidate-only elaboration and its incremental runtime cost remain unmeasured.

## Next necessary validation

Before real model use, freeze a fresh AMD-only, zero-model-call control run with these task-independent structures:

- Legal single sequential driver and legal separate combinational/registered signals.
- A variable assigned by incompatible combinational and sequential processes.
- ANSI declaration correction followed by a valid design.
- ANSI declaration correction that still leaves an elaboration error.

Also exercise the worker with controlled transport/tool outcomes to check: C bypass, P diagnostics consuming only the existing repair, corrected-source propagation, no retry after missing tool/supervision failure, and no extra functional feedback on the successful declaration-fix exit.
Synthetic outcomes are engineering controls and do not count as independent RTL benchmark tasks.
Record all attempts and negative results, and do not change controls after seeing their results to select a passing version.
Freeze exact command count, total time, resource admission and FIFO ownership before execution; no native/model/FIFO work is authorized merely by this README.

## Coordination and limits

Issue7 response6040017934 assigns this preparation to the reviewer; nzh152-lang continues the separate, previously admitted CP8 same-factor156 preparation.
Reuse unchanged evidence and do not combine A, lexical extraction changes, or CP8 behavior with this mechanism.
A114's original full terminal/archive claims have a bound owner conclusion; the reviewer has not independently re-audited its complete archive.
The full objective remains more than118/156 L3 plus the three-arm156, auditedRTLLM, required five samples and resource/interface/recovery acceptance.
