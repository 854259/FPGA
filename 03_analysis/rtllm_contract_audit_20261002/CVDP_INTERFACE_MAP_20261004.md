# CVDP complete runner/interface map

## 2026-10-05 S3：共同模块名转换前测冻结

前置：复用原302条入口映射和原工具安装，不重复AST全扫描或45个随机入口回放。官方baseline/候选的固定TopModule与来源原名冲突尚未解决；本阶段只建立评测侧的严格转换边界，不改三个求解臂的代码、技能、参考或测试台。

先冻结`cvdp_name_binding_20261005.py`再运行。题面转换仅接受`module NAME`、`module named NAME`、`Module name: NAME`的明确名称槽（允许一致的反引号/双引号）；标识符大小写保持，目标名已经出现、名称另用于端口/常量/文件名或无法判明用途时一律弃权。不进行全局英文词替换、不追加冲突标签。反向映射候选仅改唯一TopModule声明的标识符；正文、端口、注释、字符串字节保持。重名、层次/递归同名引用、宏、转义标识符等不可靠结构拒绝。尚未接入真实求解/判定链。

固定12个构造题面往返控制、20个拒绝控制，及1/8/17/64位×组合/时序共8个构造RTL原名/规范名配对，各执行5个预定向量；16次Icarus编译与16次仿真，必须全部通过、仿真输出完全一致且源码反向恢复逐字节相同。控制通过之后才按已有167条无输入/单输出且入口已解析的固定结构名单应用一次，完整保留302分母、135未尝试结构及所有弃权原因。没有通过数量门槛，不依据覆盖率追加规则。

0真实/假模型调用，0自然题RTL生成/仿真，0参考读取或测试台执行。现有Icarus完整49文件哈希验证，源码/关键词表/私有入口清单/原数据均固定SHA；AMD新隔离目录、FIFO/nohup/resource_guard，阶段300秒/槽10分钟，单工具15秒，任何构造控制失败即停止数据应用并保存现场。模型与正式部署保持。

完整逐条转换题面仅保留私有；公版只发源码、控制与汇总。名称可逆不能证明题意等价、oracle可靠或来源独立，不增加有效独立题数，不允许直接开始CVDP模型评分。全部302参考仍为空；后续必须分别补合同、正负控、家族/接触和完整预算。该阶段是接口准入前测，不能称用户要求的完整批次。

2026-10-04, frozen source95939335b98e4f5634c0f89aa6a5a16a87f8aed1. AMD driver3043491/stage3043496 completed; static mapping1.405981s, guard1.503581s; zero model/EDA/test-code execution. Public receipt: `CVDP_INTERFACE_MAP_RESULT_20261004.json`.

All302 runner test modules, HDL tops and declared source paths resolved under the limited AST mapping. All302 use non-TopModule tops;24 such names do not occur as exact tokens in their prompts. There are167 no-input/single-output records across139 name families, including16 with an undisclosed exact top name. Excluding three name-only RTLLM collisions would leave166/138; this is not an admitted or frozen validation set. Naming alone does not establish semantic independence.

Following actual runner entrypoints yields13 nonempty duplicate test-source groups/26 records, all within name families. The earlier filename-prefix method yielded12/24 after empty maps were excluded; its original evidence is retained. All810 Python files parse; this is not an import, runtime or functional certification. References remain empty. Independent admitted designs remain zero. Fair interfaces for all three arms and validated oracles are unresolved; do not change the candidate to fit this dataset.

Private archive INTERFACE_EVIDENCE.zip SHA179897cfc120b2dc4c98caed061526bc0080c75b66db194085633bfef713b0d8 and11 internal files verified locally; public projection SHAcb33381404f80e6b90887bfb5ffd9a362a4510ae05d953885317d0c08d91d3a0. Raw private inventory stays outside GitHub. The hash-verified local and AMD source transfer TARs were removed after archive verification; original sources, logs and evidence remain.

Sample-adequacy planning, not an adoption threshold or observed result: with zero harms among N independent originally-correct designs, the exact one-sided95% upper bound is 1-0.05^(1/N): N139 gives2.1321%, N178 gives1.6689%; at least299 would be needed for below1%. Repeated generations do not supply independent designs. These total source-family counts are not counts of eligible correct designs. Quality deltas and paired uncertainty must still be reported without treating finite zero-harm observations as safety proof.
