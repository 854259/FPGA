# Strict formal-tool admission preparation

2026-10-06. **Prepared, not executed or passed.** This is an engineering admission substage, not a quality run or a full batch. P remains frozen. The other owner's ticket90 is running its own frozen 156-task C/P regression; this work must wait in the existing FIFO.

At10:03+08, ticket91 is queued with monitor638501 alive; no result directory exists. Execution source61407c9ece32894eda9095d675ce8e6b5e8be0aa, source SHA25604460ec0f35281327e194724061cf9c6536d2bdb51d9b0bae7d6b1f62e233204, plan SHA256c65efde8ece96947a77ba374abbc666cbb37a6d7021e82a40a409629770f29cf. All8 prepared files match on both endpoints; model identity is unchanged. Reviewed under [draft PR23](https://github.com/854259/FPGA/pull/23), pending actual AMD validation before merge.

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
