"""Five fresh solves per selected task/mode; mean coefficients, never best-of-five."""
import hashlib,json
from pathlib import Path

def order(tasks):
    assert len(tasks)==3 and len(set(tasks))==3 and tasks==sorted(tasks)
    return [(t,i,m) for i in range(5) for j,t in enumerate(tasks) for m in (['baseline','agent'] if (i+j)%2==0 else ['agent','baseline'])]

def requests(root,trace,mode,prompt,interface,model,skills,baseline_system):
    journal=root/'requests.jsonl'
    records=[json.loads(s) for s in journal.read_text(encoding='utf-8').splitlines()] if journal.exists() else []
    events=[json.loads(s) for s in trace.splitlines()]
    assert 1<=len(records)<=({'baseline':1,'agent':2}[mode])
    received=sum(e.get('tool')=='llm' and 'error' not in e for e in events)
    assert received<=len(records)
    user=prompt+('\n\nInterface:\n'+interface if interface else '')
    bodies=[]
    for index,r in enumerate(records):
        raw=(root/(str(index)+'.request.json')).read_bytes();assert r['index']==index and hashlib.sha256(raw).hexdigest()==r['body_sha256']
        body=json.loads(raw);assert body['model']==model and body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
        assert [e['role'] for e in body['messages']]==['system','user']
        if index==0:assert body['messages'][1]['content']==user
        else:
            content=body['messages'][1]['content'];assert content.startswith(user+'\nPrevious candidate:\n') and '\nCandidate diagnostics:\n' in content
        if mode=='agent':assert body['messages'][0]['content']==skills[0]+('\n'+skills[1] if index else '')
        else:assert body['messages'][0]['content']==baseline_system
        if index==1:
            native=[e for e in events if e.get('tool')=='map_feedback' and e.get('round')==0 and e.get('repair_available')]
            if native:assert body['messages'][1]['content'].endswith('\nCandidate diagnostics:\n'+native[-1]['excerpt'])
        bodies.append(body)
    if mode=='baseline':
        assert sum(e.get('tool')=='baseline_meta' for e in events)==1
        assert all(e.get('tool') in ['baseline_meta','llm','supervisor'] for e in events)
    return {'attempted_model_posts':len(records),'received_model_responses':received,'unconfirmed_attempts':len(records)-received,'worker_model_pids':sorted({r['pid'] for r in records}),'supervisor_deadline':any(e.get('tool')=='supervisor' and e.get('event')=='deadline' for e in events)}

def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['sample_index'],r['mode']) for r in rows]==order(tasks)
    grouped={m:{t:[r['verdict'] for r in rows if r['task']==t and r['mode']==m] for t in tasks} for m in ['baseline','agent']}
    for r in rows:
        v=r['verdict'];assert not v['tool_error'] and v['task_id']==r['task'] and v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[v['level']]
    official={m:scorer.summarize(grouped[m]) for m in grouped}
    assert all(s['tasks']==s['scored_tasks']==3 and s['samples_per_task']==5 and s['tool_errors']==0 for s in official.values())
    per_task={m:{t:sum(v['coefficient'] for v in vs)/5 for t,vs in ts.items()} for m,ts in grouped.items()}
    means={m:sum(per_task[m].values())/3 for m in per_task}
    return {'official_scores':official,'coefficients':means,'task_five_sample_means':per_task,'unconfirmed_attempts':sum(r['model']['unconfirmed_attempts'] for r in rows),'deadline_rows':[{'task':r['task'],'sample_index':r['sample_index'],'mode':r['mode']} for r in rows if r['model']['supervisor_deadline']],'model_posts_by_mode':{m:sum(r['model']['attempted_model_posts'] for r in rows if r['mode']==m) for m in grouped},'independent_natural_tasks':0,'full156_five_sample_measured':False,'target_offline_single32gb_verified':False,'adoption':False}
