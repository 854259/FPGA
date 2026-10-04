"""Bind human review of the 44 archived A failures to prompt/DUT bytes only.

No generated answer, model request, EDA invocation, reference RTL or TB read.
Four historical external judge logs are read only to distinguish failure phases.
"""
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
ARCHIVE = REPO / '03_analysis/full156_postflight_20261004/raw_evidence/full312.zip'
ARCHIVE_SHA = '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'

# Human annotations are hypotheses unless a separate native evidence directory is named.
NOTES = {
 '034': ('unlocalized', '题面仅8位上升沿DFF；q<=d表面一致，未声明复位/初始化，不补造初值。'),
 '045': ('native_pending', '组合pulse由旧输入与新输入异或，在更新历史后脉冲消失；边沿校准票28待执行。'),
 '050': ('prior_native_witness', '卡诺图2/8失配已有原生证据；单反例及完整care反馈均可修此已知题，三题门槛仍未达。'),
 '053': ('unlocalized', 'q<=in^q符合反馈XOR文字，但初始状态未声明；不能把未知状态默认成零。'),
 '054': ('native_pending', '组合上升pulse在历史更新后消失；时钟边沿题面未指定，正负边沿均须作为正确控制。'),
 '057': ('prior_native_witness', '卡诺图6/16失配已有原生证据；两种反馈仍未修好，不重复宣称有效。'),
 '062': ('spec_uncertainty', '八位mux与文字接口表面一致；标量/向量意图需分开，不靠参考答案改规格。'),
 '064': ('spec_uncertainty', '高低位w/z打包次序不能凭变量顺序确定，尚未定位可靠题面契约。'),
 '066': ('unlocalized', '下降沿粘滞捕获结构基本一致；需检查复位释放与历史初始化边界，静态未证实原因。'),
 '074': ('static_hypothesis', '题面明确三个DFF初值为零，而稿中三个寄存器无初始化；须原生验证启动边界。'),
 '078': ('unlocalized', '两边沿寄存器加时钟mux表面可实现双边沿采样；delta/切换时序仍未定位。'),
 '082': ('static_hypothesis', 'Galois LFSR next位重复连续驱动且部分反馈使用next自身；需独立原生控制定位。'),
 '083': ('static_contradiction', '题面波形00时输出1；稿x&y在00时为0，至少一明确组合观察不一致。'),
 '089': ('static_hypothesis', '题面要求Moore串行二补数；稿输出依赖当前输入，首个1后状态与翻转相位需验证。'),
 '093': ('static_contradiction', '卡诺图Gray列序与mux数组索引混用，ab=10/11对应列被交换。'),
 '097': ('static_contradiction', '九输入16位mux使用16*(4-sel)偏移，不符合九个槽位的选择范围。'),
 '099': ('dataset_interface_inconsistency', '正式题面接口Y1/Y3，外侧测试日志却实例化Y2/Y4；保留L0，不写测试特化改名。'),
 '101': ('static_contradiction', '波形a0b0c0d1要求q0，稿OR(b,c,d)为1。'),
 '102': ('static_contradiction', '表格a0b1c0d0要求q0，稿b&~a为1；另有已知行不匹配。'),
 '104': ('unlocalized', 'q<=L?r:qinput与可见DFF/mux文字一致；初始化及同拍竞争未定位。'),
 '108': ('static_contradiction', 'Rule90一侧拼接未形成对应邻居移位，左右边界及邻居索引需原生校准。'),
 '112': ('prior_native_witness', '最低置位优先被写成最高置位优先，原生11/16失配；一次修复及新生成小阶段已通过。'),
 '113': ('static_contradiction', '卡诺图轴x0x1/x2x3映射有误：x0=1其余0的明确单点为1，稿为0。'),
 '115': ('prior_native_witness', '无符号q>>>错误零填充；原生32/335采样失配，一次修复新生成小阶段已过。'),
 '116': ('spec_uncertainty', '接口四位x通常x3:0，表格却用x1至x4；不得臆造位映射或读参考RTL填缺口。'),
 '117': ('static_contradiction', '波形出现6→0，稿三位+1产生6→7；同边沿输入变化的采样另有歧义。'),
 '125': ('prior_native_witness', '卡诺图6/13 care失配已有原生证据；完整care反馈6→7，当前机制拒绝扩大。'),
 '133': ('static_hypothesis', '连续三拍窗口计数经过专门输出状态，可能丢弃下一窗口输入；须定义精确输出相位校准。'),
 '134': ('native_compile_diagnostic', '外侧xvlog实际报input y被always_ff过程赋值，VRFC10-1280；保留原L0。'),
 '135': ('static_contradiction', '要求next-state位Y1，稿直接输出当前y1，遗漏状态转移逻辑。'),
 '137': ('static_hypothesis', 'done_reg被组合与时序过程共同赋值，计数与输出相位亦有疑点，未原生定位完整机制。'),
 '139': ('static_hypothesis', '复位释放f多等待一状态，序列检测像11而非101；需协议序列原生验证。'),
 '141': ('static_contradiction', 'BCD边界09加0x0A成为13；小时09加1成为0A，AM/PM翻转边界亦待验证。'),
 '143': ('static_contradiction', '状态表S9同时out1/out2为1，稿两输出均漏S9项。'),
 '145': ('static_hypothesis', '波形q在下降边沿等相位改变，而稿两个posedge寄存器；需排除时钟/输入同拍歧义。'),
 '146': ('static_hypothesis', 'case(next_state)在进入接收态时采集start位，合法stop后离开CHECK_STOP使done路径缺失。'),
 '147': ('static_contradiction', 'next_state和q重复连续驱动，state_reg又有两个时序驱动；最终q=a^b也忽略显式状态依赖。'),
 '149': ('static_contradiction', 'reset要求四输出都1但dfr=rising为0；prev_level逐拍更新丢掉上次传感器变化方向，fr0重复驱动。'),
 '150': ('static_contradiction', 'Count_next漏Count且!done_counting自保持，Wait_next漏Wait且!ack自保持。'),
 '152': ('static_contradiction', 'walking输出在FALL/DIG也为1，与状态/输出描述冲突；还须区分不同方向的碰撞要求。'),
 '153': ('native_compile_diagnostic', '模块级if对wire作过程赋值，外侧xvlog报语法/非常量generate条件，VRFC10-4982/10-2951。'),
 '154': ('static_hypothesis', 'IDLE识别起始字节后下一状态才保存，三字节帧可能错位；须按题面波形原生验证。'),
 '155': ('static_contradiction', 'WALK_L仅在bump_right分支内检查bump_left，单独左碰撞被忽略；计数边界另待验证。'),
 '156': ('native_elaboration_diagnostic', 'xvlog通过但xelab报组合与时序过程共同驱动多个变量，VRFC10-3818/10-2921。'),
}
PRIOR = {
 '050': '03_analysis/prompt_map_contract_20261004/RESULT.md',
 '057': '03_analysis/prompt_map_contract_20261004/RESULT.md',
 '125': '03_analysis/prompt_map_contract_20261004/RESULT.md',
 '112': '03_analysis/priority_contract_20261005/RESULT.md',
 '115': '03_analysis/shift_contract_20261005/README.md',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def main():
    assert sha(ARCHIVE.read_bytes()) == ARCHIVE_SHA
    inv_path = REPO / '03_analysis/full156_postflight_20261004/full312_inventory/RESULTS.json'
    inv = json.loads(inv_path.read_text(encoding='utf-8'))
    bad = [r for r in inv['records'] if r['arm'] == 'A' and r['level'] < 3]
    assert len(bad) == 44
    assert {r['task'][4:7] for r in bad} == set(NOTES)
    rows = []
    with zipfile.ZipFile(ARCHIVE) as z:
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        def consume(member):
            data = z.read(member)
            assert sha(data) == manifest[member], member
            return data
        for r in bad:
            task = r['task']; num = task[4:7]
            p = f'kit/bench/tasks_veval/{task}/prompt.txt'
            d = f'run/samples/A/{task}/worker/solution.v'
            assert sha(consume(p)) == r['prompt_sha256']
            assert sha(consume(d)) == r['solution_sha256']
            status, finding = NOTES[num]
            row = dict(task=task, archived_A_level=r['level'], prompt_member=p,
                       prompt_sha256=r['prompt_sha256'], candidate_member=d,
                       candidate_sha256=r['solution_sha256'], attribution_status=status,
                       finding=finding, new_model_calls=0, new_eda_calls=0,
                       causal_native_test_executed_this_review=False)
            if num in PRIOR:
                witness = REPO / PRIOR[num]; assert witness.is_file()
                row['prior_native_report'] = PRIOR[num]
                row['prior_native_report_sha256'] = sha(witness.read_bytes())
            if num in ['099', '134', '153', '156']:
                log = f'run/samples/A/{task}/judge/judge_work_logs/w_judge.log'
                body = consume(log).decode('utf-8')
                codes = {'099':['10-3180'], '134':['10-1280'],
                         '153':['10-4982','10-2951'], '156':['10-3818','10-2921']}[num]
                assert all(code in body for code in codes)
                row.update(historical_external_log_member=log, historical_external_log_sha256=sha(consume(log)),
                           diagnostic_codes=codes, log_fed_to_candidate=False)
            if num == '099':
                assert not any(n.startswith(f'kit/bench/tasks_veval/{task}/') and n.endswith('/interface.txt') for n in z.namelist())
                row['interface_override_present_in_frozen_kit'] = False
            rows.append(row)
    report = dict(schema='full312_failure_manual_review_v2', archive_sha256=ARCHIVE_SHA,
                  reviewer_sha256=sha(Path(__file__).read_bytes()),
                  inventory_sha256=sha(inv_path.read_bytes()), reviewed_A_failures=len(rows),
                  status_counts=dict(sorted(Counter(r['attribution_status'] for r in rows).items())),
                  model_calls=0, eda_calls=0, reference_rtl_or_tb_body_read=False,
                  runtime_or_test_changes=0, new_score=False, rows=rows,
                  limits=['手工静态矛盾不等于原生功能根因。', '旧原生机制与本轮新调用分开。',
                          '099原始L0和完整分母保持；任何纠错数据版本需独立登记。',
                          '44题是旧轮A失败集合，不代表正在运行的新轮结果。'])
    (ROOT / 'RESULTS.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'rows'}, ensure_ascii=False))

if __name__ == '__main__':
    main()
