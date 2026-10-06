# Peer vector results and waveform resource failure

Updated 2026-10-06 20:11+08. This is a bounded read-only review of original AMD evidence, not another model experiment, the owner's full generation-provenance audit or an all-inclusive batch.

## Vector ticket98: result binding verified; not adopted

Frozen spec be08491a5eed64483ac8c6b4871731e9b3faa557a8b18aa7c57013cdf7f6d395; original summary c0f92c62b882a4d71fc57ef45036690a5af8268559034240c2f4fdcebf8f41a5. All116 frozen sources match. All312 original rows cover156 C/P development pairs; each matches its saved row, solution/verdict hashes, request journal and successful worker/judge command receipts. All332 counted requests have responses; no deadline or paired level regression was recorded.

| Measure | C | P |
|---|---:|---:|
| L3 fully correct |112|115|
| Weighted mean |0.767948718|0.783333333|
| Model requests |167|165|
| Model-route outputs |156|153|
| Mechanical vector outputs |0|3|
| Solver elapsed sum, seconds |3158.762|3232.246|

P's three mechanical outputs contain two L1-to-L3 improvements and one already-L3 task. The third paired improvement comes from a model route with two requests versus one in C. This route distinction is verified; it does not prove every algorithmic causal attribution. Three paired gains do not all become vector-producer gains. Mechanical outputs are not model samples.

The fixed historical113 gate fails on three tasks, all L1 in both current C and P; these are regressions relative to the archived baseline, not three current paired P regressions. One historically correct task uses an extra P request, violating the fixed cost gate even though P's total calls are lower. P also remains below120 L3 and0.80. The frozen decision remains adoption=false. The resource guard passed separately; it is distinct from the failed historical-quality guard.

Paired weighted difference is +0.015384615. Only3 pairs are discordant, all positive; the two-sided exact sign/McNemar p=0.25 assumes independent discordances, unproved for related development tasks. This descriptive check introduces no new adoption threshold. N=156 is the paired development count; admitted independent tasks remain0 and effective independent family N is unknown. No independent/five-sample qualification follows. The owner's complete model/native-route replay and final provenance decision remain pending.

## Waveform101/103: concrete execution blocker

Ticket101/spec29245c3265c0ed7f9567d78ee94bdc0d05e66d2d31fdcfcf95e31fbd4dd4a5da stopped after two rows/4 model calls. The third worker returned1 before run_worker, created no request journal and logged resource admission is stale. Original log SHA256 fb35be3a3982973eb55a99abedf089203c6cbb127221dbd9bfd2e2c49422cf06. Stage elapsed139.210s.

The admission check accepts a first check only while its receipt is0–120 seconds old. Waveform worker.py:45 supplies first=True on every subprocess. The stage already has an initial freshness check and ordinary checks between samples. Continued work therefore fails once the initial receipt ages, despite retained ownership/model/protection.

Queued103/spec9b90acec3379490e4d313d59bceb6fd9833ed713624267f1a0aa05de96cc121c has the identical worker SHA5ea05bec155c64807da1aee9cd94f2dd734abcd2b618f5c6b9601441e9959306 and dependency check. Its endpoint-semantics correction did not fix this blocker. Earlier bounded prompt/wire review did not cover cross-task admission age and cannot stand for runtime acceptance.

Ticket102/spec451d7191252877db37971f49ecc80a35881da5eec6bb8c493a9fcb8a5167bd41 calls the ordinary check at worker.py:103 (SHA036e1bf19fedc01b3d9d5484913b819b39832ba87f92091219d455ea5f6bc1a1), while its stage retains first=True. This specific counterexample does not match102; complete runtime acceptance remains pending.

Recommended owner action: preserve101 failure/frozen evidence, handle its held FIFO state, and consider cancelling unstarted103 before a new source/preparation freeze. Retain fresh admission at stage start and ownership/model/protected-file validation in workers. Do not refresh the original timestamp or remove protection. Generic controls should cover stale initial admission rejection, later worker checks after120 seconds under a valid lease, and changed lock/model rejection. This is an engineering repair, not a redraw for a better score.

Both original98/101 guards record unchanged model/protected files, zero remaining owned descendants, idle backend at exit and released resource slots.101's stage failure still leaves its FIFO ticket held. This task did not edit, cancel, release or restart peer tasks.

## Evidence and next step

Read-only review c006876694dd7e3aa0e39ef7c9be8074dec39c3bf329c3759bf041c47b79862d is archived privately under05_handoff/independent_validation_20261004/peer_vector98_waveform101_review_20261006. ZIP b3d8ea0333a7ba45d6ff2e8480e5ef0c946078f9597296d60c94836d0439d2de,425844bytes,20 members/19 hashed payloads, verified at both endpoints. Originals remain private; no unnecessary task-created intermediate/cache/empty directory remains.

[Issue7 comment6015906969](https://github.com/854259/FPGA/issues/7#issuecomment-6015906969) contains the root cause and was read back. Acknowledgement/adoption remains pending. The candidate owner retains original terminal audits,101 queue handling and103 repair/refreeze; this task reviews the concrete diff and receipts without takeover or redundant model/EDA runs.

Own source-body substage100 is complete; [PR50](https://github.com/854259/FPGA/pull/50) merged as dd7a76b3137e274f8a336a394a2c0ec4735bb78c. Independent-source correctness admission remains withheld. Full A/P/B, audited RTLLM, important five samples, actual full budgets and formal32GB delivery remain open.
