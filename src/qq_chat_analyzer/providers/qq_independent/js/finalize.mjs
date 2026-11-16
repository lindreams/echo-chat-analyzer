import {closeSync,existsSync,fstatSync,lstatSync,openSync,readSync,writeSync} from 'node:fs';
const PAGE_SIZE=4096,HEADER=Buffer.from('SQLite format 3\0');
function fail(code) {
  const error = new Error(code);
  error.code = code;
  throw error;
}

function readExactly(fd, length, position) {
  const result = Buffer.alloc(length);
  let read = 0;
  while (read < length) {
    const count = readSync(fd, result, read, length - read, position + read);
    if (count === 0) fail('short_read');
    read += count;
  }
  return result;
}

export function finalizeStandaloneSnapshot(path, pageCount, onDiagnostic = () => {}) {
  const observe = witness => { try { onDiagnostic(witness); } catch {} };
  const state = lstatSync(path);
  observe({regular_file: state.isFile(), single_link: state.nlink === 1,
    file_bytes: state.size, expected_pages: pageCount, file_size_matches: state.size === pageCount * PAGE_SIZE,
    sidecar_present: ['-wal', '-shm', '-journal'].some(suffix => existsSync(path + suffix))});
  if (!state.isFile() || state.nlink !== 1 ||
      ['-wal', '-shm', '-journal'].some(suffix => existsSync(path + suffix))) {
    fail('plaintext_snapshot_invalid');
  }
  const fd = openSync(path, 'r+');
  let failed = false;
  try {
    const header = readExactly(fd, 100, 0);
    const fileBytes = fstatSync(fd).size;
    // SQLite 3.54.1 lockBtree() uses a nonzero, counter-valid header size
    // unless it exceeds the Pager size. Preallocated trailing capacity is legal.
    // Zero or stale header sizes fall back to the already verified image size.
    const pageCountValid = header.readUInt32BE(28) === 0 || header.readUInt32BE(24) !== header.readUInt32BE(92) ||
      header.readUInt32BE(28) <= pageCount;
    observe({file_bytes: fileBytes, file_size_matches: fileBytes === pageCount * PAGE_SIZE,
      sqlite_signature_valid: header.subarray(0, 16).equals(HEADER),
      page_size_valid: header.readUInt16BE(16) === PAGE_SIZE,
      format_versions_valid: [1, 2].includes(header[18]) && header[19] === header[18],
      header_pages: header.readUInt32BE(28),
      header_count_nonzero: header.readUInt32BE(28) !== 0,
      header_counters_equal: header.readUInt32BE(24) === header.readUInt32BE(92),
      header_pages_match_commit: header.readUInt32BE(28) === pageCount,
      page_count_valid: pageCountValid});
    if (!Number.isSafeInteger(pageCount) || pageCount < 1 ||
        fileBytes !== pageCount * PAGE_SIZE) {
      fail('plaintext_snapshot_invalid');
    }
    if (!header.subarray(0, 16).equals(HEADER) || header.readUInt16BE(16) !== PAGE_SIZE ||
        ![1, 2].includes(header[18]) || header[19] !== header[18] ||
        !pageCountValid) {
      fail('plaintext_header_invalid');
    }
    // SQLite WAL mode (2/2) can require writable auxiliary files even for
    // mode=ro. All committed pages are already in this image; publish 1/1.
    // Preserve reserve bytes, page count, counters and every b-tree byte.
    const versions = Buffer.from([1, 1]);
    let written = 0;
    while (written < versions.length) {
      const count = writeSync(fd, versions, written, versions.length - written, 18 + written);
      if (count === 0) fail('short_write');
      written += count;
    }
  } catch (error) {
    failed = true;
    throw error;
  } finally {
    try { closeSync(fd); }
    catch (error) {
      observe({close_failed: true, close_error_code: ['EIO', 'EBADF', 'EINVAL', 'ENOSPC', 'EINTR'].includes(error.code)
        ? error.code : 'close_failed'});
      if (!failed) throw error;
    }
  }
}
