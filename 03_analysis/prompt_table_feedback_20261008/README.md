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

FIFO127 is accepted and queued behind the peer's separate FSM prompt comparison.
It will run seven simulated worker paths and three native XOR-output controls
(correct, incorrect, unknown). Limits: zero real model requests, nine simulated
HTTP requests, at most nine EDA commands; 60s/tool, 400s child, 430s outer including
30s cleanup reserve, 445s guard, nine-minute slot. These are safety caps, not an
ETA. Frozen original source and submitted ticket must not be overwritten or
resubmitted. Native and flow results are pending; do not claim scoring admission.

After those controls pass, freeze the nine applicable model-generated pairs and
original-baseline comparison using the existing judge and queue. Correct the
copied activity namespace when preparing that new run; do not modify frozen127.
Full official ranking still requires the official five-sample protocol,
same-run original baseline, measured wall time and engineering assessment.
Historical per-task preservation and relative model-call counts are diagnostics,
not selection vetoes. The only ranking criterion is the competition's rules.

Exact source, input and queue receipt hashes are in `PUBLIC_RESULT.json`.
Private per-task inputs and process evidence remain in the two AMD roots it names.
