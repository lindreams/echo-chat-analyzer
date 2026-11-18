// One sequential pass over an original held by the worker's deny-write lock.
import {createHash} from 'node:crypto';
import {closeSync,fstatSync,openSync,readSync} from 'node:fs';
import {authenticatePages} from './qq_independent_codec.mjs';

const BLOCK=1024*1024, PREFIX=1024, PAGE=4096;
const MAGIC=Buffer.from('SQLite header 3\0');

export function openOriginal(selection) {
  if (typeof selection?.path !== 'string' || !Number.isSafeInteger(selection.size) ||
      selection.size<PREFIX+PAGE || (selection.size-PREFIX)%PAGE) throw Error('snapshot_selection_refused');
  const fd=openSync(selection.path,'r');
  const digest=createHash('sha256');
  let window=Buffer.alloc(0), start=0, end=0, before, firstPage;

  const read=(from,to)=>{
    if(from<start || from>end || to<from || to>selection.size || to-from>BLOCK) throw Error('snapshot_read_limit');
    if(to<=end) return window.subarray(from-start,to-start);
    const previous=window.subarray(from-start);
    start=end;
    const size=Math.min(end ? BLOCK : BLOCK+PREFIX,selection.size-end);
    window=Buffer.alloc(size);
    for(let offset=0;offset<size;){
      const count=readSync(fd,window,offset,size-offset,start+offset);
      if(!count) throw Error('snapshot_short_read');
      offset+=count;
    }
    digest.update(window);
    end+=size;
    if(to>end) throw Error('snapshot_short_read');
    const remaining=window.subarray(0,to-start);
    return previous.length ? Buffer.concat([previous,remaining]) : remaining;
  };

  try {
    before=fstatSync(fd,{bigint:true});
    if(!before.isFile() || before.nlink!==1n || before.size!==BigInt(selection.size)) throw Error('snapshot_identity_refused');
    firstPage=Buffer.from(read(0,PREFIX+PAGE));
    if(!firstPage.subarray(0,MAGIC.length).equals(MAGIC)) throw Error('invalid_size');
  } catch(error){window.fill(0);firstPage?.fill(0);closeSync(fd);throw error;}

  return {
    firstPage,
    authenticate(raw,deadline){
      let header;
      const result=authenticatePages({length:selection.size,subarray:read},raw,firstPage.subarray(PREFIX,PREFIX+16),{
        allowZeroCapacity:true,
        onHeader:value=>{header=value;},
        onProgress:()=>{if(performance.now()>=deadline) throw Error('full_decode_deadline');},
      });
      if(![1,2].includes(header.write_version) || header.write_version!==header.read_version)
        throw Error('plaintext_header_invalid');
      if(end!==selection.size) throw Error('snapshot_short_read');
      const after=fstatSync(fd,{bigint:true});
      for(const key of ['dev','ino','size','mtimeNs','ctimeNs']) if(before[key]!==after[key]) throw Error('snapshot_changed');
      return {bytes:selection.size, pages:result.pages, sha256:digest.digest('hex')};
    },
    close(){firstPage.fill(0);window.fill(0);closeSync(fd);},
  };
}
