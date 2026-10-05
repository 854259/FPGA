"""Observe the original baseline CLI in its own Python process, without retries.

Client attempts are not proof of server execution. A durable request record is
written before urlopen; response bytes are recorded by the original read call.
Initialization is explicit, so recording failures cannot silently disable it.
"""
import json
import os
from pathlib import Path
import runpy
import sys
import time
import urllib.request
from urllib.parse import urlsplit

from official_baseline_arm_20261005 import OFFICIAL, sha


def save(path, value):
    with path.with_suffix('.pending').open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush(); os.fsync(handle.fileno())
    path.with_suffix('.pending').replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    assert sys.platform == 'linux' and len(sys.argv) == 5
    script = Path(sys.argv[1]).resolve()
    assert script.name == 'baseline.py'
    for name, expected in OFFICIAL.items():
        assert sha(script.parent/name) == expected
    out = Path(os.environ['BASELINE_RECEIPTS']).resolve()
    assert out.is_dir() and not any(out.iterdir())
    endpoint = os.environ['LLM_BASE_URL'].rstrip('/')
    parsed=urlsplit(endpoint)
    assert (parsed.scheme,parsed.hostname,parsed.path)==('http','127.0.0.1','/v1')
    assert parsed.port and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
    save(out/'BOOTSTRAP.json',dict(observer_sha256=sha(__file__), official_sha256=OFFICIAL,
        python=sys.executable, argv=sys.argv[1:], endpoint=endpoint, ready=True))
    original = urllib.request.urlopen
    attempts = []

    def observed_open(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if url == endpoint+'/models':
            return original(request, *args, **kwargs)
        assert url == endpoint+'/chat/completions' and request.get_method() == 'POST'
        assert not attempts, 'Official baseline is one attempt; no implicit retry'
        folder = out/'request_0'; folder.mkdir()
        raw_request = request.data
        with (folder/'request.bin').open('wb') as handle:
            handle.write(raw_request); handle.flush(); os.fsync(handle.fileno())
        state = dict(index=0, client_attempted=True, server_received=None,
                     request_sha256=sha(folder/'request.bin'), response_body_complete=False,
                     headers_received=False, started_unix=time.time(), error=None)
        attempts.append(state)
        save(folder/'STATE.json',state)
        try:
            response = original(request, *args, **kwargs)
        except Exception as error:
            state.update(error=type(error).__name__, http_status=getattr(error,'code',None),
                         elapsed_s=time.time()-state['started_unix'])
            save(folder/'STATE.json',state)
            raise
        state.update(headers_received=True,http_status=response.status,
                     content_length=response.headers.get('Content-Length'))
        save(folder/'STATE.json',state)
        original_read = response.read

        def observed_read(*read_args, **read_kwargs):
            try:
                raw = original_read(*read_args, **read_kwargs)
            except Exception as error:
                state.update(error=type(error).__name__,elapsed_s=time.time()-state['started_unix'])
                save(folder/'STATE.json',state)
                raise
            # The pinned CLI reads once with no size argument. Do not read ahead,
            # transform data, or change the returned response/context manager.
            assert not read_args and not read_kwargs
            with (folder/'response.bin').open('wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            state.update(response_body_complete=True,response_sha256=sha(folder/'response.bin'),
                         elapsed_s=time.time()-state['started_unix'])
            save(folder/'STATE.json',state)
            return raw

        response.read = observed_read
        return response

    urllib.request.urlopen = observed_open
    sys.argv = sys.argv[1:]
    try:
        runpy.run_path(str(script),run_name='__main__')
    finally:
        urllib.request.urlopen = original


if __name__ == '__main__':
    main()
