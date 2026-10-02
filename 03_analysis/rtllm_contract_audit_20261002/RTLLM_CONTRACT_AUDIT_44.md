> 发布说明：本报告记录先前本地静态审计阶段；下列证据路径是私有冻结包中的相对标识，并非公开附件。服务器后续只读核验、最新修正理由与接管状态见同目录 README.md；不发布原始prompt/reference/candidate全集。

# RTLLM 44题冻结文本契约审计

日期：2026-10-02。范围：仅本地已下载证据的静态审计；本轮未连接服务器、运行模型、编译、仿真、评测或修改源文件/冻结候选/结果/凭据。新建文件仅本审计报告及同内容44行CSV。

## 主要发现

1. BCD题面A/B限定0–9，TB却随机四位满域。现有agent在合法和0–19中corrected_sum[4]进位逻辑可与十进制进位一致；和≥26时五位修正和回卷的差异属于非法输入，不能据13次差异认定合法BCD错误。这是静态推导，不是新测试通过。
2. fixed_point_substractor题面没有N/Q默认，参考32/15、双方候选16/8；TB的localparam32/15只决定线宽，并未把参数传给good/dut。另有明确正零规则被ref同号负数分支违反；算术语义内部矛盾，不能仅改参数便称合同已闭合。
3. multi_booth_8bit不能简单称中间p无题面依据：Implementation明确16轮、符号扩展、每轮累加和a→multiplier/b→multiplicand。它又称Radix-4 Booth，端口角色相反，产生合同冲突。只看rdy时产品是一项可重判的子合同，不能替代原全合同。
4. instr_reg的TB复位极性反了：rst低有效，却在200次测量期间恒为0。正常选择/保持功能没有被测量，原L3不能证明正常功能。
5. accu、serial2parallel参考错误处理无效输入；synchronizer刺激违反明确稳定性/使能宽度约束，且参考混用了A/B reset。若采用参考等价作为唯一oracle，会否定符合题面的实现。

## 证据与方法

本地包含44题×5文件=220文件（prompt/ref/TB/task.json/原控制solution.sv）、88份实际模型候选solution.v、88份冻结判定JSON以及snapshot.json。tasks_verified中的solution.sv是原控制候选，不是模型产物。逐题人工静态阅读prompt/ref/TB；全部88份模型候选读取并形成结构/参数/原等级/哈希目录，重点完整检查BCD、定点减法、Booth等争议候选。未对88份候选声称完整功能证明。此前交叉审阅反馈已逐项静态复核。

snapshot记录冻结源/模型配置与原输入哈希。taskset_manifest.json未在本地，但44个目录、两侧44个候选及两侧各44个结果task_id已只读核对，均唯一且与本地44个目录一致；缺manifest不阻止现有文本审计，也不声称已经重建或验证原服务器冻结任务manifest。原始模型响应和当时生成runtime源码未在本地完整证据包中，无法判定缺失helper是模型遗漏还是提取器丢弃；此前共享提取器只保留TopModule的观察作为历史待复核线索。

分类C=已确认契约问题（若同时有歧义仍列C并写明）；A=规格歧义；L=未发现明确冲突但覆盖有限。分类只描述现有文本和夹具可信边界，不等于候选正确/测试通过。表内“可复用”表示未来可保持candidate字节不变重新判定，不表示本轮已重判。

## 通用夹具限制

- 组合题随机200次，约1ns稳定后全输出比较；时序题一般4周期reset、16周期预热，之后200次在negedge后约1ps驱动随机输入，跨过posedge到下一negedge后约1ps全输出比较。主时钟5ns，CDC的B时钟7ns。Booth单独每笔reset两周期、检查20中间周期及最终check，200笔事务；其errors包含中间比较，不能当200独立最终产品差异数。
- 所有good/dut实例均没有#参数覆盖。TB localparam不是实例绑定；状态枚举/参考内部实现参数不应自动升级成题面外部参数要求。
- 无valid遮罩、没有普遍交易scoreboard、没有测量期中途reset。已知参考正负对照只证明参考等价检测能力，不证明prompt→fixture/oracle正确。
- 部分prompt第一行TopModule与后面的原模块名同时存在。规范包装要求及源码打包规则要从冻结系统指令复核。不能为修成绩直接改候选名、补缺失helper或替换官方baseline；改变生成/打包协议应作为新协议实验。
- 功能、结构与精确逐拍实现要求分开记录。多个题面指定子模块/CLA/shift-add架构，功能相同并不自动满足结构合同；现有TB一般未检查这些要求。

## 44行逐题审计表

参数列从参考/TB原文提取，完整候选默认见附录；无外部参数题的参考内部状态枚举也可能显示在该列。L类均含上述通用覆盖局限。

主分类统计：C 12题；A 11题；L 21题。此统计不是通过率。

