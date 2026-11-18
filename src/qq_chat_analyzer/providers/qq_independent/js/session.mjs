// One explicitly authorized account. Event and keys never leave scoped memory.
import {connectOnce} from './connect.mjs';
import {decryptSnapshot,decryptMetadataSnapshots,snapshotFailureReceipt,SNAPSHOT_FAILURE_CODES} from './qq_full_read.mjs';
import {openSync,readSync,closeSync,writeSync} from 'node:fs';
const abort=new AbortController();
const report=value=>writeSync(1,Buffer.from(JSON.stringify(value)+'\n'));
let input=Buffer.alloc(0),receive,rejectFrame;
process.stdin.on('data',chunk=>{
  if(chunk.length===1 && chunk[0]===1){chunk.fill(0);abort.abort();rejectFrame?.(Error('cancelled'));return;}
  const old=input;input=Buffer.concat([old,chunk]);old.fill(0);chunk.fill(0);
  if(input.length>131076){abort.abort();rejectFrame?.(Error('frame_limit'));return;}
  if(input.length<4)return;
  const n=input.readUInt32LE(0);
  if(!n||n>131072){abort.abort();rejectFrame?.(Error('frame_limit'));return;}
  if(input.length<4+n)return;
  if(!receive||input.length!==4+n){abort.abort();rejectFrame?.(Error('unexpected_frame'));return;}
  const frame=Buffer.from(input.subarray(4));input.fill(0);input=Buffer.alloc(0);
  const deliver=receive;receive=undefined;rejectFrame=undefined;deliver(frame);
});
const readFrame=()=>new Promise((resolve,reject)=>{receive=resolve;rejectFrame=reject;});
process.stdin.on('end',()=>{abort.abort();rejectFrame?.(Error('closed'));});
process.stdin.on('error',()=>{abort.abort();rejectFrame?.(Error('closed'));});
let page,timer,failure,stage='admission';
const safeFailure=error=>{
  if(error instanceof SyntaxError)return 'protocol_invalid_json';
  if(error instanceof TypeError)return 'request_invalid';
  const allowed=[...SNAPSHOT_FAILURE_CODES,'selection_refused','frame_limit','unexpected_frame','closed','cancelled','exit_deadline','short_page','session_refused','build_refused'];
  return allowed.includes(error?.message)?error.message:allowed.includes(error?.code)?error.code:'worker_internal_error';
};
try {
  let frame=await readFrame();
  const request=JSON.parse(frame.toString('utf8'));frame.fill(0);
  if(request.target.mode!=='approved-qq')throw Error('selection_refused');
  request.target.created=BigInt(request.target.created);
  let selections,complete=false;
  stage='transport';
  const result=await connectOnce({...request,signal:abort.signal,consumerTimeoutMs:120000,
    onStatus:(phase,timing)=>report({phase,...timing}),
    prepareAuthentication:async()=>{
      stage='exit';
      const ready=readFrame();
      timer=setTimeout(()=>{abort.abort();rejectFrame?.(Error('exit_deadline'));},120000);
      report({phase:'awaiting_exit'});
      frame=await ready;clearTimeout(timer);
      selections=JSON.parse(frame.toString('utf8'));frame.fill(0);
      page=Buffer.alloc(5120);
      const descriptor=openSync(selections.snapshot.path,'r');
      try {if(readSync(descriptor,page,0,5120,0)!==5120)throw Error('short_page');}
      finally {closeSync(descriptor);}
      return page;
    },
    consumeAuthenticatedKey:(key,withDatabaseKey)=>{
      stage='message';
      try {decryptSnapshot(selections.snapshot,page,key);}
      catch(error){failure={failure_code:snapshotFailureReceipt(error).failure,failure_stage:stage};throw error;}
      stage='snapshot';
      decryptMetadataSnapshots(selections.metadata,withDatabaseKey,value=>{
        if(value.phase==='snapshot_failure')failure={failure_code:value.key_scope_failure??value.failure,
          failure_stage:['group_info','profile_info'].includes(value.role)?value.role:'snapshot'};
      });
      complete=true;
    }});
  report({phase:'result',authenticated:result.authenticated,complete:complete&&result.authenticated,
    observation_stopped:result.observation_stopped,reads_stopped:result.reads_stopped,
    hook_disabled:result.hook_disabled,inflight:result.inflight,state:result.state,loader_exit_code:result.loader_exit_code,
    ...(failure??{failure_code:result.failure_code,failure_stage:result.state==='transport_refused'?'transport':'event'}),
    ...(failure&&result.key_scope_failure?{cause_code:result.key_scope_failure}:{})});
  if(!complete||!result.authenticated||!result.observation_stopped)process.exitCode=2;
}catch(error){report({phase:'result',authenticated:false,complete:false,state:'refused',
  ...(failure??{failure_code:safeFailure(error),failure_stage:stage})});process.exitCode=2;}
finally{clearTimeout(timer);page?.fill(0);input.fill(0);process.stdin.destroy();}
