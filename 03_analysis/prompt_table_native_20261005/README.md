# 显式 Kmap 全 care 原生检查：待真实校准

本目录 `contract.py` 是上一阶段封口源的原字节副本，SHA256 `46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206`。解析器能够接收的 waveform 在本阶段仍拒绝：只支持 `kind=karnaugh_map`、显式完整 cared truth table。没有任务 ID 选择逻辑、答案/TB 输入、复位/初值推断、DUT 生成或额外模型请求。

三个纯函数供后续受控接入：

- `render_tb(prompt, case_id)` 返回自包含 `R2Probe` 检查 TB。TopModule 原端口名和宽度保持；各输入按原声明及下标逐 bit 设置，每个 cared 格等待 1ns 后动态打印全部输入 bit、expected、observed。don't-care 不作为零值检查，完全无 cared 义务则拒绝。
- `parse_observations(prompt, case_id, log)` 重新从完整题面派生契约，要求唯一 `TABLE_BINDING` 的题面/契约 SHA、全部 cared 行和唯一结束 summary。每行的编号、输入位名/顺序/实际值和 expected 必须精确绑定；缺行、重复、乱序、X/Z、未知输入或统计不符均抛 `ValueError`，不能成为语义反馈。
- `make_feedback(prompt, case_id, log, mode)` 只对同一份完整、验证过的失败日志返回 `first` 或 `full` 文本。first 也必须先验证所有行；full 包含通过及失败格的实际观测。全对返回 `None`，异常不生成反馈。两个形式改变展示的观测行数，不改变契约或重新执行仿真。

已读取 `03_analysis/ross_diagnostic_repair_20261004/probe_runner.py` 的 `_parse_summary` 和原 map renderer。现有结束标记实际是 `R2_PROBE_RESULT task=... checks=... mismatches=...`，不是 `R2_PROBE_SUMMARY`；本 TB 保持该格式、`R2Probe` 顶层名和 1ns/1ps 时间精度。其原 runner 的 `TASK_CHECKS` 是固定三题表，本目录不会修改它；后续 caller 须将新 contract checks 显式绑定到自己的冻结运行规则。

这些函数只验证字符串和生成检查代码，没有原生执行、阶段收据、许可/启动/超时处理。调用方须先证明 xvlog/xelab/xsim 零错误完整结束、输入文件/源 SHA 没变化，再使用日志结果；日志本身的一致性不能证明执行来源。纯测试中的 simulator stdout 明确为 synthetic，不作为真实 native evidence，也不代替官方 TB 或得分。

本阶段没有 worker/stage/guard/collector 或部署。真实多负控制和 first/full 反馈校准由后续受控任务执行；此前单点表格修复 1/3 的失败仍保留。原 parser 目录及其它冻结源保持封口。本地测试使用固定 Python 3.12.14、`python -m unittest test_render.py`，0 模型/EDA/cloud/FIFO。
