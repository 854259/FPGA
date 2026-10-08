# 五题波形恢复诊断：已真实准备，尚未入队或测分

C/P 都保留完整 table＋onehot/timer；仅 P 在模型第一次用户请求中加入原105波形事实，repair 保持原请求。固定001/057/143/145/151五题，目标核验145恢复及共同机械策略和通用对照保持。本试验不包含 CP8；已独立排队的125不受影响，旧成绩不相加。

AMD worker新增6机械模拟上下文、2原baseline/runtime模拟上下文及1传输失败上下文通过。来源/评分v2新增10正向/10拒绝、2合成评分正向/12元数据拒绝/5门槛拒绝通过。v1因合成repair遗漏原提取器换行而失败，140原件16526e3a完整保留；v2仅修测试夹具，生产proof及原replay未改。旧套件/native/intake没有重跑，模拟检查不授新native资格。

真实prepare在AMD约2.920秒exec0/reaped并独立退休，143源冻结fc00d930；155成员34f3d35f、211成员79f96bb4及旧worker/失败档案均AMD/E逐项绑定。公开生产源码与实际freeze逐字一致，新增测试分别绑定实际worker/v2 controls。001/145两臂首请求在新包重建并与原105绑定，仅P145改变；容量依据复用旧首请求usage，没有新tokenization，也不声称所有repair容量已证明。

原8192/max2/repair1/零重试/300/300/360保持；10输出/max20请求、路线结构上限8、21保护。7200/7600/130只是stage/guard/slot安全上限。五个P都L3、无配对回退、原113历史及同级逐题/总请求成本门槛必须通过；这五题不授全156或采用资格。

目前prepared，queued/score/full156/adoption均false。下一步由root审查PR并唯一FIFO提交。原始题面、模型wire/usage/scope、输出、fixture和完整冻结规格留在私有档案；此目录是公开来源索引，不是可脱离私有冻结目录运行的安装包。适配metadata中的draft标志是原字节历史记录；本次真实状态以PUBLIC_RESULT为准。