| 题目 | 分类 | 合法输入域 | 参数默认与绑定 | reset/enable/clock | 交易与可观察边界 | TB/ref一致性及覆盖 | 最小修正方案 | 候选复用或重生成 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| accu | 已确认契约问题 | data_in 0–255；valid_in 0/1，允许输入间隙 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低；仅valid_in接受 | 每四个有效数据求10位和；valid_out一拍，非有效周期数据未定义 | ref ready_add=!valid_out或valid_in，无效输入也计数；TB随机valid且全时比较data_out | 独立四有效样本scoreboard；核对valid脉冲并只在有效时判数据 | 原prompt下可重判现存候选；若新增输出延迟要求须重生成 | `accu/prompt.txt` / `accu/ref.sv` / `accu/tb.sv` |
| adder_16bit | 未发现明确冲突但覆盖有限 | a,b 0–65535；Cin 0/1 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | {Co,y}=a+b+Cin；题面另要求8位子加法器实例化 | 200随机对照没有结构验收或进位边界保证 | 数学oracle、进位链定向样本；将结构要求独立静态验收 | 可复用；缺失辅助模块不可臆补 | `adder_16bit/prompt.txt` / `adder_16bit/ref.sv` / `adder_16bit/tb.sv` |
| adder_32bit | 未发现明确冲突但覆盖有限 | A/B为32位无符号；接口声明[32:1] | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 33位加法及CLA结构/16位CLA块 | 200随机只判S/C32，未证明CLA架构；向量连接位宽相同不自动证明索引声明一致 | 独立加法oracle、进位定向样本及结构检查 | 可复用；改变模块打包协议时受影响题需新生成或找回原响应 | `adder_32bit/prompt.txt` / `adder_32bit/ref.sv` / `adder_32bit/tb.sv` |
| adder_8bit | 未发现明确冲突但覆盖有限 | a,b 0–255；cin 0/1 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 9位加法；多个位级full-adder | 200随机功能对照，未验结构；baseline成品引用缺失full_adder且carry[7:0]访问[8] | 加法oracle与结构分开；确认完整多模块打包链 | 可复用当前成品重判；不得凭猜测补helper | `adder_8bit/prompt.txt` / `adder_8bit/ref.sv` / `adder_8bit/tb.sv` |
| adder_bcd | 已确认契约问题 | A/B严格0–9；Cin 0/1 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | sum_decimal=A+B+Cin；Sum为个位，Cout为十进制进位 | TB四位满域随机涵盖10–15，越出prompt明确域；agent差异在非法大和域 | 穷举10×10×2=200个合法组合；独立十进制oracle | 两份原候选均可直接重新判定；不需重生成 | `adder_bcd/prompt.txt` / `adder_bcd/ref.sv` / `adder_bcd/tb.sv` |
| adder_pipe_64bit | 规格歧义 | adda/addb全部64位；i_en 0/1 | ref DATA_WIDTH=64, STG_WIDTH=16；TB DATA_WIDTH=64, STG_WIDTH=16；good/dut未#覆盖 | clk正沿；rst_n低；i_en接受请求 | 65位加法，o_en标记有效；确切延迟/无效result未给 | ref四级由隐藏STG_WIDTH=16决定；TB精确逐拍、全时判result/o_en | 交易队列判有效和顺序；需明确延迟或合法延迟范围，否则预排除 | 可重判不加新约束的功能子合同；新可见延迟/级数须新生成 | `adder_pipe_64bit/prompt.txt` / `adder_pipe_64bit/ref.sv` / `adder_pipe_64bit/tb.sv` |
| barrel_shifter | 未发现明确冲突但覆盖有限 | in 0–255；ctrl 0–7 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 零填充右移，不旋转；题面指定mux2X1分级实现 | 200随机不足覆盖2048组合/结构；agent成品helper缺失并含重复stage驱动风险 | 穷举2048组合数学移位oracle，另验结构/完整打包 | 可复用；不据成品缺helper推断模型原响应也缺 | `barrel_shifter/prompt.txt` / `barrel_shifter/ref.sv` / `barrel_shifter/tb.sv` |
| calendar | 未发现明确冲突但覆盖有限 | 无数据输入；仅时钟与RST | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | CLK正沿；RST高异步 | 秒/分0–59，时0–23；含59/59/23级联回卷 | 16预热+200检查仅覆盖秒/少量分钟，未覆盖3600/86400边界 | 足够长的独立计数scoreboard及中途reset/跨层回卷 | 可复用；本轮未运行长测试 | `calendar/prompt.txt` / `calendar/ref.sv` / `calendar/tb.sv` |
| comparator_3bit | 未发现明确冲突但覆盖有限 | A/B 0–7 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 大于/等于/小于三个互斥输出 | 200随机并不构成全部64组合穷举证明 | 穷举64组合独立比较oracle | 可复用 | `comparator_3bit/prompt.txt` / `comparator_3bit/ref.sv` / `comparator_3bit/tb.sv` |
| comparator_4bit | 未发现明确冲突但覆盖有限 | A/B 0–15 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 三个互斥比较输出；借位实现说明 | 200随机未覆盖全部256组合或结构 | 穷举256组合独立比较oracle，结构另验 | 可复用 | `comparator_4bit/prompt.txt` / `comparator_4bit/ref.sv` / `comparator_4bit/tb.sv` |
| counter_12 | 未发现明确冲突但覆盖有限 | valid_count 0/1 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低；valid_count=0保持 | 0–11循环计数 | 逐拍参考比较与功能描述未见冲突；无定向长暂停或测量期reset | 独立mod12计数，暂停、11回卷、中途reset | 可复用 | `counter_12/prompt.txt` / `counter_12/ref.sv` / `counter_12/tb.sv` |
| div_16bit | 已确认契约问题 | A 0–65535；可判域B 1–255，B=0未定义 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | quotient/remainder；说明用greater但数学除法等号需减 | TB允许B=0；未定义域强制等价；文字greater/参考>=需区分 | 非零域数学除法oracle，定向A=B/小于B/极值；零域先不判 | 可复用非零明确子域；要求新除零行为须重生成 | `div_16bit/prompt.txt` / `div_16bit/ref.sv` / `div_16bit/tb.sv` |
| edge_detect | 规格歧义 | a 0/1，题面说缓慢变化但未量化 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低 | 开头/中段说单拍边沿脉冲，末句说保持到下次边沿 | 内部文字矛盾；TB每拍随机a只强制ref单拍实现 | 澄清脉冲与保持优先级；缓慢/连续边沿定向测相位 | 单拍子合同可复用但单列；新增明确行为后的全任务须新生成或预排除 | `edge_detect/prompt.txt` / `edge_detect/ref.sv` / `edge_detect/tb.sv` |
| fixed_point_adder | 已确认契约问题 | N位固定点；编码、溢出规则需澄清 | ref Q=15, N=32；TB Q=15, N=32；good/dut未#覆盖 | 组合；无reset/enable/clock | 同号幅度相加、异号幅度相减；Q定小数尺度 | prompt无N/Q默认；ref32/15，agent8/0，baseline16/8；TB32/15不绑定；overflow描述不精确 | 显式#(.N(32),.Q(15))绑定双方；独立明确编码/零/溢出oracle | 参数化现成候选可重判指定配置；增加默认、编码/溢出新要求须新生成 | `fixed_point_adder/prompt.txt` / `fixed_point_adder/ref.sv` / `fixed_point_adder/tb.sv` |
| fixed_point_substractor | 已确认契约问题 | N位固定点；全符号组合；零须正零 | ref Q=15, N=32；TB Q=15, N=32；good/dut未#覆盖 | 组合；无reset/enable/clock | 题面同号保持符号/异号比较与通常减法矛盾；零符号明确清0 | prompt无默认；双方16/8、ref32/15；TB无绑定；ref相同负数相减保留负零 | 先同绑定32/15；独立验证零规则；澄清符号编码/算术，不自动改成二补码减法 | 现有参数化候选可重判；agent成品本身有动态module级if/赋值语法问题，不会仅靠参数修好；新语义须新生成 | `fixed_point_substractor/prompt.txt` / `fixed_point_substractor/ref.sv` / `fixed_point_substractor/tb.sv` |
| float_multi | 已确认契约问题 | 全部IEEE754单精度位模式，含NaN/Inf/±0/次正规 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk；rst高；无valid/ready，外部采样合同未给完整 | IEEE乘积/舍入；首次时钟提取输入，最终时刻未规定 | ref特殊值早写z后普通counter7无条件覆盖；or rst使释放也触发计数；TB每周期换a/b全时比较隐藏序列 | 预排除；先独立IEEE oracle，明确舍入/NaN比较及输入保持、输出时刻 | 仅不变合同的有限功能子域可复用；完整新时序/舍入合同须新生成 | `float_multi/prompt.txt` / `float_multi/ref.sv` / `float_multi/tb.sv` |
| freq_div | 已确认契约问题 | 题面输入时钟100MHz | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | CLK_in正沿；RST高异步 | 输出÷2/÷10/÷100，即50/10/1MHz | TB #2.5周期5ns=200MHz，只能检验比率，不能宣称绝对频率正确 | 输入周期10ns；双边沿测比率、周期和reset | 可复用；无需新生成 | `freq_div/prompt.txt` / `freq_div/ref.sv` / `freq_div/tb.sv` |
| freq_divbyeven | 未发现明确冲突但覆盖有限 | NUM_DIV合法偶数2–32；默认6 | ref NUM_DIV=6；TB NUM_DIV=6；good/dut未#覆盖 | clk正沿；rst_n低；无enable | 每NUM_DIV/2个正沿翻转；reset输出0 | TB只默认6且没有实例参数覆盖；未覆盖2/32及中途reset | 显式绑定双方NUM_DIV；覆盖合法偶数，边沿波形oracle | 已有暴露参数的候选可复用；若题面要求参数而候选写死，应保留结构失败，不改候选 | `freq_divbyeven/prompt.txt` / `freq_divbyeven/ref.sv` / `freq_divbyeven/tb.sv` |
| freq_divbyfrac | 未发现明确冲突但覆盖有限 | 固定3.5分频；MUL2_DIV_CLK=7半步描述 | ref MUL2_DIV_CLK=7；TB MUL2_DIV_CLK=7；good/dut未#覆盖 | clk双边沿；rst_n低异步 | 每7半步，前3高、后4低 | 复核发现ref OR合成可达均匀3.5周期；仅负沿检查未验证全部半步与reset相位 | 双边沿独立7半步波形oracle；不要误把正沿支路4/3间隔当合成输出 | 可复用；撤回独立审阅的确定oracle错误判断 | `freq_divbyfrac/prompt.txt` / `freq_divbyfrac/ref.sv` / `freq_divbyfrac/tb.sv` |
| freq_divbyodd | 未发现明确冲突但覆盖有限 | NUM_DIV奇数；默认5；其他合法范围未给 | ref NUM_DIV=5；TB NUM_DIV=5；good/dut未#覆盖 | clk双边沿；rst_n低异步，支路reset为1 | 两个边沿计数/整除半段后OR的明确波形 | TB只默认5、负沿比较；不覆盖另一半步和参数范围 | 绑定默认5；双边沿波形oracle；扩参数域前确认计数宽度/支持范围 | 默认5可复用；不要自行扩成任意无限奇数 | `freq_divbyodd/prompt.txt` / `freq_divbyodd/ref.sv` / `freq_divbyodd/tb.sv` |
| fsm | 已确认契约问题 | 连续1位IN；10011与100110011重叠匹配 | ref s0=3'b000, s1=3'b001, s2=3'b010, s3=3'b011, s4=3'b100, s5=3'b101；TB s0=3'b000, s1=3'b001, s2=3'b010, s3=3'b011, s4=3'b100, s5=3'b101；good/dut未#覆盖 | CLK状态正沿；RST高；Mealy输出 | 最后输入出现时MATCH高，例子第五/第九位 | TB输入在negedge后变化却跨过posedge后下一negedge检查，可能错过前半拍组合脉冲 | 驱动后、采样posedge前检查Mealy输出并检查reset/定向重叠 | 可复用；不把registered候选与组合脉冲差异全归因题面不清 | `fsm/prompt.txt` / `fsm/ref.sv` / `fsm/tb.sv` |
| instr_reg | 已确认契约问题 | data 0–255；fetch=1/2装不同寄存器，0/3保持 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst明确低有效；reset即时相位细节未规定 | ins/ad1拆首寄存器，ad2为第二；正常期选择/保持 | TB rst=1再置0，所有200次测量都在reset；正常功能未测 | 改低有效reset序列；逐种fetch及保持独立scoreboard；不强行加未给异步要求 | 可复用原候选；原L3不能作为正常功能证据 | `instr_reg/prompt.txt` / `instr_reg/ref.sv` / `instr_reg/tb.sv` |
| JC_counter | 未发现明确冲突但覆盖有限 | 无数据输入；64位状态 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低异步 | Q={~Q[0],Q[63:1]}，128拍循环 | 200测量覆盖周期长度但预热跳过初始16状态；无测量期reset | 独立移位scoreboard，自reset首拍检查和128状态回卷 | 可复用 | `JC_counter/prompt.txt` / `JC_counter/ref.sv` / `JC_counter/tb.sv` |
| LFSR | 未发现明确冲突但覆盖有限 | 无数据输入；4位状态 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst高；prompt写沿内reset判断 | 反馈~(out[3]^out[2])，左移，reset0 | ref异步高reset，prompt沿内措辞未明确异步；TB不测中途reset；仅已采样序列 | 独立15状态/反馈轨迹，reset采样相位明确后扩测 | 可复用已明确沿内行为；若新增reset异步约束须新生成 | `LFSR/prompt.txt` / `LFSR/ref.sv` / `LFSR/tb.sv` |
| multi_16bit | 规格歧义 | ain/bin无符号16位；start=0使i归0 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低；start持续才能走完装载+16计算 | 题面明确i、逐位累加及yout赋值，故中间轨迹有文字依据；done完成 | 随机start不保证完成；新交易未清累加与通常独立乘法含义冲突；不能简单说中间值未规定 | reset隔离完整交易，持续start、判最终数学乘积/done；逐拍实现要求另报，重启/abort先澄清 | 完整单交易子合同可复用；新重启规则/改变算法合同須新生成 | `multi_16bit/prompt.txt` / `multi_16bit/ref.sv` / `multi_16bit/tb.sv` |
| multi_8bit | 未发现明确冲突但覆盖有限 | A/B 0–255，无符号 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 16位乘积；移位加法算法 | 200随机非65536穷举，参考等价不验算法；不能仅凭窄输入断言表达式结果截断 | 独立数学乘积及高位/全1定向；算法结构另验 | 可复用 | `multi_8bit/prompt.txt` / `multi_8bit/ref.sv` / `multi_8bit/tb.sv` |
| multi_booth_8bit | 规格歧义 | a/b 8位；Implementation明确符号扩展，端口符号文字不足 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；reset高异步装载；16轮后rdy | Implementation明确每轮shift/add，并给a→multiplier/b→multiplicand；整体却称Radix-4 Booth且端口角色相反 | TB每交易20中间周期逐拍判p/rdy；算法文字确有依据但与整体规格冲突；交换a/b保持最终乘积却改变轨迹 | 选择最终signed乘积+rdy子合同，或先公布逐拍算法优先级；不可直接删除中间检查后称原全合同通过 | 现存候选可重判最终产品子合同；统一Radix-4/指定逐拍算法后的新版必须新生成，或预排除 | `multi_booth_8bit/prompt.txt` / `multi_booth_8bit/ref.sv` / `multi_booth_8bit/tb.sv` |
| multi_pipe_4bit | 未发现明确冲突但覆盖有限 | mul_a/b默认4位无符号；size=4 | ref size=4, N=2 * size；TB size=4, N=2 * size；good/dut未#覆盖 | clk正沿；rst_n低异步；每拍接收 | 题面两级寄存，第二级输出前一拍部分和，即两采样边沿链 | TB默认size=4、无显式绑定；200样本，未查reset中途/结构 | 显式size=4；两级数学流水scoreboard，穷举256输入组合与连续流 | 可复用；不扩size任意范围（ref仅四项分组） | `multi_pipe_4bit/prompt.txt` / `multi_pipe_4bit/ref.sv` / `multi_pipe_4bit/tb.sv` |
| multi_pipe_8bit | 规格歧义 | mul_a/b 0–255；mul_en_in 0/1 | ref size=8；TB size=8；good/dut未#覆盖 | clk正沿；rst_n低；输入寄存仅enable更新 | mul_en_out有效输出；题面明确invalid mul_out=0；未给enable管线宽度 | ref三位enable另寄存共四采样级；disable清输入与prompt保持不同；reset mul_a重复、mul_b缺初始化 | 澄清enable与数据对齐延迟；独立交易oracle，同时保留invalid=0检查；补reset评测 | 当前成品可重判明确子合同；agent缺TopModule仍为成品接口问题；新延迟合同须新生成 | `multi_pipe_8bit/prompt.txt` / `multi_pipe_8bit/ref.sv` / `multi_pipe_8bit/tb.sv` |
| parallel2serial | 未发现明确冲突但覆盖有限 | d 4位，每四周期一帧 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低；无输入valid | valid_out仅标首位，随后三周期dout仍承载剩余位 | TB全时dout检查可有依据；不能按valid=0屏蔽后三位；预热跳过首帧 | 首位valid定位四位scoreboard及首帧/reset；明确reset起始计数相位若新要求 | 可复用；只mask初始未成帧期 | `parallel2serial/prompt.txt` / `parallel2serial/ref.sv` / `parallel2serial/tb.sv` |
| pe | 未发现明确冲突但覆盖有限 | a/b任意32位整数；c为32位模截断 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst高异步；每拍累加 | c←c+a*b低32位 | signed/unsigned乘法的低32位一致，不应凭未写signed造冲突；随机无定向溢出/reset | 独立mod2^32 MAC、零/极值/累加溢出、中途reset | 可复用 | `pe/prompt.txt` / `pe/ref.sv` / `pe/tb.sv` |
| pulse_detect | 规格歧义 | 连续data_in位；例01010→00101 | ref s0=2'b00, s1=2'b01, s2=2'b10, s3=2'b11；TB s0=2'b00, s1=2'b01, s2=2'b10, s3=2'b11；good/dut未#覆盖 | clk正沿；rst_n低；输出说明含时钟always | 010尾周期pulse；题面时钟输出与ref组合Mealy时相不一致 | TB统一negedge且跨posedge，不能裁定组合/寄存相位解释 | 明确尾位采样前/后相位；定向01010及重叠；预排除有冲突全合同 | 可复用无新时相子合同；明确新可见时相須新生成 | `pulse_detect/prompt.txt` / `pulse_detect/ref.sv` / `pulse_detect/tb.sv` |
| radix2_div | 规格歧义 | 8位signed/unsigned；明确子域divisor≠0，排-128/-1溢出 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst极性未显式，ref高同步；opn_valid请求/res_ready消费 | result仅res_valid时含余数高8位/商低8位；内部8步说明 | TB每拍乱改sign/request/ready、全时判中间result；ref实时sign未锁存；busy接受请求条件不充分规定 | 一笔交易、sign稳定、等待res_valid并验持有/消费；除零/溢出/busy/reset极性需澄清 | 可复用明确子域、协议假设单列；完整新握手/reset合同须新生成 | `radix2_div/prompt.txt` / `radix2_div/ref.sv` / `radix2_div/tb.sv` |
| right_shifter | 未发现明确冲突但覆盖有限 | d 0/1 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；无reset；prompt明确initial q=0 | q←{d,q[7:1]}，首次值0 | 16预热把初始状态与初始错误冲掉；只测后续移位 | t=0及首8拍独立shift scoreboard | 可复用；不要将initial误判为无题面许可 | `right_shifter/prompt.txt` / `right_shifter/ref.sv` / `right_shifter/tb.sv` |
| ring_counter | 未发现明确冲突但覆盖有限 | 无输入数据；8位onehot | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；reset高，起始00000001；异步未明确 | 左循环移位、onehot | 200拍覆盖周期，但预热跳过启动；无异步相位/恢复检查 | 首8拍onehot/方向/回卷scoreboard；reset相位以原可见合同为界 | 可复用 | `ring_counter/prompt.txt` / `ring_counter/ref.sv` / `ring_counter/tb.sv` |
| sequence_detector | 规格歧义 | data_in连续0/1 | ref IDLE=5'b00001, S1=5'b00010, S2=5'b00100, S3=5'b01000, S4=5'b10000；TB IDLE=5'b00001, S1=5'b00010, S2=5'b00100, S3=5'b01000, S4=5'b10000；good/dut未#覆盖 | clk正沿；rst_n低；S4输出Moore | 检测1001，第四位后进入S4；重叠退出策略未明确 | TB强制ref S4退出/重叠路径；不能默认所有合理FSM逐拍等价 | 明确1001001等重叠政策；独立序列scoreboard，普通非重叠子域先判 | 非重叠明确子域可复用；新增重叠要求须新生成或预排除 | `sequence_detector/prompt.txt` / `sequence_detector/ref.sv` / `sequence_detector/tb.sv` |
| serial2parallel | 已确认契约问题 | din_serial 0/1；din_valid允许间隙 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低；只接受有效位 | 八个有效位MSB先，随后一输出拍；输出拍忽略输入 | ref invalid清cnt，违背八个有效位且暗加连续条件；TB随机valid触发 | 独立计数八有效位；输出拍不接收；只valid时判parallel，测间隙/连续 | 可复用原候选；不得为迎合ref增加连续输入前提 | `serial2parallel/prompt.txt` / `serial2parallel/ref.sv` / `serial2parallel/tb.sv` |
| signal_generator | 未发现明确冲突但覆盖有限 | 无输入数据；5位wave | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低异步 | 0–31往返，0/31各多停一拍 | ref端点保持符合文字；200拍有限覆盖，预热跳过启动 | 独立64拍轨迹/端点保持、首拍与中途reset | 可复用 | `signal_generator/prompt.txt` / `signal_generator/ref.sv` / `signal_generator/tb.sv` |
| square_wave | 规格歧义 | freq非零明确子域1–255；0未定义，变频语义不足 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；无reset；prompt未给count/wave初始值 | count到freq-1翻wave；稳定freq半周期freq拍 | ref initial 0形成隐藏初相；TB随机freq含0且每拍变，强制初相及动态行为 | 先澄清上电/初值/变频生效；非零稳定频率测周期而非隐藏相位 | 有限周期子合同可复用需注明初始化缺口；新增init/reset/变频合同须新生成 | `square_wave/prompt.txt` / `square_wave/ref.sv` / `square_wave/tb.sv` |
| sub_64bit | 未发现明确冲突但覆盖有限 | A/B全部64位二补码有符号 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | 组合；无reset/enable/clock | 差低64位；异号输入且结果符号不同则overflow | 200随机参考对照，未保证min/max/equal溢出边界 | 独立64位差与符号oracle，定向极值 | 可复用 | `sub_64bit/prompt.txt` / `sub_64bit/ref.sv` / `sub_64bit/tb.sv` |
| synchronizer | 已确认契约问题 | data_en高≥3 clk_b周期；期间data_in恒定；相邻数据变化≥10 clk_b周期 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk_a/clk_b周期TB为5/7ns；arstn/brstn低异步 | A采数据/enable，B两级enable后更新并保持dataout | TB每5ns改data/en，违背明示CDC域；ref en_data_reg判断brstn而敏感arstn，与prompt A reset不同 | 交易刺激遵守稳定/间隔；独立时钟域scoreboard，两个reset分别测 | 原候选可复用；不需要新增prompt，只修非法刺激/错误oracle | `synchronizer/prompt.txt` / `synchronizer/ref.sv` / `synchronizer/tb.sv` |
| traffic_light | 规格歧义 | pass_request 0/1，按钮剩余>10时缩到10 | ref idle=2'd0；TB idle=2'd0, s1_red=2'd1, s2_yellow=2'd2, s3_green=2'd3；good/dut未#覆盖 | clk正沿；rst_n低异步；状态参数只是枚举 | 正文60绿/5黄/10红；clock倒计时亦输出 | 正文与count=3转移、退出/进入装载文字冲突；ref条件与prompt无条件重置10也不同 | 预排除；先统一时长/过渡初态/count观察/按钮策略，再独立scoreboard | 明确新版合同后必须新生成；只旧候选参考等价不能解决 | `traffic_light/prompt.txt` / `traffic_light/ref.sv` / `traffic_light/tb.sv` |
| up_down_counter | 已确认契约问题 | up_down 0/1；16位mod65536 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | prompt明确posedge同步reset高；ref为异步高reset | 每拍±1，reset置0 | ref异步与prompt同步不同；TB只初始reset，不揭示此差异/长程边界 | 独立同步reset计数，中拍assert后在posedge前后观察；定向回卷 | 可复用原候选重判原同步合同 | `up_down_counter/prompt.txt` / `up_down_counter/ref.sv` / `up_down_counter/tb.sv` |
| width_8to16 | 规格歧义 | data_in 0–255；valid_in允许间隙 | ref 无外部参数；TB 无localparam；good/dut未#覆盖 | clk正沿；rst_n低异步；每两有效字节一组 | 首字节高8；开头next clock与后文第二输入边沿立即拼接有歧义 | TB强制ref第二有效边沿与invalid数据保持；无效数据要求不充分 | 澄清第二/下一边沿；有效交易拼接oracle，invalid只验已明示控制 | 原候选可重判无新要求子合同；新版可见延迟须新生成 | `width_8to16/prompt.txt` / `width_8to16/ref.sv` / `width_8to16/tb.sv` |

