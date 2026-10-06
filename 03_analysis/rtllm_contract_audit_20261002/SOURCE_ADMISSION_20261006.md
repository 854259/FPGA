## Current gate: complete source metadata inventory — verified

2026-10-06 16:41+08. FIFO ticket 97 completed on AMD at 06:41:00Z. All 64 source/reference description pairs are unique across five declared families. All 84 reference-directory RTL assets are bound to the pinned Git tree; 53 have no identical blob in the corresponding original Src family. This is a provenance gap, not evidence that those assets are incorrect: testbenches, formatting, extraction or edits still require body inspection.

Execution commit 182c4ddc5222074891fc1edeea12d4626a4c33e9; source SHA256 fcb0f33d72433ca679bd1b087e8aa9bf38d74eec2a55882a563de376390f4d80; plan SHA256 e91589afd911108f7124e1c337891e9bf5765209bfddbaecb771440939805e3b. The source in PR44 remains identical to executed source. The earlier strict formal-tool controls passed and were merged through PR23 (eadb360b919c4041f946169676d60fe9a2658ff2); neither stage admits benchmark tasks.

The complete ChipVerilog tree at 3eea482f20c048966d54ed04c418b85e5fd4d498 contains 5565 metadata entries, not truncated; tree SHA256 102874d7e191b48fdbc00a9ad071ee56446aec6c2dcfabd9a84c2f2e0cb1d497. Every output row and asset was rechecked against that tree during terminal review. Family counts are OR1200 38, MIPS 11, double FPU 9, I2C 3 and CORDIC 3. No rows were discarded. No task descriptions, reference RTL, testbench or generated-output bodies were acquired by this stage. No upstream verifier was executed.

Stage time 0.0637936983s; guard time 0.2512672730s; model/compiler/simulator calls 0. The frozen limits were 120 seconds and a five-minute FIFO slot. The guard confirmed model/protected-file identity, no remaining owned descendants, idle backend at exit and slot release. Follow-up at 08:38Z found no active owned runner/child; other-owner tickets 98 running and 99 queued were left unchanged. Queue wait is separate from execution time.

Private evidence: 05_handoff/independent_validation_20261004/source_contract_inventory_20261006/. The 263588-byte terminal ZIP contains 12 members (11 hashed content files plus manifest), SHA256 f47d117b3d1647b28dfe87c8e0e747788c9925a6d63f5a53cbd7975009ccd4a7. Both endpoints and all members match. Result SHA256 f6ae361ab4f7ecab872084ae216dcdad5aaa31f8372cd13e1d0860138a1d5324; guard SHA256 58d9aad8d71da8bca876fd9410676a83ac4a715e445be1193a93b94f79e4b0e2. No temporary transfer package, generated cache or empty temporary directory remains; frozen inputs and evidence are retained.

Decision: metadata inventory accepted; correctness, full contract, dependency completeness, exact licensing and independent admission remain unverified. All five families need source-body review; CORDIC exact licensing and some LGPL source notices remain unresolved. Team-wide/training exposure is unknown. Independent admitted count stays 0; effective independent-family N is unknown. This is an engineering substage, not an all-inclusive batch or quality improvement.

Next: freeze an evaluation-only body/provenance audit covering all 64 tasks and their source families, without exposing reference/testbench bodies to generation or modifying P. Preserve every ambiguous or missing dependency and do not fabricate stubs. Any material used for candidate/rule tuning becomes development data. Actual quota/expiry, full A/P/B budget, independent materials and formal 32GB delivery remain open.

---


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
