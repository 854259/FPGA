# 队友S7原始判定器诊断复核：一条自然记录不能用于独立成绩

归档SHA `296359d8abfec37ea8f545f8630ca564cbd28964975ce9ab62e877e448b9e4bf`，46文件SHA、SOURCE_TRANSFER、源提交fe234c9、driver a120da36、私有freeze710a97e4及原S5数据cbcd8129的记录/原harness逐字节核验。只读解析记录/XML/AST，不执行归档Python/测试/驱动，不重新调用模型或EDA。复核源SHA `ccf263cffb85f639e7bf35a6f9dd91a23c11bdaf06698d91e5d8399b6c61b566`。

记录`cvdp_copilot_convolutional_encoder_0010`的原测试有完整时钟、复位、随机输入、27次输出观察，但没有assert/raise，也没有参考输出比较。原测试对两种明显错误设计（两个输出全0、两个输出全1）均真实运行330ns，原Cocotb结果1测试/0失败，进程rc0。故这条记录不能作为独立功能验证通过的依据，不能把程序正常运行当功能正确。

队友的第三个控制仅在该测试末尾加一个故意抛出的断言，用原全0稿运行；真实330ns、1测试/1失败、rc1，XML和日志中S7_FAILURE_PROPAGATION一致。它证明此运行方式能传播失败，定位误通过来自原harness没有检测错误；这是诊断控制，不能替换原题库测试，也不能计为模型求解成绩。

复核三份DUT/原harness与单断言变体、27输出观察、330ns/固定随机种子、Cocotb XML与pytest XML、原日志SHA和编译blob，重算2误通过。原历史guard的文件/模型保护、清理释放与FIFO43完成绑定。0此次模型/EDA、0独立准入/部署；不重复队友工作或改其文件。

三个原build/test记录由固定driver/runner、编译产物和定时仿真日志支持，但档案缺完整逐条native argv/rc收据；不能声称已独立重建完整编译命令序列。档案外Python/toolchain安装文件只由原freeze/driver/日志约束，未在此全部重新哈希或执行；guard仍属原历史现场证据，不是新硬件/断网验收。

只排除这一个已证实错误的判定记录，不推断CVDP全部无效。其他自然题须保留原ABI/context/harness并通过正确稿、多个错误稿和失败传播控制、完整工具证据及曝光审查，再纳入同预算独立模型验证。上一S5的54条机械可回转仍不是54条通过功能准入。

源码/原测试/RTL/控制稿/回复保留在私有档案；公共只列SHA、元数据、范围和结论。REVIEW_NOTES记录复核前的未成功schema假设，EVALUATOR_EXCLUSIONS只适用于固定数据版本。当前FSM FIFO44在运行，G3/G4/G5继续active。
