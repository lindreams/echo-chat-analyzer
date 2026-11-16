// Research only: a closed synthetic round trip, never a QQ process/key reader.
// Candidate profile: 1024-byte wrapper, 4096-byte pages, AES-256-CBC,
// PBKDF2-HMAC-SHA512 (4000), page HMAC-SHA1, 48-byte cipher footer.
// SQLite's B-tree reserve can independently be 48 or 80 bytes. With 80,
// offsets 4016..4047 are encrypted/authenticated reserved bytes, NOT an IV.
// The standalone CLI is a self round trip; the separate reference driver
// verifies SQLCipher interoperability. Neither establishes QQ version support.
import { readFileSync, writeFileSync } from 'node:fs';
import { createCipheriv, createDecipheriv, createHmac, pbkdf2Sync, randomBytes, timingSafeEqual } from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const PAGE = 4096, PREFIX = 1024, CIPHER_RESERVE = 48;
const MAGIC = Buffer.from('SQLite format 3\0');
const passphrase = 'echo-fictional-spike-only';
const salt = randomBytes(16);
const rawKey = pbkdf2Sync(passphrase, salt, 4000, 32, 'sha512');

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

export function encode(plain, key = rawKey, pageSalt = salt) {
  assert.equal(plain.length % PAGE, 0);
  assert.ok(plain.subarray(0, 16).equals(MAGIC));
  assert.equal(plain.readUInt16BE(16), PAGE);
  assert.ok([48, 80].includes(plain[20]));
  const prefix = Buffer.alloc(PREFIX);
  Buffer.from('SQLite header 3\0').copy(prefix);
  const pages = [prefix];
  for (let offset = 0, number = 1; offset < plain.length; offset += PAGE, number++) {
    const first = number === 1;
    const body = plain.subarray(offset + (first ? 16 : 0), offset + PAGE - CIPHER_RESERVE);
    const iv = randomBytes(16);
    const cipher = createCipheriv('aes-256-cbc', key, iv);
    cipher.setAutoPadding(false);
    const ciphertext = Buffer.concat([cipher.update(body), cipher.final()]);
    pages.push(Buffer.concat([first ? pageSalt : Buffer.alloc(0), ciphertext, iv,
      pageTag(ciphertext, iv, number, key, pageSalt), Buffer.alloc(12)]));
  }
  return Buffer.concat(pages);
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

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
const [input, output] = process.argv.slice(2);
assert.ok(input && output && process.argv.length === 4, 'synthetic driver paths required');
const original = readFileSync(input);
const encrypted = encode(original);
const restored = decode(encrypted, rawKey);
assert.ok(restored.equals(original), 'synthetic database byte round trip');
assert.ok(decode(encrypted, pbkdf2Sync(passphrase, salt, 4000, 32, 'sha512')).equals(original));
assert.throws(() => decode(encrypted, Buffer.alloc(32)), /page_hmac_mismatch/);
assert.throws(() => decode(encrypted, rawKey, Buffer.alloc(16)), /salt_mismatch/);
assert.throws(() => decode(encrypted, rawKey, salt, 'sha512'), /page_hmac_mismatch/);
assert.throws(() => decode(encrypted.subarray(0, encrypted.length - 1), rawKey), /invalid_size/);
// Corrupt a later page: opening only sqlite_master/page one would miss this.
assert.ok(encrypted.length >= PREFIX + 2 * PAGE);
const damaged = Buffer.from(encrypted);
damaged[PREFIX + PAGE + 100] ^= 1;
assert.throws(() => decode(damaged, rawKey), /page_hmac_mismatch/);
writeFileSync(output, restored, { flag: 'wx' });
console.log(JSON.stringify({ synthetic_codec: 'passed', pages: restored.length / PAGE,
  refusals: ['wrong_key', 'wrong_salt', 'wrong_hmac_profile', 'truncated_page', 'later_page_corruption'],
  sqlcipher_interoperability: 'not_tested', qq_54395: 'not_tested' }));
}
