"""Three real local inference requests. Run only after the GPU server is ready."""
from datetime import datetime
import json
import os
from pathlib import Path
import time
import urllib.request
import uuid

base = os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8000/v1').rstrip('/')
model = os.environ['MODEL_NAME']
out = Path(__file__).resolve().parent / 'logs' / ('model_smoke_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
out.mkdir(parents=True, exist_ok=False)
for i in range(3):
    body = {'model': model, 'messages': [
        {'role': 'system', 'content': 'Return only synthesizable Verilog code.'},
        {'role': 'user', 'content': 'Implement module TopModule(input a, input b, output y); with y equal to a AND b.'}],
        'temperature': 0, 'top_p': 1, 'max_tokens': 8192}
    request = urllib.request.Request(base + '/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=300) as response:
        value = json.load(response)
    (out / f'response_{i}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    choice = value['choices'][0]
    content = choice['message'].get('content') or ''
    print(json.dumps({'request': i + 1, 'elapsed_s': round(time.monotonic() - started, 2),
                      'finish_reason': choice.get('finish_reason'), 'usage': value.get('usage')}, ensure_ascii=False), flush=True)
    if 'module' not in content or 'endmodule' not in content or choice.get('finish_reason') == 'length':
        raise SystemExit('Incomplete code / truncation. Inspect ' + str(out))
print('Three requests returned code. This is not an EDA correctness verdict. Evidence:', out)
