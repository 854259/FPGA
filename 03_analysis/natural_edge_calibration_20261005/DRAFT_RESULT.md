> 历史准备说明：主任务后续已审阅并冻结11资产，通过双环境静态检查；当前实际状态以README、RUN_SPEC、PREPARATION及Linux收据为准。下面是冻结前作者的记录。

# 准备结果：原边沿 harness 尚未实际运行

已完成：完整原数据集 SHA 验证及私有同字节复制；一条原记录的原模块/全部端口/prompt/context/harness/runner 绑定；正确稿、五份语义错误稿和一份明确标记的断言传播控制；一记录/七控制的 own55 阶段及只读审计适配；工具记录器同字节复用。

本机 3.12.14 纯静态检查通过，记录于 `raw_evidence/STATIC_CHECKS.json`。共解析六份自有 Python 源、原 test/runner，并解析 sentinel 后的测试；文本核对七份 RTL 的原模块及三输入/两输出、固定顺序和 7 个计划原生 case。原数据共 302 行。静态报告明确 `quality_verified=false`、实际原生次数 0；没有 RTL 语义、编译或仿真通过结论。

原记录规范 SHA：`0cabf0a3c97f589d6b52e508325194321e1100044013cdc1a6a0ea274c4a1011`；原 test SHA：`efff9fd2ede0205be0bea5c3aeba32ea006b34e99b794c446359189aa729cb71`；原 runner SHA：`c4fdb8b020a32445c207260464efa2e6ab0006aeb384815b0ff8555a50a9fb7e`。其余原字节 SHA 在私有控制清单与静态报告中。

预期而非实测：正确稿通过，恒 0/恒 1/正负互换/两拍脉冲被检出，sentinel 以指定标记失败。`reset_ignored` 与正常正确边沿流水完全相同，仅不处理 reset 且没有初始化；原测试没有运行期 reset 断言，预计存在误通过风险。若它或任何其他错误稿通过，必须保留原证据并把原记录/原 harness 的校准准入置 false，不能改测试、缩端口、删控制或放宽规则。

仍待：主任务静态审阅、源码/工具/依赖/保护清单冻结、创建实际运行规格、自己的整任务 FIFO 守卫、7 次真实编译/仿真及完整档案终态审计。此目录未创建 RUN_SPEC、actual FIFO 或运行结果；0 模型、0 EDA、0 独立样本、0 采用。注册脉冲相位来自公有规格解释，不是参考答案或原仿真证明。
