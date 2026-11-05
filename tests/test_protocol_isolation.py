"""Raw JSON lines through the real private RPC pump; only Popen is replaced."""
import json
import unittest
from unittest.mock import patch

import test_native as native
from test_native import NativeProcess, TOOLS


def update(kind, text, session='fixture'):
    params = {'update': {'sessionUpdate': kind, 'content': {'type': 'text', 'text': text}}}
    if session is not None:
        params['sessionId'] = session
    return {'method': 'session/update', 'params': params}


class WireProcess(NativeProcess):
    def __init__(self, *, before_new=(), raw_prompt=None, followup=True, **kwargs):
        super().__init__(**kwargs)
        original = self.stdin.write
        def write(line):
            request = json.loads(line)
            if request.get('method') == 'session/prompt' and raw_prompt is not None:
                self.sent.append(request)
                self.inbox.put(raw_prompt.replace('REQUEST_ID', str(request['id'])) + '\n')
                if followup:
                    # Even a valid executable response cannot recover an ambiguous line.
                    self.inbox.put(json.dumps({'id': request['id'], 'result': {
                        'stopReason': 'end_turn', '_meta': {'hermesToolIntentVersion': 1,
                        'hermesToolCalls': [native.CALL]}}}) + '\n')
                return len(line)
            if request.get('method') == 'session/new':
                for event in before_new:
                    self.inbox.put(json.dumps(event) + '\n')
            return original(line)
        self.stdin.write = write


class ProtocolIsolationTests(unittest.TestCase):
    client = native.NativeTests.client

    def assert_response(self, events, *, before_new=()):
        process = WireProcess(calls=[], events=events, before_new=before_new)
        client = self.client(process)
        result = client.chat.completions.create(messages=[], timeout=2)
        message = result.choices[0].message
        self.assertEqual('OWN_TEXT', message.content)
        self.assertEqual('OWN_THOUGHT', message.reasoning_content)
        self.assertFalse(message.tool_calls)
        self.assertEqual(1, process.terminations)

    def own_events(self):
        return [update('agent_message_chunk', 'OWN_TEXT'), update('agent_thought_chunk', 'OWN_THOUGHT')]

    def test_matching_session_text_and_reasoning_reach_response(self):
        self.assert_response(self.own_events())

    def test_foreign_session_text_and_reasoning_never_reach_response(self):
        self.assert_response([update('agent_message_chunk', 'FOREIGN_TEXT', 'foreign'),
                              update('agent_thought_chunk', 'FOREIGN_THOUGHT', 'foreign')] + self.own_events())

    def test_missing_session_text_and_reasoning_never_reach_response(self):
        self.assert_response([update('agent_message_chunk', 'MISSING_TEXT', None),
                              update('agent_thought_chunk', 'MISSING_THOUGHT', None)] + self.own_events())

    def test_pre_session_updates_never_reach_generic_text_handler(self):
        process = WireProcess(calls=[], events=self.own_events(), before_new=[
            update('agent_message_chunk', 'EARLY_TEXT'), update('agent_thought_chunk', 'EARLY_THOUGHT')])
        client = self.client(process)
        base = self.module.ACPClient
        original = base._handle_server_message
        delegated = []
        def handle(instance, msg, **kwargs):
            if msg.get('method') == 'session/update':
                delegated.append(msg['params']['update']['content']['text'])
            return original(instance, msg, **kwargs)
        with patch.object(base, '_handle_server_message', handle):
            result = client.chat.completions.create(messages=[], timeout=2)
        self.assertEqual('OWN_TEXT', result.choices[0].message.content)
        self.assertEqual(['OWN_TEXT', 'OWN_THOUGHT'], delegated)

    def raw_result(self, call):
        return ('{"jsonrpc":"2.0","id":REQUEST_ID,"result":{"stopReason":"end_turn",'
                '"_meta":{"hermesToolIntentVersion":1,"hermesToolCalls":[' + call + ']}}}')

    def assert_protocol_error(self, raw, *, followup=True):
        process = WireProcess(raw_prompt=raw, followup=followup)
        client = self.client(process)
        stream = client.chat.completions.create(messages=[], tools=TOOLS, stream=True, timeout=.6)
        executable = []
        try:
            with self.assertRaisesRegex(RuntimeError, 'Malformed ACP JSON-RPC message') as error:
                for chunk in stream:
                    for choice in chunk.choices:
                        executable.extend(getattr(choice.delta, 'tool_calls', None) or [])
            self.assertNotIn('SECRET', str(error.exception))
            self.assertIsNone(error.exception.__cause__)
            self.assertIsNone(error.exception.__context__)
            self.assertEqual([], executable)
            self.assertFalse(stream.worker.is_alive())
            self.assertEqual('error', stream.turn.runtime_status)
            self.assertEqual(1, process.terminations)
            self.assertNotIn(process, client._active_processes)
        finally:
            stream.close()

    def test_raw_duplicate_call_arguments_member_fails_before_tool_handoff(self):
        self.assert_protocol_error(self.raw_result(
            '{"id":"opaque/Ω:01","name":"terminal",'
            '"arguments":{"command":"FIRST_SECRET"},"arguments":{"command":"SECOND_SECRET"}}'))

    def test_raw_nested_duplicate_argument_key_fails_before_tool_handoff(self):
        self.assert_protocol_error(self.raw_result(
            '{"id":"opaque/Ω:01","name":"terminal","arguments":'
            '{"command":"ok","nested":[{"SECRET_KEY":1,"SECRET_KEY":2}]}}'))

    def test_raw_duplicate_top_level_member_fails_before_tool_handoff(self):
        self.assert_protocol_error('{"id":REQUEST_ID,' + self.raw_result(json.dumps(native.CALL))[1:])

    def test_raw_nonobject_and_invalid_json_fail_without_waiting_for_timeout(self):
        for raw in ('[]', 'null', '"SECRET_STRING"', '{"SECRET_INVALID":'):
            with self.subTest(raw_type=raw[:1]):
                # No later reply: a stopped pump must wake its consumer, not time out.
                self.assert_protocol_error(raw, followup=False)

    def test_clean_raw_native_intent_preserves_opaque_id_and_argument_values(self):
        call = {**native.CALL, 'arguments': {'command': '  printf "Ω"\\n  ',
                'nested': [{'flag': False, 'nothing': None, 'integer': 9007199254740993}],
                'escaped': '\\u0041\\\\literal'}}
        process = WireProcess(raw_prompt=self.raw_result(json.dumps(call, ensure_ascii=False)), followup=False)
        client = self.client(process)
        result = client.chat.completions.create(messages=[], tools=TOOLS, timeout=2)
        actual = result.choices[0].message.tool_calls[0]
        self.assertEqual('tool_calls', result.choices[0].finish_reason)
        self.assertEqual(call['id'], actual.id)
        self.assertEqual(call['arguments'], json.loads(actual.function.arguments))
        self.assertEqual(1, process.terminations)


if __name__ == '__main__':
    unittest.main()