## 关键证据定位与裁定

- BCD：prompt:8–9合法0–9；tb:47–49满位宽随机；agent solution.v:11–30五位原和/修正和，baseline用raw_sum>9输出进位。合法域最大19，修正后最大25，bit4不会因加6产生32以上回卷；非法域raw_sum≥26才产生该进位差异。未来200个合法组合穷举是修正计划，本轮未执行。
- 定点减法：prompt:8–10仅定义Q/N含义，无默认；tb:6–7为Q15/N32，tb:12–21无实例参数覆盖；ref:2–3默认15/32；双方solution.v:2–3默认8/16。N16候选会截断32位输入并扩展16位输出，不能把全域不匹配纯归因算术。ref:17–19同号直接保留a符号，负数相等产生负零，违背prompt:30明确零规则。agent成品module级动态if及对wire的过程赋值另有确定语法问题；参数一致不会消除它。不能为了旧成绩选择某种算术解释：先确认sign-magnitude或二补码、同号a<b/异号符号、溢出以及Q作用。
- Booth：prompt:5称Radix-4、:13–14角色说明、:22–27明确符号扩展/16轮shift-add；TB:55–62全20周期比较p/rdy。agent与baseline/参考交换了装载角色，逐步累加轨迹不同；最终16位乘积在交换操作数后具有交换律。这解释为什么中间差异不能直接叫最终乘法错误。但若Implementation被明确选为最高优先合同，agent角色交换本身违反该文字；因此不能无条件删除中间观察。须先选合同，或只发布清楚标注的“最终产品子合同”结果。
- instr_reg：prompt:10低reset、:21–26沿内行为；TB:57–59从1置0，后续未释放；:63–68在reset中检查200次。修正应rst0保持→rst1释放，并检查fetch1/2以及0/3保持。prompt并未明确异步reset，勿额外强制参考negedge即时输出。
- accu：prompt:19四个有效输入；ref:62 ready_add=!valid_out|valid_in；TB:55–59每拍随机valid并全时判输出。在valid_out=0/valid_in=0时参考仍累加，是确定违约。
- serial2parallel：prompt明确八个有效输入、不要求连续，输出拍忽略输入；ref的din_valid=0分支把cnt清0。需保留间隙例子，不能暗加连续条件迎合参考。
- synchronizer：prompt:5至少3个B周期高使能、间隔至少10个B周期，TB:33–34周期5/7ns、:55–56每5ns更新data/en；ref的en_data_reg块敏感arstn但判断brstn，与prompt A域reset相悖。两个reset同驱动会掩盖错误。
- float_multi：ref:40–88特殊值早写z，:149–160在counter7无条件普通输出并覆盖特殊值；:17对rst任意变化敏感。没有special-case旁路终止标记。题面有IEEE结果要求却没有完整latency/吞吐/NaN payload/舍入模式合同，既不能以该ref为IEEE oracle，也不能加隐藏counter7强制时序。
- fsm：prompt:5、:18–19明确Mealy末位同时输出；ref:69–74组合；TB:47以后驱动IN然后越过状态正沿才check。需要采样输入已稳定、状态未推进时的组合输出，并按明确示例检查重叠。

