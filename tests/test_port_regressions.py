"""Adopted ACP contract regressions, adapted from the reference plugin's tested behavior.
These qualify the isolated port, not live SDK/browser acceptance.
"""
import asyncio
import base64
from contextvars import ContextVar
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import test_native as native
from test_native import NativeProcess, package, TOOLS, CALL, ROOT

PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZa0AAAAASUVORK5CYII='

def update(kind, **values):
    return {'method':'session/update','params':{'sessionId':'fixture','update':{'sessionUpdate':kind,**values}}}

class PortRegressionTests(unittest.TestCase):
    client=native.NativeTests.client

    def test_exact_negotiation_versions_fail_closed(self):
        for options in ({'capability':True},{'ack':True},{'version':True},{'capability':2},{'ack':2},{'version':2}):
            with self.subTest(options=options):
                process=NativeProcess(**options); client=self.client(process)
                with self.assertRaises(RuntimeError):
                    client.chat.completions.create(messages=[],tools=TOOLS)

    def test_native_intents_preserve_parallel_ids_and_nested_arguments(self):
        second={**CALL,'id':'sdk/second','arguments':{'command':'two','nested':{'bool':False,'num':3,'list':['Ω',None]}}}
        client=self.client(NativeProcess(calls=[CALL,second]))
        result=client.chat.completions.create(messages=[],tools=TOOLS)
        calls=result.choices[0].message.tool_calls
        self.assertEqual([CALL['id'],second['id']],[c.id for c in calls])
        self.assertEqual(second['arguments'],json.loads(calls[1].function.arguments))

    def test_invalid_native_intents_never_become_streamed_executable_chunks(self):
        cases=[[{**CALL,'name':'bash'}],[{**CALL,'arguments':'{}'}],[{**CALL,'id':''}], [CALL,CALL],
            [CALL,{**CALL,'id':'other'}],[{**CALL,'arguments':{'large':'x'*(1024*1024)}}], [CALL]*33]
        for calls in cases:
            with self.subTest(count=len(calls)):
                client=self.client(NativeProcess(calls=calls)); executable=[]
                with self.assertRaises(RuntimeError):
                    for chunk in client.chat.completions.create(messages=[],tools=TOOLS,stream=True):
                        for choice in chunk.choices:
                            executable.extend(getattr(choice.delta,'tool_calls',None) or [])
                self.assertEqual([],executable)

    def test_invalid_schema_names_caps_duplicates_and_nonfinite_fail_before_spawn(self):
        cases=[TOOLS*2,TOOLS*257,[{'type':'function','function':{'name':'bad name'}}],
            [{'type':'function','function':{'name':'ok','parameters':[]}}],
            [{'type':'function','function':{'name':'ok','parameters':{'x':float('nan')}}}],
            [{'type':'function','function':{'name':'ok','description':'x'*(2*1024*1024)}}]]
        for tools in cases:
            with self.subTest(count=len(tools)):
                process=NativeProcess(); client=self.client(process)
                with self.assertRaises(RuntimeError): client.chat.completions.create(messages=[],tools=tools)
                self.assertEqual([],process.sent)

    def test_none_and_named_choices_only_declare_selected_tools(self):
        other={'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}
        for choice,expected,calls in [('none',[],[]),({'type':'function','function':{'name':'terminal'}},TOOLS,[CALL])]:
            with self.subTest(choice=choice):
                process=NativeProcess(calls=calls); client=self.client(process)
                client.chat.completions.create(messages=[],tools=TOOLS+[other],tool_choice=choice)
                new=next(r for r in process.sent if r.get('method')=='session/new')
                self.assertEqual(expected,new['params']['_meta']['hermesToolSchemas'])

    def test_literal_text_examples_remain_data(self):
        example='<tool_call>'+json.dumps({'id':'literal','type':'function','function':{'name':'terminal','arguments':'{}'}})+'</tool_call>'
        client=self.client(NativeProcess(calls=[],text=example))
        result=client.chat.completions.create(messages=[],tools=TOOLS)
        self.assertEqual(example,result.choices[0].message.content)
        self.assertFalse(result.choices[0].message.tool_calls)

    def test_cancelled_native_result_has_no_tool_handoff(self):
        client=self.client(NativeProcess(stop='cancelled'))
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            client.chat.completions.create(messages=[],tools=TOOLS)

    def test_explicit_missing_or_differently_acknowledged_model_never_falls_back(self):
        for model,process in [('unknown',NativeProcess()),('fusion-high',NativeProcess(selected='fusion-standard'))]:
            with self.subTest(model=model):
                client=self.client(process)
                with self.assertRaises(RuntimeError): client.chat.completions.create(messages=[],model=model)
                self.assertFalse(any(r.get('method')=='session/prompt' for r in process.sent))

    def test_concrete_enabled_leaf_is_selectable_without_catalog_pollution(self):
        process=NativeProcess(models=['leaf-id']); client=self.client(process)
        client.chat.completions.create(messages=[],tools=TOOLS,model='leaf-id')
        self.assertEqual('leaf-id',next(r for r in process.sent if r.get('method')=='session/set_model')['params']['modelId'])

    def test_inline_image_blocks_reach_negotiated_native_prompt(self):
        process=NativeProcess(calls=[]); client=self.client(process)
        messages=[{'role':'user','content':[{'type':'text','text':'look'},
            {'type':'image_url','image_url':{'url':'data:image/png;base64,'+PNG}}]}]
        client.chat.completions.create(messages=messages)
        blocks=next(r for r in process.sent if r.get('method')=='session/prompt')['params']['prompt']
        self.assertEqual([{'type':'image','mimeType':'image/png','data':PNG}],[b for b in blocks if b['type']=='image'])
        self.assertEqual('image_url',messages[0]['content'][1]['type'])

    def test_image_remote_urls_bad_mime_and_missing_capability_are_rejected(self):
        for url,images in [('https://example.invalid/a.png',True),('data:image/jpeg;base64,'+PNG,True),
                           ('data:image/png;base64,'+PNG,False)]:
            with self.subTest(images=images,url=url[:30]):
                process=NativeProcess(images=images); client=self.client(process)
                with self.assertRaises((ValueError,RuntimeError)):
                    client.chat.completions.create(messages=[{'role':'user','content':[{'type':'image_url','image_url':{'url':url}}]}])
                self.assertFalse(any(r.get('method')=='session/prompt' for r in process.sent))

    def test_native_rpc_files_and_permissions_remain_denied(self):
        events=[{'id':500,'method':'fs/write_text_file','params':{'path':str(ROOT/'MUST_NOT_EXIST'),'content':'unsafe'}},
                {'id':501,'method':'fs/read_text_file','params':{'path':str(ROOT/'LICENSE')}},
                {'id':502,'method':'session/request_permission','params':{}}]
        process=NativeProcess(calls=[],events=events); client=self.client(process)
        client.chat.completions.create(messages=[])
        replies={r['id']:r for r in process.sent if 'method' not in r}
        self.assertEqual(-32601,replies[500]['error']['code'])
        self.assertEqual(-32601,replies[501]['error']['code'])
        self.assertEqual('cancelled',replies[502]['result']['outcome']['outcome'])
        self.assertFalse((ROOT/'MUST_NOT_EXIST').exists())
        init=process.sent[0]['params']['clientCapabilities']['fs']
        self.assertEqual({'readTextFile':False,'writeTextFile':False},init)

    def test_progress_stream_reports_native_model_context_and_billing_separately(self):
        events=[{'method':'_fleet/model','params':{'sessionId':'fixture','model':'actual-leaf'}},
            update('usage_update',used=100,size=800,_meta={'call':{'input':40,'output':2}})]
        client=self.client(NativeProcess(calls=[],text='answer',events=events))
        stream=client.chat.completions.create(messages=[],stream=True)
        chunks=list(stream)
        reasoning=''.join(getattr(c.delta,'reasoning_content',None) or '' for chunk in chunks for c in chunk.choices)
        self.assertIn('actual-leaf',reasoning); self.assertIn('100 / 800',reasoning)
        self.assertEqual(8,chunks[-1].usage.total_tokens)
        self.assertEqual(64,stream.queue.maxsize)
        self.assertFalse(stream.worker.is_alive())

    def test_native_progress_is_observable_before_prompt_completion(self):
        process=NativeProcess(calls=[]); client=self.client(process)
        original=process.stdin.write; pending=threading.Event()
        def write(line):
            request=json.loads(line)
            if request.get('method')=='session/prompt':
                process.sent.append(request); pending.set()
                process.inbox.put(json.dumps({'method':'_fleet/model','params':{'sessionId':'fixture','model':'live-native-leaf'}})+'\n')
                return len(line)
            return original(line)
        process.stdin.write=write
        stream=client.chat.completions.create(messages=[],stream=True)
        chunks=[]; received=threading.Event(); iterator=iter(stream)
        def first():
            try: chunks.append(next(iterator))
            finally: received.set()
        reader=threading.Thread(target=first,daemon=True); reader.start()
        try:
            self.assertTrue(pending.wait(2)); self.assertTrue(received.wait(2))
            self.assertIn('live-native-leaf',chunks[0].choices[0].delta.reasoning_content)
            self.assertFalse(stream.finished); self.assertTrue(stream.worker.is_alive())
        finally:
            stream.close(); reader.join(3)

    def test_context_is_unknown_until_native_report_and_resets_on_identity_change(self):
        events=[update('usage_update',used=100,size=800),
            {'method':'_fleet/model','params':{'sessionId':'fixture','model':'new-leaf'}}]
        client=self.client(NativeProcess(calls=[],events=events))
        result=client.chat.completions.create(messages=[])
        self.assertIsNone(result.hermes_acp_context)
        self.assertEqual(['new-leaf'],result.hermes_acp_used_models)

    def test_invalid_context_boolean_and_cross_session_events_are_ignored(self):
        foreign=update('usage_update',used=1,size=2); foreign['params']['sessionId']='foreign'
        events=[foreign,update('usage_update',used=True,size=100),update('usage_update',used=200,size=100)]
        result=self.client(NativeProcess(calls=[],events=events)).chat.completions.create(messages=[])
        self.assertIsNone(result.hermes_acp_context)

    def test_stream_cancel_reaps_only_exact_turn(self):
        first=NativeProcess(hang=True); second=NativeProcess(hang=True)
        client=self.client(first)
        # helper's Popen patch is the OS boundary; keep the two clients' turn state real.
        with patch.object(self.module.subprocess,'Popen',side_effect=[first,second]):
            a=client.chat.completions.create(messages=[],stream=True)
            self.assertTrue(first.initialized.wait(2))
            b=client.chat.completions.create(messages=[],stream=True)
            self.assertTrue(second.initialized.wait(2))
            a.close()
            self.assertFalse(a.worker.is_alive()); self.assertIsNone(second.poll())
            self.assertNotIn(first,client._active_processes); self.assertIn(second,client._active_processes)
            b.close(); self.assertFalse(b.worker.is_alive())
            self.assertEqual(1,first.terminations); self.assertEqual(1,second.terminations)

    def test_close_during_popen_retires_late_child_before_initialize(self):
        process=NativeProcess(hang=True); client=self.client(process)
        entered=threading.Event(); release=threading.Event()
        def spawn(*args,**kwargs):
            entered.set(); release.wait(3); return process
        with patch.object(self.module.subprocess,'Popen',side_effect=spawn):
            stream=client.chat.completions.create(messages=[],stream=True)
            self.assertTrue(entered.wait(2))
            closer=threading.Thread(target=stream.close); closer.start()
            self.assertTrue(stream.stopped.wait(1)); release.set(); closer.join(4)
            self.assertFalse(stream.worker.is_alive()); self.assertIsNotNone(process.poll())
            self.assertFalse(process.initialized.is_set())

    def test_client_credential_snapshot_uses_installed_scope_not_ambient(self):
        with patch.dict(os.environ,{'COPILOT_GITHUB_TOKEN':'foreign'}), \
             patch('agent.secret_scope.current_secret_scope',return_value={}), \
             patch('agent.secret_scope.get_secret',return_value='scoped-owner'):
            client=package.profile.create_client(acp_cwd=str(ROOT))
        self.addCleanup(client.close)
        self.assertEqual('scoped-owner',client._copilot_credential)

    def test_unscoped_client_uses_owner_policy_and_missing_owner_does_not_borrow(self):
        for owner,expected in [({'COPILOT_GITHUB_TOKEN':'owner-file'},'owner-file'),({},'')]:
            with patch.dict(os.environ,{'COPILOT_GITHUB_TOKEN':'foreign'}), \
                 patch('agent.secret_scope.current_secret_scope',return_value=None), \
                 patch('tui_gateway.launch_profile_policy.owner_secret_scope',return_value=owner) as lookup:
                client=package.profile.create_client(acp_cwd=str(ROOT))
            self.addCleanup(client.close); self.assertEqual(expected,client._copilot_credential)
            lookup.assert_called_once()
            if not expected:
                with self.assertRaisesRegex(RuntimeError,'credential forwarding requires'):
                    client.chat.completions.create(messages=[])

    def test_stream_worker_retains_callers_contextvars(self):
        marker=ContextVar('fusion_fixture_marker',default=None)
        token=marker.set('caller-scope'); client=self.client(NativeProcess(calls=[])); seen=[]
        original=client._complete
        def complete(*args): seen.append(marker.get()); return original(*args)
        try:
            with patch.object(client,'_complete',side_effect=complete):
                self.assertTrue(list(client.chat.completions.create(messages=[],stream=True)))
            self.assertEqual(['caller-scope'],seen)
        finally: marker.reset(token)

    def test_artifact_links_only_rewrite_verified_workspace_files(self):
        client=self.client(NativeProcess(calls=[]))
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'a Ω.txt'; path.write_text('artifact')
            raw='[file](a%20%CE%A9.txt) [outside](../LICENSE) [web](https://example.invalid/a)\n```\n[file](a%20%CE%A9.txt)\n```'
            formatted=self.module.webui_artifact_links(raw,folder)
            self.assertIn(path.as_uri(),formatted)
            self.assertIn('[outside](../LICENSE)',formatted)
            self.assertIn('```\n[file](a%20%CE%A9.txt)',formatted)

if __name__=='__main__': unittest.main()
