# RTL official-contract entry

The selected table/phase candidate with the unchanged 174-word first-system
suffix is now connected to both HTTP and CLI in this source package.
CPU chain, guard, health and endpoint evidence is bound to the separate revisions
recorded in the manifest; historical suites are not claims about every later
revision. The current guard has four targeted AMD CPU state cases. Model replies
and EDA outputs in the historical integration cases were synthetic; actual
model/EDA interface qualification, resource acceptance, isolation and reproducible
deployment are still pending. This is not a scored or formally accepted deployment.

Pinned official reference: `https://gitee.com/Vickyiii/rtlagent2026`, commit
`afd135e7ba5f6ec4c6d77e7c927c894327537801`.
`baseline.py` and `run_baseline.sh` remain byte-for-byte official files,
bound by `upstream.json`. The package contains no evaluator, private vectors,
reference solutions or benchmark answers.

## Candidate and evidence

`agent/runtime.py` calls `candidate_worker.run` from the Linux main thread.
The worker uses the frozen generation loop and skills, one generation and
at most one repair, 8192 output tokens, temperature 0 and top_p 1. The
174-word suffix is applied only to the first system message. These candidate
settings are fixed; changing them requires a separately frozen comparison.

The candidate checks its own source and uses owned xvlog compilation. Where
the current prompt provides a supported contract, it builds table or
priority/shift/edge/phase checks, runs xvlog/xelab/xsim and supplies the actual
diagnostic to the sole repair. Unsupported contracts abstain. The inherited
successful ANSI declaration repair still returns before functional checking;
this limitation is preserved, not silently changed during integration.

`manifest.json` binds the source, skills and official baseline, records the
byte-identical modules and function projections, and distinguishes CPU evidence
from deployment qualification. Inputs are only staged `prompt.txt` and
optional `interface.txt`; caller task IDs do not select algorithm behavior.
The outer host must separately enforce evaluator isolation, local weights,
single-GPU memory limits and fixed model configuration.

## CLI and model service

Run project code only on the authorized AMD Linux server, from this directory:

```bash
export LLM_BASE_URL=http://127.0.0.1:8000/v1
export MODEL_NAME=YOUR_ACTUALLY_SERVED_MODEL_ID
export XILINX_VIVADO=/tools/Xilinx/2026.1/Vivado
export EDA_TMP=/tmp/eda
./run.sh TASK_DIR NEW_OUT_DIR
python3 agent/runtime.py baseline TASK_DIR NEW_BASELINE_OUT_DIR
```

Both produce `solution.v` and `trace.jsonl`. The development CLI budget
defaults to 300 seconds; `AGENT_DEADLINE_S` overrides it. This is not an
announced contest limit. The supervised baseline mode executes the untouched
official program in an owned subprocess. Direct `./run_baseline.sh` remains
the official unsupervised entry and needs an external deadline supervisor.

The model must already be served on the admitted local endpoint at port 8000. All runtime profiles require a loopback model URL;
`RTL_PROFILE=development` does not bypass this check.
`MODEL_NAME` must match its listing. Agent and baseline share its weights and
configuration. Loopback is not proof of local weights or offline isolation.
`VIVADO_BIN` overrides `XILINX_VIVADO/bin` or PATH.

## HTTP and lifecycle

```bash
export FPGACHINA_TOKEN=YOUR_PRIVATE_TOKEN
export RTL_EVIDENCE_DIR=/private/path/rtl-evidence
python3 agent/runtime.py serve --port 7860
```

`serve/serve_all.sh` starts absent services only during its initial startup.
After startup it observes and warns, including when a recorded process has
exited. It never automatically stops or restarts either service: the pinned
API_CONTRACT section 4 prohibits restarts during evaluation. A failed or
unresponsive service is retained for inspection; requests are not replayed.

The server binds 127.0.0.1. Both `GET /v1/health` and `POST /v1/solve`
require Bearer authentication. Solve accepts `task_id`, `nonce`, `mode`
(`agent` or `baseline`), `prompt`, `interface` and `deadline_s`.
Responses contain `task_id`, `solution`, `trace` and `elapsed_s`.

HTTPServer processes requests serially in the main thread so signal deadlines
and native child ownership match CLI behavior. Health requests also wait while
a solve is running. HTTP work and cleanup inherit the clock from entry to `do_POST`, before
authentication and body parsing. This includes subsequent parsing time; it
does not include earlier socket queuing or request-header receipt. Concurrent
arrival and the official sender-to-response wall clock still need qualification.