### 独立复核更正：freq_divbyfrac

不采纳独立反馈中“合成输出4/3周期交替、不均匀”的确定判断。静态NBA时间推导（首个正常posedge为t=0，以输入周期为单位）：t=0时old cnt0令ave高、cnt到1；t=0.5时adjust高；t=1 ave低；t=1.5 adjust低，首高区[0,1.5)。t=3后cnt到4，t=3.5负沿adjust拉高；t=4正沿old cnt4使ave高；t=4.5 adjust低；t=5 ave低，第二高区[3.5,5)。t=7再次拉高。于是合成rise为0、3.5、7，高1.5/低2周期，符合题面3高半步/4低半步。正沿支路自身的4/3间隔不能用于裁定OR输出。此为源码静态推导，未执行仿真；仍需双边沿独立波形oracle与reset相位覆盖。

## 最少还需的资料

1. 定点加/减：N/Q选定评测配置（可通过显式绑定实现，无须默认强迫模型）、有符号编码、非标准减法分支优先级、零/溢出规则。若确要评“默认32/15”，需把默认写进新版可见prompt并重新生成。
2. Booth：Radix-4最终产品优先，还是已写出的16轮shift-add逐拍轨迹优先；p在rdy=0是否受逐拍合同约束，ready出现边沿及reset时产品/计数初值。现有文字并非完全没有中间轨迹依据。
3. 有歧义题：流水64/8、宽度转换、float的外部latency/吞吐与invalid数据；pulse/edge采样相位；traffic计时与clock观察；square初态/零/变频；radix请求busy/reset与除零溢出；sequence重叠。无需为其余明确题等待这些资料。
4. 若要重新认证整体实验的身份/调用协议：缺失原taskset_manifest、冻结system prompt/runtime/extractor源码及原模型响应。这些不是完成44行文本审计的阻塞，但会影响完整包装/提取根因和原冻结身份的证明。可先审当前固定成品，不能恢复不可见helper或重构原响应。

