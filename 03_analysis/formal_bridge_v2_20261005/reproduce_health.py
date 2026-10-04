"""Reproduce inherited readiness defects with captured metrics/fake version."""
import hashlib,importlib.util,json,os,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
source=ROOT.parent/'formal_bridge_20261005/package/agent/core.py'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
s=importlib.util.spec_from_file_location('old_health_core',source);old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
old.vivado_version.cache_clear()
with patch.object(old.subprocess,'run',return_value=subprocess.CompletedProcess(['fake-vivado','-version'],0,'vivado v2026.1 (64-bit)')):
    lower=old.vivado_version('/fake/vivado')
    with patch.dict(os.environ,MODEL_NAME='fake-model',RTL_PROFILE='development'),patch.object(old,'models',return_value=['fake-model']),patch.object(old,'baseline_integrity',return_value=True),patch.object(old,'vivado_tool',return_value='/fake/vivado'),patch.object(old,'vram_gb',return_value=19):case=old.health()
assert lower is None and not case['ready']
snapshot=json.loads((ROOT/'MODEL_PROCESS_SNAPSHOT.json').read_text())
cards=snapshot['vram_counters']
class Counter:
    def __init__(self,row):self.row=row
    def read_text(self):return str(self.row['used_bytes'])
class SysRoot:
    def __init__(self,*a):pass
    def glob(self,*a):return [Counter(r) for r in cards]
with patch.object(old,'Path',SysRoot):total=old.vram_gb()
assert total>32
report={'schema':'staged_inherited_health_gap_reproduction_v1','source_core_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'staged_v1_spec_sha256':'a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','lowercase_vivado_version_rejected':True,'development_ready_false_due_version_reproduced':True,'snapshot_at_utc':snapshot['at_utc'],'host_gpu_counter_sum_gib':total,'cards_summed':len(cards),'vram_observation_scope':'Recorded multi-card host counters replayed through the actual old summation function, not a new live measurement.','actual_model_requests':0,'actual_eda_calls':0,'formal_deployment_changed':False,'full_research_invalidated':False,'queued_v1_changed':False,'limits':['Fake subprocess proves version parsing only.','Existing formal runtime728 already fixed; this is an inherited regression of the staged research core.','No new quality score or target/offline certification.']}
(ROOT/'HEALTH_GAPS.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))
