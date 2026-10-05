# 旧完整全量的语义错题复核（开发审查）

已经逐 SHA 复绑 10,591 个档案成员、312 个样本和 156 道题。C 臂为 110 个 L3、40 个 L1、6 个 L0；历史 333 次尝试、330 次收到回复、3 次未确认。本轮新增模型、EDA、云端调用均为 0。只使用已结束的旧全量，不使用仍在运行的 FIFO61 部分成绩。

40 个 L1 中，39 个有正不匹配；082_lfsr32 在 199999 个采样中零不匹配，仅仿真超时，不当作已证明的逻辑错题。034、053、104 的初值、062 的选择方向、116 的位号、078 的事件调度等边界保留，不通过改参考答案或全局硬加初始化解决。

最优先的可独立因子是完整表格反馈：050/057/083/102/113/125 的文字表格确实完整，但首稿读错格值、Gray 列顺序或位号。先建立只看题面的严格解析器，再以固定首稿和预算比较“首个反例”与“全部 cared 格实际观测”。此前单点表格反馈只修复 1/3，057 只补一个 minterm、125 仍保留错误项，因此原方案不具备扩展资格。解析器变更与反馈表述变更必须分别校准。

次要假设是将现有 FSM 原生观测按输出解包。143 的 next_state 全对，错误只在 S9 的两个 Moore 输出；旧 packed expected=7/observed=004 没让模型改变逻辑。150 已成功修复，但旧 FSM 因子仅 1/2，仍未过门。这个假设不扩展到串口、计数器或新状态机题。

保留合法长回复：089 首稿 4905 token、stop 结束，不能全局缩到 3072/4096。全局 concise 试验虽省 token，但系数 0.70→0.65 且 070/124 回归，已拒绝。保留 8192、一次 repair 和既有时间预算。

没有证据能将 diagram 一词等同于丢图；抽查题的档案是文字 prompt。完整表格题都已有文字表，没有 Unicode 替换字符损坏。参考实现与 TB 仅供本地审查，不进入模型、不派生题面义务。

