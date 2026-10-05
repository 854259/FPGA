# 5 个显式 Kmap 的零模型校准准备（尚未冻结/执行）

固定输入为 050、057、113、122、125 的原始完整题面，仅从已结束旧 full156 档案的 `prompt.txt` 成员复制并逐 SHA 绑定。控制生成器不读取参考实现、官方 TB 或答案。每题固定顺序为 positive、constant0、constant1、single_cell、sentinel，共 25 个控制。输入、生成控制 RTL 和研究 TB 原文均在私有 `raw_evidence`，不发布、不进入未来 worker 的模型请求。

positive 按所有 cared 格生成组合逻辑；constant0/1 应产生正失配，题面的 cared 格必须同时包含零与一才能校准；single_cell 只翻转第一个 cared 格，预期恰一个失配。don't-care 不施加输出义务。sentinel 使用 positive RTL，在原 TB 完整观测和结束 summary 之后打印绑定标记，再 `$fatal`；必须同时获得完整零失配观测和实际非零 xsim 返回码才能证明失败传播。若真实工具仍返回零，完整测量保留，但控制鉴别失败。

`contract.py`、`render.py` 是已封口原字节副本；`guard_wrapper.py` 直接复用既有保护包装器，`collect_evidence.py` 原字节复用 phase collector。stage 直接调用既有 `paired_checkpoint.check_resource/owned_command`，编译环境检查沿用 phase 工具的安装位置、PATH 和 scoped udev stub 检查，并增加冻结 entry/library SHA 与环境绑定。native-reset collector 硬编码 14×2，故没有用于新的 25×3 计数。

准备命令只生成私有材料和 `PREPARATION_RECEIPT.json`，不写 `RUN_SPEC.json`、不提交队列。当前所有测试是本机纯测试，synthetic native stdout/receipt 不能作为实际运行证据。stage 缺少 RUN_SPEC 时会在任何 prctl、子进程或工具调用之前拒绝。当前新增模型、EDA、SSH、FIFO、Git 操作均为零，尚无实际提分或正式 TB 资格。

根任务下一轮审查后才可冻结和安排整任务 FIFO，不能绕过已运行/排队任务。根需提供 schema=`prompt_table_generated_calibration_frozen_v1`；精确 `cloud_root/kit`、25 控制/每工具25/0模型预算、`source_hashes`（按 `controls.source_paths` 完整集合）、`preparation_receipt_sha256`、既有 dependency path/hash、实际 compiler_tools、vivado_bin/udev_stub、完整 udev_files、PATH/VIVADO_BIN/LD_LIBRARY_PATH 三项 compiler_env、当前 model_identity、protected 快照、slot_owner/slot_lock_path/llm_base_url/model_name、正的 native_command_timeout_s 和留有 cleanup reserve 的 stage_timeout_s。现有环境回执只供绑定和审查，不替代新 guard 的即时准入。

每个控制在新目录依次真实执行 xvlog、xelab、xsim，必须获得 75 条逐 argv/cwd/source/compiler/env/resource/spec/log SHA/真实返回码绑定的收据；attempt 在执行前落盘。编译或展开失败保留真实返回码和日志，不能算成语义负控制成功，也不重试。完整观测中的未知 X/Z、缺行、重复或绑定错误保留错误并阻止资格，不生成反馈。

audit 独立盘点全档案的 native receipts，包括 summary 未列出的额外成员，要求唯一 25×3 的实际命令、无 pending/未确认、源和依赖未变、compiler 环境绑定，以及 guard 证明模型/保护文件未变、owned cleanup 完成和自己槽已释放。测量完整与控制鉴别分开：完整但识别失败可以封存，不转成成功；单点只认恰一个 cared 失配。研究 TB 始终 `original_harness=false`。控制校准不能替代 parser admission、first/full 鲜样本收益、原官方得分、独立评测或采用资格。
