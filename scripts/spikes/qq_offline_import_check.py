"""Fictional offline-import feasibility; never discovers or accesses real QQ.

Uses the production Windows frozen-input and authentication/decryption paths.
The only substituted OS observation is the exit state of our fictional writer.
One owned Job bounds the entire diagnostic and all its children.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
ENV = ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP',
       'MPLCONFIGDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME')

PROGRAM = r'''
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {randomBytes,pbkdf2Sync} from 'node:crypto';
import {createInterface} from 'node:readline';
const {encode} = await import(ENCODER);
const {observeCdeResponse,COMMAND} = await import(OBSERVER);
const {decryptSnapshot} = await import(DECRYPTOR);
const root=process.argv[2], plain=readFileSync(join(root,'seed.db'));
const secret=randomBytes(24).map(b=>97+b%26), owned=[secret,plain];
let packet;
function field(n,b) {
  assert.ok(b.length<128);
  return Buffer.concat([Buffer.from([n*8+2,b.length]),b]);
}
function event() { return {command:COMMAND,direction:'receive',error:0,truncated:false,
  originalLength:packet.length,payload:Buffer.from(packet)}; }
const request={version:'9.9.37-54395',profile:'ntqq-sha1-4096-kdf4000',
  sessionGeneration:'fictional-offline-acquisition',account:'100000001'};
try {
  // Same credential and different salts under two different account labels.
  // Neither a directory label nor a caller-supplied UIN is authenticated by MAC.
  for(const account of ['100000001','100000002']) {
    const folder=join(root,account,'nt_qq','nt_db');mkdirSync(folder,{recursive:true});
    const salt=randomBytes(16),raw=pbkdf2Sync(secret,salt,4000,32,'sha512');
    try { const bytes=encode(plain,raw,salt);
      try {writeFileSync(join(folder,'nt_msg.db'),bytes,{flag:'wx'});} finally {bytes.fill(0);}
    } finally {salt.fill(0);raw.fill(0);}
  }
  const inner=field(1,secret),body=field(2,inner);
  const envelope=field(4,body);
  packet=Buffer.concat([Buffer.from([8,0xde,0x19,16,2,24,0]),envelope]);
  inner.fill(0);body.fill(0);envelope.fill(0);secret.fill(0);
  console.log(JSON.stringify({phase:'fixture_event_held',key_lease_created:false}));
  const line=await new Promise((resolve,reject)=>{
    const input=createInterface({input:process.stdin});
    input.once('line',s=>{input.close();resolve(s);});input.once('error',reject);
  });
  const selections=JSON.parse(line);assert.equal(selections.length,2);
  let authenticated=0, borrowed;
  for(const selection of selections) {
    const page=readFileSync(selection.path).subarray(0,5120),e=event();
    try {
      assert.equal(observeCdeResponse(e,{...request,firstPage:page},
        {deadline:performance.now()+5000},raw=>{
          borrowed=raw; assert.equal(decryptSnapshot(selection,page,raw).all_pages_authenticated,true);
        }).state,'authenticated_event');
      authenticated++;
      assert.ok(borrowed.every(b=>b===0));assert.ok(e.payload.every(b=>b===0));
    } finally {page.fill(0);}
  }
  const page=readFileSync(selections[0].path).subarray(0,5120);
  const wrong=Buffer.from(page);wrong[1050]^=1;
  for(const mode of ['wrong_database','cancelled','expired','consumer_failure','async_consumer']) {
    const e=event(),abort=new AbortController();if(mode==='cancelled')abort.abort();
    const expected={wrong_database:'key_not_authenticated',cancelled:'cancelled',expired:'deadline_reached',
      consumer_failure:'key_source_failed',async_consumer:'async_source_unsupported'}[mode];
    borrowed=undefined;
    assert.throws(()=>observeCdeResponse(e,{...request,firstPage:mode==='wrong_database'?wrong:page},
      {signal:abort.signal,deadline:performance.now()+(mode==='expired'?-1:5000)},raw=>{
        borrowed=raw;if(mode==='consumer_failure')throw Error('fictional consumer failure');
        if(mode==='async_consumer')return Promise.resolve();
        assert.fail('refused key consumed');
      }),err=>err.code===expected);
    assert.ok(e.payload.every(b=>b===0));if(borrowed)assert.ok(borrowed.every(b=>b===0));
  }
  page.fill(0);wrong.fill(0);
  console.log(JSON.stringify({phase:'offline_crypto_verified',authenticated_databases:authenticated,
    credential_and_raw_key_buffers_wiped:true,cancellation_expiry_and_consumer_failure_refused:true,
    different_account_labels_both_authenticate:true,credential_account_binding_proven:false}));
} finally {
  packet?.fill(0);for(const b of owned)b.fill(0);
  assert.ok(!packet||packet.every(b=>b===0));
  console.log(JSON.stringify({phase:'fixture_event_released',event_buffer_wiped:true}));
}
'''


def worker(root):
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == REPO/'src/qq_chat_analyzer/__init__.py'
    sys.path.insert(0, str(REPO/'tests'))
    from test_qq_direct_main_wal_poc import _reserve_48_bytes
    from qq_chat_analyzer.providers.qq_independent import snapshot
    from qq_chat_analyzer.providers.qq_independent.files import SourceError
    seed=root/'seed.db'; _reserve_48_bytes(seed)
    with closing(sqlite3.connect(seed)) as db:
        db.execute('CREATE TABLE evidence(value TEXT)')
        db.execute("INSERT INTO evidence VALUES ('fictional offline import')")
        db.commit()
    program=PROGRAM
    for name, path in (
        ('ENCODER',REPO/'scripts/spikes/qq_independent_codec.mjs'),
        ('OBSERVER',REPO/'src/qq_chat_analyzer/providers/qq_independent/js/qq_login_event_probe.mjs'),
        ('DECRYPTOR',REPO/'src/qq_chat_analyzer/providers/qq_independent/js/qq_full_read.mjs'),
    ):
        program=program.replace(name,json.dumps(path.as_uri()))
    script=root/'fixture.mjs'; script.write_text(program,encoding='utf8')
    node=subprocess.Popen([shutil.which('node'),str(script),str(root)],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW)
    writer=None
    original=snapshot.assert_qq_exited
    try:
        held=json.loads(node.stdout.readline())
        assert held=={'phase':'fixture_event_held','key_lease_created':False}
        source=root/'100000001/nt_qq/nt_db/nt_msg.db'
        writer=subprocess.Popen([sys.executable,'-c',
            'import sys; f=open(sys.argv[1],"r+b"); print("ready",flush=True); sys.stdin.buffer.read(1); f.close()',str(source)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        assert writer.stdout.readline().strip()==b'ready'
        def exited():
            if writer.poll() is None: raise SourceError('normal_qq_exit_required')
            assert writer.returncode==0
        snapshot.assert_qq_exited=exited
        parent=root/'owned'; parent.mkdir()
        try: snapshot.prepare(source,parent)
        except SourceError as error: assert error.code=='normal_qq_exit_required'
        else: raise AssertionError('live fixture admitted')
        try:
            with snapshot._read_locked(source): raise AssertionError('write handle admitted')
        except SourceError as error: assert error.code=='source_read_lock_unavailable'
        writer.stdin.write(b'x');writer.stdin.flush();assert writer.wait(timeout=5)==0
        selections=[]
        for account in ('100000001','100000002'):
            frozen=snapshot.prepare(root/account/'nt_qq/nt_db/nt_msg.db',parent)
            selections.append({'path':frozen['snapshot'],'size':frozen['size'],
                'sha256':frozen['sha256'],'output':str(root/(account+'.sqlite'))})
        node.stdin.write(json.dumps(selections)+'\n');node.stdin.flush();node.stdin.close()
        results=[json.loads(line) for line in node.stdout]
        assert node.wait(timeout=5)==0
        assert results[-1]=={'phase':'fixture_event_released','event_buffer_wiped':True}
        assert results[0]['different_account_labels_both_authenticate'] is True
        for account in ('100000001','100000002'):
            with closing(sqlite3.connect(root/(account+'.sqlite'))) as db:
                assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
                assert db.execute('SELECT value FROM evidence').fetchall()==[('fictional offline import',)]
        print(json.dumps({'exit_before_snapshot':True,'live_writer_refused':True,
            'retained_event_authenticated_after_exit':True,'sqlite_integrity_verified':True,
            'credential_account_binding_proven':False,'raw_keys_persisted':False,
            'real_qq_accessed':False,'crypto':results[0]}),flush=True)
    finally:
        snapshot.assert_qq_exited=original
        for child in (writer,node):
            if child is None: continue
            if child.poll() is None: child.kill()  # Only our fictional children.
            child.wait(timeout=5)
            for stream in (child.stdin,child.stdout):
                if stream and not stream.closed:stream.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('--worker',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    if not root.is_relative_to(REPO/'build'): raise ValueError('isolated_build_required')
    if args.worker:return worker(root)
    root.mkdir(exist_ok=False)
    env=os.environ.copy();env['PYTHONPATH']=str(REPO/'src')
    for name in ENV:
        directory=root/name;directory.mkdir();env[name]=str(directory)
    for name in ('NODE_OPTIONS','NODE_PATH','PYTHONSTARTUP'):env.pop(name,None)
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    process=launch_owned_process([sys.executable,str(Path(__file__).resolve()),str(root),'--worker'],
        cwd=REPO,env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        output,_=process.communicate(timeout=60)
        if process.returncode or len(output)>4096:raise RuntimeError('offline_fixture_refused')
        result=json.loads(output);print(json.dumps(result),flush=True)
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    finally:
        process.close_with_exit_evidence(timeout=5)
    assert process.exit_verified and process.closed
    print(json.dumps({'owned_helpers_released':True}),flush=True)


if __name__=='__main__':main()
