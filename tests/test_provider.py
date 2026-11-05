"""Clean-process discovery and declared host integration; no runtime patches."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import providers
CORE = Path(os.environ.get('HERMES_CORE_SOURCE') or Path(providers.__file__).resolve().parents[1])


def stage(home):
    target = Path(home) / 'plugins/model-providers/copilot-fusion'
    target.mkdir(parents=True)
    for name in ('__init__.py', 'plugin.yaml', 'fusion'):
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=shutil.ignore_patterns('__pycache__'))
        elif source.exists():
            shutil.copy2(source, target / name)
    return target


class DiscoveryTests(unittest.TestCase):
    def test_external_process_preflight_matches_bundled_bridge_and_cli(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as home:
            plugin=stage(home); (plugin/'bin').mkdir()
            for name in ('weave-copilot','copilot'):
                path=plugin/'bin'/name; path.write_text('#!/bin/sh\nexit 0\n'); path.chmod(0o700)
            env=dict(os.environ,HERMES_HOME=home,PYTHONPATH=str(CORE),PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,'-c','''
from providers import get_provider_profile
from hermes_cli.auth import resolve_external_process_provider_credentials
from pathlib import Path
p=get_provider_profile('copilot-fusion')
c=resolve_external_process_provider_credentials('copilot-fusion')
assert c['command']==p.process_command
assert c['args']==list(p.process_args)
assert c['base_url']==p.base_url
assert c['args'][1]==str(Path(p.process_command).with_name('copilot')), 'bundled CLI must not fall through to PATH'
client=p.create_client(command=c['command'],args=c['args'])
assert client._acp_command==c['command'] and client._acp_args==c['args']
client.close()
'''],env=env,cwd=home,capture_output=True,text=True,timeout=30)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def test_normal_discovery_declares_isolated_streaming_provider(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as home:
            env = dict(os.environ, HERMES_HOME=home, PYTHONPATH=str(CORE), PYTHONDONTWRITEBYTECODE='1')
            baseline = subprocess.run([sys.executable, '-c', '''
import json
from providers import get_provider_profile
print(json.dumps({name:getattr(get_provider_profile(name),'name',None) for name in ('copilot','copilot-acp')}))
'''], env=env, capture_output=True, text=True, cwd=home, timeout=30)
            self.assertEqual(0,baseline.returncode,baseline.stdout+baseline.stderr)
            env['FUSION_TEST_PROVIDER_BASELINE']=baseline.stdout.strip()
            stage(home)
            result = subprocess.run([sys.executable, '-c', '''
import json,sys,os
from providers import get_provider_profile
p=get_provider_profile('copilot-fusion')
assert p is not None, 'ordinary provider discovery did not load copilot-fusion'
assert p.auth_type=='external_process' and p.supports_streaming is True
assert p.supports_vision is True
assert p.name=='copilot-fusion' and not p.aliases
baseline=json.loads(os.environ['FUSION_TEST_PROVIDER_BASELINE'])
assert {name:getattr(get_provider_profile(name),'name',None) for name in baseline}==baseline, 'plugin changed an existing provider or added a sibling alias'
assert p.get_model_context_length('fusion-standard') is None
assert p.process_args[-2:]==('--hydrafusion','--hermes-tools-only')
from types import SimpleNamespace
from agent.turn_api_call import _should_stream
a=SimpleNamespace(provider=p.name,base_url=p.base_url,_has_stream_consumers=lambda:True)
assert _should_stream(a), 'host streaming gate must honor the plugin without a patch'
assert 'api.fusion_runtime' not in sys.modules
print(json.dumps({'name':p.name,'streaming':p.supports_streaming,'args':p.process_args}))
'''], env=env, capture_output=True, text=True, cwd=home, timeout=30)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual('copilot-fusion', json.loads(result.stdout)['name'])


if __name__ == '__main__':
    unittest.main()
