# Bounded token-budget calibration

This optional development experiment evaluates the frozen agent's **first request**
on eight new synthetic specifications. It never reads VerilogEval result scores,
modifies prompts after observations, repairs a response, changes the official
baseline/judge, restarts the model, or deploys a selected configuration.

Four profiles are fixed before generation: the current uncapped 8192-token request,
and thinking/total budgets 4096/8192, 6144/10240, 8192/12288. New profiles reserve
4096 tokens for final content. These are a coarse grid chosen from context/time
capacity, not demonstrated optima. Temperature, system prompt and concurrency stay
fixed. The four selection specifications use all profiles in rotating order. The
winner maximizes functional passes, then minimizes blank responses and model time;
a quality tie requires at least 10% less measured model time to replace control.
The selected profile and control each run once on four reserved specifications.
Validation may reject the selection but never starts another parameter search.

The eight specifications are engineering calibration/validation data, **not a clean
competition holdout**. Offline five-gram overlap screening only detects textual
overlap, not semantic duplicates or pretraining exposure. Functional checks use
private, deterministic vectors. Those vectors and reference RTL never enter a
model request. All eight reference designs and a deliberately wrong negative
control must validate the simulator before any model call. No synthesis/PPA or
full-agent quality claim can follow from these functional tests alone.

`prepare` writes and hashes all inputs before testing:

```bash
python -B tools/calibrate_token_budget.py prepare --out /absolute/new-directory \
  --skill submission/skill/RTL_SKILL.md --dataset bench/tasks_veval
```

`run` requires Linux/Vivado, an existing frozen plan, and the completed 312-result
predecessor. It waits at most four hours, then confirms the model service is idle.
The existing model must support `thinking_token_budget`; a 32-token capability
probe stops the experiment if activation is not demonstrated. At most 25 model
requests are issued (one capability probe, 16 selection, up to eight validation).
Each HTTP call has a 300-second timeout. Active trials stop after three hours;
exceptions stop the experiment without retries or automatic resumption.

```bash
python -B tools/calibrate_token_budget.py run --out /absolute/prepared-directory \
  --after-run /absolute/frozen-full156-output \
  --vivado-bin /absolute/Vivado/2026.1/bin
```

`plan.json`, `status.json`, `results.json`, `selection.json`, and `report.json`
separate planned, waiting, running, selected, and completed states. Candidate source,
simulation logs and metadata are retained; raw reasoning text is not saved.
Known simulator scratch is removed only inside a newly owned per-trial directory.
Current source/model settings and the original full156 artifacts remain intact.

Simulation success requires both a final PASS marker and zero FAIL markers; a
zero xsim exit code alone is insufficient. The startup negative control caught
this issue before any model call. Failed preparation evidence is retained, and
any infrastructure recovery uses a new directory with byte-identical frozen
inputs rather than overwriting the original experiment.

CPU-only regression checks:

```bash
python -B -m unittest discover -s tests -p test_token_budget_calibration.py -v
```
