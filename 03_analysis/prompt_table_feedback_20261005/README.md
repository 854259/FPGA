# 题面 Kmap 全 care 反馈：独立准备

这里只准备新 helper 与 FAKE 纯边界测试，没有 RUN_SPEC、worker 集成、冻结或真实生成。根任务已收到 FIFO71 终审：75 收据完整、20/25 控制匹配、三个普通错误类型共 15 控制均实际失配且 0 false accept，但五个 sentinel 的 `$fatal` 后 xsim 均真实 rc=0，因此 `qualified_for_generated_control_discrimination=false`。本目录仍仅准备，不能接入真实模型或称已合格。

`contract.py` 与 `render.py` 是 `../prompt_table_native_20261005/` 的逐字节副本，SHA 分别为 `46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206` 与 `2893c870e5cd5cba4b88de3cbca3f1f447cbc74836669f0f78e940dd34d9d817`。只接受完整消费的显式 Kmap，至少一格 care；waveform 和其它题面不进入本 helper。没有数据集 ID 规则、参考答案、官方 TB/ref 或研究控制解读作为模型输入。

`feedback.check(prompt, code, out, attempt, native_run, tools, deadline_monotonic, timeout_s=60)` 返回完整确认的 care 差异文本，全对返回空串；非 admitted Kmap 不调用 native。调用者提供现有 `(argv, cwd, log, seconds) -> paired.owned_command receipt`、三个固定绝对工具路径和**本次 worker 原绝对 solve deadline**。每步上限为当前剩余时间与 60 秒的较小值，不重新开始 300 秒预算，不重试。工具 flags 保持原研究 probe/calibration 的 `-sv --nolog`、`R2Probe -s … --nolog -timescale 1ns/1ps`、`-runall -nolog`；仅用新私有目录和唯一 snapshot，防止复用旧产物。

候选 RTL 按传入字节原样复制；TB 仅由 sealed `render_tb` 从完整题面生成。三个正常 rc=0、无超时/启动失败/残留组、工具和候选/TB/题面/helper 源前后 SHA 相同、日志路径/字节数/SHA 精确，才复用 `parse_observations` 与 `make_feedback(mode='full')`。完整 care 包含实际通过及失败格，不约束 don't-care。非零退出、错误日志、缺失/未知日志、X/Z、错 binding/行序/数量等抛测量异常，收据 feedback 保持空串，不能当功能通过或修复诊断。

每轮私有 `prompt_table_check_{attempt}/RESULTS.json` 先保存 pending/attempted，再保存实际 callback 收据、argv/cwd、源与工具 SHA、log SHA/bytes、逐 care 解析结果与最终状态。这是 callback 证据契约，并不能由纯测试替代实际阶段准入、真实进程身份或阶段审计。FAKE 测试只在临时目录写 synthetic 工具和 stdout，不启动任何工具；其中 receipt validity 只验证模拟接口，不证明实际 native 执行。

FAKE 边界专门保留了“全 care 协议完整、全部通过、真实返回字段 rc=0，末尾仍有 `Fatal:`/`ERROR:`”的模拟日志，要求测量失败且原 rc 保持 0。case-insensitive severity 阻断是新的 native 错误处理因素，只经过本机模拟，不代替新的真实校准，也不修改 sealed parser/render。

未来接入须经另一个预注册校准和终审决定，FIFO71 原 75 命令门槛保持失败。P 的 admitted Kmap 由本 helper **替代原 point 分支**，不能同时执行两套仿真；其它题与原 phase P 保持相同。这是“严格完整解析 + 全 care 覆盖 + full 反馈”的整个新策略，不能把旧单点/新完整覆盖的差别全归因于反馈展示形式。保持原模型、首提示、8192、唯一修复和 300 秒预算。

本机检查与文件 SHA 留在 `raw_evidence/LOCAL_PREPARATION_RECEIPT.json`。实际模型、EDA、SSH、FIFO、Git 调用均为 0；任何新提分、full 准入与采用资格均未证明。
