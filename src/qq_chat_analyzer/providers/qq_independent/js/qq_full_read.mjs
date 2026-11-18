// Bounded offline consumer. The existing codec remains the sole decoder.
// Called synchronously AFTER native observation has stopped, never returns a key.
import {openSync, closeSync, fstatSync, lstatSync, readSync, writeSync, unlinkSync, existsSync} from 'node:fs';
import {resolve, dirname} from 'node:path';
import {createHash} from 'node:crypto';
import {decode} from './qq_independent_codec.mjs';
import {finalizeStandaloneSnapshot} from './finalize.mjs';

export const MAX_SNAPSHOT_BYTES = 1024 * 1024 * 1024;
export const SNAPSHOT_FAILURE_CODES = Object.freeze(['page_hmac_mismatch', 'untrusted_page_count',
  'invalid_sink', 'invalid_size', 'salt_mismatch', 'snapshot_selection_refused',
  'snapshot_path_refused', 'snapshot_identity_refused', 'status_pipe_closed',
  'page_count_mismatch', 'nonzero_capacity_tail', 'invalid_sqlite_header', 'full_decode_deadline',
  'snapshot_read_limit', 'snapshot_short_read', 'snapshot_short_write', 'snapshot_changed',
  'plaintext_header_invalid', 'plaintext_snapshot_invalid', 'short_read', 'short_write',
  'ENOSPC', 'EACCES', 'EPERM', 'EIO', 'EMFILE', 'ENOMEM', 'ENOENT', 'EEXIST',
  'ENOTDIR', 'ELOOP', 'EBUSY', 'EROFS', 'EFBIG', 'EINVAL', 'ENFILE', 'EBADF',
  'ERR_OUT_OF_RANGE', 'ERR_CRYPTO_INVALID_KEYLEN', 'ERR_OSSL_BAD_DECRYPT']);
const STAGES = Object.freeze(['selection_validation', 'path_validation', 'input_identity', 'input_open',
  'input_prefix_verification', 'input_hash_verification', 'output_open', 'decoder_setup', 'page_authentication', 'page_decryption', 'header_validation',
  'header_receipt', 'capacity_validation', 'output_write', 'page_count_validation', 'output_close',
  'input_hash_reverification', 'input_descriptor_reverification', 'input_path_reverification',
  'finalization', 'finalization_receipt', 'input_close']);
const failureCode = error => SNAPSHOT_FAILURE_CODES.includes(error?.message) ? error.message
  : SNAPSHOT_FAILURE_CODES.includes(error?.code) ? error.code : 'full_snapshot_refused';
const failureKind = error => error instanceof RangeError ? 'range_error'
  : error instanceof TypeError ? 'type_error' : error instanceof Error ? 'error' : 'non_error';

// Shared by the real bridge and offline faults. Never copy exception strings,
// paths, stack traces, raw headers or arbitrary error properties to a receipt.
export function snapshotFailureReceipt(error) {
  const result = {failure: failureCode(error), failure_kind: ['range_error', 'type_error', 'error', 'non_error'].includes(error?.failureKind)
    ? error.failureKind : failureKind(error)};
  if (STAGES.includes(error?.stage)) result.failure_stage = error.stage;
  for (const [source, target] of [['authenticatedPages', 'authenticated_pages'], ['writtenPages', 'written_pages'],
    ['elapsedMs', 'failure_elapsed_ms'], ['page', 'failure_page']]) {
    if (Number.isSafeInteger(error?.[source]) && error[source] >= (source === 'page' ? 1 : 0)) result[target] = error[source];
  }
  if (result.failure_page && typeof error.pageAllZero === 'boolean') result.failure_page_all_zero = error.pageAllZero;
  if (typeof error?.outputRemoved === 'boolean') result.provisional_output_removed = error.outputRemoved;
  if (typeof error?.allPagesAuthenticated === 'boolean') result.all_pages_authenticated = error.allPagesAuthenticated;
  if (error?.finalizationWitness) result.finalization_witness = Object.fromEntries(Object.entries(error.finalizationWitness)
    .filter(([key, value]) => ['regular_file', 'single_link', 'file_bytes', 'expected_pages', 'file_size_matches',
      'sidecar_present', 'sqlite_signature_valid', 'page_size_valid', 'format_versions_valid', 'header_pages',
      'header_count_nonzero', 'header_counters_equal', 'header_pages_match_commit', 'page_count_valid', 'close_failed'].includes(key)
      && (typeof value === 'boolean' || Number.isSafeInteger(value) && value >= 0)
      || key === 'close_error_code' && ['EIO', 'EBADF', 'EINVAL', 'ENOSPC', 'EINTR', 'close_failed'].includes(value)));
  if (Array.isArray(error?.cleanupFailures)) result.cleanup_failures = error.cleanupFailures
    .filter(item => ['output_close', 'output_remove', 'input_close'].includes(item.operation))
    .map(item => ({operation: item.operation, code: failureCode({code: item.code})}));
  return result;
}
function safe(path) {
  for (let part = resolve(path); ; part = dirname(part)) {
    const state = lstatSync(part);
    if (state.isSymbolicLink()) throw Error('snapshot_path_refused');
    if (dirname(part) === part) break;
  }
}
const identity = state => [state.dev, state.ino, state.size, state.mtimeNs, state.ctimeNs].join(':');

