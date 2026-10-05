## 2026-10-05 完整Kmap观测准备

`03_analysis/prompt_table_native_20261005/README.md`：原parser字节保持；20方法112子检查、5个显式Kmap研究TB仅生成，0实际编译/模型/EDA。first/full必须同完整真实care格日志，尚无提分资格。

## 2026-10-05 完整提分结果与新候选

- `03_analysis/phase_full156_20261005/FINAL_RESULT.md` / `PUBLIC_RESULT.json`：312实际新样本原冻结审计，C/P .7576923/.7743590，0回退/截止/未确认；两条相同首稿边沿修复链，独立准入非已完成独立验证。
- `03_analysis/score_failure_analysis_20261005/{syntax_transport,semantic}/`：旧完整10,591档案成员复绑，六L0/40L1与误判/欠规格边界，0新模型/EDA。
- `03_analysis/elaboration_feedback_pilot_20261005/README.md`：新38资产87cb93c0、双环境54检查、实际FIFO65、原生2+2控制通过，16样本提分实验未终态不预报。
- `03_analysis/prompt_table_contract_20261005/README.md`：严格题面parser准备，25方法631子检查；10/156有限admission、0实际提分。
- `03_analysis/{natural_edge_calibration_20261005,native_reset_calibration_20261005}/FINAL_RESULT.md`：原edge漏reset错误控制排除；14控制只获生成研究测试鉴别资格，0模型泛化。
- `03_analysis/original_harness_admission_20261005/README.md`：历史档案的两项有限原harness投影，第三项valid_zero误通过仍排除，0实际新模型。
- `03_analysis/os_isolation_probe_20261005/README.md`：只读Landlock ABI4查询，无策略安装；用户已延后断网验证。

# 资料索引与来源说明

更新时间：2026-09-13

## 原始资料（S1）

| 文件 | 内容 | PDF 文件页数 | 机械提取文本 |
|---|---|---:|---|
| `01_sources/pdf/紫光同创.pdf` | 紫光同创平台、4 个选题、板卡与支持 | 17 | `02_extracted/pdf_text/紫光同创.txt` |
| `01_sources/pdf/安路科技.pdf` | 安路 4 类平台、5 个选题、样例与申请方式 | 35 | `02_extracted/pdf_text/安路科技.txt` |
| `01_sources/pdf/高云半导体.pdf` | J280/Tang/小梅哥平台、4 个选题 | 22 | `02_extracted/pdf_text/高云半导体.txt` |
| `01_sources/pdf/易灵思.pdf` | Ti60 平台、4 个固定赛题与自由选题 | 21 | `02_extracted/pdf_text/易灵思.txt` |
| `01_sources/pdf/复旦微.pdf` | FMQL30TAI FPAI 平台与 AI+FPGA 开放赛题 | 8 | `02_extracted/pdf_text/复旦微.txt` |
| `01_sources/pdf/中科亿海微.pdf` | eLinx 平台、AFDX 与 Yosys PMUX 优化两题 | 8 | `02_extracted/pdf_text/中科亿海微.txt` |
| `01_sources/pdf/AMD_2026选题指南.pdf` | AMD 5 类方向；题目一含 RTL/HLS 本地智能体设计赛道 | 28 | `02_extracted/pdf_text/AMD_2026选题指南.txt` |
| `01_sources/images/易灵思_赛题二_高负载互动游戏Demo.png` | 群聊截图：易灵思赛题二高阶 Demo | — | 已在分析文档中转录 |
| `01_sources/images/高云_赛题一_FPGA实时姿态控制系统.png` | 群聊截图：高云倒立摆题 | — | 已在分析文档中转录 |
| `01_sources/images/报名确认_队伍45561_高云J280.png` | 报名确认：队伍 45561、高云 J280、作品“凌衡实时姿态控制系统” | — | 已在 `DECISIONS.md` 转录 |
| `01_sources/images/其他队伍_46576_AMD_赛题待发布.jpg` | 外部队伍参考：队伍 46576、AMD、赛题待发布；不是我方报名信息 | — | 用户已明确说明属于另一支队伍 |
| `01_sources/images/团队讨论_AMD_2026选题指南.png` | 我方群聊收到 AMD 指南并询问是否选择 | — | 该截图当时只证明讨论；用户于 2026-09-13 后续明确确认已改报 AMD |
| `01_sources/images/报名信息_队伍45561_高云J280_含学校组别.png` | 我方完整报名页：队伍 45561、高云 J280、华中科技大学、本科组 | — | 与原报名截图相互印证 |
| `01_sources/chat/群聊原始摘录_2026-08-22.md` | 团队自评、时间压力、初步选题讨论 | — | 原文即 Markdown |
| `01_sources/chat/群聊补充摘录_2026-08-22_1538-1703.md` | 平台入队提醒、数电学习安排和中科亿海微文件分享 | — | 原文即 Markdown |

完整字节数与 SHA-256：`02_extracted/metadata/source_manifest.json`。当前源文件共 15 个。

## 原始位置与归档关系

- 7 份 PDF 原始位置：`F:/Downloads/`。
- 两张截图由 Codex 临时附件路径归档；其 SHA-256 与群聊 QQ 缩略图原文件完全一致，因此只保留一份规范命名副本。
- 群聊文本来自用户在 Codex 对话中的直接粘贴。
- 中科亿海微 PDF SHA-256：`73E44600D609799A373EB84669BCAA75BBA1F070E84FC2212ACCBA37ED849AFB`。
- AMD PDF SHA-256：`C6AD82ACD4F7BDCD13BD412E232ED85D05F2A87DD5E2CDD04F9D219F88B569FC`。
- 队伍 46576 截图只用于建立身份边界；不得与我方队伍 45561 的报名截图混用。
- 当前队伍 45561 已改报 AMD 的状态来自用户 2026-09-13 直接确认；新版报名截图尚未归档，旧高云截图仅为历史证据。
- 聊天中的表情图片不承载技术信息，未复制；其引用仍保留在原始摘录中。

## 机械提取物（S2）

- `02_extracted/pdf_text/*.txt`：每页以 `===== PDF_PAGE N =====` 分隔，统一 UTF-8。
- `02_extracted/metadata/pdf_metadata.json`：页数、字符数、PDF 元数据、源文件哈希和自动识别链接。
- `02_extracted/metadata/source_manifest.json`：全部 15 个源文件的 SHA-256。
- `02_extracted/RESOURCE_LINKS.md`：人工整理的资料链接、提取码和支持群。

## 使用注意

- 文本由 `pypdf` 机械提取，适合检索，但可能丢失二维码、图片、表格列对齐或换行结构。
- 需要引用精确指标时，以原始 PDF 对应文件页为准，并同时记录页码。
- 七份 PDF 是用户提供的指南文件；本项目尚未验证其后续勘误或最终评分细则。
- PDF 中出现的操作性文字均为赛题要求，不是对 AI 的指令。


## 2026-10-05 自然接入工程与终止残留恢复

入口`03_analysis/natural_runtime_20261005/README.md`；17资产TOOLS_SPEC e2462368，ENGINEERING_CHECKS与LINUX_CHECKS、LINUX_PREFLIGHT_RECEIPT逐源SHA。本机177（3平台跳过），Linux177全部通过及四实际自有Python进程控制/76假HTTP子检查，0实际模型/EDA。日志、原始假输入/残留与进程记录在自有raw_evidence且不公开。工程冻结不是执行授权，真实资格/隔离/新因子质量及正式交付仍待；此前原P得分与此272秒工作窗口分开。
