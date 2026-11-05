import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from test_native import ROOT

class BuildTests(unittest.TestCase):
    def test_build_is_reproducible_manifest_bound_and_contains_actual_private_transport(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            hashes=[]
            for i in range(2):
                output=Path(folder)/str(i)
                result=subprocess.run([sys.executable,str(ROOT/'scripts/build.py'),'--output',str(output)],capture_output=True,text=True)
                self.assertEqual(0,result.returncode,result.stdout+result.stderr)
                receipt=json.loads((output/'manifest.json').read_text())
                archive=output/receipt['package']
                self.assertEqual(receipt['sha256'],hashlib.sha256(archive.read_bytes()).hexdigest())
                hashes.append(receipt['sha256'])
                with tarfile.open(archive) as tar:
                    prefix='copilot-fusion-provider/'
                    for name,expected in receipt['files'].items():
                        self.assertEqual(expected,hashlib.sha256(tar.extractfile(prefix+name).read()).hexdigest())
                    self.assertEqual((ROOT/'fusion/openai_bridge.py').read_bytes(),tar.extractfile(prefix+'fusion/openai_bridge.py').read())
                    self.assertEqual((ROOT/'fusion/transport.py').read_bytes(),tar.extractfile(prefix+'fusion/transport.py').read())
                    self.assertNotIn('apply_runtime.py',' '.join(tar.getnames()))
            self.assertEqual(hashes[0],hashes[1])

if __name__=='__main__': unittest.main()