// One restricted metadata experiment, using the existing decoder independently
// for each file. No schema interpretation or identity inference belongs here.
export function decryptMetadataSnapshots(selections, withDatabaseKey, onStatus = () => {}) {
  if (typeof withDatabaseKey !== 'function' || !Array.isArray(selections) || selections.length !== 2 ||
      selections.some((item, index) => item?.role !== ['group_info', 'profile_info'][index] ||
        !Number.isSafeInteger(item.size) || item.size > 32*1024*1024) ||
      new Set(selections.map(item => resolve(item.path))).size !== 2 ||
      new Set(selections.map(item => resolve(item.output))).size !== 2) throw Error('snapshot_selection_refused');
  const results = [];
  for (const selection of selections) {
    const prefix = Buffer.alloc(5120);
    let descriptor, decoded, decoderStarted = false, failureReported = false;
    try {
      safe(selection.path);
      descriptor = openSync(selection.path, 'r');
      let at = 0;
      while (at < prefix.length) {
        const count = readSync(descriptor, prefix, at, prefix.length-at, at);
        if (!count) throw Error('snapshot_short_read');
        at += count;
      }
      closeSync(descriptor); descriptor = undefined;
      withDatabaseKey(prefix, key => {
        decoderStarted = true;
        try {
          decoded = decryptSnapshot(selection, prefix, key,
            header => onStatus({phase: 'authenticated_header', role: selection.role, ...header}), onStatus);
        } catch (error) {
          // Record decoder evidence BEFORE the scoped key contract sanitizes
          // consumer exceptions. A later page failure must keep its counters.
          failureReported = true;
          onStatus({phase: 'snapshot_failure', role: selection.role, ...snapshotFailureReceipt(error)});
          throw error;
        }
      });
      if (!decoded?.complete_image) throw Error('snapshot_selection_refused');
      results.push({role: selection.role, ...decoded});
      onStatus({phase: 'metadata_snapshot_result', role: selection.role, ...decoded});
    } catch (error) {
      if (!failureReported) {
        const keyFailure = ['key_not_authenticated', 'passphrase_required', 'source_expired', 'cancelled',
          'deadline_reached', 'source_cleanup_failed', 'key_source_failed', 'invalid_request'].includes(error?.code);
        onStatus({phase: 'snapshot_failure', role: selection.role, ...(keyFailure ? {
          failure: 'database_key_refused', key_scope_failure: error.code,
          failure_stage: decoderStarted ? 'database_key_scope' : 'database_key_authentication',
          authenticated_pages: decoded?.decrypted_pages ?? 0, written_pages: decoded?.decrypted_pages ?? 0,
          all_pages_authenticated: decoded?.all_pages_authenticated ?? false,
          provisional_output_removed: !existsSync(selection.output),
        } : snapshotFailureReceipt(error))});
      }
      throw error;
    } finally {
      prefix.fill(0);
      if (descriptor !== undefined) closeSync(descriptor);
    }
  }
  return results;
}

