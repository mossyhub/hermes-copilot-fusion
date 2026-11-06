"""Provider error normalization exercised against the real Hermes classifier."""
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fusion_budget_test', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
assert spec is not None and spec.loader is not None
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
client_module = importlib.import_module(spec.name+'.fusion.client')

BUDGET = "Execution failed: Request exceeds the model's prompt budget after reserving output (227570 tokens; limit 200000). Reduce context or compact before continuing."

class BudgetErrorTests(unittest.TestCase):
    def client(self):
        # Formatting has no OS, credential or subprocess boundary.
        return client_module.CopilotACPClient.__new__(client_module.CopilotACPClient)

    def test_native_budget_refusal_enters_real_hermes_compression_recovery(self):
        from agent.error_classifier import classify_api_error
        from agent.model_metadata import get_context_length_from_provider_error
        text = self.client()._request_error('session/prompt', {'code':-32000,'message':BUDGET})
        verdict = classify_api_error(RuntimeError(text), provider='copilot-fusion', model='fusion-standard',
            approx_tokens=124723, context_length=256000, num_messages=295, base_url='fusion://copilot')
        self.assertEqual('context_overflow', verdict.reason.value)
        self.assertTrue(verdict.should_compress)
        self.assertEqual(200000, get_context_length_from_provider_error(text,256000))
        self.assertNotIn('copilot login', text)
        self.assertIn(BUDGET, text)

    def test_generic_rpc_execution_error_does_not_invent_login_advice(self):
        text=self.client()._request_error('session/prompt',{'code':-32000,'message':'Execution failed: worker terminated unexpectedly'})
        self.assertNotIn('copilot login',text)
        self.assertIn('worker terminated unexpectedly',text)

    def test_explicit_authentication_refusal_keeps_login_advice(self):
        text=self.client()._request_error('session/new',{'code':-32000,'message':'Authentication required: not logged in'})
        self.assertIn('copilot login',text)

    def test_native_stream_budget_error_reaps_exact_process_without_tool_intents(self):
        from test_native import NativeProcess,NativeTests,TOOLS
        from agent.error_classifier import classify_api_error
        process=NativeProcess(prompt_error={'code':-32000,'message':BUDGET})
        harness=NativeTests(methodName='test_native_roundtrip_owns_negotiation_without_core_hook')
        self.addCleanup(harness.doCleanups)
        client=harness.client(process)
        with self.assertRaisesRegex(RuntimeError,'Context length exceeded') as caught:
            list(client.chat.completions.create(messages=[{'role':'user','content':'Continue'}],tools=TOOLS,stream=True))
        self.assertEqual('context_overflow',classify_api_error(caught.exception,provider='copilot-fusion',model='fusion-standard').reason.value)
        self.assertEqual(1,len([r for r in process.sent if r.get('method')=='session/prompt']))
        self.assertEqual(1,process.terminations)
        self.assertFalse(client._active_processes)
        self.assertNotIn('copilot login',str(caught.exception))

    def test_real_hermes_recovery_adopts_budget_and_restarts_compressed_history(self):
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        from agent.error_classifier import classify_api_error
        from agent.turn_overflow import recover_from_overflow
        from agent.turn_retry_state import TurnRetryState
        text=self.client()._request_error('session/prompt',{'code':-32000,'message':BUDGET})
        classified=classify_api_error(RuntimeError(text),provider='copilot-fusion',model='fusion-standard')
        original=[{'role':'system','content':'fixture system'}, {'role':'user','content':'old research '*1000},
                  {'role':'assistant','content':'old findings '*1000}, {'role':'user','content':'Continue'},
                  {'role':'assistant','content':None,'tool_calls':[{'id':'already-executed','type':'function','function':{'name':'read_file','arguments':'{}'}}]},
                  {'role':'tool','tool_call_id':'already-executed','content':'ACTUAL_COMMITTED_READ_RESULT'}]
        compressed=[original[0],{'role':'assistant','content':'Summary of old research'},*original[3:]]
        compressor=SimpleNamespace(context_length=256000)
        def update_model(**kw): compressor.context_length=kw['context_length']
        compressor.update_model=Mock(side_effect=update_model)
        agent=SimpleNamespace(model='fusion-standard',provider='copilot-fusion',base_url='fusion://copilot',api_mode='chat_completions',
            context_compressor=compressor,tools=[],max_tokens=0,log_prefix='',_buffer_vprint=Mock(),
            _buffer_diagnostic_status=Mock(),_compress_context=Mock(return_value=(compressed,'fixture system')))
        retry=TurnRetryState()
        with patch('agent.model_metadata.save_provider_context_length') as persist:
            verdict=recover_from_overflow(agent,RuntimeError(text),classified,retry,status_code=None,error_msg=text,
                wrapped_output_cap_budget=None,messages=original,api_messages=original,system_message=original[0],
                active_system_prompt='fixture system',conversation_history=original,approx_tokens=124723,
                compression_attempts=0,max_compression_attempts=3,api_call_count=1,effective_task_id=None)
        self.assertEqual('break',verdict.action)
        self.assertTrue(retry.restart_with_compressed_messages)
        self.assertEqual(200000,compressor.context_length)
        persist.assert_called_once_with('fusion-standard','fusion://copilot',200000,'copilot-fusion')
        agent._compress_context.assert_called_once()
        self.assertEqual('overflow',agent._compress_context.call_args.kwargs['trigger'])
        self.assertEqual('ACTUAL_COMMITTED_READ_RESULT',verdict.messages[-1]['content'])
        self.assertEqual('already-executed',verdict.messages[-1]['tool_call_id'])

    def test_unrelated_error_does_not_enter_context_recovery(self):
        from agent.error_classifier import classify_api_error
        text=self.client()._request_error('session/prompt',{'code':-32603,'message':'Execution failed: malformed response'})
        self.assertNotEqual('context_overflow',classify_api_error(RuntimeError(text),provider='copilot-fusion',model='fusion-standard').reason.value)

if __name__=='__main__': unittest.main()
