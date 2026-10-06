# Strict formal-tool admission result

2026-10-06. **Completed and verified: engineering admission only.** This is an engineering admission substage, not a quality run or a full batch. P remains frozen. The stage ran after the other owner's frozen 156-task C/P regression through the existing FIFO.

Preparation record at10:03+08: ticket91 was queued with monitor638501 alive; no result directory exists. Execution source61407c9ece32894eda9095d675ce8e6b5e8be0aa, source SHA25604460ec0f35281327e194724061cf9c6536d2bdb51d9b0bae7d6b1f62e233204, plan SHA256c65efde8ece96947a77ba374abbc666cbb37a6d7021e82a40a409629770f29cf. All8 prepared files match on both endpoints; model identity is unchanged. Delivered through [PR23](https://github.com/854259/FPGA/pull/23); AMD terminal validation is recorded below.

The source-metadata counterexample showed that a text label and finite simulation cannot by themselves establish full correctness. The next useful question is whether an isolated local tool can provide complete finite-width combinational proofs and valid sequential induction, while keeping bounded success, reachable counterexample, inconclusive proof and tool failure distinct.

## Frozen experiment

Use `strict_formal_tool_20261006.py` in this directory, at the preparation commit recorded in the private plan. Inputs are eight constructed RTL controls only. No corpus prompt, reference RTL or testbench is opened. No model call or generated answer. Do not expand to ChipVerilog automatically after passing.

| Control | Expected outcome |
|---|---|
| Commuted unsigned addition with full carry | Complete combinational proof |
| Dropped carry | Reachable counterexample |
| Unknown output | Counterexample, never a pass through X matching |
| Undriven output | Tool/structural error |
| Missing dependency | Tool/structural error; no generated stub |
| Counter parity invariant with explicit initial state | Inductive proof |
| Counter failure after the four-step bound | Bounded pass only |
| Same delayed-failure circuit with induction | Reachable base-case counterexample |

Five constructed parser controls additionally reject empty receipts, bounded-as-inductive success, induction-limit-as-counterexample, and timeout-as-proof. They are not hardware proof results. Stop at the first mismatched control; retain failure evidence and do not re-sample anything.

Offline installation uses only five SHA256-pinned wheels: yowasp-yosys0.69.0.0.post1233, yowasp-runtime1.96, wasmtime47.0.1 (Linux x86_64), platformdirs4.9.4 and click8.3.1. Their declared dependencies were checked for AMD Python3.12/Linux. Metadata and the two YoWASP Python entrypoints were read, but no package code ran during Windows preparation. Source/metadata downloads and transfer are pure file operations. The wheels total25,732,910bytes and are retained privately.

Use an isolated target directory and child-only Python environment, explicit WASM mount, own temporary/cache directories, two CPU affinities, observed process-group RSS cap2GiB, minimum2GiB free disk. No system package installation or shared service/configuration change. Runtime cache remains a needed dependency while this route is being evaluated. Installation90s, first startup360s, eight proof commands60s each, SAT instance limit30s; stage1200s, FIFO slot25min. Maximum9 Yosys invocations,0 model calls. Queuing time is separately recorded and is not included in the stage budget. Failed startup or any admission failure ends this substage.

References: [YoWASP runtime configuration](https://github.com/YoWASP/runtime-py#configuration), [Yosys SAT command](https://yosyshq.readthedocs.io/projects/yosys/en/v0.49/cmd/sat.html), [pinned Yosys0.69 SAT implementation](https://github.com/YosysHQ/yosys/blob/v0.69/passes/sat/sat.cc). The executable's version and actual receipts must still be verified on AMD. Explicit assertion lowering and clock-enable lowering follow the pinned tool's supported cell interface.

## Evidence limits and next gate

These are constructed two-state, finite-width examples with explicit initialization where applicable. Even a complete proof of these assertions would not prove arbitrary SystemVerilog support, correct natural-language specifications, trustworthy references, complete corpus interfaces/parameters, independent data exposure, or official32GB delivery.

A successful stage permits a separate source-family/contract audit for an independently frozen evaluation set. A failure requires a cause-specific engineering decision, preserving the original negative result. Neither outcome authorizes model expansion, adoption, deployment, or replacing the official scorer.

The bounded inventory verified the prior isolated Icarus manifest and found no Yosys in that tool prefix, team tools, current owner dependency directory, /opt or selected task/model deployment directories (maximumdepth5). This is not a machine-wide absence claim. Actual server quota/expiry remains requested; no purchase or time extension was made.

All raw wheel metadata, provenance, queue/guard receipts and future logs remain under the existing private handoff archive. Repository changes are delivered through an own-reviewed PR; AMD execution remains bound to its frozen source SHA.

## Verified terminal result

At2026-10-06 14:23+08, FIFO ticket91 completed under source61407c9ece32894eda9095d675ce8e6b5e8be0aa. All eight RTL controls and five parser controls matched the original freeze; no source, wheel, rule or budget change. Nine Yosys invocations and zero model calls. Actual tool: Yosys0.69, Git9f75ca1f9.

The addition and parity controls produced complete combinational and inductive proofs, respectively. Dropped carry and unknown output produced counterexamples. Undriven output and missing dependency were structural failures; no stubs were added. The delayed-failure circuit passed the four-step bounded check, while induction found a reachable base-case failure. This is the key distinction needed for source admission: a bounded pass cannot be reported as complete correctness.

Stage30.322595s; guard30.554557s. Queue wait14176.759977s is separate. Installation0.778389s and first startup26.247163s account for most stage time. Maximum observed subprocess-group RSS was1,540,698,112bytes, sampled every0.1s; this is not a continuous memory peak or formal32GB model-flow evidence.

Raw receipts were checked against source/plan/wheel hashes, generated control sources, command scripts, return codes and actual proof markers. All443 installed files match the terminal hashes. The guard confirmed no active owned descendants, unchanged model/protected files, backend idle at stage exit and slot release. Two finished FIFO monitors remained zombies when inspected; they were not active computation and were not killed.

The private terminal ZIP has49 members (48 content hashes plus manifest),100571bytes, SHA2562798d6bbee64d363a3572c21fa10d3d7eaa283304b811f8f52c0adc0f9ae2607. Every member and both endpoint archive hashes were verified. Result SHA256d137968a16195fd4131cb67ec22c4cc0119306b1ad90cd0ac56055a531fc4349; guard SHA25682ca6c5848e83bc1d50d18618ea6ef93f254ae5a2518f3bda9871be1628bb729. No task-owned temporary/Python-cache residue remains. Installed tool106,634,792bytes and runtime cache214,359,680bytes remain necessary dependencies; pinned wheels are retained privately. No raw logs, wheels or private receipts enter this PR.

The engineering substage is complete. It establishes a usable proof tool for the constructed contracts only; independent admission remains0 and the all-inclusive batch remains incomplete. Next, audit the pinned ChipVerilog source-family/license/contract/dependency/exposure inventory before any source-body execution or model call. No automatic benchmark expansion, reference repair, support stubbing, candidate adoption or deployment. The other owner's ticket90 has312/312 outputs, but its stage summary still reports audit_pending; that is not a reviewed acceptance decision here.
