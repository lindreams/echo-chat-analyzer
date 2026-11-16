// One GUI-authorized, frozen account selection. Secrets stay in scoped memory.
import {connectOnce} from './connect.mjs';
import {decryptSnapshot,decryptMetadataSnapshots} from './qq_full_read.mjs';
import {writeSync} from 'node:fs';
const abort=new AbortController();
const report=value=>writeSync(1,Buffer.from(JSON.stringify(value)+'\n'));
let input=Buffer.alloc(0),started=false;
process.stdin.on('data',chunk=>{
  if(started){chunk.fill(0);abort.abort();return;}
  const previous=input;input=Buffer.concat([input,chunk]);previous.fill(0);chunk.fill(0);
  if(input.length>136196){input.fill(0);abort.abort();process.exitCode=2;process.stdin.destroy();return;}
  if(input.length<4)return;
  const n=input.readUInt32LE(0);
  if(!n||n>131072){input.fill(0);process.exitCode=2;process.stdin.destroy();return;}
  if(input.length<4+n+5120)return;
  started=true;
  (async()=>{
    let page;
    try{
      if(input.length!==4+n+5120)throw Error('selection_refused');
      const request=JSON.parse(input.subarray(4,4+n).toString('utf8'));
      if(request.target.mode!=='approved-qq')throw Error('selection_refused');
      request.target.created=BigInt(request.target.created);
      page=Buffer.from(input.subarray(4+n));input.fill(0);
      let complete=false;
      const result=await connectOnce({...request,firstPage:page,signal:abort.signal,consumerTimeoutMs:120000,
        onStatus:(phase,timing)=>report({phase,...timing}),
        consumeAuthenticatedKey:(key,withDatabaseKey)=>{
          decryptSnapshot(request.snapshot,page,key);
          decryptMetadataSnapshots(request.metadata,withDatabaseKey);
          complete=true;
        }});
      report({phase:'result',authenticated:result.authenticated,complete:complete&&result.authenticated,
        observation_stopped:result.observation_stopped,reads_stopped:result.reads_stopped,
        hook_disabled:result.hook_disabled,inflight:result.inflight,state:result.state});
      if(!complete||!result.authenticated||!result.observation_stopped)process.exitCode=2;
    }catch{report({phase:'result',authenticated:false,complete:false,state:'refused'});process.exitCode=2;}
    finally{page?.fill(0);input.fill(0);process.stdin.destroy();}
  })();
});
process.stdin.on('end',()=>abort.abort());
process.stdin.on('error',()=>abort.abort());
