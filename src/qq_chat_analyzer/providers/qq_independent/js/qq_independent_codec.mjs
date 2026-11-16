// Authenticated QQ pages; shared with the independent reference checks.
import {createDecipheriv,createHmac,pbkdf2Sync,timingSafeEqual} from 'node:crypto';
const PAGE=4096,PREFIX=1024,CIPHER_RESERVE=48;
const MAGIC=Buffer.from('SQLite format 3\0');
function pageTag(ciphertext, iv, number, key, pageSalt, hash = 'sha1') {
  const masked = Buffer.from(pageSalt.map(value => value ^ 0x3a));
  const hmacKey = pbkdf2Sync(key, masked, 2, 32, 'sha512');
  const pgno = Buffer.alloc(4);
  pgno.writeUInt32LE(number);
  return createHmac(hash, hmacKey).update(ciphertext).update(iv).update(pgno).digest();
}

// Candidate authentication only. Reuse the same tag primitive as decode;
// never decrypt a page or claim database completeness from this result.
export function authenticateFirstPage(wrapped, key) {
  if (wrapped.length !== PREFIX + PAGE || key.length !== 32) return false;
  const start = PREFIX, end = start + PAGE - CIPHER_RESERVE;
  const expected = pageTag(wrapped.subarray(start + 16, end),
    wrapped.subarray(end, end + 16), 1, key, wrapped.subarray(start, start + 16));
  return timingSafeEqual(expected, wrapped.subarray(end + 16, end + 36));
}

// A bounded random-access reader may supply length/subarray instead of Buffer.
// Optional synchronous sink avoids retaining a second whole database in RAM.
// Both paths use exactly the same page authentication/decryption below.
export function decode(wrapped, key, pageSalt = wrapped.subarray(PREFIX, PREFIX + 16), hash = 'sha1', writePage, options = {}) {
  if (writePage !== undefined && typeof writePage !== 'function') throw new Error('invalid_sink');
  if (wrapped.length <= PREFIX || (wrapped.length - PREFIX) % PAGE !== 0)
    throw new Error('invalid_size');
  if (!wrapped.subarray(PREFIX, PREFIX + 16).equals(pageSalt))
    throw new Error('salt_mismatch');
  const output = [];
  let header;
  let decodedBytes = 0;
  let limit = wrapped.length;
  const physicalPages = (wrapped.length-PREFIX)/PAGE;
  let capacityPages = 0;
  for (let offset = PREFIX, number = 1; offset < limit; offset += PAGE, number++) {
    options.onProgress?.('page_authentication', number - 1);
    const first = number === 1;
    const ciphertext = wrapped.subarray(offset + (first ? 16 : 0), offset + PAGE - CIPHER_RESERVE);
    const iv = wrapped.subarray(offset + PAGE - CIPHER_RESERVE, offset + PAGE - CIPHER_RESERVE + 16);
    const stored = wrapped.subarray(offset + PAGE - CIPHER_RESERVE + 16, offset + PAGE - CIPHER_RESERVE + 36);
    const expected = pageTag(ciphertext, iv, number, key, pageSalt, hash);
    if (expected.length !== stored.length || !timingSafeEqual(expected, stored)) {
      const error = new Error('page_hmac_mismatch');
      error.page = number;
      error.pageAllZero = wrapped.subarray(offset, offset + PAGE).equals(Buffer.alloc(PAGE));
      throw error;
    }
    options.onProgress?.('page_decryption', number);
    const decipher = createDecipheriv('aes-256-cbc', key, iv);
    decipher.setAutoPadding(false);
    const page = Buffer.concat([first ? MAGIC : Buffer.alloc(0),
      decipher.update(ciphertext), decipher.final(), Buffer.alloc(CIPHER_RESERVE)]);
    try {
      if (first) {
        options.onProgress?.('header_validation', number);
        const declared = page.readUInt32BE(28), current = declared !== 0 && page.readUInt32BE(24) === page.readUInt32BE(92);
        options.onHeader?.({header_pages: declared, physical_pages: physicalPages, header_counters_current: current,
          freelist_first_trunk: page.readUInt32BE(32), freelist_pages: page.readUInt32BE(36),
          page_size: page.readUInt16BE(16), reserved_bytes: page[20],
          write_version: page[18], read_version: page[19]});
        options.onProgress?.('header_validation', number);
        if (page.readUInt16BE(16) !== PAGE || ![48, 80].includes(page[20]))
          throw new Error('invalid_sqlite_header');
        if (options.allowZeroCapacity === true) {
          if (!current) throw new Error('untrusted_page_count');
          if (declared > physicalPages) throw new Error('page_count_mismatch');
          // Only an authenticated, current header establishes the logical end.
          // Every byte outside it must be zero; never drop encrypted/damaged data.
          limit = PREFIX + declared*PAGE;
          options.onProgress?.('capacity_validation', number);
          for (let at = limit; at < wrapped.length; at += 1024*1024) {
            const tail = wrapped.subarray(at, Math.min(wrapped.length, at+1024*1024));
            if (!tail.equals(Buffer.alloc(tail.length))) throw new Error('nonzero_capacity_tail');
          }
          capacityPages = physicalPages-declared;
        }
      }
    } catch (error) { page.fill(0); throw error; }
    decodedBytes += page.length;
    if (writePage) {
      if (first) header = Buffer.from(page.subarray(0, 100));
      try {
        options.onProgress?.('output_write', number);
        writePage(page);
      } finally { page.fill(0); }
    } else output.push(page);
  }
  const plain = writePage ? header : Buffer.concat(output);
  options.onProgress?.('page_count_validation', decodedBytes / PAGE);
  // Trust a page count only when SQLite's header marks it current. This
  // research reader rejects unknown completeness instead of inferring/repairing.
  const declaredPages = plain.readUInt32BE(28);
  if (declaredPages === 0 || plain.readUInt32BE(24) !== plain.readUInt32BE(92))
    throw new Error('untrusted_page_count');
  if (declaredPages !== decodedBytes / PAGE)
    throw new Error('page_count_mismatch');
  return writePage ? {pages: decodedBytes / PAGE, physical_pages: physicalPages, zero_capacity_pages: capacityPages} : plain;
}
