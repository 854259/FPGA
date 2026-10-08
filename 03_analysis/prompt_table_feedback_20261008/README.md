# Model-generated RTL with prompt-table feedback

The original model/phase worker has no complete-table functional checker. This
factor checks its actual model output against a fully consumed prompt table and
feeds a measured counterexample into the existing single repair. It never emits
the DUT. C preserves the original worker; P adds this check and otherwise uses
the original feedback. Initial requests, extraction and request limits remain
unchanged. No table/vector RTL synthesis module is imported.

The parser is the unchanged `contract.py` from frozen123. Only complete Karnaugh
maps and explicitly combinational complete scalar waveforms are accepted, with
one scalar output and at most four input bits. The testbench checks cared rows
in forward and reverse order. Declared don't-cares are skipped; actual X/Z
outputs mismatch. These finite observations are not a proof about all internal
states, parameters or delays. Tool/protocol/input-change failures stop rather
than manufacture semantic feedback. The inherited ANSI-fix early return remains
unchanged and can bypass functional checks.

AMD prompt/interface intake finished once: 9 of the original156 development
inputs are applicable. Selection used no grading inputs or outcomes. This is
applicability, not nine improvements or independent validation.

FIFO127 completed successfully: seven simulated worker paths and three native XOR-output controls
(correct, incorrect, unknown). Limits: zero real model requests, nine simulated
HTTP requests, at most nine EDA commands; 60s/tool, 400s child, 430s outer including
30s cleanup reserve, 445s guard, nine-minute slot. These are safety caps, not an
ETA. Frozen original source and submitted ticket must not be overwritten or
resubmitted. All seven flow paths and three native controls met their expectations.
The nine native process receipts and streams were bound and the recorded guard
tree retired. External child-through-final-read time was 18.502182s; this excludes
preparation, the observer's own exit and transfer. No new model score was measured.

FIFO129 was accepted at 16:55:30 +08:00. It compares all nine applicable development
tasks with five independent samples per arm: A maps to the unchanged model C,
P adds table feedback, and B runs the original official baseline. The same existing
queue and external judge handle 135 outputs, at most 225 model requests, no retry.
The copied input/activity routes use the new owned namespace. A/P preserve max2
and one repair; B uses one request; all preserve 8192 tokens. The 43200s stage,
43600s guard and 740-minute slot are safety caps, not ETAs. Unconfirmed calls,
source/provenance/tool/resource failures stop and retain their evidence.

The added source binding checks the initial wire against the actual prompt and
skills, repairs against the previous response and retained diagnostic, and final
RTL against the last extracted model reply. Only the inherited compiler-bound
ANSI declaration repair may differ. The new binding/routing checks reuse retained
synthetic outputs; fabricated RTL and replaced prompts are rejected. They perform
no model request, EDA command or rerun of the old controls. FIFO129 is submitted,
not a completed accuracy result or a full156 evaluation.
Full official ranking still requires the official five-sample protocol,
same-run original baseline, measured wall time and engineering assessment.
Historical per-task preservation and relative model-call counts are diagnostics,
not selection vetoes. The only ranking criterion is the competition's rules.

Exact source, input and queue receipt hashes are in `PUBLIC_RESULT.json`.
Private per-task inputs and process evidence remain in the AMD roots it names.

Completed queues can be read with comparison_result.py using their frozen plan hash.
It verifies retained row seals and source bindings and calls the unchanged official
score.py summary. Fourteen synthetic aggregation checks passed on AMD with zero
model/EDA calls. Actual129 audit remains pending completion. The reader never
restarts a queue or rejudges a solution.
