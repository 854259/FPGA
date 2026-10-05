# 原生异步复位契约研究校准

状态：固定14项控制和独立生成测试的44项源码/材料已审查并冻结；本机Python3.12.14及云端3.12.3各16方法/82子检查、collector各4方法/13子检查通过，49项工具文件、936任务/35官方文件及模型/其他冻结阶段核验保持。已通过SSH在自己目录完成纯预检；已于2026-10-05 15:31（北京时间）接受为整任务FIFO63，现场queued、monitor3919181/start845913207存活，guard/results尚无；实际编译/仿真与模型调用均为0。`generated_research_test=true`、`original_harness=false`，不替代原 CVDP harness 校准或原官方成绩。

本目录的 `native_reset_contract.py` 与已交付版本同字节，SHA `94bcb3b86b7bf1209c5a2348f9d3da5e9c74136e15f77cbdeeedc838ee5fa43d`。`tool_journal.py` 与已有自然边沿记录器同字节，SHA `ec07a0cb78495de1daee9611fb06e906ff319189fd239a91e41e52f58a67c465`。只读取原 public prompt；完整原题面、全改名题面、控制 RTL、生成 TB 和逐控制 SHA/role/run 绑定放在忽略的 `raw_evidence/`。原数据来源 SHA 为 `cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857`，没有读取隐藏 harness 或答案来构造本研究测试。

每项计划 1 次真实 `iverilog -g2012` 和 1 次真实 `vvp`，共 14 次编译、14 次仿真，0 LLM。固定顺序如下；正确/错误/故意失败全部保留，不因失败、误通过或未知结果删控制。

| 顺序 | 控制 | 必需语义记录与 vvp 退出码 |
|---|---|---|
| 1 | positive | 完整零失配，rc=0 |
| 2 | reset_ignored | 完整语义失配，rc=1 |
| 3 | synchronous_reset | 完整语义失配，rc=1 |
| 4 | history_sync_only | 完整语义失配，rc=1 |
| 5 | clear_rising_only | 完整语义失配，rc=1 |
| 6 | clear_falling_only | 完整语义失配，rc=1 |
| 7 | constant_zero | 完整语义失配，rc=1 |
| 8 | constant_one | 完整语义失配，rc=1 |
| 9 | swapped_edges | 完整语义失配，rc=1 |
| 10 | two_cycle_pulse | 完整语义失配，rc=1 |
| 11 | one_cycle_late | 完整语义失配，rc=1 |
| 12 | negedge_sample | 完整语义失配，rc=1 |
| 13 | failure_propagation | 完整零失配后唯一明确标记并故意 fatal，rc=1 |
| 14 | positive_renamed | 模块与五角色全部改名，完整零失配，rc=0 |

每个生成 TB 仍有 69 观察、138 个双输出实际值。先零输入释放和两个上升沿预热；分别在正/负脉冲仍高且时钟低时异步断言复位，检查从高历史状态复位后零释放，变化/保持及上升/下降相位全部保留。故意失败控制使用正确 RTL，在完整记录和正常语义检查后追加 `OWN_NATIVE_RESET_FAILURE_PROPAGATION` 标记和 fatal；其他 13 份 TB 保持其题面生成语义。忽略复位稿没有初值或额外启动初始化。

`stage.py` 只允许未来冻结的 Linux 路径与资源身份。所有 14 项源码先在全新、自己拥有的 `results/` 中物化；每次编译/仿真前均调用自有资源准入。原样工具记录器保留实际 argv、rc、candidate/TB 输入 SHA、完整编译 blob、每次 stdout/stderr 和工具 trace；standalone 测试没有 Cocotb/XML。阶段从完整 stdout 解析全部 69 观察和首反例，并绑定完整解析文件 SHA。成功前全局确认恰好 28 收据、14+14 次尝试、0 未确认；finally 再计数若异常，撤销 complete/evidence_complete/qualified，写非空 error 并抛出异常，取消待返回的 rc0。工具错误、截止、缺/重工具调用、截断或未知/矛盾退出码停止并保留证据，绝不自动重试。

`audit.py` 从完整 ZIP 清单和冻结 spec 重建上述绑定，包括自己的 guard/resource/cleanup、工具/外层 argv、源码、编译 blob、每份 stdout/stderr、完整双输出观察和反例；不会执行归档源码或工具。独立扫描整个 results 的收据路径和原生收据结构，任何其他目录、改文件名或未知工具记录均拒绝；必须精确为 14 预定目录各一份 iverilog/vvp，并与 actual/attempted 各14、unconfirmed=0、无 journal_count_error 一致。`evidence_complete` 表示完整实际执行链；`qualified_for_generated_control_discrimination` 独立要求所有正确/错误/故意失败控制达到预定结果。错误稿若完整误通过，保留 `false_acceptance=true`，可有完整证据但不能取得控制鉴别资格。

主任务需提供 `RUN_SPEC.json` 的 `cloud_root/kit/inherited_path`、14/14/14/0 调用预算、`stage_timeout_s/native_command_timeout_s`、全部 source hashes、真实工具路径/SHA、完整 toolchain manifest、guard/command dependency hashes、当前模型与 FIFO 身份；提供 `INPUT_MANIFEST.json` 及自己的 `guard/resource_check.json`。依赖的 `paired_checkpoint.py` 必须提供 `check_resource` 和 `owned_command`，由 root 的 wholeFIFO guard 启动，不能直接调用阶段。collector/保护清单/部署包由主任务准备。

纯复现只运行 `test_preparation.py`：Python 3.12.14 的 16 方法、82 子检查通过，0 模型/EDA。合成档案内的 spec、工具收据、身份、blob 都是明确虚构的审计 fixture，没有真实工具运行；它们不能当作 14 次真实编译/仿真结果。当前控制 RTL 只做 ABI/文本区别检查，没有 SystemVerilog 编译验证。真实控制鉴别、模型质量、未见/训练独立、官方 L3、全156资格、断网或单卡32GB验证仍未完成，独立质量准入0、adoption=false。

冻结规格SHA `f4889422e53aa00848e567694d8df5e351c2d79713134ddd543ec638738a4bc3`，44资产；准备ZIP `eb24bf9f38c7e4ec9a45643e413bf7f0f83b91ab5960e13b8cdc1793f0a1a6fa`。主任务补齐自己的guard/collector、完整保护与依赖清单、公有题面精确来源收据和固定14/14/0预算：每条工具命令30秒、阶段1200秒、守卫1300秒、25分钟租约保险。预检只有Python解析/虚构协议控制，未启动原生工具或真实模型；真实结果仍须FIFO运行、全28原生收据和69双输出观察独立审计。

实际队列收据见SUBMISSION.json及LIVE_SNAPSHOT.json。等待FIFO61全量与FIFO62原harness校准结束，按先到先得执行，不绕过队列；第63号是单独研究校准，不称原harness结果或真实模型质量。
