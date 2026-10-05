# Native calibration v2 — static preparation only

This new source draft has not been imported, tested, frozen, queued or executed
locally. Project execution, imports, mocks and tests are restricted to AMD. The
root agent owns AMD preparation, review, source freeze, FIFO guard and native
execution. No RUN_SPEC is created by this draft. No model request or score gain
is claimed. The future eight-task/sixteen-arm model pilot remains a separate,
unfrozen proposal conditional on this native calibration qualifying.

## Fixed matrix after independent reset review

The abandoned, unfrozen 35-control draft used left-only nonwalking reset
contexts and then added right contexts. Root explicitly kept the three
activity-ignore mutants and added three direction-retention mutants rather
than deleting meaningful controls to preserve the earlier count.

| Family / type | Variants | Checks per simulation | Planned observations |
| --- | ---: | ---: | ---: |
| Walking/falling semantic | 10 | 55 | 550 |
| Walking/falling/digging semantic | 14 | 115 | 1610 |
| Walking/falling transport refusal | 5 | 55 | 275 |
| Walking/falling/digging transport refusal | 5 | 115 | 575 |
| EDA failure | 2 | none | 0 |
| Owned supervisor probe | 2 | none | 0 |
| Total | 38 | — | 3010 |

The 24 semantic variants comprise two production positives, two independent
fixture positives, fourteen original negatives, three activity-ignore reset
negatives and three direction-retention reset negatives. There are 34 complete
simulation pipelines. The compile-error control adds one xvlog; the missing
module control adds xvlog and xelab. Thus planned native calls are xvlog36,
xelab35 and xsim34, total105. Two supervisor commands are counted separately:
107 owned commands and216 guard receipts (initial, before/after each, final).
These are planned counts, never substituted for actual calls or trace counts.

Left/right FALL reset assertions begin at walking observations39/52 and digging
69/95. Left/right DIG reset assertions begin at digging79/112. Recovery steps
bring each activity-ignore mutant back to a shared context; a WALK reset before
the right DIG check also aligns direction after the preceding FALL check.
Direction-retention faults require actual mismatches at52,95,112 respectively.
No assertion claims exhaustive product-state or arbitrary narrative coverage.

## Input and evidence boundaries

`--case-root` must be inside the future packet. It contains the original44
prepared files plus PREPARATION_BINDING.json, all byte/hash checked, and the
three pinned production sources. The old native_fixtures.py is replayed from
pinned bytes only on AMD. The new recipe adds literal stimulus/expectation
steps to its independent clause trajectories; it does not derive expected
outputs from production transitions and never reads judge, reference RTL or
official testbench material. Original44 source bytes are not modified.

`prepare.py` writes new prepared DUT/TB/expected files and draft plan/receipt,
then stops. Root must review AMD pure results and add CASE_PLAN.json, reviewed
environment/protected captures, all old45 inputs, new prepared assets and all
executed sources to a fresh frozen RUN_SPEC. The latest root read reported16
protected groups/742 assets, including FIFO83's89 sources. That is a capture
request for root, not a locally verified cloud capture. The implementation
binds exact captured groups/assets to the new spec and never substitutes a
hardcoded group count. Synthetic pure fixtures use eight explicitly FAKE
groups solely to exercise metadata gates.

Every actual tool call is recorded as an immutable attempt before launch,
followed by a physical completion preserving the unaltered pinned owned_command
result, merged stdout/stderr bytes and SHA, command SHA, DUT/TB before/after
SHA, and before/after guard references. Completion evidence is saved before a
probe validation error can reject the row. Stage monotonic/realtime admission
and completion clocks bind elapsed time; the audit also checks the sum of real
owned command times, individual physical intervals and first/last span.

Positive admission requires complete independently bound TRACE/DONE, one exact
PASS count, no mismatch, generic FAIL/ERROR or FATAL marker, compile/elab/xsim
rc0, no launch/timeout/live-group failure and unchanged DUT/TB bytes. Semantic
negative success requires complete normal rc0 simulation, actual expected !=
actual counterexamples at predeclared indices, immediate per-TRACE FAIL lines,
exact DONE mismatch counts and no PASS/FATAL. Compiler errors, missing modules,
timeouts, partial traces or signals never count as semantic-negative success.

The transport matrix deliberately measures refusal of PASS-then-FATAL,
finish-without-PASS, wrong PASS count, duplicate PASS and post-xsim scratch DUT
mutation for each family. The unique fatal marker is printed before $fatal,
because real xsim rc0 alone does not imply normal completion. Only owned scratch
DUT bytes are mutated; canonical/frozen inputs stay unchanged. EDA controls must
show the actual intended syntax/missing-module diagnostics, not generic errors
or environment faults. Exact tool diagnostic patterns still require real AMD
Vivado calibration; the draft does not assert that guessed diagnostic wording
has already been observed.

The timeout probe spawns one pinned-Python descendant in the owned session,
saves both PID/start/PGID identities and prints them physically. Qualification
requires SIGKILL/rc-9, no remaining group and both original processes absent;
PID reuse claims must contain well-formed changed starttimes. The missing
launcher probe requires real Errno2 with an empty physical log. Both remain
separate from native commands and semantic results.

`audit.py` replays the frozen recipe and all fixed38 rows from raw attempts,
completions, logs, physical source bytes, clocks and216 guards. It rejects
unknown/repeated/unconfirmed receipts and compares reconstructed decisions to
stored rows, progress and summary. `evidence_complete` and `native_qualified`
are distinct. Any missing control or refused evidence prevents qualification.
The legacy native71 failure is preserved as a policy reference to its original
spec SHA, explicitly `policy_reference_only_not_reaudit`; this new audit does
not pretend to have re-audited native71's complete archive.

## AMD handoff commands

Use Python3.12 with `-B`. Paths below are placeholders for root's new isolated
Linux packet; no Windows path or old working-tree path is guessed in code.

```text
python3.12 -B <source-root>/test_calibration.py --case-root <old45-case-root> --dependency-root <pinned-dependencies>
python3.12 -B <source-root>/prepare.py --root <new-packet> --case-root <new-packet>/cases
```

The33 pure methods include a complete38-row/107-command/216-guard/3010-trace
FAKE archive reconstruction and negative controls for first freeze admission,
altered raw receipts/logs, unknown attempts, malformed cleanup proof, terminal
self flags and elapsed tampering. FAKE outputs do not simulate RTL or establish
native capability. These methods are written but have not been run for this
draft; root's earlier14 AMD pure checks concern the unchanged production
preparation, not this new stage.

Only after root completes pure/source review, Linux preparation, independent
review and freeze may the guarded FIFO stage run:

```text
python3.12 -B <new-packet>/stage.py --root <new-packet> --case-root <new-packet>/cases --dependency-root <pinned-dependencies> --resource-check <new-packet>/guard/resource_check.json --kit <AMD-kit>
python3.12 -B <new-packet>/audit.py --root <new-packet-or-archive> --case-root <new-packet-or-archive>/cases --dependency-root <pinned-dependencies> --report <new-exclusive-audit-report>
```

Private stage cap is at most3600s; native command cap at most300s; supervisor
probe cap is positive and below1s. Root proposes guard3800s/slot70minutes.
There is no retry, resampling, frozen-source edit or model request in this stage.
