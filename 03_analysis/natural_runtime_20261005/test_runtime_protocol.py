"""Pure HTTP protocol controls. All connections are in-memory FAKE objects.

No real transport/native entry, network, model, EDA, SSH or FIFO is invoked.
Fixtures and failure receipts are retained in this directory's ignored raw tree.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import io
import json
import socket
import sys
import unittest
import uuid
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
definition = importlib.util.spec_from_file_location('natural_http_protocol_under_test', HERE / 'runtime.py')
runtime = importlib.util.module_from_spec(definition)
RUNTIME_BYTES = (HERE / 'runtime.py').read_bytes()
exec(compile(RUNTIME_BYTES, str(HERE / 'runtime.py'), 'exec'), runtime.__dict__)

MODEL = 'SYNTHETIC_PROTOCOL_MODEL'
FIXTURES = HERE / 'raw_evidence' / 'runtime_protocol_fake'
SUBCHECKS = 0


def request():
    return dict(messages=[dict(role='system', content='Return complete native RTL files.'),
                          dict(role='user', content='Public synthetic prompt: 保留端口与所有文件。\r\n')],
                max_tokens=8192, temperature=0, top_p=1)


def payload(**changes):
    value = dict(model=MODEL, choices=[dict(index=0, message=dict(role='assistant', content='合成回复'), finish_reason='stop')])
    value.update(changes)
    return value


def json_body(value=None):
    return json.dumps(payload() if value is None else value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def fixed_response(body=None, status=200, extra_headers=b''):
    body = json_body() if body is None else body
    return ('HTTP/1.1 ' + str(status) + ' SYNTHETIC\r\nContent-Length: ' + str(len(body)) + '\r\n').encode('ascii') + extra_headers + b'\r\n' + body


def chunked_response(body=None):
    body = json_body() if body is None else body
    parts = [body[:7], body[7:31], body[31:]]
    encoded = b''.join(format(len(part), 'x').encode() + b'\r\n' + part + b'\r\n' for part in parts)
    return b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n' + encoded + b'0\r\n\r\n'


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, value):
        self.now += value


class FakeSocket:
    io_kind = 'FAKE'

    def __init__(self, blocks, clock=None, delays=None, send_error=None, close_error=None):
        self.blocks = list(blocks)
        self.clock = clock
        self.delays = list(delays or [])
        self.send_error = send_error
        self.close_error = close_error
        self.sent = []
        self.timeouts = []
        self.recv_calls = 0
        self.close_calls = 0

    def settimeout(self, seconds):
        self.timeouts.append(seconds)

    def sendall(self, wire):
        self.sent.append(wire)
        if self.send_error:
            raise self.send_error

    def recv(self, size):
        self.recv_calls += 1
        if self.clock and self.delays:
            self.clock.advance(self.delays.pop(0))
        item = self.blocks.pop(0) if self.blocks else b''
        if isinstance(item, BaseException):
            raise item
        if len(item) > size:
            self.blocks.insert(0, item[size:])
            item = item[:size]
        return item

    def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


class FakeConnect:
    io_kind = 'FAKE'

    def __init__(self, sock, directory, error=None):
        self.sock = sock
        self.directory = directory
        self.error = error
        self.calls = []
        self.durable_attempts_observed = []

    def __call__(self, address, timeout):
        self.calls.append(dict(address=address, timeout=timeout))
        # Observe the actual file BEFORE simulated connection invocation.
        path = self.directory / 'HTTP_ATTEMPT.json'
        self.durable_attempts_observed.append(runtime.read_json(path) if path.is_file() else None)
        if self.error:
            raise self.error
        return self.sock


class ProtocolControls(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.case = FIXTURES / (self._testMethodName + '_' + uuid.uuid4().hex)
        self.case.mkdir()
        # Catch accidental network creation, including an unanticipated fallback.
        self.socket_block = mock.patch.object(socket, 'socket', side_effect=AssertionError('real socket forbidden in pure controls'))
        self.connect_block = mock.patch.object(socket, 'create_connection', side_effect=AssertionError('real connection forbidden in pure controls'))
        self.socket_block.start()
        self.connect_block.start()
        self.addCleanup(self.connect_block.stop)
        self.addCleanup(self.socket_block.stop)

    def check(self):
        global SUBCHECKS
        SUBCHECKS += 1

    def exchange(self, blocks, *, timeout=10, clock=None, delays=None, send_error=None, close_error=None, connect_error=None):
        self.check()
        directory = self.case / 'exchange'
        clock = clock or FakeClock()
        sock = FakeSocket(blocks, clock, delays, send_error, close_error)
        connector = FakeConnect(sock, directory, connect_error)
        result = runtime.http_exchange(request(), MODEL, timeout, directory, connector, clock, mode='FAKE')
        receipt = runtime.read_json(directory / 'HTTP_RECEIPT.json')
        self.assertEqual(receipt['schema'], 'natural_http_receipt_v1')
        self.assertEqual(receipt['mode'], 'FAKE')
        self.assertIs(receipt['finalized'], True)
        self.assertIs(receipt['attempted'], True)
        self.assertIs(receipt['server_job_cancellation_confirmed'], False)
        self.assertEqual(len(connector.calls), 1, 'unconfirmed attempts must never cause automatic reconnect')
        self.assertIsNotNone(connector.durable_attempts_observed[0], 'durable attempt must precede connect')
        self.assertIs(connector.durable_attempts_observed[0]['attempted'], True)
        self.assertEqual(connector.calls[0]['address'], ('127.0.0.1', 8000))
        return result, receipt, sock, connector, directory

    def test_request_wire_preserves_public_unicode_and_byte_length(self):
        self.check()
        wire, body = runtime.request_wire(request(), MODEL)
        head, observed = wire.split(b'\r\n\r\n', 1)
        self.assertEqual(observed, body)
        self.assertGreater(len(body), len(body.decode('utf-8')))
        self.assertIn(('Content-Length: ' + str(len(body))).encode(), head)
        self.assertEqual(head.split(b'\r\n')[0], b'POST /v1/chat/completions HTTP/1.1')
        self.assertIn(b'Host: 127.0.0.1:8000', head)
        self.assertIn(b'Connection: close', head)
        decoded = json.loads(body)
        self.assertEqual(decoded['messages'], request()['messages'])
        self.assertIs(decoded['stream'], False)
        self.assertEqual(decoded['model'], MODEL)

    def test_request_fixed_budget_roles_and_complete_message_shape(self):
        mutations = [lambda r: r.update(max_tokens=4096), lambda r: r.update(temperature=1),
                     lambda r: r.update(top_p=False), lambda r: r.update(temperature=False),
                     lambda r: r.update(top_p=True), lambda r: r.update(extra='unknown'),
                     lambda r: r['messages'].reverse(), lambda r: r['messages'].append(dict(role='user', content='extra')),
                     lambda r: r['messages'][0].update(hidden='unknown'), lambda r: r['messages'][1].update(content=1)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.check()
                value = request()
                mutate(value)
                with self.assertRaises(ValueError):
                    runtime.request_wire(value, MODEL)

    def test_content_length_fragmentation_and_close_delimited_eof(self):
        raw = fixed_response()
        for offset in [1, 20, raw.index(b'\r\n\r\n') + 3, len(raw) - 1]:
            self.check()
            self.assertIsNone(runtime.parse_http(raw[:offset]))
        self.assertEqual(runtime.parse_http(raw)['body'], json_body())
        close_raw = b'HTTP/1.0 200 OK\r\nConnection: close\r\n\r\n' + json_body()
        self.assertIsNone(runtime.parse_http(close_raw))
        self.assertEqual(runtime.parse_http(close_raw, eof=True)['body'], json_body())

    def test_chunked_fragmentation_is_byte_faithful(self):
        self.check()
        raw = chunked_response()
        self.assertEqual(runtime.parse_http(raw)['body'], json_body())
        self.assertEqual(runtime.parse_http(raw)['raw_header'], raw.split(b'\r\n\r\n')[0] + b'\r\n\r\n')
        for offset in [raw.index(b'\r\n\r\n') + 4, len(raw) - 2, len(raw) - 1]:
            self.check()
            self.assertIsNone(runtime.parse_http(raw[:offset]))
            with self.assertRaises(ValueError):
                runtime.parse_http(raw[:offset], eof=True)

    def test_ambiguous_duplicate_or_malformed_framing_rejected(self):
        body = json_body()
        invalid = [fixed_response(body, extra_headers=b'Content-Length: ' + str(len(body)).encode() + b'\r\n'),
                   fixed_response(body, extra_headers=b'Transfer-Encoding: chunked\r\n'),
                   b'HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n',
                   b'HTTP/1.1 200 OK\r\nContent-Length: 1, 1\r\n\r\na',
                   b'HTTP/2 200 OK\r\n\r\n', b'HTTP/1.1 200 OK\r\n folded: value\r\n\r\n',
                   b'HTTP/1.1 200 OK\r\nBad Header: value\r\n\r\n',
                   b'HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n',
                   b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n',
                   fixed_response() + b'extra']
        for raw in invalid:
            with self.subTest(raw=raw[:80]):
                self.check()
                with self.assertRaises(ValueError):
                    runtime.parse_http(raw, eof=True)

    def test_chunk_extensions_trailers_bad_separators_and_extra_reply_rejected(self):
        head = b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
        for body in [b'1;extension=x\r\na\r\n0\r\n\r\n', b'1\r\naXX0\r\n\r\n',
                     b'0\r\nTrailer: value\r\n\r\n', b'0\r\n\r\nHTTP/1.1 200 OK', b'z\r\n']:
            self.check()
            with self.assertRaises(ValueError):
                runtime.parse_http(head + body, eof=True)

    def test_truncated_header_body_and_raw_limit_rejected(self):
        for raw in [b'HTTP/1.1', fixed_response()[:-1]]:
            self.check()
            with self.assertRaises(ValueError):
                runtime.parse_http(raw, eof=True)
        self.check()
        with mock.patch.object(runtime, 'RAW_HTTP_MAX', 20):
            with self.assertRaises(ValueError):
                runtime.parse_http(fixed_response())

    def test_chat_confirmation_requires_single_matching_finished_assistant_choice(self):
        result, decoded = runtime.classify_chat(runtime.parse_http(fixed_response()), MODEL)
        self.check()
        self.assertEqual(result, dict(confirmed=True, reply='合成回复', finish_reason='stop'))
        self.assertEqual(decoded, payload())
        values = []
        for alter in [lambda p: p.update(model='OTHER'), lambda p: p['choices'][0].update(index=False),
                      lambda p: p['choices'][0].update(index=1), lambda p: p['choices'][0].update(finish_reason='length'),
                      lambda p: p['choices'][0].update(finish_reason=None), lambda p: p['choices'][0]['message'].update(role='user'),
                      lambda p: p['choices'][0]['message'].update(content=None), lambda p: p['choices'].append(copy.deepcopy(p['choices'][0]))]:
            value = payload()
            alter(value)
            values.append(value)
        for value in values:
            self.check()
            result, _ = runtime.classify_chat(runtime.parse_http(fixed_response(json_body(value))), MODEL)
            self.assertIs(result['confirmed'], False)

    def test_chat_json_duplicate_fields_at_all_levels_and_nonfinite_rejected(self):
        original = json_body()
        bad = [original.replace(b'"model":', b'"model":"OTHER","model":', 1),
               original.replace(b'"index":0', b'"index":0,"index":0'),
               original.replace(b'"role":"assistant"', b'"role":"assistant","role":"assistant"'),
               original[:-1] + b',"usage":NaN}', original[:-1] + b',"usage":Infinity}',
               original[:-1] + b',"usage":-Infinity}', b'not JSON', b'\xff']
        for body in bad:
            self.check()
            with self.assertRaises((ValueError, UnicodeError)):
                runtime.classify_chat(runtime.parse_http(fixed_response(body)), MODEL)

    def test_fixed_reply_receipt_binds_raw_request_and_response_before_confirmation(self):
        raw = fixed_response()
        result, receipt, sock, _, directory = self.exchange([raw[:23], raw[23:87], raw[87:]])
        self.assertIs(result['confirmed'], True)
        self.assertIs(receipt['evidence_complete'], True)
        self.assertIs(receipt['response_confirmed'], True)
        self.assertIs(receipt['response_observed'], True)
        self.assertIs(receipt['invocation_started'], True)
        self.assertIs(receipt['request_sent'], True)
        self.assertIsNone(receipt['error'])
        self.assertEqual(receipt['status'], 200)
        self.assertEqual(receipt['raw_response_sha256'], runtime.sha(raw))
        self.assertEqual(receipt['raw_response_bytes'], len(raw))
        self.assertEqual((directory / 'response.http').read_bytes(), raw)
        self.assertEqual((directory / 'response_body.bin').read_bytes(), json_body())
        self.assertEqual((directory / 'request.http').read_bytes(), sock.sent[0])
        self.assertEqual(receipt['request_wire_sha256'], runtime.sha(sock.sent[0]))
        self.assertEqual(receipt['request_body_sha256'], runtime.file_sha(directory / 'request.json'))
        self.assertEqual(sock.close_calls, 1)

    def test_chunked_reply_and_connection_close_reply_confirmed_without_reconstruction(self):
        for name, raw, blocks in [('chunked', chunked_response(), None),
                                 ('close', b'HTTP/1.0 200 OK\r\n\r\n' + json_body(), None)]:
            self.case = self.case / name
            self.case.mkdir()
            result, receipt, _, _, directory = self.exchange([raw[:80], raw[80:], b''])
            self.assertIs(result['confirmed'], True)
            self.assertEqual((directory / 'response.http').read_bytes(), raw)
            self.assertEqual(receipt['raw_response_sha256'], runtime.sha(raw))

    def test_http_error_preserves_status_and_body_without_confirming_or_retry(self):
        raw = fixed_response(json_body(dict(error=dict(message='synthetic overload', type='capacity'))), status=503)
        result, receipt, sock, _, directory = self.exchange([raw])
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertEqual(receipt['status'], 503)
        self.assertEqual(runtime.read_json(directory / 'decoded_http_body.json')['error']['type'], 'capacity')
        self.assertEqual(sock.close_calls, 1)

    def test_finish_length_partial_model_reply_retained_without_retry(self):
        value = payload()
        value['choices'][0]['finish_reason'] = 'length'
        result, receipt, _, _, directory = self.exchange([fixed_response(json_body(value))])
        self.assertIs(result['confirmed'], False)
        self.assertEqual(result['reply'], '合成回复')
        self.assertEqual(result['finish_reason'], 'length')
        self.assertIs(receipt['response_confirmed'], False)
        self.assertEqual(runtime.read_json(directory / 'decoded_http_body.json'), value)

    def test_socket_timeout_keeps_exact_partial_and_unconfirmed_attempt(self):
        partial = fixed_response()[:-17]
        result, receipt, sock, _, directory = self.exchange([partial, socket.timeout('synthetic receive timeout')])
        self.assertIs(result['confirmed'], False)
        self.assertEqual(result['finish_reason'], 'timeout')
        self.assertIs(receipt['response_confirmed'], False)
        self.assertEqual((directory / 'response.http').read_bytes(), partial)
        self.assertEqual(receipt['raw_response_sha256'], runtime.sha(partial))
        self.assertEqual(receipt['raw_response_bytes'], len(partial))
        self.assertIn('timeout', receipt['error'])
        self.assertEqual(sock.close_calls, 1)

    def test_client_deadline_keeps_partial_and_stops_next_receive(self):
        clock = FakeClock()
        partial = fixed_response()[:-13]
        result, receipt, sock, _, directory = self.exchange([partial, fixed_response()[-13:]], timeout=1, clock=clock, delays=[1.1])
        self.assertIs(result['confirmed'], False)
        self.assertEqual(result['finish_reason'], 'timeout')
        self.assertEqual(sock.recv_calls, 1)
        self.assertEqual((directory / 'response.http').read_bytes(), partial)
        self.assertEqual(receipt['raw_response_bytes'], len(partial))

    def test_connection_failure_is_single_durable_unconfirmed_invocation(self):
        result, receipt, sock, _, directory = self.exchange([], connect_error=ConnectionRefusedError('synthetic refusal'))
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['invocation_started'], True)
        self.assertIs(receipt['request_sent'], False)
        self.assertIs(receipt['response_observed'], False)
        self.assertEqual(receipt['raw_response_bytes'], 0)
        self.assertIn('ConnectionRefusedError', receipt['error'])
        self.assertEqual(sock.close_calls, 0)
        self.assertTrue((directory / 'HTTP_ATTEMPT.json').is_file())

    def test_send_failure_never_claims_sent_and_does_not_reconnect(self):
        result, receipt, sock, _, _ = self.exchange([], send_error=BrokenPipeError('synthetic send interruption'))
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['request_sent'], False)
        self.assertIn('BrokenPipeError', receipt['error'])
        self.assertEqual(len(sock.sent), 1)
        self.assertEqual(sock.close_calls, 1)

    def test_receive_failure_and_bad_json_preserve_original_raw_bytes(self):
        cases = [('receive', [b'HTTP/1.1 200', ConnectionResetError('synthetic reset')], b'HTTP/1.1 200'),
                 ('duplicate', [fixed_response(json_body().replace(b'"index":0', b'"index":0,"index":0'))], None)]
        original_case = self.case
        for name, blocks, raw in cases:
            self.case = original_case / name
            self.case.mkdir()
            result, receipt, _, _, directory = self.exchange(blocks)
            self.assertIs(result['confirmed'], False)
            raw = raw or blocks[0]
            self.assertEqual((directory / 'response.http').read_bytes(), raw)
            self.assertEqual(receipt['raw_response_sha256'], runtime.sha(raw))
            self.assertIsNotNone(receipt['error'])

    def test_complete_reply_with_close_exception_revokes_confirmation(self):
        raw = fixed_response()
        result, receipt, sock, _, directory = self.exchange([raw], close_error=OSError('synthetic close failure'))
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertIs(receipt['evidence_complete'], False)
        self.assertIn('synthetic close failure', receipt['close_error'])
        self.assertEqual((directory / 'response.http').read_bytes(), raw)
        self.assertEqual(sock.close_calls, 1)

    def test_body_evidence_save_failure_revokes_confirmation_but_keeps_partial(self):
        original = runtime.new_bytes
        def fail_body(path, data):
            if Path(path).name == 'response_body.bin':
                raise OSError('synthetic body evidence persistence failure')
            return original(path, data)
        raw = fixed_response()
        with mock.patch.object(runtime, 'new_bytes', side_effect=fail_body):
            result, receipt, sock, _, directory = self.exchange([raw])
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertIs(receipt['evidence_complete'], False)
        self.assertIn('persistence failure', receipt['error'])
        self.assertEqual((directory / 'response.http').read_bytes(), raw)
        self.assertEqual(sock.close_calls, 1)

    def test_decoded_json_evidence_save_failure_revokes_provisional_confirmation(self):
        original = runtime.save
        def fail_decoded(path, value):
            if Path(path).name == 'decoded_http_body.json':
                raise OSError('synthetic decoded evidence persistence failure')
            return original(path, value)
        with mock.patch.object(runtime, 'save', side_effect=fail_decoded):
            result, receipt, _, _, directory = self.exchange([fixed_response()])
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertIs(receipt['evidence_complete'], False)
        self.assertTrue((directory / 'HTTP_ATTEMPT.json').is_file())

    def test_final_receipt_save_failure_raises_and_never_returns_confirmed(self):
        original = runtime.save
        directory = self.case / 'exchange'
        sock = FakeSocket([fixed_response()])
        connector = FakeConnect(sock, directory)
        def fail_final(path, value):
            if Path(path).name == 'HTTP_RECEIPT.json':
                raise OSError('synthetic final receipt persistence failure')
            return original(path, value)
        self.check()
        with mock.patch.object(runtime, 'save', side_effect=fail_final):
            with self.assertRaises(OSError):
                runtime.http_exchange(request(), MODEL, 10, directory, connector, FakeClock(), mode='FAKE')
        self.assertEqual(len(connector.calls), 1)
        self.assertEqual(sock.close_calls, 1)
        self.assertTrue((directory / 'HTTP_ATTEMPT.json').is_file())
        self.assertTrue((directory / 'response.http').is_file())
        self.assertFalse((directory / 'HTTP_RECEIPT.json').exists())

    def test_final_receipt_persistence_consumes_deadline_and_revokes_confirmation(self):
        original = runtime.save
        clock = FakeClock()
        directory = self.case / 'exchange'
        raw = fixed_response()
        sock = FakeSocket([raw], clock)
        connector = FakeConnect(sock, directory)
        final_writes = []
        def slow_first_final(path, value):
            answer = original(path, value)
            if Path(path).name == 'HTTP_RECEIPT.json':
                final_writes.append(copy.deepcopy(value))
                if len(final_writes) == 1:
                    # The filesystem write returns after the entire client budget.
                    clock.advance(1.5)
            return answer
        self.check()
        with mock.patch.object(runtime, 'save', side_effect=slow_first_final):
            result = runtime.http_exchange(request(), MODEL, 1, directory, connector, clock, mode='FAKE')
        receipt = runtime.read_json(directory / 'HTTP_RECEIPT.json')
        self.assertIs(result['confirmed'], False)
        self.assertEqual(result['finish_reason'], 'timeout')
        self.assertIs(receipt['response_confirmed'], False, 'persisted provisional success must be revoked after a late final write')
        self.assertIs(receipt['evidence_complete'], False)
        self.assertIs(receipt['finalized'], True)
        self.assertGreaterEqual(receipt['elapsed_s'], 1)
        self.assertIsNotNone(receipt['error'])
        self.assertIs(receipt['server_job_cancellation_confirmed'], False)
        self.assertEqual(len(connector.calls), 1)
        self.assertEqual(sock.close_calls, 1)
        self.assertEqual((directory / 'response.http').read_bytes(), raw)

    def test_preconnect_preparation_deadline_does_not_claim_socket_invocation(self):
        original = runtime.save
        clock = FakeClock()
        directory = self.case / 'exchange'
        sock = FakeSocket([fixed_response()], clock)
        connector = FakeConnect(sock, directory)
        initial_writes = []
        def slow_initial_attempt(path, value):
            answer = original(path, value)
            if Path(path).name == 'HTTP_ATTEMPT.json':
                initial_writes.append(copy.deepcopy(value))
                if len(initial_writes) == 1:
                    clock.advance(2)
            return answer
        self.check()
        with mock.patch.object(runtime, 'save', side_effect=slow_initial_attempt):
            result = runtime.http_exchange(request(), MODEL, 1, directory, connector, clock, mode='FAKE')
        receipt = runtime.read_json(directory / 'HTTP_RECEIPT.json')
        self.assertIs(result['confirmed'], False)
        self.assertEqual(result['finish_reason'], 'timeout')
        self.assertEqual(connector.calls, [], 'expired client budget must reject before connector invocation')
        self.assertIs(receipt['attempted'], True)
        self.assertIs(receipt['invocation_started'], False, 'durable local intent is distinct from an actual socket invocation')
        self.assertIs(receipt['request_sent'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertIs(receipt['server_job_cancellation_confirmed'], False)
        self.assertEqual(sock.close_calls, 0)

    def test_durable_attempt_save_failure_refuses_connection(self):
        original = runtime.save
        directory = self.case / 'exchange'
        connector = FakeConnect(FakeSocket([fixed_response()]), directory)
        def fail_attempt(path, value):
            if Path(path).name == 'HTTP_ATTEMPT.json':
                raise OSError('synthetic initial attempt persistence failure')
            return original(path, value)
        self.check()
        with mock.patch.object(runtime, 'save', side_effect=fail_attempt):
            try:
                result = runtime.http_exchange(request(), MODEL, 10, directory, connector, FakeClock(), mode='FAKE')
            except OSError:
                result = None
        self.assertEqual(connector.calls, [])
        if result is not None:
            self.assertIs(result['confirmed'], False)

    def test_raw_stream_write_failure_cannot_confirm_in_memory_reply(self):
        directory = self.case / 'exchange'
        connector = FakeConnect(FakeSocket([fixed_response()]), directory)
        real_open = Path.open
        class BrokenStream:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def write(self, data):
                raise OSError('synthetic raw stream persistence failure')
            def flush(self):
                pass
        def selective_open(path, *args, **kwargs):
            if path.name == 'response.http' and args and args[0] == 'xb':
                return BrokenStream()
            return real_open(path, *args, **kwargs)
        self.check()
        with mock.patch.object(Path, 'open', selective_open):
            result = runtime.http_exchange(request(), MODEL, 10, directory, connector, FakeClock(), mode='FAKE')
        receipt = runtime.read_json(directory / 'HTTP_RECEIPT.json')
        self.assertIs(result['confirmed'], False)
        self.assertIs(receipt['response_confirmed'], False)
        self.assertIs(receipt['evidence_complete'], False)
        self.assertEqual(len(connector.calls), 1)
        self.assertIn('raw stream persistence failure', receipt['error'])

    def test_fake_exchange_requires_explicit_fake_connector(self):
        self.check()
        connector = lambda *args, **kwargs: self.fail('untagged connector must not be invoked')
        with self.assertRaises((PermissionError, ValueError)):
            runtime.http_exchange(request(), MODEL, 10, self.case / 'exchange', connector, FakeClock(), mode='FAKE')

    def test_no_spec_real_client_admission_rejects_before_socket_creation(self):
        empty_root = self.case / 'empty_admission'
        (empty_root / 'raw_evidence').mkdir(parents=True)
        self.check()
        with mock.patch.object(runtime, 'ROOT', empty_root), mock.patch.object(sys, 'platform', 'linux'), \
             mock.patch.object(socket, 'create_connection', side_effect=AssertionError('no-spec path must reject before socket creation')) as connect:
            with self.assertRaises((PermissionError, FileNotFoundError)):
                runtime.make_real_clients({}, empty_root / 'raw_evidence' / 'solve', dict(native_feedback_required=False))
            connect.assert_not_called()

    def test_forged_capability_or_grant_cannot_enable_io(self):
        self.check()
        with mock.patch.object(runtime, 'file_sha', side_effect=AssertionError('forged token must reject before evidence access')):
            with self.assertRaises(PermissionError):
                runtime.revalidate(dict(real_execution_admitted=True, include_isolation_verified=True, http_attempts=0, native_attempts=0))


def main():
    global SUBCHECKS
    SUBCHECKS = 0
    source_before = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                     for name in ['runtime.py', 'test_runtime_protocol.py', 'worker.py', 'adapter.py']}
    imported_runtime_sha = hashlib.sha256(RUNTIME_BYTES).hexdigest()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProtocolControls)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / 'LAST_CHECKS.log').write_bytes(stream.getvalue().encode('utf-8'))
    source_after = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in source_before}
    sources_unchanged = source_before == source_after and source_before['runtime.py'] == imported_runtime_sha
    receipt = dict(schema='natural_runtime_pure_http_protocol_checks_v1', complete=result.wasSuccessful() and sources_unchanged,
                   tests_run=result.testsRun, subchecks=SUBCHECKS, failures=len(result.failures), errors=len(result.errors),
                   skipped=len(result.skipped), python_version=sys.version.split()[0],
                   source_sha256=source_after, source_before_sha256=source_before, imported_runtime_sha256=imported_runtime_sha,
                   evidence_scope='Pure protocol controls, injected in-memory FAKE sockets only; not real transport or EDA verification.',
                   real_http_connections=0, actual_model_requests=0, actual_native_commands=0, fifo_operations=0,
                   real_execution_admitted=False, independent_validation_qualified=False, adoption=False,
                   source_files_changed_during_checks=not sources_unchanged, fixtures=str(FIXTURES))
    (FIXTURES / 'LAST_CHECKS.json').write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(receipt, ensure_ascii=False))
    if not result.wasSuccessful():
        print(stream.getvalue())
    return 0 if receipt['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
