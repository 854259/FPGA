# 五样本质量脚本：评分聚合静态审查

日期：2026-10-03。状态：**当前核对版本中问题仍存在；仅新增报告，脚本未修复。**

核对分支 `feat/official-rtl-contract`，HEAD `41dec5aa8c9d99096eff5538cbea292aea914d27`。本报告依据该提交中的脚本和仓库锁定的 `afd135e7ba5f6ec4c6d77e7c927c894327537801` 判分口径；没有核查或宣称正式上游最新规则。锁定依据见 [UPSTREAM.json](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/UPSTREAM.json)。

## 原因、重点与意义

`five_sample_quality.py` 已逐样本调用判定器，但自行汇总时改变了失败分类和统计定义。下述问题可使同一批原始结果得到不同的题集得分、pass@5及增益；两个模式的受影响比例可能不同，不能假定比值会抵消偏差。

本轮只做完整文件读取、分支与源码静态核对、手工算例推导及报告发布。没有运行脚本、测试、模型、EDA或服务器操作，没有修改另一工程负责人维护的脚本。已证实收益限于定位聚合口径差异并给出可核对算例；纠正真实成绩的幅度仍未知。

## 1. 空答及请求失败被移出 pass@1 分母

[脚本第144–164行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L144-L164)把空白 `solution` 记作 `None`，再以 `graded = [x for x in levels if x is not None]` 过滤，均值只除以留下的样本数。[第55–67行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L55-L67)捕获请求异常并返回错误payload，通常也进入相同空答分支。

pinned [接口契约第118–127行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/docs/API_CONTRACT.md#L118-L127)将求解空答记为正常L0，超时、断连或格式失败也按L0处理；[judge第55–77行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/selftest/judge.py#L55-L77)对空解保留 `level=0`、`coefficient=0`、`tool_error=None`。这些求解或服务失败应保留在采样分母，不能当作判定环境错误排除。

因此，一题出现1个L3和4个空答时，脚本对唯一保留样本取均值为 **1.0**；正确计入五次尝试应为 `(1+0+0+0+0)/5 = 0.2`。全为空答时脚本的数值恰为0，不代表混合成功/空答情形的分母正确。

## 2. pass@5 改成了任一L3的二值指标

[脚本第164行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L164)使用 `1.0 if any(x == 3 ...) else 0.0`。[pinned score第98–105行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/selftest/score.py#L98-L105)采用该题可计分样本的**最高系数**：L0/L1/L2/L3分别为0/0.2/0.7/1.0，再按题平均。

五个L1应得 pass@5 **0.2**，脚本给0；五个L2应得 **0.7**，脚本也给0。脚本可另报“任一L3”的完全通过诊断，但应改名，不能把它标成这里锁定的 graded pass@5。`--samples` 可配置，报告还应声明实际采样数，避免非五样本结果继续使用固定标签。

## 3. 聚合层丢失 tool_error，环境失败被计零分

[judge第141–149行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/selftest/judge.py#L141-L149)对 `LICENSE_ERROR` 等环境或题目异常保留级别0并设置 `tool_error`。[pinned score第73–105行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/official_reference/selftest/score.py#L73-L105)排除这些样本，记录原因与 `scored_samples` / `excluded_samples`；若整题均环境失败，逐题分数为None并记录整题排除。

脚本[第155–164行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L155-L164)仅抽取 `v.get('level')`。因此1个L3加4个LICENSE_ERROR会被当作 `[3,0,0,0,0]`，pass@1为 **0.2**；pinned规则是排除4个环境错误，剩余样本均值 **1.0**，同时报告 **excluded=4、scored_samples=1**。这个1.0只有一份可评分样本支撑，不能被描述为五样本稳定通过。

原始判定信息仍通过 [run_judge第86–99行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L86-L99)调用judge落盘并读取 `verdict.json`。缺失的是 `quality.json` 汇总层的分类，不能写成“原始verdict丢失”。判定文件缺失或不可解析时函数返回空字典，后续也会出现None；应显式记录判定失败及原因，不能静默过滤或将其混同求解空答。

## 4. 默认规模及完成性

[默认题单与参数](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L41-L44)与[默认样本参数](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L102)为8题、两模式、每模式5样本，计划 **8×2×5=80** 次；156题相同协议才是 **1560** 次。脚本头部已经说明默认是子集，本报告不把它称为完整156题评测。

[第132–137行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L132-L137)遇缺题直接跳过，[第172–193行](https://github.com/854259/FPGA/blob/41dec5aa8c9d99096eff5538cbea292aea914d27/04_project/amd_rtl_agent/bench/five_sample_quality.py#L172-L193)仍按请求题数打印汇总并返回成功，`quality.json`没有明确的预期与实际覆盖或complete字段。需按预定task×mode×sample键记录缺失/已尝试/判定失败/排除，区分运行覆盖完成与可评分分母；缺题不能冒充完整80或1560次协议。

## 静态算例：直接由上述分支推导

下表均为一题、五次尝试的构造例子，**不是实际模型成绩，也不是已执行测试**。

|构造输入|脚本 pass@1|pinned pass@1|脚本 pass@5|pinned pass@5|分类说明|
|---|---:|---:|---:|---:|---|
|1×L3＋4×空答|1.0|0.2|1.0|1.0|五次求解尝试均计分，空答为L0|
|5×L1|0.2|0.2|0.0|0.2|最佳样本系数为0.2|
|5×L2|0.7|0.7|0.0|0.7|最佳样本系数为0.7|
|1×L3＋4×LICENSE_ERROR|0.2|1.0|1.0|1.0|排除4环境错误，并公开有效样本数1|

这些例子证明偏差方向可相反：过滤空答向上，环境错误计零向下，L1/L2最佳等级被二值化使pass@5向下。真实题集分数和agent/baseline增益的方向、幅度需结合原始样本分类重算，不能预先断言净影响。

## 最小修正建议与待验证项

1. 逐次保留完整判定字段，包括 `level`、`coefficient`、`tool_error`、请求失败类别和样本身份。空答及求解HTTP失败产生明确L0记录；judge环境异常保留 `tool_error`。不要让None承担多个失败含义。
2. 将标准化样本交给该锁定版本的 `score.summarize` 或 `score.collect`→`summarize` 聚合，复用排除记录、最高系数与两层平均；不要再维护一份自行过滤/二值化的评分公式。
3. 由预定任务清单核对task×mode×sample覆盖，记录计划数、尝试数、判定数、环境排除数、缺题和完成状态。完成性校验不能仅靠pinned scorer从现有文件推断。
4. 由脚本负责人按授权范围完成上述静态算例的聚合检查，并优先复用现存 `response.json`、空白解与 `verdict.json` 重建新摘要；保留旧汇总，以不同文件名或新目录发布纠正值。无需为单纯重聚合再次调用模型，但原始记录不足时须明确无法重建的样本。

建议尚未实施，本次没有验证真实样本受影响数量、修正版执行行为或赛事最终验收。报告未改变官方baseline、judge、score或任何运行参数。代码修复仍由工程负责人决定与实施。

回退：本次只有一个新增文档，可revert其提交；未来重聚合产物另存并保留旧摘要，弃用新版摘要即可回到原记录。运行代码和原始结果不依赖本报告。
