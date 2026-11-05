#!/usr/bin/env python3
"""Reproducible source package, including plugin-private transport and executable receipts."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]


def build(output):
    files={}
    for name in ('__init__.py','plugin.yaml','README.md','LICENSE','THIRD_PARTY.md','COMPATIBILITY.md','PROVENANCE.json'):
        path=ROOT/name
        if path.is_file(): files[name]=path.read_bytes()
    for folder in ('fusion','scripts','tests','receipts'):
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                files[str(path.relative_to(ROOT))]=path.read_bytes()
    digests={name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}
    files['SHA256SUMS']=''.join(f'{digest}  {name}\n' for name,digest in digests.items()).encode()
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer,mode='wb',mtime=0,filename='') as gz:
        with tarfile.open(fileobj=gz,mode='w',format=tarfile.PAX_FORMAT) as tar:
            for name,data in sorted(files.items()):
                info=tarfile.TarInfo('copilot-fusion-provider/'+name)
                info.size=len(data); info.mode=0o755 if name.startswith('scripts/') else 0o644
                info.mtime=0; info.uid=info.gid=0; info.uname=info.gname=''
                tar.addfile(info,io.BytesIO(data))
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    package='copilot-fusion-provider-0.1.0.tar.gz'
    data=buffer.getvalue(); digest=hashlib.sha256(data).hexdigest()
    (output/package).write_bytes(data)
    manifest={'package':package,'sha256':digest,'files':digests,'binaries_bundled':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    (output/(package+'.sha256')).write_text(f'{digest}  {package}\n')
    print(json.dumps({'package':str(output/package),'sha256':digest,'file_count':len(digests)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    build(parser.parse_args().output)
