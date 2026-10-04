# 编译缺口跨任务盘点：静态疑点不作为修复收益

完成1024条历史自然候选的只读盘点，511个独特题面／源码对。**常数越界疑点只有已见adder_8bit，其他任务为0；不据此扩大自动位宽修复。** 现有开发runtime的缺辅助模块提示命中11条、6个任务，下一轮优先在不同组合数学任务上验证完整回复抽取。

| 已核验项目 | 结果 |
|---|---:|
| 历史记录／独特题面源码对 | 1024／511 |
| 简单内部数值向量声明 | 444 |
| 常数索引疑点 | 1条，adder_8bit |
| 其他任务的同类疑点 | 0 |
| 原runtime缺模块提示 | 11条、6任务 |
| 历史agent编译缺口上下文 | 6条、2任务、4独特源码 |
| 历史判定日志 | 1024份，全部空文件 |
| 元数据归档SHA | 3083文件全部通过 |
| 本地边界测试 | 16项通过 |
| 新模型／EDA／功能判定 | 0／0／0 |

## 来源与方法

沿用前阶段natural_coverage的冻结源包，整体SHA `c35e8c7e8a1c699aea6028cf3774f7b1797d52015a553440a49eb7d90cf8cfcc`，覆盖三轮156题配对及一轮历史RTLLM 44题配对。PAIR_MANIFEST中的每个公开题面／源码SHA与此次云端原文件重新读取值相同，扫描前后不变；各experiment哈希仍与原证据匹配。

云端仅复制旧verdict、trace和判定日志到自己的 `/workspace/team/runs/fpga_owner/compiler_inventory_20261004_v1`，不启动模型或EDA，不使用或修改GPU／SLOT锁，不触碰对方运行目录。所有3083元数据文件与ZIP整体SHA验证通过。分析在独立本地工作区执行，重复完整扫描结果及私有SCAN.json字节一致。

`RUN_SPEC.json`在元数据收集与完整候选扫描之前冻结9项代码／测试文件。`runtime_snapshot.py`是当前开发728499f4字节快照，只调用原有纯函数undefined_submodules，未改生产代码。`literal_bounds.py`只识别单名、内部、纯数值packed声明以及直接十进制bit-select；注释／字符串遮蔽，重复声明弃权。不展开参数或generate，不检查端口、part-select或复杂作用域。16项测试覆盖有效边界、注释／字符串、层次引用、多个模块、重名及不支持结构。初版漏掉同一行块内重名，1项测试失败；原代码和失败输出保留，再扩大弃权识别后全通过。修正发生在冻结及候选扫描之前。

没有提示不代表源码正确。提示只用于安排实际工具验证，既不修改源码，也不证明编译错误。旧verdict及trace没有在生成时绑定候选SHA；此次匹配证明现有归档身份一致，不能把trace中某次编译与最终源码强行绑定。所有旧判定日志为空，本轮未取得新的真实报错全文；不把历史L0、静态疑点或模型修复线索当成新功能等级。

## 判断与下一步

缺模块提示涉及Prob078_dualedge、adder_8bit、adder_16bit、adder_32bit、barrel_shifter、div_16bit。历史完整回复未保存，不能判断各自属于输出遗漏还是抽取丢失。本轮不恢复虚构helper，也不按题名补功能。

历史编译缺口只有Prob099与Prob156的三轮重复。它们不是新发现的独立自然错误：

- [先前离线复盘](../09_新版156题离线复盘_20260921.md)已记录Prob099的题面／参考Y1/Y3与TB Y2/Y4接口不一致，并有参考自比展开失败；本轮不重跑或改官方判定，不据L0认定需要改候选端口。
- [先前156题展开覆盖](../35_xelab展开检查_覆盖与成本实测_20261003.md)已检测Prob156多驱动；[R1六调用](../codex_takeover_20261003/R1_RESULT.md)直接诊断与普通复查均0/3展开通过，未晋级。本轮静态盘点不覆盖或重算这些结果。全量展开的旧成本条件也不能自动推广到新模型或基准时间。

RESULTS的known_development_task仅表示RUN_SPEC预列的当前位宽研究任务集合，不能解释为该任务未被项目其他研究使用。后置INTERPRETATION.json明确登记上述既有研究；冻结扫描结果保持。

下一项先校准adder_16bit、adder_32bit和barrel_shifter的公开数学契约及正负控制；只消除题面双模块名冲突并保留原文。沿用已冻结完整模块抽取器，不按此盘点改规则；在同一份新完整回复上比较两臂。这些任务按既有缺模块机制选择，属于目标机制覆盖验证，不是随机盲测、总分或pass@5。div_16bit的时序规格未确认，暂不混入组合数学检查。其他任务占用云端时只准备本地材料，实际EDA／模型阶段仍必须经双锁。

## 复核与归档

Git只提交源码、冻结规格与摘要。私有corpus.zip、metadata.zip和本机解压目录被忽略；元数据ZIP整体SHA见ARCHIVE.json，逐文件清单在raw_evidence/MANIFEST.json。local_audit_bundle.zip另保存冻结本地代码、完整SCAN、结果和源包，整体与逐项SHA见ARCHIVE及LOCAL_AUDIT_MANIFEST。

准备好两份私有ZIP及对应解压目录后，在仓库根目录运行，不调用模型／EDA：

```text
python -B -m unittest discover -s 03_analysis/compiler_inventory_20261004 -p test_literal_bounds.py -v
python -B 03_analysis/compiler_inventory_20261004/scan.py
```

没有部署，没有新的收益或成绩。用户提醒的同步开发约束继续生效：只更新独立分支，实例和共享模型持续运行。
