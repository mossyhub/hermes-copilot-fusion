#!/usr/bin/env python3
"""Catalog/inference blackbox for an explicitly selected installed profile. Never executes tools."""
import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import sys


def plain(value):
    if value is None or isinstance(value,(str,int,float,bool)): return value
    if isinstance(value,dict): return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [plain(v) for v in value]
    if hasattr(value,'model_dump'): return plain(value.model_dump())
    return plain(vars(value))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',required=True)
    commands=parser.add_subparsers(dest='action',required=True)
    commands.add_parser('catalog')
    infer=commands.add_parser('infer')
    infer.add_argument('--model',default='fusion-standard')
    infer.add_argument('--prompt',required=True)
    infer.add_argument('--stream',action='store_true')
    infer.add_argument('--tools-json',type=Path)
    infer.add_argument('--image',type=Path,action='append',default=[])
    infer.add_argument('--timeout',type=float,default=300)
    args=parser.parse_args()
    home=Path(args.home).expanduser()
    if not home.is_absolute() or not home.is_dir(): parser.error('--home must name an existing absolute profile home')
    os.environ['HERMES_HOME']=str(home.resolve())
    # This is a new process dedicated to exactly this owner, not a multiplexed host mutation.
    from dotenv import load_dotenv
    load_dotenv(home/'.env',override=True)
    from providers import get_provider_profile
    from hermes_cli.auth import resolve_external_process_provider_credentials
    profile=get_provider_profile('copilot-fusion')
    if profile is None: parser.error('copilot-fusion is not installed in the selected home')
    credentials=resolve_external_process_provider_credentials(profile.name)
    if args.action=='catalog':
        print(json.dumps(profile.discover_models(command=credentials['command'],args=credentials['args']),ensure_ascii=False))
        return
    tools=json.loads(args.tools_json.read_text()) if args.tools_json else []
    content=[{'type':'text','text':args.prompt}]
    for path in args.image:
        mime=mimetypes.guess_type(path)[0] or 'application/octet-stream'
        content.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode('ascii')}})
    client=profile.create_client(command=credentials['command'],args=credentials['args'])
    try:
        result=client.chat.completions.create(messages=[{'role':'user','content':content}],model=args.model,
            tools=tools,stream=args.stream,timeout=args.timeout)
        if args.stream:
            with result:
                for chunk in result: print(json.dumps(plain(chunk),ensure_ascii=False),flush=True)
        else:
            print(json.dumps(plain(result),ensure_ascii=False))
    finally: client.close()

if __name__=='__main__': main()