| 题目 | 官方不匹配/采样 | 分类 | 具体证据或保留边界 |
|---|---:|---|---|
| Prob034_dff8 | 1/41 | initial_boundary | DFF recurrence matches prompt; reference alone supplies initial zero. |
| Prob045_edgedetect2 | 212/228 | output_event_timing | History is clocked but edge output is continuous, not the required next-cycle registered pulse. |
| Prob050_kmap1 | 49/219 | complete_table_reading | Map row bc=01, column a=0 is 1; a|(b&c) yields 0. |
| Prob053_m2014_q4d | 1/100 | initial_boundary | XOR recurrence matches no-reset prompt; reference alone initializes out=0. |
| Prob054_edgedetect | 206/227 | output_event_timing | Continuous in&~previous_in computes between edges instead of registered next-cycle pulse. |
| Prob057_kmap2 | 76/232 | complete_table_reading | Full 16-cell Gray-order map is present; first SOP violates cared cells. |
| Prob062_bugs_mux2 | 109/114 | selection_boundary | Original expression selects b for sel=1; candidate preserves this while reference selects a. Independent selection convention absent. |
| Prob064_vector3 | 126/126 | bit_layout | Concatenation is correct but w/x/y/z consume low-to-high bytes, reversing declared output order. |
| Prob066_edgecapture | 99/266 | reset_history_scope | Candidate resets input history; reference continues sampling it during synchronous output reset. |
| Prob074_ece241_2014_q4 | 45/118 | explicit_initial_omission | Prompt explicitly starts three DFFs at 0; candidate omits initialization. |
| Prob078_dualedge | 93/224 | event_scheduling_boundary | Compile repair fixes procedural wire declarations; final continuous dual-edge mux differs from reference delta-cycle output. |
| Prob082_lfsr32 | 0/199999 | simulation_timeout_only | Official 199999 samples have zero mismatches but sim_timeout=true; no positive logic counterexample. |
| Prob083_mt2015_q4b | 21/110 | complete_table_reading | Complete waveform contains x=y=0 -> z=1; candidate x&y yields 0. |
| Prob086_lfsr5 | 4412/4443 | shift_direction | Declared right-shift Galois LFSR candidate shifts from lower bits and forces bit0=0. |
| Prob089_ece241_2014_q5a | 210/436 | moore_output | LSB-first Moore complementer is replaced by two-state input-dependent output; direct x dependence violates Moore contract. |
| Prob093_ece241_2014_q3 | 38/60 | partial_output_map | Kmap Gray columns are confused with binary mux input indexing; columns ab=10 and 11 disagree. |
| Prob095_review2015_fsmshift | 2/200 | state_literal_width | S4=2'd4 truncates to zero despite wider state register, reducing shift enable sequence. |
| Prob097_mux9to1v | 117/220 | selector_offset | 9-way mux uses 16*(4-sel) on nine concatenated inputs rather than matching a..i offsets. |
| Prob102_circuit3 | 35/121 | complete_table_reading | a=0,b=1,c=d=0 waveform gives q=0; candidate term b&~a produces 1. |
| Prob104_mt2015_muxdff | 1/199 | initial_boundary | Mux-DFF recurrence matches prompt; reference alone adds Q initial zero. |
| Prob111_fsm2s | 94/241 | moore_output_latency | Correct transitions but registered out computed from old current_state inserts extra output cycle. |
| Prob113_2012_q1g | 31/100 | complete_table_reading | Full Kmap labels use x[0]x[1] columns and x[2]x[3] rows; candidate SOP misreads literal bit placement. |
| Prob116_m2014_q3 | 6/100 | axis_index_boundary | Declared four-bit x conflicts with map x[4]; one-based remapping would be an unstated assumption. |
| Prob117_circuit9 | 196/245 | waveform_wrap | Observed sequence 4,5,6,0,1 is implemented as modulo-eight increment, retaining 7. |
| Prob125_kmap3 | 33/232 | complete_table_reading | Nonstandard labeled column order 01,00,10,11 and explicit dont-cares; candidate violates cared cells. |
| Prob135_m2014_q6b | 13/100 | next_state_bit_table | For state F=101 both w values transition to C/D, whose next bit1=1; candidate omits F. |
| Prob137_fsm_serial | 72/905 | serial_output_ownership | done_reg is assigned in combinational and sequential blocks; direct STOP input pulse replaces Moore DONE state. |
| Prob139_2013_q2bfsm | 726/1002 | pattern_and_latency | Transition chain accepts adjacent ones instead of 101; f/g computed from old state also add latency. |
| Prob140_fsm_hdlc | 174/801 | sequence_saturation | Error asserted only entering seven-ones state, then dropped for further consecutive ones. |
| Prob141_count_clock | 199580/199999 | clock_width_and_boundary | Unsized BCD additions inside concatenations risk truncation; PM toggle checks 12->1 instead of 11->12. |
| Prob142_lemmings2 | 50/441 | fsm_output_priority | Fall states retain walk outputs; WALK_RIGHT gives bump_left priority and ignores simultaneous bump_right. |
| Prob143_fsm_onehot | 27/224 | moore_output_table | All next-state equations pass official diagnostics; S9=(1,1) is omitted from both output equations. |
| Prob145_circuit8 | 156/240 | latch_and_clock_edge | Waveform p follows a during high clock, requiring transparent latch; candidate edge FF and q sourcing from p disagree. |
| Prob146_fsm_serialdata | 62/905 | serial_bit_event | case(next_state) shifts start bit and skips last data bit; storage event is attached to wrong state phase. |
| Prob147_circuit10 | 20/232 | state_waveform_equations | Candidate next-state omits majority hold terms and output uses OR instead of XOR of inputs. |
| Prob149_ece241_2013_q4 | 1666/2040 | history_and_reset | Previous level is overwritten each clock rather than last sensor change; reset omits explicit dfr=1. Direction prose/reference tension retained. |
| Prob150_review2015_fsmonehot | 23/300 | fsm_self_loop | Count and Wait next-state equations omit their own hold conditions. |
| Prob152_lemmings3 | 56/443 | directional_bump | Both bump signals are ORed in either walking direction; irrelevant-side bump incorrectly switches direction. |
| Prob153_gshare | 529/1083 | speculative_history | Final compiled source still updates GHR on every train_valid, including correct predictions; prompt permits recovery only on misprediction. PHT reset 00 vs reference 01 remains underspecified. |
| Prob154_fsm_ps2data | 434/1619 | packet_handoff | S3 can recognize next start byte, but capture only occurs in IDLE; contiguous next packet reuses old first byte. |

每个样本的 prompt、首稿、最终 RTL、官方诊断 SHA 均在 RESULTS.json；原文与参考/TB 留在被忽略的 raw_evidence。原因强度逐项标记：题面反例、源代码静态证据、官方信号诊断、多原因或边界，不声称所有不匹配已由单一原因解释。

原档案 SHA256：`ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055`。

当前没有新增收益测量、独立复验或采用资格。