## 只交方案：后续最小处理顺序

- 先冻结本报告、原88个candidate字节及原结果；原成绩继续标为“冻结参考夹具等价结果”，不能叫可信prompt正确率、技能泛化负增益。禁止看成绩挑选一个有利子集再称原44题成绩。
- 不改可见prompt的夹具/oracle修正可保持候选：BCD合法穷举、instr reset、CDC合法刺激与reset oracle、accu/serial有效输入scoreboard、fsm相位、freq输入周期、同步counter reset、数学/覆盖定向测试。重新判定时两侧同条件，用新的判定协议与结果路径，保留旧结果。
- 参数化候选同绑定N/Q可复用，但定点算术歧义未闭合前仅报告明确子域/零规则，不发布完整分数。未暴露必要参数/缺Top/缺helper的成品照实记录，不能帮候选补代码。
- Booth/multi16最终交易、radix非零稳定模式、pipe64有效数据等，可对原候选做明确标注的有限子合同重判；不得据此声明原全任务通过。若需发布全任务，先澄清；一旦新增可见要求（默认值、精确延迟、算法、init、握手/符号/溢出）须重新生成两侧候选，不能给旧候选后加要求再归因模型。
- 必须新生成的具体边界：统一后的Booth/traffic全规格；带新外部采样/舍入规定的IEEE float；新增流水64/8或width精确latency；新增square初态/变频规则；选择新定点编码/算术/默认；新增pulse/edge相位、sequence重叠、radix完整握手/reset政策。若选择预排除，则在任何新批次之前固定排除原因和manifest，无须生成被排除任务。
- 未发现冲突的L类不必重新生成，只需独立oracle及缺失覆盖。结构合同与功能结果分栏，不能把静态巡视改写为测试通过。没有执行本段任一步骤。

