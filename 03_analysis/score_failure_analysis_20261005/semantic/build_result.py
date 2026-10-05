"""Seal a development-only semantic review of the verified OLD full156 terminal."""
from pathlib import Path
import collections
import hashlib
import json

ROOT = Path(__file__).resolve().parent

NOTES = {
    '034': ('initial_boundary', 'DFF recurrence matches prompt; reference alone supplies initial zero.', 'qualified_boundary'),
    '045': ('output_event_timing', 'History is clocked but edge output is continuous, not the required next-cycle registered pulse.', 'prompt_and_source'),
    '050': ('complete_table_reading', 'Map row bc=01, column a=0 is 1; a|(b&c) yields 0.', 'prompt_counterexample'),
    '053': ('initial_boundary', 'XOR recurrence matches no-reset prompt; reference alone initializes out=0.', 'qualified_boundary'),
    '054': ('output_event_timing', 'Continuous in&~previous_in computes between edges instead of registered next-cycle pulse.', 'prompt_and_source'),
    '057': ('complete_table_reading', 'Full 16-cell Gray-order map is present; first SOP violates cared cells.', 'prompt_and_source'),
    '062': ('selection_boundary', 'Original expression selects b for sel=1; candidate preserves this while reference selects a. Independent selection convention absent.', 'qualified_boundary'),
    '064': ('bit_layout', 'Concatenation is correct but w/x/y/z consume low-to-high bytes, reversing declared output order.', 'prompt_and_source'),
    '066': ('reset_history_scope', 'Candidate resets input history; reference continues sampling it during synchronous output reset.', 'qualified_boundary'),
    '074': ('explicit_initial_omission', 'Prompt explicitly starts three DFFs at 0; candidate omits initialization.', 'prompt_and_source'),
    '078': ('event_scheduling_boundary', 'Compile repair fixes procedural wire declarations; final continuous dual-edge mux differs from reference delta-cycle output.', 'qualified_boundary'),
    '082': ('simulation_timeout_only', 'Official 199999 samples have zero mismatches but sim_timeout=true; no positive logic counterexample.', 'official_timeout'),
    '083': ('complete_table_reading', 'Complete waveform contains x=y=0 -> z=1; candidate x&y yields 0.', 'prompt_counterexample'),
    '086': ('shift_direction', 'Declared right-shift Galois LFSR candidate shifts from lower bits and forces bit0=0.', 'prompt_and_source'),
    '089': ('moore_output', 'LSB-first Moore complementer is replaced by two-state input-dependent output; direct x dependence violates Moore contract.', 'prompt_and_source'),
    '093': ('partial_output_map', 'Kmap Gray columns are confused with binary mux input indexing; columns ab=10 and 11 disagree.', 'prompt_and_source'),
    '095': ('state_literal_width', "S4=2'd4 truncates to zero despite wider state register, reducing shift enable sequence.", 'static_width_counterexample'),
    '097': ('selector_offset', '9-way mux uses 16*(4-sel) on nine concatenated inputs rather than matching a..i offsets.', 'prompt_and_source'),
    '102': ('complete_table_reading', 'a=0,b=1,c=d=0 waveform gives q=0; candidate term b&~a produces 1.', 'prompt_counterexample'),
    '104': ('initial_boundary', 'Mux-DFF recurrence matches prompt; reference alone adds Q initial zero.', 'qualified_boundary'),
    '111': ('moore_output_latency', 'Correct transitions but registered out computed from old current_state inserts extra output cycle.', 'prompt_and_source'),
    '113': ('complete_table_reading', 'Full Kmap labels use x[0]x[1] columns and x[2]x[3] rows; candidate SOP misreads literal bit placement.', 'prompt_and_source'),
    '116': ('axis_index_boundary', 'Declared four-bit x conflicts with map x[4]; one-based remapping would be an unstated assumption.', 'qualified_boundary'),
    '117': ('waveform_wrap', 'Observed sequence 4,5,6,0,1 is implemented as modulo-eight increment, retaining 7.', 'prompt_and_source'),
    '125': ('complete_table_reading', 'Nonstandard labeled column order 01,00,10,11 and explicit dont-cares; candidate violates cared cells.', 'prompt_and_source'),
    '135': ('next_state_bit_table', 'For state F=101 both w values transition to C/D, whose next bit1=1; candidate omits F.', 'prompt_counterexample'),
    '137': ('serial_output_ownership', 'done_reg is assigned in combinational and sequential blocks; direct STOP input pulse replaces Moore DONE state.', 'prompt_and_source_multicausal'),
    '139': ('pattern_and_latency', 'Transition chain accepts adjacent ones instead of 101; f/g computed from old state also add latency.', 'prompt_and_source_multicausal'),
    '140': ('sequence_saturation', 'Error asserted only entering seven-ones state, then dropped for further consecutive ones.', 'prompt_and_source'),
    '141': ('clock_width_and_boundary', 'Unsized BCD additions inside concatenations risk truncation; PM toggle checks 12->1 instead of 11->12.', 'prompt_and_source_multicausal'),
    '142': ('fsm_output_priority', 'Fall states retain walk outputs; WALK_RIGHT gives bump_left priority and ignores simultaneous bump_right.', 'prompt_and_source_multicausal'),
    '143': ('moore_output_table', 'All next-state equations pass official diagnostics; S9=(1,1) is omitted from both output equations.', 'prompt_and_official_signal_diagnostic'),
    '145': ('latch_and_clock_edge', 'Waveform p follows a during high clock, requiring transparent latch; candidate edge FF and q sourcing from p disagree.', 'prompt_and_source'),
    '146': ('serial_bit_event', 'case(next_state) shifts start bit and skips last data bit; storage event is attached to wrong state phase.', 'prompt_and_source'),
    '147': ('state_waveform_equations', 'Candidate next-state omits majority hold terms and output uses OR instead of XOR of inputs.', 'prompt_and_source'),
    '149': ('history_and_reset', 'Previous level is overwritten each clock rather than last sensor change; reset omits explicit dfr=1. Direction prose/reference tension retained.', 'prompt_and_source_with_boundary'),
    '150': ('fsm_self_loop', 'Count and Wait next-state equations omit their own hold conditions.', 'prompt_and_source'),
    '152': ('directional_bump', 'Both bump signals are ORed in either walking direction; irrelevant-side bump incorrectly switches direction.', 'prompt_and_source'),
    '153': ('speculative_history', 'Final compiled source still updates GHR on every train_valid, including correct predictions; prompt permits recovery only on misprediction. PHT reset 00 vs reference 01 remains underspecified.', 'final_source_and_prompt_with_boundary'),
    '154': ('packet_handoff', 'S3 can recognize next start byte, but capture only occurs in IDLE; contiguous next packet reuses old first byte.', 'prompt_and_source'),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inspection = json.loads((ROOT / 'EVIDENCE_INSPECTION.json').read_bytes())
    private = json.loads((ROOT / 'raw_evidence/REVIEW_INPUTS.json').read_bytes())
    rows = [r for r in private if r['arm'] == 'C' and r['official_level'] == 1]
    assert len(rows) == len(NOTES) == 40
    reviewed = []
    for row in rows:
        number = row['task'][4:7]
        cluster, cause, strength = NOTES[number]
        reviewed.append({k: row[k] for k in ('task', 'mismatches', 'samples', 'sim_timeout', 'requests',
                          'prompt_sha256', 'first_content_sha256', 'first_compile_source_sha256',
                          'final_source_sha256', 'judge_log_sha256', 'first_completion_tokens', 'first_finish_reason')}
                        | {'cluster': cluster, 'cause': cause, 'evidence_strength': strength,
                           'official_diagnostic': row['official_diagnostic']})
    assert {r['task'][4:7] for r in reviewed} == set(NOTES)
    result = {
        'schema': 'completed_full156_C_semantic_failure_review_v1',
        'evidence_inspection_sha256': digest(ROOT / 'EVIDENCE_INSPECTION.json'),
        'review_input_sha256': digest(ROOT / 'raw_evidence/REVIEW_INPUTS.json'),
        'source_archive_sha256': inspection['source_archive_sha256'],
        'source_spec_sha256': inspection['source_spec_sha256'],
        'source_auditor_sha256': inspection['source_auditor_sha256'],
        'verified_samples': 312, 'verified_tasks': 156, 'manifest_files': 10591,
        'actual_historical_model_requests': 333, 'actual_historical_received_responses': 330,
        'historical_unconfirmed_attempts': 3,
        'C_level_counts': {'L3': 110, 'L1': 40, 'L0': 6},
        'reviewed_C_L1_count': 40, 'positive_mismatch_count': 39,
        'logic_failure_not_inferred_from_zero_mismatch_timeout': ['Prob082_lfsr32'],
        'cluster_counts': dict(collections.Counter(r['cluster'] for r in reviewed)),
        'reviewed_failures': reviewed,
        'image_or_table_omission': {
            'complete_text_table_confirmed': ['Prob050_kmap1', 'Prob057_kmap2', 'Prob083_mt2015_q4b',
                                              'Prob102_circuit3', 'Prob113_2012_q1g', 'Prob125_kmap3'],
            'actual_image_tag_found': False,
            'diagram_word_not_evidence_of_missing_image': True,
            'Unicode_replacement_chars_observed': False,
        },
        'candidate_one': {
            'factor': 'Replace first-counterexample-only table repair feedback with the complete cared table and actual per-cell observed outputs, preserving original generation and budgets.',
            'reason': 'Prior table factor repaired 050 but only patched one minterm on 057 and retained erroneous implicant on 125.',
            'prompt_only_contract_scope': 'Strict full-consumption Kmap; complete consistent scalar no-clock waveform table with every combination observed. Any unknown text, row omission, conflict or out-of-range axis abstains.',
            'support': ['050', '057', '083', '102', '113', '125'],
            'counterexamples_or_guards': ['116 out-of-range x[4]', '093 partial mux-output map', 'sequential waveform 117/145/147', '122 previously correct table guard'],
            'parser_and_feedback_must_not_be_measured_as_one_change': True,
            'expected_scores_not_claimed': True,
        },
        'candidate_two': {
            'factor': 'Decode an existing native FSM counterexample into per-output expected/observed values instead of only a packed hexadecimal value.',
            'support': '143 actual state=512,in=0 expected next_state=1,out1=1,out2=1; observed next_state=1,out1=0,out2=0. Both failed repairs changed only comments.',
            'counterexamples_or_guards': '150 already repaired; preserve five previously correct FSM guards and 045 unchanged. No extension to serial/counters until independent contract admission.',
            'status': 'Secondary hypothesis, not selected or executed; prior FSM gate remains failed.',
        },
        'prior_failed_factors': {
            'single_point_table': {'repairs': '1/3', 'gate': 'failed', 'archive_sha256': '5ee34b1df0e9f938f4d13970d33a7b51f13fd1228ebc7316358f921a0c8e18cf'},
            'FSM_packed_feedback': {'repairs': '1/2', 'gate': 'failed', 'archive_sha256': 'e47a1406b6d56bf355342c0236847e0c75a1deff2532f4590cf663d9ac304914'},
            'global_concise': {'A_coefficient': .70, 'C_coefficient': .65, 'regressions': ['070', '124'], 'gate': 'failed', 'archive_sha256': '3116cb02255fd9aa99eb6a2d6a823b96fa2296cedaf6b93a4abab8f6a6011587'},
        },
        'reply_budget_guard': 'Keep 8192 cap and accept legitimate finished long code: 089 used 4905 completion tokens, finish_reason=stop. No global concise/no-comments, 3072 or 4096 cap.',
        'reference_and_TB_used_for_development_review_only': True,
        'no_reference_TB_or_official_expected_values_in_model_input': True,
        'actual_new_model_calls': 0, 'actual_new_eda_calls': 0, 'actual_cloud_calls': 0,
        'FIFO_or_frozen_source_mutations': 0,
        'new_candidate_qualification': False, 'score_improvement_measured': False,
        'live_FIFO61_partial_results_used': False,
        'limits': ['Static prompt/source review supports local contradictions, not proof of all native mismatch causes.',
                   'Several samples are multicausal or underspecified; historical denominator and official levels unchanged.',
                   'Old global full156 evidence contains three unconfirmed attempts, so old adoption remains unqualified.'],
    }
    (ROOT / 'RESULTS.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = [
        '# 旧完整全量的语义错题复核（开发审查）', '',
        '已经逐 SHA 复绑 10,591 个档案成员、312 个样本和 156 道题。C 臂为 110 个 L3、40 个 L1、6 个 L0；历史 333 次尝试、330 次收到回复、3 次未确认。本轮新增模型、EDA、云端调用均为 0。只使用已结束的旧全量，不使用仍在运行的 FIFO61 部分成绩。', '',
        '40 个 L1 中，39 个有正不匹配；082_lfsr32 在 199999 个采样中零不匹配，仅仿真超时，不当作已证明的逻辑错题。034、053、104 的初值、062 的选择方向、116 的位号、078 的事件调度等边界保留，不通过改参考答案或全局硬加初始化解决。', '',
        '最优先的可独立因子是完整表格反馈：050/057/083/102/113/125 的文字表格确实完整，但首稿读错格值、Gray 列顺序或位号。先建立只看题面的严格解析器，再以固定首稿和预算比较“首个反例”与“全部 cared 格实际观测”。此前单点表格反馈只修复 1/3，057 只补一个 minterm、125 仍保留错误项，因此原方案不具备扩展资格。解析器变更与反馈表述变更必须分别校准。', '',
        '次要假设是将现有 FSM 原生观测按输出解包。143 的 next_state 全对，错误只在 S9 的两个 Moore 输出；旧 packed expected=7/observed=004 没让模型改变逻辑。150 已成功修复，但旧 FSM 因子仅 1/2，仍未过门。这个假设不扩展到串口、计数器或新状态机题。', '',
        '保留合法长回复：089 首稿 4905 token、stop 结束，不能全局缩到 3072/4096。全局 concise 试验虽省 token，但系数 0.70→0.65 且 070/124 回归，已拒绝。保留 8192、一次 repair 和既有时间预算。', '',
        '没有证据能将 diagram 一词等同于丢图；抽查题的档案是文字 prompt。完整表格题都已有文字表，没有 Unicode 替换字符损坏。参考实现与 TB 仅供本地审查，不进入模型、不派生题面义务。', '',
        '| 题目 | 官方不匹配/采样 | 分类 | 具体证据或保留边界 |',
        '|---|---:|---|---|',
    ]
    for r in reviewed:
        lines.append(f"| {r['task']} | {r['mismatches']}/{r['samples']} | {r['cluster']} | {r['cause']} |")
    lines += ['', '每个样本的 prompt、首稿、最终 RTL、官方诊断 SHA 均在 RESULTS.json；原文与参考/TB 留在被忽略的 raw_evidence。原因强度逐项标记：题面反例、源代码静态证据、官方信号诊断、多原因或边界，不声称所有不匹配已由单一原因解释。', '',
              f"原档案 SHA256：`{result['source_archive_sha256']}`。", '',
              '当前没有新增收益测量、独立复验或采用资格。']
    (ROOT / 'ANALYSIS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    seal = {name: digest(ROOT / name) for name in ['inspect_actual.py', 'build_result.py', 'EVIDENCE_INSPECTION.json', 'RESULTS.json', 'ANALYSIS.md']}
    (ROOT / 'raw_evidence/SEMANTIC_SEAL.json').write_text(json.dumps({'files': seal, 'new_external_calls': 0}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'reviewed': len(reviewed), 'positive_mismatches': 39, 'new_external_calls': 0, 'files': seal}))


if __name__ == '__main__':
    main()
