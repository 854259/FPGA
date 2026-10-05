# 完整组合题面表格直接生成 RTL：未冻结草案

这是一个新生成策略的纯 prototype，不是已实测提分、正式接入或部署。输入只有完整题面字符串和可选接口字符串；没有题号、旧答案、候选、参考答案、TB、判定、路径、模型、网络或原生工具输入。生产函数不读取任何数据集。

contract.py 保持原 sealed parser 字节，SHA256 为 46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206。reserved_keywords.py 保持当前 phase P 的关键词事实源字节。synthesis.synthesize(prompt, interface="") 只对 parser 完整消费、明确组合行为的 Kmap 或完整组合波形返回 canonical case RTL。更宽的“仅 simulation waveform”模板仍显式弃权，不能从完整有限观测证明没有题面未提及的隐藏状态。单独非空 interface 暂弃权，避免忽略矛盾、额外输出或端口宽度。

范围最多四个输入位、一个标量输出。所有端口的原名字、方向、宽度及声明顺序保留；向量高低位按明确下标绑定。格子覆盖全部二进制输入域，标签按题面值而非固定 Gray 顺序绑定；重复/缺失/重叠轴、超界下标、X/Z care 输出、额外输出、状态/时钟/复位、未消费文字、关键词端口与全 don't-care 均弃权。显式允许任意值的 don't-care 格选择零并如实记录，未知 care 不补零；非二进制输入默认输出 X，没有把它们伪装成已证明的表格义务。

这条分支不使用 FIFO71 未准入的 native 反馈或它的仿真返回码。FIFO71 五个 sentinel 真 rc=0 导致失败传播门槛失败，这个失败保持。表格转换可作为独立生成因子，经新的正负控制和原正式 judge 验证；本地纯测试只能证明字符串与数据绑定，不证明 native 执行或官方 L3。

真实接入应只在新研究 worker 的 P 分支、加载原 phase P runtime 前调用该纯函数。emitted 时记录零模型请求、空 requests journal、完整 prompt/contract/RTL SHA、emit receipt、绝对原 300 秒截止；不创建伪 HTTP request 或 response，不借用 C 首稿，不把确定性生成样本称为全新模型样本。弃权时原 phase P 路径保持，最多两次真实请求/8192 token。新 stage/auditor 必须针对已绑定生成分支严格验证 journal=0 与所有证明，而其它行仍要求 1–2 次真实请求；原 auditor 与冻结文件不可放松或覆盖。

下一步是原判定的独立小对照及全量审计，不承诺净收益。开发集实际覆盖和逐题证据另存根任务指定的私有 review 文件。
