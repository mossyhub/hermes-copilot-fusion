"""Blackbox CLI through normal discovery and actual OS ACP pipes, no provider/core injection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_native import ROOT
from test_provider import CORE, stage
import os

class BlackboxTests(unittest.TestCase):
    def test_catalog_and_streamed_native_inference_via_ordinary_discovery(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder)/'home'; home.mkdir(); plugin=stage(home)
            (home/'.env').write_text('COPILOT_GITHUB_TOKEN=fixture-owner-token\n')
            (plugin/'bin').mkdir(); binary=plugin/'bin/weave-copilot'
            binary.write_text('''#!/usr/bin/env python3
import json,sys
models={'currentModelId':'fusion-standard','availableModels':[{'modelId':m} for m in ['fusion-standard','fusion-high','fusion-max']]}
for line in sys.stdin:
 r=json.loads(line); method=r.get('method'); p=r.get('params',{})
 if not method: continue
 if method=='initialize': result={'agentCapabilities':{'promptCapabilities':{'image':True}},'_meta':{'hermesToolIntentVersion':1}}
 elif method=='session/new':
  assert set(p['_meta'])=={'hermesToolSchemas'}
  result={'sessionId':'pipes','models':models,'_meta':{'hermesToolIntentVersion':1}}
 elif method=='session/set_model':
  models['currentModelId']=p['modelId']; result={'models':models}
 elif method=='session/prompt':
  print(json.dumps({'method':'_fleet/model','params':{'sessionId':'pipes','model':'fixture-leaf'}}),flush=True)
  print(json.dumps({'method':'session/update','params':{'sessionId':'pipes','update':{'sessionUpdate':'agent_message_chunk','content':{'text':'OS_PIPE_ANSWER'}}}}),flush=True)
  result={'stopReason':'end_turn','_meta':{'hermesToolIntentVersion':1,'hermesToolCalls':[]},'usage':{'inputTokens':2,'outputTokens':1,'totalTokens':3}}
 else: raise RuntimeError(method)
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
'''); binary.chmod(0o700)
            env=dict(os.environ,HERMES_HOME=str(home),PYTHONPATH=str(CORE),PYTHONDONTWRITEBYTECODE='1')
            # This copied host's PM stamp names an unavailable host venv. Override ONLY its path lookup.
            wrapper='''import sys,runpy; from pathlib import Path; from unittest.mock import patch
with patch('pm.environments.selected_venv',return_value=Path(sys.prefix)):
 runpy.run_path(sys.argv.pop(1),run_name='__main__')
'''
            for command in [['catalog'],['infer','--model','fusion-high','--prompt','hello','--stream']]:
                result=subprocess.run([sys.executable,'-c',wrapper,str(ROOT/'scripts/probe.py'),'--home',str(home),*command],
                    cwd=folder,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                if command[0]=='catalog':
                    self.assertEqual(['Fusion Standard','Fusion High','Fusion Max'],[r['label'] for r in json.loads(result.stdout)])
                else:
                    rows=[json.loads(line) for line in result.stdout.splitlines()]
                    self.assertIn('fixture-leaf',result.stdout)
                    self.assertIn('OS_PIPE_ANSWER',result.stdout)
                    self.assertEqual(3,rows[-1]['usage']['total_tokens'])

if __name__=='__main__': unittest.main()
