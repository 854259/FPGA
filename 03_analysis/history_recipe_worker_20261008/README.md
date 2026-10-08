# 组合题面规则的完整worker接线

本轮把PR168唯一完整recipe选择接入原onehot worker的完整生成/编译/反馈框架。P固定调用两个原producer，只按原prompt/interface选择；C不调用selector。未命中、冲突或残缺返回原common phase-P baseline；命中原样保留producer recipe和RTL，绑定selector、两个producer、实际选中者与完整selection。原一次编译、原反馈及零模型机械路径不变，不增加修复。逐步骤位置及全字节SHA可逆恢复原worker，包括显式CRLF→LF物化步骤；baseline/runtime/skills保持原字节。

AMD新增12完整wrapper上下文通过，HTTP/编译/common worker模拟。另以实际原baseline/runtime/skills执行6新fallback上下文与1传输失败上下文：首次和repair wire在C/P逐字一致、8192/max2/repair1/原system保持，未确认调用只保留一次且不重抽。第二组仅HTTP/native/功能probe/活动模拟，不能当真实模型/EDA或新native资格。旧test方法、原解析/native/156 intake不重跑；新67/200原件ZIP分别c27f1737/983ea44c已AMD/E逐项绑定，两个受限进程exec0/reaped并另读退休。

复用原109/110各156个P生成路线记录与相同INPUT_MANIFEST：原onehot仅143、timer仅151，两集合不交叉。这是旧独立运行的元数据合并，不是新组合156执行，也不相加分数。复查原105发现已修正68312067波形端点澄清曾将145从C L1恢复到P L3、均1请求；原105整体仍拒绝，其波形因素没有加入本worker。保留端点不排除隐藏边沿的限制，避免重新发明三道历史题已有的成功机制。

本目录是AMD物化bundle中源码快照。完整bundle还需原common runtime/skills、PR168 selector、两个逐字producer与旧测试fixture；公开不含私有自然输入、recipe/RTL或原始日志。此处未准备评分stage、生成/完整归档审计或新组合native准入，不能直接部署、授全156或采用；尚无新分数。peer继续持123/三臂及原终态，root下一既定模型任务仍为PR166两题诊断。后续依据123实审结果规划必要的单因素叠加筛选，保留原历史113/配对/逐题及总请求成本门，目标120/.80 ACTIVE。
