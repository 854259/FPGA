# 独立表格测试观察器草稿

这份未冻结草稿只动态加载既有 team_coordination.py，强制核对 SHA256 为
71c6c8490c201a37ded586d2c3a898d3651b2aec917babaf8ef8b062a5449b30，
在所加载模块的 RUN_SCHEMAS 中加入 table_synthesis_pilot_v1。
磁盘上的原工具、实验源、现有 plan 与 watcher 均没有修改或启动。

旧 CLI 的 publish/watch/ack/check 及其参数原样转发，卡仍为
team_coordination_v1；原命名空间检查、锁、原子写入、最长 14 小时、
终态停止条件和当前 revision ACK 逻辑沿用。
额外参数 --base-tool 必须给出原工具的实际路径，安装位置无需硬编码。

示例形式（此草稿没有执行任何 watch 或共享发布）：

~~~text
python -B table_coordination_wrapper.py --base-tool <原工具绝对路径> check --ledger-root <共享日志根>
python -B table_coordination_wrapper.py --base-tool <原工具绝对路径> watch --owner fpga_owner --plan <已批准plan绝对路径> --stop-ticket <新table票号>
~~~

同一 owner 的原观察器和新观察器都写同一张卡，所有权锁仅保证一次写入互斥；
同时运行两版观察器可能使后写的旧卡覆盖新版附加字段。安装方应安排该 owner
的唯一卡写入者；本草稿没有停止老进程、释放 FIFO 或修改共享 plan。

## 新测试显示

原 CURRENT_WORK.md 显示 n/28 完成输出及原阶段状态；
卡中的新 table run 附加字段与独立 TABLE_PROGRESS.md 显示：

- actual_model_requests：绑定摘要报告的整个阶段调用数，允许真实零值；未拿到
  有效摘要时为 null，不会把完成行数或回复数当作调用数。
- completed_row_model_requests、completed_row_requests_by_arm：
  只统计已经完成并落入摘要的行。
- unrepresented_model_requests：阶段总调用数减去已完成行调用数。真实 stage
  先持久化 worker journal 成本，再追加 row，运行中或失败后可有此差额。
- execution_state：pending/running/terminal/unknown。
- quality_conclusion：运行中 pending，阶段结束或票终态
  pending_terminal_audit。terminal_quality_result_observed 恒为 false。

只有冻规格 SHA、ticket/cwd、摘要 schema/SHA 绑定均通过后才读取新字段；
规格必须为 14 个不同 task、两臂 C/P、28 输出。摘要 rows 须为冻结 stage 的
交错顺序前缀；row 模型路线必须记录 1–2 次调用，机械路线须为 P 且记录零调用。
成功完成阶段还须 28/28 且 rows 调用总数等于阶段总数。
规格或 ticket 不匹配、缺数据、计数无效、快照变化均显示未知或观察错误。

这些检查验证观察数据内部一致性，**不会证明机械零调用来源真实**。严格
prompt/interface/source/recipe、空请求档案、监督编译及原判定绑定仍由原终态
审计完成。此处明确标注 stage_reported_not_audited，不显示分数、提高量，
不从 passed/screening_eligible 推断质量通过，也不读取实验私有档案发布成绩。
正常编译或语义不通过仍可形成真实 stage 行；观察器不会把正常负结果当工具故障。

TABLE_PROGRESS.md 是原 publish 完成后，重新取得同一 owner 的锁写入的派生文件；
卡为主要观测快照，派生显示有极短独立写入窗口。原 STATUS.md/SNAPSHOT.json、
peer 命名空间及 ACK 记录不受修改。提醒是否已确认由原 check 读取原 revision
收据决定，不产生自动 ACK。

## 本地隔离验证

test_table_coordination_wrapper.py 使用系统临时目录作为 runs/tickets/ledger，
不触及真实共享记录，没有 HTTP、模型、EDA、云端或 watcher。
本地测试默认寻找工作区原工具；异地安装后测试须通过
TEAM_COORDINATION_BASE_TOOL 环境变量显式指定原工具绝对路径，仍校验同一 SHA。
覆盖旧源 hash/唯一 schema 扩展、28 输出与真实调用数的区别、prefix 调用成本、
阶段失败、排队缺摘要、无效调用与非法机械零值、ticket/spec/source 绑定、
快照变化、旧 schema、peer/主状态保留、pending/已确认/新 revision ACK 和 CLI 转发。

真实阅读依据：既有工具和原 6 个测试、旧本地 OWNER_PLAN，以及新 table v2
pilot.py/metrics.py/prepare.py/audit.py。读取时 v2 尚无 RUN_SPEC；测试只构造隔离
fixture，不把未准备或未运行状态表示为已完成。没有读取云端数据。
