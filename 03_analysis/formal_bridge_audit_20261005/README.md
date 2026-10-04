# 接入层终态证据采集与只读核验

目前工具已冻结、安装，10项本机/Linux纯合成边界测试通过；尚未采集/审计实际30或31的终态。合成数据默认禁止进入正式CLI验收，测试显式fixture模式仅验证核验器，不计模型/EDA/质量分或部署。

## 核验范围

同时支持固定v1规格a9b4bb66及v2健康规格b98742b9。采集源码/完整包目录、实际假后端请求、题面派生TB和反例、真实原生日志/receipt、阶段汇总及guard；v2将v1完整ZIP作为依赖一起绑定。完整性检查覆盖源SHA、官方baseline、包额外文件、936任务/35官方受保护身份和模型PID/starttime、空闲/清理/释放。只保存保护清单，不采集比赛参考RTL/TB正文。

v1重新构造改名4位优先契约，独立重算16输入和错误稿12失配，逐项核对两次桥接及两次原始probe的DUT/TB/命令/摘要/日志及反例；将原反馈和两次真实送到假后端的消息精确重建，技能/抽取/预算/trace/最终稿一致才接受。推理仍是假后端，不变成真实模型收益。

v2递归复核v1证据后，确认新增范围只在health与入口，求解/原生反馈/parser/技能/基线保持；复核21 Linux测试日志、两次实际GET健康的模型/显存/就绪字段、一次真实版本命令及现场卡计数。瞬时开发卡观测不当R9700/物理32GB/峰值/独占或断网证书。

## 失败与进程状态

passed采集需要终态guard、正确云目录、所有已记录自有进程已退出或身份已改变；不能只凭JSON complete=true采集仍在写的结果。--failure单独保留失败/缺源证据，失败包永不通过验收。输出ZIP和审计JSON放在新路径，不写旧冻结run、队友、共享模型或实例。

测试覆盖正结构v1及嵌套v2、合成默认拒绝、失败收集但拒绝验收、计数被改、第二请求反馈改写、TB被改且重绑定、包额外模块、32GiB越界/错PID/计数不一致、清理/释放失败、完成JSON但自有进程仍活。第一轮Windows默认编码夹具失败已保留并修成明确UTF-8，未放宽验收，0模型EDA。

72个原字节资产含5份工具、固定旧审计读取器以及两个候选的source-only合成依赖，规格ca1b50b1，准备ZIP0858b3f4；生产run和队列未修改。本机/Linux纯预检10项通过，0模型/EDA，actual_shipping_evidence_audited=false。

## 终态后用法

工具云根：/workspace/team/runs/fpga_owner/formal_bridge_audit_tools_20261005_v1/source/03_analysis/formal_bridge_audit_20261005。输出应先创建自己的新证据目录，位于冻结run之外；已有ZIP/JSON不覆盖。以下流程需要30/31实际终态，现阶段不得把合成测试当完成。

1. collect.py --root /workspace/team/runs/fpga_owner/formal_bridge_20261005_v1 --archive <新v1.zip>
2. audit.py --archive <新v1.zip> --out <新v1审计.json>
3. collect.py --root /workspace/team/runs/fpga_owner/formal_bridge_v2_20261005_v1 --archive <新v2.zip> --prior <已核验v1.zip>
4. audit.py --archive <新v2.zip> --out <新v2审计.json>

发生失败则用collect.py的--failure收集，保留失败身份，不修改冻结源使旧记录通过、不重抽模型。审计器更新必须另记新工具版本/差异和失败证据。

## 现场与剩余要求

05:15全量238/312、已记录250请求、无阶段error，runner3390465/start841229941仍活；队友26/27及自身28～31继续整任务FIFO等待。当前可引用完整分仍为旧A0.7692/C0.7641，部分不发新分。新全量、边沿/FSM、接入/健康均待终态及证据审计；独立自然验证、真实模型正式API、正式镜像断网目标单卡32GB、五样本仍未验收，goal active。
