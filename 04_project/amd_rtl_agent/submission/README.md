# RTL official-contract entry

Pinned reference: `https://gitee.com/Vickyiii/rtlagent2026`, commit
`afd135e7ba5f6ec4c6d77e7c927c894327537801` (2026-09-21).

This directory is the submission source boundary. It contains no reference
solutions, evaluator, historical benchmark outputs or task-specific answers.
`baseline.py` and `run_baseline.sh` are byte-for-byte upstream Git blobs;
`upstream.json` records their SHA-256. Do not edit either official file.

## Inputs and outputs

On Linux, from this directory:

```bash
./run.sh /path/to/task /tmp/new-agent-output
./run_baseline.sh /path/to/task /tmp/new-baseline-output
```

Both read `prompt.txt` and optionally `interface.txt`, and write `solution.v`
and JSONL `trace.jsonl`. The first entry supervises a worker with an internal
development default of 300 seconds (`AGENT_DEADLINE_S` overrides it). This is
not an announced contest budget. The unchanged baseline script relies on the
external caller for termination; the HTTP service and external evaluation
driver supervise both modes. Use a new output directory per sample.

Python equivalents for local integration checks:

```bash
python3 runtime.py run TASK_DIR NEW_OUT_DIR
python3 runtime.py baseline TASK_DIR NEW_OUT_DIR
```

The latter calls the unchanged official baseline in a supervised subprocess.
The agent reads only staged prompt/interface text. It generates once, checks
source structure, and checks its own candidate with `xvlog` followed by
`xelab work.TopModule`. The second check catches unresolved submodules and port
connections that parsing alone accepts. Both checks share the remaining solve
deadline and use only the candidate source, with no testbench or reference.
`RTL_REPAIRS=0..1` controls additional model calls (default 1). No hidden
testbench, reference solution, task metadata, or external judging result is
read by this worker. Missing tools leave the candidate explicitly unverified.
No self-generated functional testbench is implemented
in this first adaptation. A successful candidate compile is **not** labelled
official L1 or functional success; only the external official judge assigns
L0–L3. The old development agent remains outside this directory.

## Shared model service and environment

```bash
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export MODEL_NAME=YOUR_ACTUALLY_SERVED_MODEL_ID
export XILINX_VIVADO=/tools/Xilinx/2026.1/Vivado
export EDA_TMP=/tmp/eda
export FPGACHINA_TOKEN=YOUR_PRIVATE_TOKEN
python3 runtime.py serve --port 7860
```

Keep the model server running in the same environment on loopback. Both modes
use this same base URL and model ID. The baseline's system message,
temperature=0, top_p=1 and max_tokens=8192 are upstream constants. Agent
defaults match the sampling limits; `RTL_MAX_TOKENS` and `RTL_TEMPERATURE`
are explicit agent-only experiment settings. No legacy `LLM_MOCK_FILE`,
`LLM_MODEL`, `LLM_API_KEY` or `enable_thinking` option is used here.

Both `RTL_PROFILE=submission` and `RTL_PROFILE=development` reject non-loopback
model URLs. All current experiments require weights deployed on the same server
and direct access to its local inference process; no external model API or
forwarding gateway is allowed. A loopback address alone does not establish this:
verify the served local weight path/version and enforce no external network at
complete-runtime acceptance. Keep the official baseline unchanged and point it
at that same verified local service.

`VIVADO_BIN` overrides the tool directory; otherwise `XILINX_VIVADO/bin` or
PATH is used. There are no hardcoded drive letters in the submission code.

## HTTP contract

Both `GET /v1/health` and `POST /v1/solve` require
`Authorization: Bearer <FPGACHINA_TOKEN>`. The server binds only 127.0.0.1.
Requests accept `task_id`, `nonce`, `mode` (`agent` or `baseline`), `prompt`,
`interface` (normally empty), and `deadline_s`. Responses contain `task_id`,
`solution`, `trace`, and `elapsed_s`. Task IDs are echoed, never used as paths.
Requests are serialized for the shared model. HTTP body reception and waiting time consume
the supplied deadline. Each request uses new local scratch and a separate
worker process. Timeout cancels the process tree and returns the candidate
already available (or empty text), followed by future requests normally.

Trace records model calls and candidate checks; `*_start` entries identify
in-flight operations if a deadline interrupts them. A supervisor timeout event
is additional diagnostic information, not a fabricated baseline model call.
Normal baseline traces remain exactly upstream `baseline_meta` + one `llm`.

Health checks the model listing, baseline hashes, xvlog/xelab availability and actual
Vivado 2026.1 version. In submission mode it also requires readable amdgpu
VRAM byte counters and <=32,000,000,000 bytes (conservative 32 GB limit);
the legacy `vram_gb` response field is in GiB. Unavailable VRAM is `null` and readiness is
false, never an invented zero. This is a readiness probe, not a GPU performance
test. Model loading, quantization, offline network enforcement and final image
validation remain deployment work. Do not expose the inference port.

## Packaging boundary

Package only this directory as the agent source; do not copy the parent
`official_reference/`, old `bench/`, `outputs/` or historical agent into the
submission environment. The process stages inputs by allowlist; it is not an
OS sandbox. Final isolation must also keep evaluator files outside the agent
container. Official image, weights, inference startup and full MODEL/manifest
declarations are still pending. This source adaptation is not a final image.
