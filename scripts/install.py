#!/usr/bin/env python3
"""Install only into an explicit, nonexistent profile home; never select a live profile."""
from __future__ import annotations
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
RUNTIME_FILES=('__init__.py','plugin.yaml','fusion','LICENSE','THIRD_PARTY.md','README.md','COMPATIBILITY.md','PROVENANCE.json')


def publish_new(source: Path, target: Path):
    if sys.platform.startswith('linux'):
        libc=ctypes.CDLL(None,use_errno=True)
        rename=getattr(libc,'renameat2',None)
        if rename is None:
            raise RuntimeError('Atomic no-replace installation needs Linux renameat2')
        rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        if rename(-100,os.fsencode(source),-100,os.fsencode(target),1)!=0:
            code=ctypes.get_errno(); raise OSError(code,os.strerror(code),str(target))
    elif os.name=='nt':
        os.rename(source,target)  # Windows rename fails when the destination exists.
    else:
        raise RuntimeError('Fresh atomic installer currently supports Linux/Windows only; use manual discovery install')


def copy_verified(source: str, expected: str, target: Path):
    if re.fullmatch('[a-f0-9]{64}',expected or '') is None:
        raise ValueError('A lowercase exact SHA-256 is required for every supplied executable')
    original=Path(source)
    if not original.is_file() or not os.access(original,os.X_OK):
        raise ValueError('Supplied executable must be an executable regular file')
    digest=hashlib.sha256()
    target.parent.mkdir(parents=True,exist_ok=True)
    with original.open('rb') as src, target.open('xb') as dst:
        for block in iter(lambda:src.read(1024*1024),b''):
            digest.update(block); dst.write(block)
        dst.flush(); os.fsync(dst.fileno())
    if digest.hexdigest()!=expected:
        raise ValueError('Executable checksum mismatch; refusing installation')
    target.chmod(0o700)
    return expected


def install(args):
    requested=Path(args.home).expanduser()
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError('--home must be an explicit absolute, nonexistent path')
    home=requested.resolve()
    forbidden={Path.home()/'.hermes'}
    if os.getenv('HERMES_HOME'):
        forbidden.add(Path(os.environ['HERMES_HOME']).resolve())
    if home in forbidden or home.exists():
        raise ValueError('Refusing an existing/default/active profile home')
    if not home.parent.is_dir():
        raise ValueError('Target parent directory must already exist')
    for binary,key in ((args.bridge,args.bridge_sha256),(args.cli,args.cli_sha256)):
        if bool(binary)!=bool(key):
            raise ValueError('Executable and its --*-sha256 must be supplied together')
    with tempfile.TemporaryDirectory(prefix='.fusion-install-',dir=home.parent) as stage_dir:
        stage=Path(stage_dir)/'home'; stage.mkdir(mode=0o700)
        plugin=stage/'plugins/model-providers/copilot-fusion'; plugin.mkdir(parents=True)
        for name in RUNTIME_FILES:
            source=ROOT/name
            if source.is_dir():
                shutil.copytree(source,plugin/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            elif source.is_file():
                shutil.copy2(source,plugin/name)
            elif name in ('__init__.py','plugin.yaml','fusion','LICENSE'):
                raise ValueError('Incomplete provider package: '+name)
        binaries={}
        if args.bridge:
            binaries['weave-copilot']=copy_verified(args.bridge,args.bridge_sha256,plugin/'bin/weave-copilot')
        if args.cli:
            binaries['copilot']=copy_verified(args.cli,args.cli_sha256,plugin/'bin/copilot')
        (stage/'config.yaml').write_text('model:\n  provider: copilot-fusion\n  default: fusion-standard\n  base_url: fusion://copilot\n',encoding='utf-8')
        receipt={'provider':'copilot-fusion','home':str(home),'binaries':binaries,'credentials_bundled':False}
        (stage/'copilot-fusion-install.json').write_text(json.dumps(receipt,indent=2)+'\n')
        publish_new(stage,home)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',required=True)
    parser.add_argument('--bridge'); parser.add_argument('--bridge-sha256')
    parser.add_argument('--cli'); parser.add_argument('--cli-sha256')
    args=parser.parse_args()
    try:
        print(json.dumps(install(args),sort_keys=True))
    except (OSError,ValueError,RuntimeError) as exc:
        parser.exit(1,f'Install refused: {exc}\n')

if __name__=='__main__': main()
