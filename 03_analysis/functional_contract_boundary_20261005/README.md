# 标识符边界修正与复查

队友R1的4275个冻结输入、16个真实Vivado语法证据和保护清理收据只读归档逐SHA核对。复现旧4047个误接受，修正后0误接受/0错误弃权；114个有效接口契约与TB字节保持，额外6944个两类parser保留字及合法大写检查通过。此前八个真实校准契约和TB完整不变。本地0模型/EDA，未改队友工作，也未重跑其16个检查。

保留字采用248项静态集，关键词匹配区分大小写；移位selector说明与端口角色必须同大小写。基础122项来源[AMD UG901](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/Verilog-Reserved-Keywords)，另126项按语言标志从[主项目lexer源码](https://raw.githubusercontent.com/steveicarus/iverilog/master/lexor_keyword.gperf)提取；未运行该外部编译器，EDA仍只用Vivado。来源身份见KEYWORD_SOURCES.json。

原19移位probe/6综合校准仍有效；旧parser只在那几个已校准接口上有效，扩大准入前的边界风险现已修正。RESULTS.json是词法边界结果，不是独立自然题、模型修复分或完整回归。

全部156个已冻结公开题面只读覆盖统计：优先规则支持071、112，移位支持115；其余153个保持原流程。COVERAGE.json绑定完整题面哈希，0模型/EDA。这说明当前候选覆盖很窄，不能据三题改善声称隐藏题泛化或国一门槛；后续需要独立验证与其它错误机制。

v1新生成包因路径问题在安装前拒绝，v2安装自检完成但在推理前因本边界问题拒绝；均0真实模型/EDA且不入队。v3独立冻结修正parser、关键词集和本复查结果，所有推理/判定/反馈脚本与v2相同；原件不改。
