// Authenticated QQ pages; shared with the independent reference checks.
import {createDecipheriv,createHmac,pbkdf2Sync,timingSafeEqual} from 'node:crypto';
const PAGE=4096,PREFIX=1024,CIPHER_RESERVE=48;
const MAGIC=Buffer.from('SQLite format 3\0');
function deriveHmacKey(key, pageSalt) {
  const masked = Buffer.from(pageSalt.map(value => value ^ 0x3a));
  return pbkdf2Sync(key, masked, 2, 32, 'sha512');
}

function pageTag(ciphertext, iv, pageNumber, hmacKey, hash) {
  return createHmac(hash, hmacKey).update(ciphertext).update(iv).update(pageNumber).digest();
}

// Candidate authentication only. Reuse the same tag primitive as decode;
// never decrypt a page or claim database completeness from this result.
export function authenticateFirstPage(wrapped, key) {
  if (wrapped.length !== PREFIX + PAGE || key.length !== 32) return false;
  const start = PREFIX, end = start + PAGE - CIPHER_RESERVE;
  const hmacKey = deriveHmacKey(key, wrapped.subarray(start, start + 16));
  try {
    const pageNumber = Buffer.alloc(4);
    pageNumber.writeUInt32LE(1);
    const expected = pageTag(wrapped.subarray(start + 16, end),
      wrapped.subarray(end, end + 16), pageNumber, hmacKey, 'sha1');
    return timingSafeEqual(expected, wrapped.subarray(end + 16, end + 36));
  } finally { hmacKey.fill(0); }
}

// A bounded random-access reader may supply length/subarray instead of Buffer.
// Optional synchronous sink avoids retaining a second whole database in RAM.
export function decode(wrapped, key, pageSalt = wrapped.subarray(PREFIX, PREFIX + 16), hash = 'sha1', writePage, options = {}) {
  if (writePage !== undefined && typeof writePage !== 'function') throw new Error('invalid_sink');
  return processPages(wrapped, key, pageSalt, hash, writePage, options, false);
}

// Authenticate every declared page for a native reader. Only the first page
// needs decryption for the SQLite header. Read any capacity tail last so the
// caller can also compute a digest in the same sequential pass.
export function authenticatePages(wrapped, key, pageSalt = wrapped.subarray(PREFIX, PREFIX + 16), options = {}) {
  return processPages(wrapped, key, pageSalt, 'sha1', undefined, options, true);
}

function checkCapacityTail(wrapped, limit, onProgress) {
  onProgress?.('capacity_validation', 1);
  for (let at = limit; at < wrapped.length; at += 1024 * 1024) {
    const end = Math.min(wrapped.length, at + 1024 * 1024);
    const tail = wrapped.subarray(at, end);
    if (tail.length !== end - at) throw new Error('short_read');
    if (!tail.equals(Buffer.alloc(tail.length))) throw new Error('nonzero_capacity_tail');
  }
}

function processPages(wrapped, key, pageSalt, hash, writePage, options, authenticateOnly) {
  if (wrapped.length <= PREFIX || (wrapped.length - PREFIX) % PAGE !== 0)
    throw new Error('invalid_size');
  if (!wrapped.subarray(PREFIX, PREFIX + 16).equals(pageSalt))
    throw new Error('salt_mismatch');
  const output = [];
  let declared = 0, current = false, pages = 0;
  let limit = wrapped.length;
  const physicalPages = (wrapped.length - PREFIX) / PAGE;
  const pageNumber = Buffer.alloc(4);
  const hmacKey = deriveHmacKey(key, pageSalt);
  try {
    for (let offset = PREFIX, number = 1; offset < limit; offset += PAGE, number++) {
      options.onProgress?.('page_authentication', number - 1);
      const first = number === 1;
      const encrypted = wrapped.subarray(offset, offset + PAGE);
      if (encrypted.length !== PAGE) throw new Error('short_read');
      const end = PAGE - CIPHER_RESERVE;
      const ciphertext = encrypted.subarray(first ? 16 : 0, end);
      const iv = encrypted.subarray(end, end + 16);
      const stored = encrypted.subarray(end + 16, end + 36);
      pageNumber.writeUInt32LE(number);
      const expected = pageTag(ciphertext, iv, pageNumber, hmacKey, hash);
      if (expected.length !== stored.length || !timingSafeEqual(expected, stored)) {
        const error = new Error('page_hmac_mismatch');
        error.page = number;
        error.pageAllZero = encrypted.equals(Buffer.alloc(PAGE));
        throw error;
      }
      pages = number;
      if (authenticateOnly && !first) continue;

      options.onProgress?.('page_decryption', number);
      const decipher = createDecipheriv('aes-256-cbc', key, iv);
      decipher.setAutoPadding(false);
      const page = Buffer.concat([first ? MAGIC : Buffer.alloc(0),
        decipher.update(ciphertext), decipher.final(), Buffer.alloc(CIPHER_RESERVE)]);
      let retained = false;
      try {
        if (first) {
          options.onProgress?.('header_validation', number);
          declared = page.readUInt32BE(28);
          current = declared !== 0 && page.readUInt32BE(24) === page.readUInt32BE(92);
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
            limit = PREFIX + declared * PAGE;
            if (!authenticateOnly) checkCapacityTail(wrapped, limit, options.onProgress);
          }
        }
        if (writePage) {
          options.onProgress?.('output_write', number);
          writePage(page);
        } else if (!authenticateOnly) {
          output.push(page);
          retained = true;
        }
      } finally { if (!retained) page.fill(0); }
    }
    if (authenticateOnly && options.allowZeroCapacity === true)
      checkCapacityTail(wrapped, limit, options.onProgress);
    options.onProgress?.('page_count_validation', pages);
    if (!current) throw new Error('untrusted_page_count');
    if (declared !== pages) throw new Error('page_count_mismatch');
    if (writePage || authenticateOnly)
      return {pages, physical_pages: physicalPages, zero_capacity_pages: physicalPages - pages};
    return Buffer.concat(output);
  } finally { hmacKey.fill(0); }
}
