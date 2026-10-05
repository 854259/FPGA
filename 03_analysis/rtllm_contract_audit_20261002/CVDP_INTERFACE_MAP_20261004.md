## S7 实测结论（2026-10-05 09:16）

2026-10-05 09:16：S7误接纳诊断已完成，固定fe234c9/票43/阶段PID3691977。原测试把恒零、恒一两个确定错误设计均判通过；显式失败控制正常传回cocotb→pytest→监督器，确认缺少功能断言导致假通过。一个开发诊断家族、3编译/3仿真/0模型，阶段2.566秒、守卫2.758秒；不是修复数/准确率或完整批次。46文件ZIP 296359d8abfec37ea8f545f8630ca564cbd28964975ce9ab62e877e448b9e4bf 双端核验，3仿真产物及双端传输ZIP清理，源文件/失败/日志完整、模型/保护文件/进程清理/槽释放正常。S6的54/54静态审查保持：21阻塞、33仍缺控制/覆盖，独立准入0。停止将该原包扩展为独立主基准，不针对坏测试调求解器。下一步先只读核验另一归属已完成票42的边沿反馈正信号：首次回复可比性、实际触发/收益与成本；不重复启动、不把单样本正例当五样本或泛化。完整全包含批次、独立材料及32GB交付仍未完成。

## 2026-10-05 S7：固定误接纳与失败传播诊断（执行前冻结）

S6的54项审查全部结束，独立准入仍为0。S7只把“原测试仅记录输出、没有功能断言”的静态发现转为可复现实测：在私有评测侧使用一个已诊断编码器家族，固定三个控制，顺序为原测试末尾显式失败、原测试＋恒零输出、原测试＋恒一输出。两常量设计在固定三抽头奇偶生成多项式的稳态0/1输入下必有错误；判断不依赖未明确的复位惯例。原数据源不修改，后两组原测试与runner逐字节保持；第一组仅私有副本增加固定失败哨兵，验证cocotb→pytest→监督器的失败传播。

先冻结全三组源码及测试哈希，再执行；私有冻结SHA `710a97e43c19600c4793659897b7d60d834dc940d025d6ed414d415120c74651`。共享工具49文件、Python270文件及配对子进程监督器执行前后核验。最多3编译/3仿真、0模型，单命令60秒、阶段300秒、资源槽10分钟。执行必须走现有AMD FIFO/nohup和资源守卫；不安装依赖、不修改模型、候选或正式部署。哈希、资源、超时、缺少真实仿真/XML或失败传播控制异常立即停止并保存现场，不重试挑结果。

预期若失败哨兵被正确拒绝、两错误常量仍通过，则确认原测试存在误接纳；这不是修复数、模型成绩或泛化证据。即使两负控均拒绝，也不能推出完整功能覆盖。只报告一个开发诊断家族的三控制，不扩大独立样本量。完成后双端核验私有归档，清理本次可重建仿真产物，公开汇总；原包停止原样晋级，不继续靠扩张缺陷数据集填充完整批次。

# CVDP complete runner/interface map

## 2026-10-05 08:26 S5终态与S6合同审查冻结

S5已实证原规则会改变规范中的字符串常量：原实现通过，按被改变的规范实现后仅回映射声明会因LITERAL_CHANGED失败。收窄规则弃权；12往返、24拒绝与8原名/规范名RTL对照通过，19编译19仿真、0模型/自然题EDA，0.346094秒。固定167项中54机械可逆、113弃权；不可将54当有效独立题。详见CVDP_NAME_S5_RESULT_20261005.json。135文件双端核验、19自有编译产物清理；旧失败与S4记录保留。

S6仅评测侧审查，不启动模型或EDA，不再补名称规则以提高覆盖数。预先固定S5的全部54项和ID字典序，保留302总分母、113弃权、135未进结构范围。逐条审查完整原题、转换差异、实际映射测试入口和依赖；记录端口/位宽/符号、参数域、复位/时序/握手、明确功能义务与断言对应、内部实现依赖、空洞测试、参考/正负控制来源、已见/同源家族和未解决项。文本正确或静态可解析不自动准入；缺参考时须有独立可审核合同和实际正负控，当前全部仍缺该运行证据。

