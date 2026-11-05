"""Fresh-only atomic installer and checksum-bound binary staging."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_native import ROOT

class InstallTests(unittest.TestCase):
    def run_install(self, *args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/install.py'),*map(str,args)],capture_output=True,text=True,timeout=20)

    def test_explicit_new_home_is_installed_and_existing_home_is_never_changed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder)/'fresh'
            result=self.run_install('--home',home)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            plugin=home/'plugins/model-providers/copilot-fusion'
            self.assertTrue((plugin/'fusion/client.py').is_file())
            config=(home/'config.yaml').read_bytes()
            self.assertIn(b'copilot-fusion',config)
            self.assertFalse((home/'.env').exists())
            result=self.run_install('--home',home)
            self.assertNotEqual(0,result.returncode)
            self.assertEqual(config,(home/'config.yaml').read_bytes())

    def test_installed_readme_links_have_their_documentation_and_provenance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder)/'fresh'
            result=self.run_install('--home',home)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            plugin=home/'plugins/model-providers/copilot-fusion'
            for name in ('COMPATIBILITY.md','PROVENANCE.json','THIRD_PARTY.md'):
                self.assertTrue((plugin/name).is_file(),'Installer omitted '+name)
                self.assertEqual((ROOT/name).read_bytes(),(plugin/name).read_bytes(),name)

    def test_checksum_mismatch_leaves_no_partial_home(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder)/'fresh'; binary=Path(folder)/'source'
            binary.write_bytes(b'fixture executable'); binary.chmod(0o700)
            result=self.run_install('--home',home,'--bridge',binary,'--bridge-sha256','0'*64)
            self.assertNotEqual(0,result.returncode); self.assertFalse(home.exists())
            result=self.run_install('--home',home,'--bridge',binary,'--bridge-sha256',hashlib.sha256(binary.read_bytes()).hexdigest())
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            installed=home/'plugins/model-providers/copilot-fusion/bin/weave-copilot'
            self.assertEqual(binary.read_bytes(),installed.read_bytes())
            receipt=json.loads((home/'copilot-fusion-install.json').read_text())
            self.assertEqual(hashlib.sha256(binary.read_bytes()).hexdigest(),receipt['binaries']['weave-copilot'])

    def test_missing_relative_default_and_active_home_targets_are_rejected(self):
        for args in [[],['--home','relative'],['--home',str(Path.home()/'.hermes')]]:
            with self.subTest(args=args):
                self.assertNotEqual(0,self.run_install(*args).returncode)

if __name__=='__main__': unittest.main()
