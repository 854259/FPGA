"""Readonly completed-prefix exposure; no model, EDA, score or runtime changes."""
import pathlib,json,time,hashlib
root=pathlib.Path('/workspace/team/runs/fpga_owner/functional_full156_20261005_v1')
spec=json.loads((root/'RUN_SPEC.json').read_text());report=json.loads((root/'results/summary.json').read_text())
selected=spec['target_tasks']+[spec['correct_guard']];patches=[];natural_selected=[]
for row in report['rows']:
    task,arm=row['task'],row['arm'];work=root/'results/samples'/arm/task/'worker'
    trace=[json.loads(x) for x in (work/'trace.jsonl').read_text().splitlines()]
    fixes=[e for e in trace if e['tool']=='declaration_fix']
    if fixes:patches.append({'task':task,'arm':arm,'success_patch_events':len(fixes),'map_check_present':any(work.glob('map_check_*')),'solution_sha256':row['solution_sha256']})
    if task in selected:natural_selected.append({'task':task,'arm':arm,'success_patch_events':len(fixes),'native_receipts':len(list(work.glob('map_check_*/probe/result.json'))),'model_requests':row['actual_model_requests']})
print(json.dumps({'at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'capture_source_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'completed_prefix_samples':len(report['rows']),'full_terminal':report['complete'],'source_spec_sha256':hashlib.sha256((root/'RUN_SPEC.json').read_bytes()).hexdigest(),'declared_functional_tasks':selected,'success_patch_rows':patches,'selected_rows':natural_selected,'model_calls':0,'eda_calls':0,'score_measured_or_published':False,'limits':'Completed-prefix control-flow exposure only; final full evidence audit remains required. No raw prompt/reply/reference/TB content.'}))
