"""Freeze a zero-model, zero-EDA input-adapter engineering tool; no actual run stage."""
from pathlib import Path
import ast,datetime,hashlib,json,subprocess,sys,zipfile
R=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
if __name__=='__main__':
    assert not (R/'TOOLS_SPEC.json').exists()
    subprocess.run([sys.executable,str(R/'inventory.py')],check=True)
    result=json.loads((R/'RESULTS.json').read_bytes());assert result['tests_passed']==15 and result['records']==302 and result['actual_model_calls']==result['actual_eda_calls']==0
    names=['adapter.py','test_adapter.py','inventory.py','prepare.py']
    for n in names:ast.parse((R/n).read_text(encoding='utf-8'));compile((R/n).read_text(encoding='utf-8'),n,'exec')
    spec=dict(schema='natural_input_adapter_engineering_tools_v1',frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),source_hashes={n:sha((R/n).read_bytes()) for n in names},dataset_sha256=result['dataset_sha256'],full_run_spec_sha256=sha((R.parent/'phase_full156_20261005/RUN_SPEC.json').read_bytes()),real_model_calls=0,real_eda_calls=0,actual_model_run_stage=False,actual_fifo_submitted=False,independent_quality_admitted=0,adoption=False)
    save(R/'TOOLS_SPEC.json',spec)
    with zipfile.ZipFile(R/'raw_evidence/preparation.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['TOOLS_SPEC.json']:z.write(R/n,n)
    save(R/'PREPARATION_RECEIPT.json',dict(tools_spec_sha256=sha((R/'TOOLS_SPEC.json').read_bytes()),source_assets=4,archive_sha256=sha((R/'raw_evidence/preparation.zip').read_bytes()),local_python=result['python'],local_checks=15,all_records_lossless=302,actual_model_calls=0,actual_eda_calls=0,actual_fifo_submitted=False))
    print(json.dumps(json.loads((R/'PREPARATION_RECEIPT.json').read_bytes())))
