"""Stage exact approved native binaries and the already pinned official Node.

No QQ process or account access. Never overwrite an existing runtime tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def stage(native, node):
    pins=json.loads((ROOT/'src/qq_chat_analyzer/providers/qq_independent/native-pins.json').read_text())
    receipt=json.loads((native/'build-receipt.json').read_text(encoding='utf-8-sig'))
    if receipt['build']!=pins['build'] or receipt['minhook_revision']!=pins['minhook_revision']:
        raise ValueError('Native build identity mismatch')
    files={name:native/name for name in pins['binaries']}
    files['node.exe']=node
    expected={**pins['binaries'],'node.exe':pins['node_sha256']}
    expected['MinHook.LICENSE.txt']='d5c2224982b0b95a16b098a561335fa93f3eaf4d0aa964b7843edb986df78dc8'
    files['MinHook.LICENSE.txt']=native/'MinHook.LICENSE.txt'
    for name,path in files.items():
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected[name]:
            raise ValueError('Program artifact mismatch: '+name)
    target=ROOT/'runtime/qq-independent'
    if target.exists():
        if {p.name for p in target.iterdir()} != set(files)|{'build-receipt.json'}:
            raise ValueError('Existing independent runtime contains unknown state')
        for name in files:
            if hashlib.sha256((target/name).read_bytes()).hexdigest()!=expected[name]:
                raise ValueError('Existing runtime differs; preserve it for review')
        return target
    target.mkdir()
    for name,path in files.items(): shutil.copyfile(path,target/name)
    (target/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='ascii')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-build',type=Path,required=True)
    parser.add_argument('--node',type=Path,required=True)
    args=parser.parse_args()
    stage(args.native_build,args.node)
    print('Independent runtime verified; no QQ process accessed.')