Preparation, model transport and native stages share one monotonic work end.
HTTP reserves `min(10, deadline_s / 2)` seconds for cleanup and
`min(1, deadline_s / 10)` seconds for the response, both inside the requested
total budget. Agent native operations, baseline supervision, child cleanup
and model-idle recovery inherit the same absolute cleanup ceiling. Cleanup is
also capped at ten seconds from the first observed cancellation. CLI retains
its work budget plus at most ten seconds of cleanup unless an earlier ceiling
is supplied. A work timeout clears the proposal and records unknown calls
where appropriate. If recovery cannot be verified in its reserve, the runtime
blocks rather than borrowing time or reporting recovery complete. Response
headroom is not proof of the official sender-to-response limit.
A failed tool/protocol/recovery check retains evidence and stops further work
with HTTP 503 until inspection. A process cancellation exits the HTTP service after bounded cleanup, even when a transport wrapper or recovery fails. There are no implicit model retries.

Every request gets a unique private evidence directory, defaulting to
`EDA_TMP/rtl-evidence`. It retains staged inputs, request/response receipts,
trace, source/check diagnostics and cleanup/recovery records. Keep this outside
public artifacts. Scratch is removed only after cleanup succeeds; failure
scratch is retained. No cache or resume path is used.

Health checks the model listing, official baseline hashes and Vivado 2026.1.
It reports attributed VRAM or null. Unknown VRAM does not by itself make
readiness false. Readiness therefore does not establish the official memory
limit, peak usage or isolation; verify raw bytes across the full lifecycle.
The cached health version probe now uses an owned native group and reaps detached descendants, with 30 seconds of work and one shared 10-second cleanup reserve. Cancellation exits after cleanup. It retains private health evidence; unknown cleanup blocks further work. These limits apply to the version probe, not an asserted bound on every health operation. Actual Vivado qualification remains pending.

## Validation and packaging

The historical fourteen-case qualification at runtime `2ea06b05` and native supervisor `16f559e7` followed a native cleanup error that erased an earlier SIGTERM timestamp. The supervisor now preserves that timestamp on the replacement error, so callers clean up and exit. The new regression sends a real signal, injects a process-group cleanup failure, and verifies descendant retirement and service exit. The previous eleven- and two-case reports below remain historical scopes; no actual model or EDA qualification is implied.

Two targeted health cases additionally cover normal version-probe child cleanup and cancellation through the real HTTP endpoint using a synthetic CPU executable. Both failures were reproduced before the fix. Other runtime functions remain AST-identical to the eleven-case version; the two health cases were run separately, without repeating unrelated model controls.

Eleven AMD CPU cases cover repeated direct/HTTP calls, authentication, CLI
dispatch, one actual signal-based deadline followed by another request,
malformed-checker blocking, SIGTERM cleanup/recovery sharing and reaping a
detached tool child. Three additional cases send real SIGTERM during transport, a native stage and failing recovery. The historical bounded shell guard case retained a live agent but permitted restarting an exited agent; that restart expectation is now superseded by the no-restart contract check below. HTTP baseline execution is stubbed in these cases; CLI
coverage calls `runtime.main`, not the shell wrapper. See manifest validation
receipts. Original failed test evidence is retained. The early seven-case fixture corrected the expected final newline from the unchanged baseline extractor. Later regressions reproduced HTTP cancellation being swallowed and the guard trying to restart a live child; both are fixed and verified.

The updated guard method runs the original shell monitoring loop with synthetic
health/start/stop functions and real CPU child lifecycles. The old script
reproduced three forbidden restart/stop branches; the fixed script passes all
four model/agent alive/exited cases. Its startup functions are unchanged and
were not exercised by these cases. Other test methods were not rerun. This
checks monitoring policy, not real service availability or deployment.

A retained original CPU HTTP control requested 0.1 seconds but recorded
1.343 seconds internally; it checked recovery and the next request, not timely
completion. The revised controls check a three-second timeout returning empty
in 2.470 seconds followed by a successful request in the same service, and a
0.1-second recovery limit returning 503 in 0.091 seconds and blocking further
work. These are actual local HTTP observations with synthetic model/EDA work.
Inherited request start, baseline cleanup ceiling, native ceiling forwarding
and unchanged default CLI reserve are also checked. An initial allocation left
only 1.2 seconds for a required 1.25-second quiet interval; that failed control
is retained. Recovery and response reserves are now separate, without relaxing
either tested deadline. Only affected methods were rerun.

Package only this directory. No parent evaluator or private archive is needed
by generation. Prompt allowlisting is not an OS sandbox. The final image,
service supervisor, real model cancellation, baseline execution, actual EDA,
formal resource limit and reproducible offline deployment remain to be verified.
