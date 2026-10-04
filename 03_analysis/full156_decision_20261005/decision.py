"""Complete-only attribution supplement. No scores filtered, calls or retries."""
import argparse,hashlib,json,math
from pathlib import Path,PurePosixPath
import zipfile

ROOT=Path(__file__).resolve().parent
SPEC_SHA='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def classify(a,c):
    delta=c['coefficient']-a['coefficient']
    base={'delta':delta,'first_content_identical':a['first'] is not None and a['first']==c['first'],'same_final_source':a['final']==c['final']}
    if a['deadline'] or c['deadline'] or a['unconfirmed'] or c['unconfirmed']:return dict(base,category='deadline_or_unconfirmed',matched_native_repair=False,flow_anomaly=False)
    if a['final']==c['final'] and delta:return dict(base,category='same_dut_different_judgment',matched_native_repair=False,flow_anomaly=False)
    matched=(base['first_content_identical'] and a['first_compile_pass'] and c['first_compile_pass'] and a['first_compile_source']==c['first_compile_source'] and c['forwarded_first_native_failure'] and c['requests']==2 and a['coefficient']<1 and c['coefficient']==1 and a['final']!=c['final'])
    if matched:return dict(base,category='matched_draft_native_repair',matched_native_repair=True,flow_anomaly=False)
    unchanged=(not c['native_checks'] and a['replies']==c['replies'] and a['final']!=c['final'])
    if unchanged:return dict(base,category='unchanged_flow_source_anomaly',matched_native_repair=False,flow_anomaly=True)
    if delta:return dict(base,category='score_change_without_matched_native_chain',matched_native_repair=False,flow_anomaly=False)
    return dict(base,category='equal_coefficient',matched_native_repair=False,flow_anomaly=False)

def summarize(pairs,frozen_gate,fixture=False):
    assert len(pairs)==156 and len({p['task'] for p in pairs})==156
    rows=[dict(task=p['task'],**classify(p['A'],p['C'])) for p in pairs]
    matched=[r['task'] for r in rows if r['matched_native_repair']]
    anomalies=[r['task'] for r in rows if r['flow_anomaly']]
    total=sum(r['delta'] for r in rows)/156
    # Adds an evidence gate; never relaxes the frozen no-regression quality gate.
    allowed=frozen_gate and bool(matched) and not anomalies and not fixture
    return {'schema':'full156_complete_attribution_v1','full_denominator':156,'rows':rows,'coefficient_mean_delta_all156':total,'matched_native_repair_tasks':matched,'unchanged_flow_anomalies':anomalies,'frozen_quality_gate':frozen_gate,'qualified_for_independent_validation_after_attribution':bool(allowed),'actual_full_result_processed':not fixture,'fixture_only':fixture,'quality_score_recomputed_or_filtered':False,'official_baseline_gain_measured':False,'five_sample_measured':False,'independent_natural_tasks':0,'adoption':False,'model_calls':0,'eda_calls':0,'limits':['Matched draft, first compilation, factual feedback and final L3 form one observed repair chain, not independent natural or five-sample proof.','Other changes and all regressions remain in the full156 denominator; model/judgment differences are not attributed to the helper.','Does not calculate uncertainty intervals or replace teammate T1; unchanged flow anomalies require investigation before validation expansion.']}

def process(archive,audit_path,fixture=False):
    evidence=json.loads(audit_path.read_text(encoding='utf-8'))
    assert evidence['evidence_valid'] and evidence['full156_evidence_valid'] and not evidence['historical_fixture_only']
    assert evidence['spec_sha256']==SPEC_SHA and evidence['expected_samples']==312 and evidence['archive_sha256']==sha(archive)
    assert evidence['auditor_sha256']==sha(ROOT.parent/'functional_full156_20261005/audit.py')
    with zipfile.ZipFile(archive) as z:
        def read(name):return json.loads(z.read(name))
        manifest=read('ARCHIVE_MANIFEST.json');assert manifest['schema']=='functional_fresh_archive_v1' and manifest.get('synthetic_fixture',False) is fixture
        assert manifest['run_spec_sha256']==SPEC_SHA
        spec=read('run/RUN_SPEC.json');assert hashlib.sha256(z.read('run/RUN_SPEC.json')).hexdigest()==SPEC_SHA
        report=read('run/results/summary.json');assert report['complete'] and report['passed'] and len(report['rows'])==312
        tasks=spec['task_ids'];assert len(tasks)==156 and len(set(tasks))==156
        provenance={(r['task'],r['arm']):r for r in evidence['provenance']};assert len(provenance)==312
        records={t:{} for t in tasks}
        for row in report['rows']:
            task,arm=row['task'],row['arm'];assert arm in ['A','C'] and not records[task].get(arm)
            prefix=f'run/results/samples/{arm}/{task}/worker/';journal=read(prefix+'requests.json');assert len(journal)==row['actual_model_requests'] and 1<=len(journal)<=2
            replies=[];first=None;forwarded=False
            for i,j in enumerate(journal):
                body=read(prefix+f'requests/{i}/request.json');assert body['model']==spec['model'] and body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
                if j['response_received']:
                    content=read(prefix+f'requests/{i}/response.json')['choices'][0]['message'].get('content') or '';identity=hashlib.sha256(content.encode()).hexdigest();replies.append(identity)
                    if i==0:first=identity
                else:replies.append(None)
                if arm=='C' and i==1:
                    checks=provenance[(task,arm)]['native_checks'];negative=[c for c in checks if c['index']=='map_check_0' and c['status']=='fail' and c['mismatches']>0]
                    if negative:
                        text=read(prefix+'map_check_0/feedback.json')['text'];assert text
                        forwarded=body['messages'][1]['content'].endswith('\nCandidate diagnostics:\n'+text)
            p=provenance[(task,arm)];assert p['first_reply_sha256']==first
            name=prefix+'compile_journal.json';compiles=read(name) if name in z.namelist() else []
            initial=[e for e in compiles if PurePosixPath(e['argv'][-1]).parent.name=='compile-0']
            records[task][arm]={'coefficient':row['verdict']['coefficient'],'first':first,'replies':replies,'final':row['solution_sha256'],'deadline':row['solve_deadline_reached'],'unconfirmed':row['actual_model_requests']-row['received_model_responses'],'requests':len(journal),'native_checks':p['native_checks'],'first_compile_pass':bool(initial and initial[0]['returncode']==0 and not initial[0]['timeout']),'first_compile_source':initial[0]['source_before_sha256'] if initial else None,'forwarded_first_native_failure':forwarded}
        assert all(set(p)=={'A','C'} for p in records.values())
    result=summarize([dict(task=t,**records[t]) for t in tasks],evidence['candidate_qualified_for_independent_validation'],fixture)
    expected=evidence['coefficients']['C']-evidence['coefficients']['A'];assert math.isclose(result['coefficient_mean_delta_all156'],expected,abs_tol=1e-12)
    result.update(archive_sha256=sha(archive),audit_result_sha256=sha(audit_path),source_spec_sha256=SPEC_SHA,decision_source_sha256=sha(Path(__file__)),official_scores=evidence['official_scores'],coefficients=evidence['coefficients'],regressions=evidence['regressions'],requests_by_arm=evidence['requests_by_arm'],solve_seconds_by_arm=evidence['solve_seconds_by_arm'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--audit-result',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();r=process(a.archive,a.audit_result);a.out.write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps({k:r[k] for k in ['full_denominator','coefficient_mean_delta_all156','matched_native_repair_tasks','unchanged_flow_anomalies','qualified_for_independent_validation_after_attribution','adoption']}))
