# 原始 edge detector harness 校准准备

状态：主任务已审阅并补强执行证据绑定，11源资产已冻结于 `RUN_SPEC.json`；本机Python3.12.14及云端3.12.3静态检查、49工具/270依赖文件和936任务/35官方保护文件核验通过。已于北京时间14:35按整任务FIFO提交第62号任务，当前确认queued、monitor3870791/start845579592存活；等待第61号完整评测释放整任务资源。实际模型/EDA/原生控制调用均为0；独立模型准入和采用均为false。

原记录为 `cvdp_copilot_edge_detector_0001`，保持原模块 `sync_pos_neg_edge_detector`、三个输入、两个输出及原输出路径 `rtl/sync_pos_neg_edge_detector.sv`。完整原数据集同字节复制到私有 `raw_evidence/ORIGINAL_DATASET.jsonl`，SHA-256 为 `cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857`。`CONTROLS.json` 绑定原 JSON 行、规范记录、prompt/context/output、原四个 harness 文件、test 和 runner 的 SHA；原记录、题面、context、runner 均不修改，源记录没有参考答案。

固定七个控制，每个调用原 runner 的一个 pytest case，计划总计 7 次真实编译和 7 次仿真。控制只用于评价，不向模型提供，不接入生产求解器或按任务 ID 分派的求解检查器。正确稿仅依据公有题面，采用当前输入与延迟一拍采样比较、寄存输出脉冲、低有效异步复位清状态的相位解释。

| 固定次序 | 控制 | 进入原判定器校准所需结果 |
|---|---|---|
| 1 | positive | 通过 |
| 2 | constant_zero | 失败 |
| 3 | constant_one | 失败 |
| 4 | swapped_edges | 失败 |
| 5 | widened_pulse | 失败 |
| 6 | reset_ignored | 失败；原测试可能误通过，须保留 |
| 7 | failure_propagation | 标记断言失败并传播 |

`reset_ignored` 保留正确稿全部正常边沿逻辑，只去掉复位敏感边沿和复位分支；没有 initial 块或寄存器初值，也没有把启动复位当初始化的额外语义。原测试只在启动复位后比较四个脉冲值，既不观察启动期间未知值，也不检查运行期异步复位。它可能接受这个错误稿；**任何错误稿通过都排除该原记录/原 harness，不能用修改后的研究测试替代原成绩。** 唯一改动测试的是标清 `original_harness=false` 的 sentinel：保留正确 RTL，在原测试末尾追加 `OWN_NATURAL_FAILURE_PROPAGATION` 断言。

`stage.py` 和 `audit.py` 由 own55 冻结源调整为一记录/七控制；`tool_journal.py` 与 own55 完全同字节，SHA `ec07a0cb78495de1daee9611fb06e906ff319189fd239a91e41e52f58a67c465`。阶段在原资源准入检查及当前锁/模型/保护文件检查后才运行原 pytest，且准入文件必须属于自己的 `guard/resource_check.json`。透明记录器原样调用真实工具，保留实际 argv、rc、源码输入 SHA、编译 blob、每次新 XML、stdout/stderr；审计从完整档案重新绑定这些证据。失败控制均保留，`summary.passed` 只表示执行证据完整，记录鉴别能力由独立的 `natural_original_harness_calibration` 字段判断。

本机 Python 3.12.14 的纯静态检查结果在 `raw_evidence/STATIC_CHECKS.json`：全部冻结 Python 源、两份原 Python 测试/runner 及 sentinel 可解析，完整 302 行数据与原记录绑定通过；七份 RTL 仅做文本 ABI/结构检查，未经 SystemVerilog 编译或仿真。运行 `static_check.py` 不调用模型、模拟器、网络或队列。源码/工具/依赖/保护清单及运行规格已固定，实际执行仍须通过自己的 FIFO 守卫；不得直接调用阶段或工具记录器。

题面和 harness 已有评价曝光，此准备不证明未见、训练独立、完整规格、官方 Vivado L3、求解质量或断网单卡 32GB 能力。阶段源、审计源和私有控制在冻结后必须保持不变；全 156 和自然模型比较的其他门槛继续保留。

主任务冻结前复查与修正见 `ROOT_REVIEW.json`：完整执行参数、干净子进程环境、资源身份、编译与仿真输入/产物、原XML身份及正常断言退出码均逐项绑定。静态检查不证明真实执行通过；原控制和题面/test/runner未修改。当前实际规格SHA为 `e68dff0e4bab1a708a9617552776e3ed86adcb6d7d53aa6c004c49728707fa65`。
