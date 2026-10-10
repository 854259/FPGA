## HTTP交付接线（2026-10-08 21:36）

2026-10-08 21:36 +08:00：已补齐原132表格反馈到正式HTTP入口的隔离接线。原bridge v2传输/超时/进程树与core、官方baseline、两skill逐字复用；新入口调用原132单反例table.check及其实际phase回退函数，避免退回旧bridge点反馈。AMD新增4个HTTP流程（错误→修复、正确直返、弃权回退、官方baseline）一次通过，5模拟模型回复/13假工具进程，另核回退绑定与异常恢复；真实模型/EDA/新FIFO0，不重跑T5/T6/旧native。准备3044489与控制3044490均一次rc0/exec/reap且退休；.134898/1.584091秒仅各childwait，控制内部1.384586秒不称完整外部耗时。109成员原档案2abcaf13双端全成员hash核，包未部署，未授新native/32GB/镜像/评分资格。

原132/133/134不变，21:30同出生/命令分别running/queued/queued。新Gmail1a11ba4c292def37与6060636572全文相同，peer135结构定位比较已实际queued、monitor3017416同出生S活及RESUME4d5193a8绑定，排原三票后；其源码/控制只按披露记，不抢WIP或重复审。继续按官方总分相关量选优；23:00停止本地，远端依原冻结串行继续。完整目标未达，不用接口检查充当正确率提升。

## 已冻结的下一比较（2026-10-08 21:12）

FIFO134已条件入队，模型尚未开始。prepare_multi_comparison.py保持原全部9项题面准入、五样本三臂；A使用归档单反例，P使用多反例，B保持原样官方baseline。worker.py仅在显式冻结control_feedback_sha256时给A接旧反馈，模型来源绑定函数不变。远端入口核原133真实资格后唯一启动；失败不重试。最大225请求、原8192与A/P2/B1仅为本次因素比较的冻结。完整156的132和原133不受本次源码更新影响。详见PUBLIC_RESULT.json；不把合成检查或受理当成绩。

## 当前候选版本（2026-10-08 20:49）

仓库中的table_feedback.py现在是待验证的多反例版；在跑132仍使用先前冻结原版，不由Git更新替换。新增反馈逐一绑定实际仿真不符、按输入位宽显示二进制并保留总不符数，不生成DUT、不增加本次模型请求上限。multi_counterexample_controls.py的纯检查已在AMD通过，真实向量探针已排FIFO133，尚无native或评分资格。旧controls.py及下文早期结果对应其原冻结版本，不重跑旧7路径/3原生控制。详细来源、诊断和队列见PUBLIC_RESULT.json。

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

## 五样本结果及完整156接续（2026-10-08）

原135份结果已一次终审：官方系数均值A/P/B为0.5377778/0.7333333/0.3777778；P增加19.5556个百分点，真实耗时也增加。45对首次请求及回答内容相同，11份修复改善分布于3题；仅9项开发题，不外推完整成绩。保留原候选，`prepare_full_comparison.py`在AMD复用26份原源码与完整156输入生成2340行、最多3900请求的五样本三臂计划。36小时队列上限为安全停止边界；准备不等于提交。按赛题要求比较，旧逐题/调用否决条件不恢复。原RESULT与过程、私有档案SHA见PUBLIC_RESULT.json。