export function decryptSnapshot(selection, firstPage, key, onHeader = () => {}, onStatus = () => {}) {
  let input, output;
  let fd, destination, block, readCache, readCacheStart = -1, outputCreated = false;
  let stage = 'selection_validation', authenticatedPages = 0, writtenPages = 0;
  let allPagesAuthenticated = false;
  let finalizationWitness;
  const started = performance.now();
  const checkpoint = () => onStatus({phase: 'snapshot_progress', stage,
    authenticated_pages: authenticatedPages, written_pages: writtenPages,
    elapsed_ms: Math.floor(performance.now()-started)});
  const closeOutput = () => { const owned = destination; destination = undefined; closeSync(owned); };
  const closeInput = () => { const owned = fd; fd = undefined; closeSync(owned); };
  try {
    if (typeof selection?.path !== 'string' || typeof selection.output !== 'string') throw Error('snapshot_selection_refused');
    input = resolve(selection.path); output = resolve(selection.output);
    if (input === output || !/^[a-f0-9]{64}$/.test(selection.sha256 ?? '') ||
        !Number.isSafeInteger(selection.size) || selection.size < 5120 || selection.size > MAX_SNAPSHOT_BYTES ||
        (selection.size-1024)%4096) throw Error('snapshot_selection_refused');
    stage = 'path_validation';
    safe(input); safe(dirname(output));
    stage = 'input_identity';
    const before = lstatSync(input, {bigint: true});
    if (!before.isFile() || before.nlink !== 1n || before.size !== BigInt(selection.size)) throw Error('snapshot_identity_refused');
    stage = 'input_open';
    fd = openSync(input, 'r');
    if (identity(fstatSync(fd, {bigint: true})) !== identity(before)) throw Error('snapshot_changed');
    const checkRead = (start, end) => {
      if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < start ||
          end > selection.size || end-start > 1024*1024) throw Error('snapshot_read_limit');
    };
    const read = (start, end) => {
      checkRead(start, end);
      const bytes = Buffer.alloc(end-start);
      let at = 0;
      while (at < bytes.length) {
        const n = readSync(fd, bytes, at, bytes.length-at, start+at);
        if (!n) throw Error('snapshot_short_read');
        at += n;
      }
      return bytes;
    };
    const readPage = (start, end) => {
      checkRead(start, end);
      if (!readCache || start < readCacheStart || end > readCacheStart+readCache.length) {
        readCache?.fill(0);
        readCache = read(start, Math.min(selection.size, start+1024*1024));
        readCacheStart = start;
      }
      // Keep the codec's independent slices: an IV/tag read may refill the
      // cache while the same page's ciphertext is still being authenticated.
      return Buffer.from(readCache.subarray(start-readCacheStart, end-readCacheStart));
    };
    const hash = () => {
      const digest = createHash('sha256');
      for (let at = 0; at < selection.size; at += 1024*1024) {
        block = read(at, Math.min(selection.size, at+1024*1024)); digest.update(block); block.fill(0);
      }
      return digest.digest('hex');
    };
    stage = 'input_prefix_verification';
    if (!read(0, 5120).equals(firstPage)) throw Error('snapshot_changed');
    stage = 'input_hash_verification';
    if (hash() !== selection.sha256) throw Error('snapshot_changed');
    stage = 'output_open';
    destination = openSync(output, 'wx', 0o600); outputCreated = true;
    const deadline = performance.now()+120000;
    stage = 'decoder_setup';
    const {pages, physical_pages, zero_capacity_pages} = decode({length: selection.size, subarray: readPage}, key, firstPage.subarray(1024, 1040), 'sha1', page => {
      if (performance.now() >= deadline) throw Error('full_decode_deadline');
      let at = 0;
      while (at < page.length) {
        const n = writeSync(destination, page, at, page.length-at);
        if (!n) throw Error('snapshot_short_write');
        at += n;
      }
      writtenPages++;
    }, {allowZeroCapacity: true, onHeader: header => {
      stage = 'header_receipt';
      onHeader(header);
    }, onProgress: (currentStage, count) => {
      stage = currentStage;
      authenticatedPages = count; // Count at the MAC boundary, before decrypt/write.
      // At most eight progress receipts under the 1 GiB admission bound. Fatal
      // process loss cannot run catch; retain bounded progress without page logs.
      if (stage === 'output_write' && (count === 1 || count % 32768 === 0)) checkpoint();
    }}); // Every logical page is authenticated; current header binds its exact count.
    allPagesAuthenticated = true;
    stage = 'output_close';
    checkpoint();
    closeOutput();
    stage = 'input_hash_reverification';
    checkpoint();
    if (hash() !== selection.sha256) throw Error('snapshot_changed');
    stage = 'input_descriptor_reverification';
    if (identity(fstatSync(fd, {bigint: true})) !== identity(before)) throw Error('snapshot_changed');
    stage = 'input_path_reverification';
    if (identity(lstatSync(input, {bigint: true})) !== identity(before)) throw Error('snapshot_changed');
    stage = 'finalization';
    checkpoint();
    finalizeStandaloneSnapshot(output, pages, witness => { finalizationWitness = {...finalizationWitness, ...witness}; });
    stage = 'finalization_receipt';
    onStatus({phase: 'snapshot_finalization', ...finalizationWitness});
    stage = 'input_close';
    closeInput();
    return {all_pages_authenticated: true, decrypted_pages: pages, physical_pages, zero_capacity_pages, complete_image: true};
  } catch (error) {
    // Fixed codes only; neither codec/native exception strings nor paths escape.
    const failure = Error(failureCode(error));
    failure.failureKind = failureKind(error);
    failure.finalizationWitness = finalizationWitness;
    failure.stage = stage;
    failure.authenticatedPages = authenticatedPages;
    failure.writtenPages = writtenPages;
    failure.allPagesAuthenticated = allPagesAuthenticated;
    failure.elapsedMs = Math.floor(performance.now()-started);
    failure.cleanupFailures = [];
    const cleanup = (operation, action) => {
      try { action(); } catch (cleanupError) { failure.cleanupFailures.push({operation, code: failureCode(cleanupError)}); }
    };
    if (destination !== undefined) cleanup('output_close', closeOutput);
    failure.outputRemoved = !outputCreated;
    if (outputCreated) cleanup('output_remove', () => { unlinkSync(output); failure.outputRemoved = true; });
    if (fd !== undefined) cleanup('input_close', closeInput);
    if (Number.isSafeInteger(error?.page) && error.page >= 1 && error.page <= (selection.size-1024)/4096) {
      failure.page = error.page;
      if (typeof error.pageAllZero === 'boolean') failure.pageAllZero = error.pageAllZero;
    }
    throw failure;
  } finally {
    block?.fill(0);
    readCache?.fill(0);
  }
}
