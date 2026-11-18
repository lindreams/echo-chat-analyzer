// Offline reader fault regression. No account discovery, native load or real input.
// Uses the actual codec/reader and injects only local filesystem failures.
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {resolve, dirname, join} from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {encode} from './qq_independent_codec.mjs';
import {decryptSnapshot, snapshotFailureReceipt} from './qq_full_read.mjs';

const parent = resolve(process.argv[2]);
const root = fs.mkdtempSync(join(parent, 'snapshot-diagnostics-'));
const originals = Object.fromEntries(['readSync', 'writeSync', 'closeSync', 'unlinkSync'].map(name => [name, fs[name]]));
const restore = () => { Object.assign(fs, originals); syncBuiltinESMExports(); };
const raw = Buffer.alloc(32, 31), salt = Buffer.alloc(16, 13);
const plain = Buffer.alloc(4096*3);
plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48;
plain[18] = plain[19] = 1; plain.writeUInt32BE(3, 28);
let counter = 0;
const make = (bytes = encode(plain, raw, salt)) => {
  const path = join(root, `input-${counter++}.db`), output = path+'.sqlite';
  fs.writeFileSync(path, bytes, {flag: 'wx'});
  return {selection: {path, output, size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')},
    prefix: bytes.subarray(0, 5120)};
};
const expect = (run, code, stage, authenticated, written) => {
  let receipt;
  assert.throws(run, error => {
    receipt = snapshotFailureReceipt(error);
    assert.equal(receipt.failure, code); assert.equal(receipt.failure_stage, stage);
    assert.equal(receipt.authenticated_pages, authenticated); assert.equal(receipt.written_pages, written);
    assert.equal(JSON.stringify(receipt).includes('PRIVATE_SENTINEL'), false);
    return true;
  });
  return receipt;
};
try {
  expect(() => decryptSnapshot({path: root, output: root, size: 5120, sha256: 'invalid'}, Buffer.alloc(5120), raw),
    'snapshot_selection_refused', 'selection_validation', 0, 0);

  // Page two passes MAC, then only part of it reaches disk. A cleanup failure
  // must not replace the original I/O error or claim plaintext was removed.
  const partial = make(); let writes = 0;
  fs.writeSync = (...args) => {
    if (args[1].length === 4096 && ++writes === 2) return originals.writeSync(args[0], args[1], 0, 1024);
    if (writes === 3) throw Object.assign(Error('PRIVATE_SENTINEL'), {code: 'EIO'});
    return originals.writeSync(...args);
  };
  fs.unlinkSync = () => { throw Object.assign(Error('PRIVATE_SENTINEL'), {code: 'EACCES'}); };
  syncBuiltinESMExports();
  const receipt = expect(() => decryptSnapshot(partial.selection, partial.prefix, raw), 'EIO', 'output_write', 2, 1);
  assert.equal(receipt.provisional_output_removed, false);
  assert.deepEqual(receipt.cleanup_failures, [{operation: 'output_remove', code: 'EACCES'}]);
  restore(); assert.equal(fs.statSync(partial.selection.output).size, 4096+1024);
  fs.unlinkSync(partial.selection.output);

  const header = make();
  const rejectedHeader = expect(() => decryptSnapshot(header.selection, header.prefix, raw,
    () => { throw new RangeError('PRIVATE_SENTINEL'); }), 'full_snapshot_refused', 'header_receipt', 1, 0);
  assert.equal(rejectedHeader.failure_kind, 'range_error'); assert.equal(rejectedHeader.provisional_output_removed, true);

  // A completed header receipt must not label a later header guard failure.
  plain.writeUInt32BE(1, 92);
  const staleHeader = make(); let headerDelivered = false;
  const stale = expect(() => decryptSnapshot(staleHeader.selection, staleHeader.prefix, raw,
    () => { headerDelivered = true; }), 'untrusted_page_count', 'header_validation', 1, 0);
  assert.ok(headerDelivered); assert.equal(stale.provisional_output_removed, true);
  plain.writeUInt32BE(0, 92);

  // Valid MACs do not establish supported SQLite format. The actual finalizer
  // rejects this version and the receipt retains its boolean guard witness.
  plain[18] = plain[19] = 3;
  const invalidFormat = make();
  const final = expect(() => decryptSnapshot(invalidFormat.selection, invalidFormat.prefix, raw),
    'plaintext_header_invalid', 'finalization', 3, 3);
  assert.equal(final.finalization_witness.format_versions_valid, false);
  assert.equal(final.finalization_witness.file_size_matches, true);
  assert.equal(final.all_pages_authenticated, true);
  assert.equal(final.provisional_output_removed, true);
  // The shared finalizer owns another descriptor. Its finally-close must not
  // erase a preceding format refusal either.
  const dual = make(); let finalizerClosed = false;
  const dualReceipt = expect(() => decryptSnapshot(dual.selection, dual.prefix, raw, () => {}, status => {
    if (status.stage === 'finalization') {
      fs.closeSync = descriptor => {
        originals.closeSync(descriptor);
        if (!finalizerClosed) { finalizerClosed = true; throw Object.assign(Error('PRIVATE_SENTINEL'), {code: 'EIO'}); }
      };
      syncBuiltinESMExports();
    }
  }), 'plaintext_header_invalid', 'finalization', 3, 3);
  assert.equal(dualReceipt.finalization_witness.close_failed, true);
  assert.equal(dualReceipt.finalization_witness.close_error_code, 'EIO'); restore();
  plain[18] = plain[19] = 1;

  const short = make(); let finalizerWrites = 0;
  fs.writeSync = (...args) => {
    if (args[1].length === 2) {
      if (++finalizerWrites === 1) return 0;
      throw Error('PRIVATE_SENTINEL repeated zero write'); // Detect a loop without hanging.
    }
    return originals.writeSync(...args);
  };
  syncBuiltinESMExports();
  const shortReceipt = expect(() => decryptSnapshot(short.selection, short.prefix, raw), 'short_write', 'finalization', 3, 3);
  assert.equal(finalizerWrites, 1); assert.equal(shortReceipt.provisional_output_removed, true); restore();

  const closing = make(); let outputClosed = false;
  const closeFailure = expect(() => decryptSnapshot(closing.selection, closing.prefix, raw, () => {}, status => {
    if (status.stage === 'output_close') {
      fs.closeSync = descriptor => {
        originals.closeSync(descriptor);
        if (!outputClosed) { outputClosed = true; throw Object.assign(Error('PRIVATE_SENTINEL'), {code: 'EIO'}); }
      };
      syncBuiltinESMExports();
    }
  }), 'EIO', 'output_close', 3, 3);
  assert.equal(closeFailure.provisional_output_removed, true); restore();

  // A later failure must leave the completed authenticated-header and full MAC
  // checkpoints available to the append-only owning worker.
  const completed = make(), statuses = [];
  decryptSnapshot(completed.selection, completed.prefix, raw,
    value => statuses.push({phase: 'authenticated_header', ...value}), value => statuses.push(value));
  assert.deepEqual(statuses.filter(value => value.phase === 'snapshot_progress').map(value => value.stage),
    ['output_write', 'output_close', 'input_hash_reverification', 'finalization']);
  assert.equal(statuses.find(value => value.stage === 'input_hash_reverification').authenticated_pages, 3);
  assert.equal(statuses.at(-1).format_versions_valid, true);

  // More than one read-ahead block: decoding stays byte-identical without
  // amplifying each 4 KiB page into three filesystem reads.
  const largePlain=Buffer.alloc(4096*520);
  plain.copy(largePlain,0,0,4096);largePlain.writeUInt32BE(520,28);
  const largeBytes=encode(largePlain,raw,salt),large=make(largeBytes);
  let reads=0;
  fs.readSync=(...args)=>{reads++;return originals.readSync(...args);};syncBuiltinESMExports();
  decryptSnapshot(large.selection,large.prefix,raw);
  assert.ok(reads<520);restore();
  assert.ok(fs.readFileSync(large.selection.output).equals(largePlain));

  // An in-place mutation of already-prefetched ciphertext is still rejected
  // by the independent, uncached final fingerprint pass.
  const changed=make(largeBytes);let mutated=false;
  const changedReceipt=expect(()=>decryptSnapshot(changed.selection,changed.prefix,raw,()=>{},status=>{
    if(status.stage==='output_write'&&!mutated){
      const offset=1024+4096+123,fd=fs.openSync(changed.selection.path,'r+');
      try{fs.writeSync(fd,Buffer.from([largeBytes[offset]^1]),0,1,offset);}
      finally{fs.closeSync(fd);}
      mutated=true;
    }
  }),'snapshot_changed','input_hash_reverification',520,520);
  assert.equal(changedReceipt.provisional_output_removed,true);
  assert.equal(changedReceipt.all_pages_authenticated,true);
  largePlain.fill(0);largeBytes.fill(0);
  console.log(JSON.stringify({snapshot_diagnostic_faults: 'passed', primary_error_survives_cleanup_failure: true,
    authenticated_and_written_counts_separate: true, finalizer_guard_witness_retained: true,
    raw_exception_redacted: true, buffered_pages_byte_identical:true, cached_input_reverified:true,
    real_qq_accessed: false}));
} finally {
  restore(); raw.fill(0); plain.fill(0);
  assert.equal(dirname(resolve(root)), parent); assert.ok(root.startsWith(join(parent, 'snapshot-diagnostics-')));
  fs.rmSync(root, {recursive: true});
}
