# FSM校准观察器扩展v2：未执行准备稿

本v2命名空间保留v1的完整3源副本，仅修正测试夹具名称：self.run_card替代
self.run，hasattr也检查run_card，避免覆盖unittest.TestCase.run。root实际AMD
预检报告旧v1的14方法全部ERROR；原v1源码及失败process不覆盖。生产wrapper字节
完全保持，14测试方法数量保持；本v2尚未执行，待root在AMD重新预检。

此目录只新增3个准备源：fsm_coordination_wrapper.py、必要的14个合成元数据门
测试和本说明。没有改原table扩展3源、原base工具或新校准6源；没有启动watcher、
发布共享卡、操作云/FIFO、调用模型/EDA、执行本机项目代码/import/mock或测试。
实际安装、AMD纯检查、独立branch/PR/review/merge和唯一自有观察器切换由root负责。
新校准FIFO票号尚未知；代码和说明没有指定任何真实未来票号。测试ticket99仅为FAKE。

扩展先核对sealed table wrapper SHA
012370da40913ba32b26fc129e03dd524a419d803f7b43e02b88bc72ae6775db
与base SHA
71c6c8490c201a37ded586d2c3a898d3651b2aec917babaf8ef8b062a5449b30，
再动态加载这两层。所有非FSM frozen schema按原table层原样delegation；80稳定性
和83表格观察的字段、格式、MODEL route统计和TABLE_PROGRESS.md不改。新卡仍为
team_coordination_v1，原命名空间、owner锁、CURRENT_WORK.md、PROBLEMS.md、
REVIEW_REQUIRED.md、revision绑定ACK/check、最长14小时和终态停止规则保留。

FSM独立分支识别fsm_native_calibration_frozen_v2，避免原base强索引summary.passed
与FSM summary不兼容。必须通过票号/cwd、RUN_SPEC SHA、实际root、CASE_PLAN source
SHA和固定scope绑定后，才显示新计数。scope为38控制行、105原生工具调用
（xvlog36/xelab35/xsim34）、另2 owned supervisor probes、107 owned commands、
模型计划0。控制kind/顺序与107条命令顺序必须为被冻结CASE_PLAN的完整或前缀范围。

运行中读取已落盘ROW和最后连续progress快照；原stage先记命令成本再落ROW，所以
允许当前progress.completed_rows与已完成ROW数差0或1。控制行数、原生工具调用数
和监督探针始终分别统计，不把38行当38次模型调用，也不把107命令当107控制。
没有有效阶段记录时，调用数为null；实际模型0仅标注stage_reported_not_audited。
失败后的unconfirmed attempts保留为独立阶段记录，不能冒充已确认成本或零成本。

终态读取fsm_native_calibration_measurement_v2。reported_stage_native_qualified和
reported_stage_evidence_complete只显示阶段自报声明。无论summary是否qualified，
native_qualification/quality_conclusion都等待pending_terminal_audit；
terminal_quality_result_observed始终false。不解析成绩、不自动verified_bounded、
不替队友ACK、不采用质量结论、不把有限校准转换成全量能力收益。实际资格由原档案
审计另行决定。snapshot变化、未知控制行、计数不合法、CASE_PLAN丢失绑定或跨owner
票据均fail closed为unknown/观察错误，并清空未绑定计数及阶段资格声明。

发布时只在原publish完成后，重新取得同一owner锁，新增派生FSM_NATIVE_PROGRESS.md。
主要卡与派生显示之间有短独立写入窗口，沿用旧TABLE_PROGRESS.md的方式。该owner
必须只有一个实际writer；锁不能消除两版watcher轮流覆盖卡的问题。root切换前须
核实自己的旧observer PID/start/cmd，不能结束队友/共享模型进程、改变FIFO或自动ACK。
原STATUS.md/SNAPSHOT.json和peer目录不写入。

AMD纯检查（14方法尚未运行；FAKE元数据不证明RTL能力）：

```text
python3.12 -B <new-source-root>/test_fsm_coordination_wrapper.py --table-wrapper <sealed-table-wrapper> --base-tool <sealed-base-tool>
```

测试覆盖pin-before-import、排队未知成本、运行中ROW/command先后、终态阶段声明
不能提升资格、失败成本/未确认尝试、非法模型/native/probe计数、非前缀/冻结plan
丢失绑定、跨namespace票/root、快照变化清空声明、peer/主状态/待ACK保留、旧80/83
精确delegation、票失败无summary、CLI原样转发。没有真实HTTP/watcher/云/模型/EDA。

以下仅为未来安装方的形式，不代表已经调用；stop-ticket必须用root实际确认的新票：

```text
python3.12 -B <new-source-root>/fsm_coordination_wrapper.py --table-wrapper <sealed-table-wrapper> --base-tool <sealed-base-tool> check --ledger-root <shared-ledger>
python3.12 -B <new-source-root>/fsm_coordination_wrapper.py --table-wrapper <sealed-table-wrapper> --base-tool <sealed-base-tool> watch --owner <own-member> --plan <approved-owner-plan> --stop-ticket <actual-owned-ticket>
```
