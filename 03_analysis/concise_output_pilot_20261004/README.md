# 完整源码、无注释输出：单因素小实验

状态：本地准备并冻结，尚未调用真实模型或EDA；必须先完成当前156题A/C全量及审计，再通过整任务FIFO运行。它是成本／截断候选，不是已验证的功能修复或交付配置。

前278样本审计绑定盘点发现：A的8道题回复≥2000字符且注释字符比例>50%，其中5道最终L3；最长一份6421输出token、约220秒。C/086首回复8192token截断，随后一次请求未返回即达300秒。字符比例不是思考token统计，不能据此证明禁止注释必然提升质量或速度。

只在C的原generation技能末尾增加：`Output complete synthesizable source code only. Do not emit comments, explanations, or reasoning in the answer.` 原技能全部功能规则保留，repair技能、runtime22e322、baseline抽取、温度0、8192输出上限及整题300秒全部保持。两臂都走原抽取／普通复查，**不启用helper追加**。未加入功能清单、按题答案、参考或测试台；当前服务器聊天模板不变。

选择规则在新生成前冻结：前139道A样本中全部8道满足上述注释阈值的题，加017/033/085/123四份原正确稿守卫，共12题24样本，各最多一次普通修复、总请求尝试上限48。两臂独立真实首生成，按题交错顺序，不回放或重抽。12题均为已知开发材料；改参数或重命名不称独立盲测。控制采用固定官方judge正稿L3／语法负稿L0，不称独立功能控制覆盖。

事前门槛：全部24完成、0工具错误／未确认请求；无A-L3/C<3；C平均系数不低于A、已收回复数不高于A；累计已收回复输出token至少下降20%，实际求解累计时间至少下降10%。通过仅允许继续156题完整回归，不自动部署；未满足即停止扩大这一写法。一次观测含缓存和推理波动，不称稳定提速。外部judge时间与内部求解分开，正式HTTP入口和单卡32GB尚未验收。

6项本地假传输／假编译边界检查通过：两个arm的真实worker控制流仅收到题面；C实际系统消息包含追加要求；缺helper时双方仍进入第二次原复查，第二轮收到原候选诊断；原抽取保留；已有锁拒绝／停止标记均不启动模型。它们不是RTL正确性实验。数据文件见PREPARATION_RECEIPT，15资产／936输入／35官方文件及原依赖已固定；审计器完整24分支尚待真实结果验证。

启动采用同目录evaluate_batch.py queue，继承正确的MODEL_NAME、LLM_BASE_URL、VIVADO_BIN、RTL_REPAIRS=1环境；先核验RUN_SPEC及前置全量审计，再通过服务器task_fifo.py submit登记独立任务，completion-json指向queue_status.json，slot-owner-prefix为fpga_owner_concise_output_。保留内层双锁、不更改共享模型，自己的STOP_AFTER_CURRENT仅在样本间停止。

结束用本目录collect_evidence.py采集新ZIP，再运行audit.py；所有SHA和原始请求／响应／编译／判定绑定。审计仅输出12题诊断均值，full_round_complete恒为false，不与旧156分或baseline拼接。原始ZIP不入Git，只留自己的云目录及本地raw_evidence。