## 88份冻结候选结构目录

等级只抄录原result JSON，不是本轮评分；SHA256仅证明当前本地candidate字节。模块名/parameter来自静态文本扫描，不构成完整编译或功能验收。

|侧|题目|模块声明|候选参数|原等级|当前本地SHA256|
|---|---|---|---|---|---|
| agent | accu | TopModule | 未声明parameter | 1 | e3c5fd75ff33414f55f056907cfe1868d9963f26e3a20f64fbf425b2c7d9dcf6 |
| baseline | accu | TopModule | 未声明parameter | 1 | effcc6f462226906f8eb3506946049e22bd22e3a73d8387c631d90730daff422 |
| agent | adder_16bit | TopModule | 未声明parameter | 0 | e06b4dbece09508a04f706429ab193ec59b9f3a595b69fbadc0d72de4fc3ff03 |
| baseline | adder_16bit | TopModule | 未声明parameter | 0 | d5f80ae24e09af1a9280fcfcff26bdcfe724f28821aade575d856c22591161cf |
| agent | adder_32bit | TopModule | 未声明parameter | 0 | 28aa6d922edd5cfd25db597c7e58de6d7998bda5ba635867756e0378ef74ab87 |
| baseline | adder_32bit | TopModule | 未声明parameter | 0 | 7fea3512bf965b719cd686d9c44b4428286f2bfe359f84f513f2f42e6bcdc2b7 |
| agent | adder_8bit | TopModule | 未声明parameter | 3 | 07575c939f850637b6bbad6346f6d9a48051672bc4ffd342ae29e7dffeaee1fe |
| baseline | adder_8bit | TopModule | 未声明parameter | 0 | b0e1fb46b0851ec75186a3a192bd43f7f2befc38d0951137b0c21613c03de205 |
| agent | adder_bcd | TopModule | 未声明parameter | 1 | 70066103ae99dcd76e8e1288f5e4d5ed915389d61a9ddc0952887fb9cbb6d4f7 |
| baseline | adder_bcd | TopModule | 未声明parameter | 3 | e942481b764affe51314e94d2e6aa8f7eb2b408577459dc5c34b19f6ef790634 |
| agent | adder_pipe_64bit | TopModule | 未声明parameter | 1 | b905b3ffe90af40e24b66b7bcd3b28a2b2631c5d9b27e906f4dd26fd7ed39b24 |
| baseline | adder_pipe_64bit | TopModule | 未声明parameter | 1 | baabe1045aa173d6e50bd46bf59dad1e729c76cb92dacff387d4b1cdc482b77b |
| agent | barrel_shifter | TopModule | 未声明parameter | 0 | 88410f4c7fd5aa1e6fb5eef32f8220abda456d1516c5c94545c95f3754ea3c52 |
| baseline | barrel_shifter | TopModule | 未声明parameter | 3 | b9b4f69d82bf3034e90a90aa01dd9215bced1e01771a3b7e8a78857fea38f8f2 |
| agent | calendar | TopModule | 未声明parameter | 3 | 3ad046d63758aa00a1bceddcac602e323ea608c9fdfa415895210ecd16bdb710 |
| baseline | calendar | TopModule | 未声明parameter | 3 | 364b0349c5b26b49438bc039d077700a136e2795920834692c47e4d42be66499 |
| agent | comparator_3bit | TopModule | 未声明parameter | 3 | 38b1c4e797bdf963f47aa3571f143f5ebb8c9c9865d03437dd659b3cc86e42ee |
| baseline | comparator_3bit | TopModule | 未声明parameter | 3 | 26b3ca7ddd00831f528068f5ae7f18ca5f83af7291674b5ceac06a815a4614b0 |
| agent | comparator_4bit | TopModule | 未声明parameter | 3 | 5663bc297c6c56fe027cd7f041b6a3e0e673163ee6294fee621ef48ec273aa69 |
| baseline | comparator_4bit | TopModule | 未声明parameter | 3 | 6b14c01d2d0ed00d55939bbb1c7fccf26bbd2a7971bc6b2d79426e2d1d9c2392 |
| agent | counter_12 | TopModule | 未声明parameter | 3 | 68c1ce25b992765716cf88ac592e9787b554b0d817cbe777330a81b3613d33df |
| baseline | counter_12 | TopModule | 未声明parameter | 3 | 544b2197b9ba0843b1a57e61deb9c321282c0473e1b9204db7c176597bc8cf99 |
| agent | div_16bit | TopModule | 未声明parameter | 0 | 11291746dfebc55adb5a18a9b33b4563460ca42666b63f975b99f4e589b5e395 |
| baseline | div_16bit | TopModule | 未声明parameter | 0 | 111b5d9b0b2e6b3e12616cab79862b8be9fa9f0f031be755d9749f14f046bc09 |
| agent | edge_detect | TopModule | 未声明parameter | 3 | 4c40273a9077a7fd2bd200a24d6602ca000e02cb7bced5476d600459f89110c3 |
| baseline | edge_detect | TopModule | 未声明parameter | 3 | e0661ef858a71f13fc5200d51262c0835a322a01b8ed667d9c6d8ecea085119d |
| agent | fixed_point_adder | TopModule | Q=0,N=8 | 0 | 2a9512dd1a26967df47e087ed31e7bd37f246abbaaee6aecc25ae155817f11ff |
| baseline | fixed_point_adder | TopModule | Q=8,N=16 | 0 | 2118a199cbd324647ce9af03779337acc92ccfd46d049c0dadc068295119a00b |
| agent | fixed_point_substractor | TopModule | Q=8,N=16 | 0 | 60ebaa64409d14df20d19da715b7edffa1f83218bce988b1dcccfd546f04880c |
| baseline | fixed_point_substractor | TopModule | Q=8,N=16 | 1 | 03ea3eb12eaff1ad028d6d4dcc67b9122e478d1cfc8cd17599e03736eb63ecc8 |
| agent | float_multi | TopModule | 未声明parameter | 0 | 929244bf16566e053ea245ebe8d3b133c5b5c18336c561bb287d333cc38ef66f |
| baseline | float_multi | TopModule | 未声明parameter | 0 | 45cbf251f4749fae68914d653eaec0671d7c906d639e1d499bfe34331c4fd090 |
| agent | freq_div | TopModule | 未声明parameter | 3 | 2d7e74fdd49a3d1eefa53ef69a7569463211996a297be78023b59e7d4fde4866 |
| baseline | freq_div | TopModule | 未声明parameter | 3 | 5a15bff939486228b92826855854e90d1226818d3e11d3a1532668d4213f081c |
| agent | freq_divbyeven | TopModule | NUM_DIV=6 | 3 | e0cb26403ecd04474fbc36b7931d42913a49ef439e6b4e85373517b5e5c607ee |
| baseline | freq_divbyeven | TopModule | NUM_DIV=6 | 3 | 4c66c6e0c2d683ef166dba95ebf10f2eadef0be6c8c206504f7afcfdf16cb350 |
| agent | freq_divbyfrac | TopModule | 未声明parameter | 1 | 78a81a601c4e8da67006cda3d97fea286a3652972bb9ced1ba12f6da9a9269e1 |
| baseline | freq_divbyfrac | TopModule | 未声明parameter | 1 | 7eacea05f67940946aad29b20ea4020081c4a0066c158c34452e94d12673562e |
| agent | freq_divbyodd | TopModule | NUM_DIV=5 | 1 | 0ad4bf2dd19a012ce082790bfd4441a0ee8cb60070346ed8cd7effe1fe2fb539 |
| baseline | freq_divbyodd | TopModule | NUM_DIV=5 | 1 | 82efb09ab4174c9d2eec63a68b8c613f53f7b0b233300e3551ac68818d123b72 |
| agent | fsm | TopModule | 未声明parameter | 1 | 932c2bce188ea4ec47c0f071e3d50484751e4d7aa315c6d7e256c87108a32bf8 |
| baseline | fsm | TopModule | 未声明parameter | 0 | bb109cc3a6741c8df903bcd9cc70578e79538fd32038785f8edf82950efcb979 |
| agent | instr_reg | TopModule | 未声明parameter | 3 | 454878ed74dbe192c4c5525631465526f73caaf4f088aa9387182a62cdee58ed |
| baseline | instr_reg | TopModule | 未声明parameter | 3 | 89a54006060e7cc20cdabe1206926d65bf939053abc377fb63d7050ed829210b |
| agent | JC_counter | TopModule | 未声明parameter | 3 | 91360da74af59744a9c07ecfcc00bbac34486576d9ab5822a6ab0aee2a844854 |
| baseline | JC_counter | TopModule | 未声明parameter | 3 | 91360da74af59744a9c07ecfcc00bbac34486576d9ab5822a6ab0aee2a844854 |
| agent | LFSR | TopModule | 未声明parameter | 3 | 08c807e83a55e2f17b9c913cc7e2e86490be8d431d7848f7b521aa0fd2fe0ac6 |
| baseline | LFSR | TopModule | 未声明parameter | 3 | f8e99afaa62dab380c0e17d19824a50a0fe565270d4eec21e996a562d25fc861 |
| agent | multi_16bit | TopModule | 未声明parameter | 1 | 3f4dc95dd635bcc2d8d5ca662d8ce182c62b4c713065a137c696a1abc48fddac |
| baseline | multi_16bit | TopModule | 未声明parameter | 1 | e902c2be83884de60cf76794d35a38a8b29f76c1368eea54add58cf3bf9af9e7 |
| agent | multi_8bit | TopModule | 未声明parameter | 3 | 52a2d1b74a05d9ca147497b5223e265101b0082363d919bf60a0158476d380a8 |
| baseline | multi_8bit | TopModule | 未声明parameter | 3 | c8e8219fb6ea937e534d967312df60ca5508c131f4cd92b0ea4611cec5cc7664 |
| agent | multi_booth_8bit | TopModule | 未声明parameter | 1 | 5ee4141ed2b3947974ebe47c9356d6b9efe1cc940feeb65c9c4294c52ee90df1 |
| baseline | multi_booth_8bit | TopModule | 未声明parameter | 3 | 06cb5fe2402da043be3f241a519b67eda8978f6e5798eec67f575e80107ea5da |
| agent | multi_pipe_4bit | multi_pipe_4bit | size=4 | 0 | 5b8637bbf68ade28220572db6b9a33339c1595cd94a5a3e1745369aa9ffa25f0 |
| baseline | multi_pipe_4bit | multi_pipe_4bit | size=4 | 0 | 3cf716ec38c856cdab2f88a6265b0738efa87422bd7958b40cdd2b16a3886d13 |
| agent | multi_pipe_8bit | multi_pipe_8bit | 未声明parameter | 0 | efca4f1a757aadfb37db5097637f9d13f4daaef496c1b317f331b61ed0eea311 |
| baseline | multi_pipe_8bit | TopModule | 未声明parameter | 1 | 563398d863104f888857e6b17c59ddbabb995790ab689ad5b2e0235e6e9c57f7 |
| agent | parallel2serial | TopModule | 未声明parameter | 1 | 98d9e0f8633641eaf0edf9d30223b4de62e27678cf168ba01d5420b1f1731428 |
| baseline | parallel2serial | TopModule | 未声明parameter | 1 | 13786daee1d0ffe2f2216f674b5a7c5f02a5a0421aca40b50ba33f0ba6bb4a23 |
| agent | pe | TopModule | 未声明parameter | 3 | 15bf2c059e45c12fdbd09af951c78639790202eae8191fb9f85f8fc09f85370a |
| baseline | pe | TopModule | 未声明parameter | 3 | 06b8b871868e678df70545b9097b567549ba57b74f092b10220112306f198a16 |
| agent | pulse_detect | TopModule | 未声明parameter | 1 | c2870113aee0b88d8f75e45cc10a491b0bb62595e53c5aec79aaae795860dee9 |
| baseline | pulse_detect | TopModule | 未声明parameter | 1 | 64c25d9dd84203435679c79160eb182464701506be1999c5eeb6f6a8dc207fa7 |
| agent | radix2_div | TopModule | 未声明parameter | 0 | b7024bec8343bf0d46895e17d93a019df64ce23b5fe93d2261a9e42461011743 |
| baseline | radix2_div | TopModule | 未声明parameter | 0 | dc2e2be3373025acbc4dc8e6f0a53bf044adb4d7a56efe140a9a85131237051c |
| agent | right_shifter | TopModule | 未声明parameter | 3 | e0af6d5da63848b0342f3d202aa52bb351e66ffae5b24dfc539586a34aa57aea |
| baseline | right_shifter | TopModule | 未声明parameter | 3 | dfe05538bd74928f0f21cef16a259f82603d29a70e1267fed390f574aa87e021 |
| agent | ring_counter | TopModule | 未声明parameter | 3 | b1df16ab2e109fc573385e2916e7d768657baa3582f2d3cb7781ec60d01677a2 |
| baseline | ring_counter | TopModule | 未声明parameter | 3 | b1df16ab2e109fc573385e2916e7d768657baa3582f2d3cb7781ec60d01677a2 |
| agent | sequence_detector | TopModule | 未声明parameter | 1 | d2e6dadd3c8c89c89cd25be7ae879bbe2d28cd36e768ad1d9299bcaede7bc6d0 |
| baseline | sequence_detector | TopModule | 未声明parameter | 1 | 2b6a3f33515d8c29468afc33fc357ee9f6eb997f3e28d72d874271363599971e |
| agent | serial2parallel | TopModule | 未声明parameter | 1 | fe64111c7dfe8d7c35f8724d6efac318f6140181ba1d06402d8986c38df28977 |
| baseline | serial2parallel | TopModule | 未声明parameter | 1 | be440dfff1bb54dfe81497d4616406c22bc5c01c34eb7ea7bb8e3174b29d2a77 |
| agent | signal_generator | TopModule | 未声明parameter | 3 | 3138af8b01da3a0b62eb1a8de2945a4a09bfbf17d421c0c3064c4a0410f8142a |
| baseline | signal_generator | TopModule | 未声明parameter | 3 | 6d8995a3bd92224c0184c042aa0491e08ae9062c1903d5d2e89eec941c3c6d72 |
| agent | square_wave | TopModule | 未声明parameter | 1 | 9f994355987a48cc1c127566db56ef2096233b0552dc597b2e7cf4ba57318f60 |
| baseline | square_wave | TopModule | 未声明parameter | 1 | 600c761492550b9c2170b10a958e68ca79e4d6a8e8e72d55307f0d89b644e1c2 |
| agent | sub_64bit | TopModule | 未声明parameter | 3 | 72c9fc6aa5a6e74d5753d2ac5c291feb28431bd3c1fda3ea4cee4b9183b870ab |
| baseline | sub_64bit | TopModule | 未声明parameter | 3 | 60f478538dc8275e2a87d018a1446414d0ffda27045166b9b37f495df9929494 |
| agent | synchronizer | TopModule | 未声明parameter | 3 | 01f6a9e9f229d74226f4d05f0a882118275d5651ce5f34fab76f4e5f11807c15 |
| baseline | synchronizer | TopModule | 未声明parameter | 3 | 61788269020dd3fa32a9d5b3e1eb0704cf4bb1dc977f58f1a9dbbc50358572ef |
| agent | traffic_light | TopModule | 未声明parameter | 1 | 907541d130c109ddf52c22d417e5b1a2ac0a110c89d462a1e0ef6aeda5f67990 |
| baseline | traffic_light | TopModule | 未声明parameter | 1 | fd30615be35c0d42eec7d037850eb1638dc1fa8292487b97030636a0dae8c377 |
| agent | up_down_counter | TopModule | 未声明parameter | 3 | f6dac9a3b232e70a9f37cdeb70ee8018841a71d16e88b89978561ad39a7b7df0 |
| baseline | up_down_counter | TopModule | 未声明parameter | 3 | a02e994158cbaeb488faf2caa0299a28ee004e17cf55c1219d57e0d25b794a39 |
| agent | width_8to16 | TopModule | 未声明parameter | 3 | f6fc62b1b8f3169ceb2b538c74d0124cd2da28eb72a927e5b756cda2bcc68c87 |
| baseline | width_8to16 | TopModule | 未声明parameter | 3 | a9b75e638b4ee841b02afcebc5c1d5ff87487177ab74b0c1cec7897506ce1529 |

## 本轮完成与限制

完成44行合同表、88成品目录、独立反馈交叉复核与最小修正/复用边界方案。未执行任何修正/重判/新生成；未声称原score可靠。现有prompt/ref/TB无缺项；manifest和原响应等缺项仅限制身份/提取链完整证明。
