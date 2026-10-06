# Independent-source admission: bounded classifier counterexample

Checked 2026-10-06 09:31 +08:00. This substage is complete. No new model quality result, independent admitted task, or all-inclusive batch completion.

ChipVerilog remains a candidate source, but its generic function_pass aggregate is not admitted as full-correctness evidence. A constructed testbench that only prints "No errors", without a functional comparison, is classified as self-checking; the output parser finds no failure. This establishes a classifier counterexample, not an observed false acceptance in the benchmark corpus. No benchmark task or RTL was run.

## Source and exposure

Only papers, README, licenses and generic evaluation scripts were inspected. No new task prompts, reference RTL, testbench bodies or per-task model outputs were opened. Focused searches of this research branch's state, 03_analysis and 05_handoff found no prior source registration; team-wide and model-training exposure remain unknown.

- [ChipVerilog](https://github.com/HKUSTGZ-MICS-LYU/ChipVerilog/tree/3eea482f20c048966d54ed04c418b85e5fd4d498): README describes 64 tasks from five source families. Task count is not an independent-family count.
- [RTL-BenchLS](https://github.com/hkust-zhiyao/RTL-BenchLS/blob/main/README.md): round-trip, infilling and repository-repair tasks differ from the current prompt-to-RTL contract; no dataset downloaded.
- [FormalRTL](https://arxiv.org/abs/2603.08738): an open-source release is promised in the abstract; an available dataset was not verified.
- [TuRTLe](https://github.com/HPAI-BSC/turtle): evaluation framework availability does not establish new independent tasks; not installed.

ChipVerilog is pinned to 3eea482f20c048966d54ed04c418b85e5fd4d498. Five files were acquired: README, LICENSE, THIRD_PARTY_LICENSES, formal_equivalence and recompute_corrected_summary. Byte sizes and Git blob hashes match. Its MIT license does not replace upstream RTL licenses; family-specific review is still required ([license scope](https://github.com/HKUSTGZ-MICS-LYU/ChipVerilog/blob/3eea482f20c048966d54ed04c418b85e5fd4d498/THIRD_PARTY_LICENSES.md)).

The initial AMD GitHub metadata request timed out without acquiring upstream files. Pinned files were then downloaded as pure file operations on Windows and transferred to AMD. All project code execution remained on AMD. No installation, SSH change or shared-service change.

## Executed control

Execution commit e4737d883e88f933d3b64d5014839dbb316abda3; FIFO ticket89, monitor616828, stage616834, all exited. Plan SHA256 8bc6176e93025a8caf2b0e51fdf0e8a28889005f570e92fd51da6421a20a6b97; stage cap60s, slot5min.

The probe executes only five statically reviewed functions and four regex assignments selected from the hash-pinned verifier. It never imports its module or runs its CLI.

| Constructed text | Functional comparison | Classified self-checking |
|---|---:|---:|
| Print No errors only | No | Yes: counterexample |
| Print done only | No | No |
| Conditional mismatch print | Yes | Yes |
| Error words in comment only | No | No |

MISMATCH remains a detected failure. A constructed bounded-proof row yields function_pass=1, full=0, bounded=1. This is an aggregation control, not an actual formal proof. Upstream already distinguishes proof types; we must preserve that distinction. Automatic support stubs were inspected statically, not executed.

Source: [classifier L587](https://github.com/HKUSTGZ-MICS-LYU/ChipVerilog/blob/3eea482f20c048966d54ed04c418b85e5fd4d498/tools/formal_equivalence.py#L587), [aggregation L443](https://github.com/HKUSTGZ-MICS-LYU/ChipVerilog/blob/3eea482f20c048966d54ed04c418b85e5fd4d498/tools/formal_equivalence.py#L443), [support generation L1719](https://github.com/HKUSTGZ-MICS-LYU/ChipVerilog/blob/3eea482f20c048966d54ed04c418b85e5fd4d498/tools/formal_equivalence.py#L1719).

Probe0.017377s; guard0.251180s. Model identity, protected files, descendant cleanup and slot release passed. New model, compiler and simulator calls:0. Independent admitted:0. This is a bounded diagnostic, not a general security checker or official scorer.

## Decision and next gate

Keep P frozen. Do not expand this corpus or repeat old model samples. A possible admission route must first establish complete combinational equivalence or valid induction with no generated stubs, preserving interfaces, state assumptions, failure and timeout distinctions. That route is not implemented or verified. Actual quota, independent materials and formal32GB delivery remain blockers for an all-inclusive run. At09:36, no Yosys was found in the current default PATH or three standard locations; this bounded lookup does not prove absence from isolated installations. No tools were installed or executed. Next: inspect the existing isolated-tool manifests before preparing any proof route. Actual remaining hours and expiry have been requested from the user; no purchase or model expansion is authorized by this report.

## Evidence and cleanup

Private directory: 05_handoff/independent_validation_20261004/source_metadata_20261006/.
The17-file terminal ZIP is74440bytes, SHA256 bc4d35bd931b3eff59533015567c8737d6ddbaeb7d347546c0830c4c89d1b547. Original files and every archive member match; both endpoints verified. No generated compiler/Python cache or temporary transfer package remains. Originals, provenance and failure information are retained privately.

Result SHA256 8f15d0e4b3ca6bae9540e58fbf1a5105988f2fd97209733958806ef08505b036.
Guard SHA256 b2d2ed9391f949573fe9d19baf28d16eb5cfc6a1cdbaacc1a01133f3d32f0aa3.
Only the bounded probe source and reviewed aggregate report are public.
