#!/usr/bin/env python3
"""Run local contract tests against the selected unmodified Hermes runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]

class Result(unittest.TextTestResult):
    def startTest(self,test):
        if not hasattr(self,'test_ids'): self.test_ids=[]
        self.test_ids.append(test.id())
        super().startTest(test)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core',type=Path)
    parser.add_argument('--pattern',default='test_*.py')
    parser.add_argument('--receipt',type=Path,default=ROOT/'receipts/tests.json')
    args=parser.parse_args()
    os.environ['PYTHONDONTWRITEBYTECODE']='1'; sys.dont_write_bytecode=True
    if args.core:
        core=args.core.resolve(); sys.path.insert(0,str(core))
        os.environ['HERMES_CORE_SOURCE']=str(core)
        os.environ['PYTHONPATH']=str(core)+os.pathsep+os.environ.get('PYTHONPATH','')
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    receipt={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'success':result.wasSuccessful() and result.testsRun>0,
        'test_ids':getattr(result,'test_ids',[]),'python':sys.version,'executable':sys.executable,
        'scope':'local fixtures + actual unmodified core discovery/preflight/streaming gate; not live SDK or browser',
        'inputs':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('fusion','tests','scripts') for p in sorted((ROOT/folder).rglob('*.py'))}}
    args.receipt.parent.mkdir(parents=True,exist_ok=True)
    args.receipt.write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    print(json.dumps({key:receipt[key] for key in ('tests','failures','errors','skipped','success')}))
    return 0 if receipt['success'] else 1

if __name__=='__main__': sys.exit(main())
