"""Actual formatter + private ACP transport over fixture pipes (Popen boundary only)."""
import importlib.util
import io
import json
from pathlib import Path
import queue
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fusion_package_test', ROOT / '__init__.py', submodule_search_locations=[str(ROOT)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
TOOLS = [{'type':'function','function':{'name':'terminal','description':'SCHEMA_SENTINEL',
    'parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command']}}}]
CALL = {'id':'sdk/opaque Ω:01','name':'terminal','arguments':{'command':"printf 'native Ω'"}}


class NativeProcess:
    def __init__(self, *, capability=1, ack=1, version=1, calls=None, text='', stop='end_turn', images=True,
                 hang=False, models=None, selected=None, events=(), prompt_error=None):
        self.inbox=queue.Queue(); self.exited=threading.Event(); self.initialized=threading.Event()
        self.sent=[]; self.returncode=None; self.stderr=io.StringIO(); self.terminations=0
        self.models=models or ['fusion-standard','fusion-high','fusion-max']
        process=self
        class Input(io.StringIO):
            def write(self, text_line):
                size=super().write(text_line); request=json.loads(text_line); process.sent.append(request)
                if 'method' not in request: return size
                method=request['method']
                if method=='initialize':
                    process.initialized.set()
                if hang: return size
                if method=='session/prompt' and prompt_error is not None:
                    process.inbox.put(json.dumps({'id':request['id'],'error':prompt_error})+'\n')
                    return size
                catalog={'currentModelId':selected or request['params'].get('modelId','fusion-standard'),
                    'availableModels':[{'modelId':m,'name':m} for m in process.models]}
                reply={'initialize':{'agentCapabilities':{'promptCapabilities':{'image':images}},
                                     '_meta':{'hermesToolIntentVersion':capability}},
                       'session/new':{'sessionId':'fixture','models':catalog,'_meta':{'hermesToolIntentVersion':ack}},
                       'session/set_model':{'models':catalog},
                       'session/prompt':{'stopReason':stop,'_meta':{'hermesToolIntentVersion':version,
                           'hermesToolCalls':[CALL] if calls is None else calls},
                           'usage':{'inputTokens':5,'outputTokens':3,'totalTokens':8}}}[method]
                if method=='session/prompt':
                    for event in events:
                        process.inbox.put(json.dumps(event)+'\n')
                    if text:
                        process.inbox.put(json.dumps({'method':'session/update','params':{'sessionId':'fixture',
                            'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':text}}}})+'\n')
                process.inbox.put(json.dumps({'id':request['id'],'result':reply})+'\n')
                return size
        class Output:
            def __iter__(self):
                while not process.exited.is_set():
                    try: yield process.inbox.get(timeout=.02)
                    except queue.Empty: pass
        self.stdin=Input(); self.stdout=Output()
    def poll(self): return self.returncode
    def terminate(self): self.terminations+=1; self.returncode=-15; self.exited.set()
    def kill(self): self.returncode=-9; self.exited.set()
    def wait(self, timeout=2): return self.returncode


class NativeTests(unittest.TestCase):
    def client(self, process):
        client=package.profile.create_client(command='weave-copilot', acp_cwd=str(ROOT))
        self.assertIsNotNone(client, 'profile must construct its own native client')
        import importlib
        module=importlib.import_module(client.__class__.__module__)
        self.module=module
        # Credential policy is tested separately. Only OS launch and sanitizer path discovery replaced.
        scope=patch('agent.secret_scope.current_secret_scope',return_value={})
        # Client already captured absent credentials; use test-owned explicit snapshot.
        client._copilot_credential='fixture-token'
        self.addCleanup(client.close)
        boundary=patch.object(module.subprocess,'Popen',return_value=process)
        boundary.start(); self.addCleanup(boundary.stop)
        pm=patch('pm.environments.selected_venv',return_value=Path(sys.prefix))
        pm.start(); self.addCleanup(pm.stop)
        return client

    def test_catalog_lists_only_enabled_friendly_fusion_rows(self):
        process=NativeProcess(models=['fusion-standard','fusion-high','leaf-id'])
        client=self.client(process)
        with patch.object(package.profile,'create_client',return_value=client):
            rows=package.profile.discover_models()
        self.assertEqual([{'id':'fusion-standard','label':'Fusion Standard'},
                          {'id':'fusion-high','label':'Fusion High'}],rows)
        self.assertEqual({'hermesToolSchemas':[]},next(r for r in process.sent if r.get('method')=='session/new')['params']['_meta'])
        self.assertFalse(any(r.get('method')=='session/prompt' for r in process.sent))

    def test_strict_policy_cannot_be_disabled_or_launch_native_executor(self):
        for overrides in ({'require_native_tools':False}, {'forward_copilot_token':False},
                          {'args':['--copilot-cli','copilot','--hydrafusion']},
                          {'args':['--copilot-cli','copilot','--hydrafusion','--hermes-tools-only','--unsafe']},
                          {'acp_command':'foreign-cli'}, {'acp_args':['--unsafe']}):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex((ValueError,RuntimeError),'strict|launch|native|override'):
                    package.profile.create_client(**overrides)

    def test_followup_preserves_native_tool_call_and_result_identity(self):
        process=NativeProcess(calls=[],text='done'); client=self.client(process)
        client.chat.completions.create(messages=[{'role':'assistant','content':None,'tool_calls':[
            {'id':CALL['id'],'type':'function','function':{'name':'terminal','arguments':json.dumps(CALL['arguments'],ensure_ascii=False)}}]},
            {'role':'tool','tool_call_id':CALL['id'],'content':'ACTUAL_RESULT_SENTINEL'}], tools=TOOLS)
        prompt=next(r for r in process.sent if r.get('method')=='session/prompt')['params']['prompt'][0]['text']
        self.assertIn(CALL['id'],prompt)
        self.assertIn(CALL['arguments']['command'],prompt)
        self.assertIn('ACTUAL_RESULT_SENTINEL',prompt)

    def test_native_roundtrip_owns_negotiation_without_core_hook(self):
        process=NativeProcess(); client=self.client(process)
        response=client.chat.completions.create(messages=[{'role':'user','content':'use terminal'}],tools=TOOLS,model='fusion-standard')
        self.assertEqual('tool_calls',response.choices[0].finish_reason)
        call=response.choices[0].message.tool_calls[0]
        self.assertEqual(CALL['id'],call.id)
        self.assertEqual(CALL['name'],call.function.name)
        self.assertEqual(CALL['arguments'],json.loads(call.function.arguments))
        new=next(r for r in process.sent if r.get('method')=='session/new')
        self.assertEqual({'hermesToolSchemas':TOOLS},new['params']['_meta'])
        prompt=next(r for r in process.sent if r.get('method')=='session/prompt')['params']['prompt'][0]['text']
        self.assertNotIn('SCHEMA_SENTINEL',prompt)
        self.assertNotIn('MUST output tool calls using',prompt)
        self.assertEqual(8,response.usage.total_tokens)
        self.assertEqual(1,process.terminations)


if __name__=='__main__': unittest.main()
