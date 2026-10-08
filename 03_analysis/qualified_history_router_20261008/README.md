# 复用已验证语义规则的纯组合选择器

原one-hot与串行计时器完整回归分别在143和151获得L3/0模型请求，但各轮完整策略均未通过历史保护和成本门，仍保持拒绝。本次只复用各自完整题面规则，不相加跨轮分数，不从旧答案或题号派发。

`selector.select(prompt, interface, providers)`把原始两字符串传给分别冻结、独立准入的producer。只有唯一完整recipe且输入、RTL、contract哈希与声明一致时，原样返回该recipe；多重匹配即使RTL相同也弃权，任何残缺或不一致记录也弃权。调用方仍须保留原worker/compile/判题及原预算；此模块没有接入完整worker。provider列表由调用方可信源码配置，receipt自报零调用不能替代独立来源/执行证据，producer异常直接传播，不静默变成成功。

AMD新增22模拟组合控制及2原自然输入的组合上下文通过，两个生产器源码逐字保持，所选recipe与原档案完全相同，逆序也相同。仅检查两个已有自然输入，不是全156组合覆盖，更不是新native或得分。原native/纯算法/worker/156 intake均不重跑；0新模型/EDA/FIFO。实际40秒受限进程exec0/reaped、独立child退休，19成员原件档案逐项AMD/E绑定。原122、peer123冻结源、共享模型及PRIMARY两文件保持。

onehot源码fc1af52c与timer源码9080c49a由原109/110私有完整档案物化，公开仅放本次selector、模拟控制与摘要。两个原producer和私有自然题面/recipe不复制到本目录；此目录不是独立部署包。既有公开接口见`../onehot_cp_adapter_20261007/synthesis.py`及`../serial_timer_cp_adapter_20261007/worker.py`，真实来源以PUBLIC_RESULT绑定为准。

下一步先核对已有intake的路由交集和完整worker来源接线，再决定必要的新组合筛选。尚未入队、未授全156或采用资格，目标120/156且加权80%仍未达；peer继续持123/三臂与终态，root下一既定模型任务仍为PR166两题诊断。
