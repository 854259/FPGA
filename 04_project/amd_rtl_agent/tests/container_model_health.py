import json
import time
import urllib.request


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


deadline = time.monotonic() + 180
while True:
    try:
        request("http://127.0.0.1:8000/health")
        break
    except Exception:
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)

result = request("http://127.0.0.1:8000/v1/chat/completions", {
    "model": "/workspace/model/qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    "messages": [{"role": "user", "content": "Reply with OK."}],
    "max_tokens": 4,
    "temperature": 0,
})
content = result["choices"][0]["message"]["content"]
if not isinstance(content, str) or not content:
    raise RuntimeError("model returned no text")
print("CONTAINER_OFFLINE_MODEL=PASS", repr(content))
