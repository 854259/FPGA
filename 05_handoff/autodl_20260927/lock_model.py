"""Fetch public model metadata only; no weights, credentials, or code execution."""
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parent / 'kit'
repo = 'nvidia/Qwen3.6-27B-NVFP4'
url = 'https://huggingface.co/api/models/' + repo
with urllib.request.urlopen(url, timeout=30) as response:
    meta = json.load(response)
revision = meta['sha']
with urllib.request.urlopen(f'https://huggingface.co/{repo}/resolve/{revision}/config.json', timeout=30) as response:
    config = json.load(response)
lock = {'repository': repo, 'revision': revision, 'source': url,
        'status': 'candidate; GPU compatibility not validated locally',
        'weights_downloaded': False, 'architecture': config.get('architectures'),
        'quantization_config': config.get('quantization_config'),
        'deployment_reference': 'https://recipes.vllm.ai/Qwen/Qwen3.6-27B'}
(root / 'model-lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
(root / 'candidate-model-config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'repository': repo, 'revision': revision, 'status': lock['status']}))
