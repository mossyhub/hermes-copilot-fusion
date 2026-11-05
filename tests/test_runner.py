import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_native import ROOT

class RunnerTests(unittest.TestCase):
    def test_runner_records_executed_ids_and_rejects_empty_suites(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            receipt=Path(folder)/'tests.json'
            for pattern,expected in [('test_native.py',0),('test_missing_deliberate.py',1)]:
                result=subprocess.run([sys.executable,str(ROOT/'scripts/test.py'),'--pattern',pattern,'--receipt',str(receipt)],capture_output=True,text=True,timeout=30)
                self.assertEqual(expected,result.returncode,result.stdout+result.stderr)
                data=json.loads(receipt.read_text())
                self.assertEqual(expected==0,data['success'])
                self.assertEqual(data['tests'],len(data['test_ids']))
                self.assertEqual(4 if expected==0 else 0,data['tests'])
            # Deliberately fail an existing test assertion in an isolated runner process.
            wrapper="import sys,runpy,unittest; from unittest.mock import patch; patch.object(unittest.TestCase,'assertEqual',side_effect=AssertionError('negative-control')).start(); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
            result=subprocess.run([sys.executable,'-c',wrapper,str(ROOT/'scripts/test.py'),'--pattern','test_native.py','--receipt',str(receipt)],capture_output=True,text=True,timeout=30)
            self.assertEqual(1,result.returncode)
            data=json.loads(receipt.read_text())
            self.assertFalse(data['success']); self.assertGreater(data['failures'],0)

if __name__=='__main__': unittest.main()