完整54项清单先登记后逐项填写，未审项保持pending，不能以少量审查结论代表全54。发现合同冲突仅标阻塞；诊断或修正该题及同家族后永久列开发/回归，不能据已见评分选变体或调求解器。固定候选、官方baseline、模型均保持，参考/测试台只在私有评测侧。全部结论、来源SHA及接触记录保留；只有审查与控制具备的材料才能进入随后独立验证协议。该工作是数据准入子阶段，不是模型实验或完整大测试。

## 2026-10-05 08:15 S5语义字符串反例预案（尚未执行）

票39/40仍按原冻结配置运行/排队期间，静态审查发现独立于CVDP记录和模型成绩的漏洞：明确要求输出字符串`"module Leaf7"`时，旧题面转换也会改动常量内部的名称；其文本往返仍可逆，但源码回映射只改声明，无法恢复已改变的输出常量。尚未查看S4的167条转换结果/覆盖数，先冻结本反例和收窄规则；不据覆盖率补语法。

新构造反例以原规则固定SHA22658a7ca54687254e021cd767303142dd1c0db0038530df9619522f047eb3a0确认“旧转换接受且改变常量，文字往返可逆”，再用Icarus证明原实现通过而符合转换后常量的实现回映射后失败；新规则必须弃权。只有经该因果对照确认，才认定旧规则的语义不安全。最小收窄只拒绝双引号字符串中含完整模块短语的名称位置，以及不平衡双引号；独立名称引号`module named "Leaf7"`保持支持，源码回映射不变。

S5固定12个往返/24个拒绝控制、S3初始化诊断、8个原名/规范名RTL对照，并新增上述反例2编译/2仿真，总上限19编译/19仿真、0模型/自然题EDA、300秒/槽10分钟。每一步失败立即保留现场，不开始或继续自然记录转换。控制全过后按原167结构名单应用一次，私有保留原版/新版转换和弃权关系；这属于评测接口修正，不能宣传算法增益或独立题准入。S4冻结包不修改，任何S4机械可逆结果均须等待语义审查，禁止直接用于模型质量评分。

启动须先读取票40终态、确认其来源/初始化诊断及守卫结论并归档同步；若票40失败原因不同，先查因，不能按本预案盲跑。S5目前仅源码与计划准备，不作已启动或已通过记录。

## 2026-10-05 S3：共同模块名转换前测冻结

07:49终态：c285394/票38已止于第一个原名RTL的首次向量，编译成功、仿真失败；没有执行规范名对照，也没有应用167条自然记录。初始输入声明为0、首次仍赋0，日志在time2报VALUE；这只定位到构造激励问题，尚须受控复现确认。0模型、1编译/1仿真，guard0.251227秒；模型/保护文件、自有后代及槽释放正常。失败ZIP `76f5f4e7178405647cc0a8a6ed8568c6313b94563ddfb267206e7c608bae459e` 保留，20文件远端核验后释放自有held票，不阻塞其他既有队列。

07:54更新：S3失败包20文件已双端逐项校验；原始DUT/TB/log保留，归档内保留编译产物后清理自有simulation.vvp，无缓存/空目录残留。S4已固定330f9cc2cef1674d92c73cfd027a2ee3c934cffb并同步GitHub，票40/monitor3660638，排在已有票39的repair-context v2模型任务之后，尚无执行PID。计划SHA `ba43ad75b7e70bf9bad2d6f28650d5a4edfcbc6210708515354ee4b44eaf1116`。准备时AST逐函数确认bind_prompt/bind_source/valid_name/word与S3完全相同；仅构造激励和诊断改动，不根据自然记录扩规则。日志待执行后在该阶段guard/stage.log生成；不能把排队写成通过。既有票39由另一归属运行，本阶段不派发、不重启或改其配置。

接续S4事前冻结：首先使用S3原DUT的固定哈希44fc85bcdbacae77ca2b90eccb986d9aaf1ae55cad798437d01112d2d2e02a68复现“未产生输入事件时q为x，显式1→0输入后得到正确结果”。若不能同时复现两者，立即停止，不把猜测写成根因。确认后只修构造测试激励：d不在声明时初始化，initial先等一个时间单位再执行同一顺序的五个向量；DUT、转换函数、拒绝规则及167条结构名单不变。新增该诊断1编译/1仿真，全S4最多17编译/17仿真，仍0模型/0自然题仿真、300秒阶段/10分钟槽。只有所有控制通过才首次应用自然记录，不依据记录结果修改规则或补采样。

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
