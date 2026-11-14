// Research only: a closed synthetic round trip, never a QQ process/key reader.
// Candidate profile: 1024-byte wrapper, 4096-byte pages, AES-256-CBC,
// PBKDF2-HMAC-SHA512 (4000), page HMAC-SHA1, 48 reserved bytes.
// The standalone CLI is a self round trip; the separate reference driver
// verifies SQLCipher interoperability. Neither establishes QQ version support.
import { readFileSync, writeFileSync } from 'node:fs';
import { createCipheriv, createDecipheriv, createHmac, pbkdf2Sync, randomBytes, timingSafeEqual } from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const PAGE = 4096, PREFIX = 1024, RESERVE = 48;
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

export function encode(plain, key = rawKey, pageSalt = salt) {
  assert.equal(plain.length % PAGE, 0);
  assert.ok(plain.subarray(0, 16).equals(MAGIC));
  assert.equal(plain.readUInt16BE(16), PAGE);
  assert.equal(plain[20], RESERVE);
  const prefix = Buffer.alloc(PREFIX);
  Buffer.from('SQLite header 3\0').copy(prefix);
  const pages = [prefix];
  for (let offset = 0, number = 1; offset < plain.length; offset += PAGE, number++) {
    const first = number === 1;
    const body = plain.subarray(offset + (first ? 16 : 0), offset + PAGE - RESERVE);
    const iv = randomBytes(16);
    const cipher = createCipheriv('aes-256-cbc', key, iv);
    cipher.setAutoPadding(false);
    const ciphertext = Buffer.concat([cipher.update(body), cipher.final()]);
    pages.push(Buffer.concat([first ? pageSalt : Buffer.alloc(0), ciphertext, iv,
      pageTag(ciphertext, iv, number, key, pageSalt), Buffer.alloc(12)]));
  }
  return Buffer.concat(pages);
}

export function decode(wrapped, key, pageSalt = wrapped.subarray(PREFIX, PREFIX + 16), hash = 'sha1') {
  if (wrapped.length <= PREFIX || (wrapped.length - PREFIX) % PAGE !== 0)
    throw new Error('invalid_size');
  if (!wrapped.subarray(PREFIX, PREFIX + 16).equals(pageSalt))
    throw new Error('salt_mismatch');
  const output = [];
  for (let offset = PREFIX, number = 1; offset < wrapped.length; offset += PAGE, number++) {
    const first = number === 1;
    const ciphertext = wrapped.subarray(offset + (first ? 16 : 0), offset + PAGE - RESERVE);
    const iv = wrapped.subarray(offset + PAGE - RESERVE, offset + PAGE - RESERVE + 16);
    const stored = wrapped.subarray(offset + PAGE - RESERVE + 16, offset + PAGE - RESERVE + 36);
    const expected = pageTag(ciphertext, iv, number, key, pageSalt, hash);
    if (expected.length !== stored.length || !timingSafeEqual(expected, stored))
      throw new Error('page_hmac_mismatch');
    const decipher = createDecipheriv('aes-256-cbc', key, iv);
    decipher.setAutoPadding(false);
    output.push(Buffer.concat([first ? MAGIC : Buffer.alloc(0),
      decipher.update(ciphertext), decipher.final(), Buffer.alloc(RESERVE)]));
  }
  const plain = Buffer.concat(output);
  // Trust a page count only when SQLite's header marks it current. This
  // research reader rejects unknown completeness instead of inferring/repairing.
  const declaredPages = plain.readUInt32BE(28);
  if (declaredPages === 0 || plain.readUInt32BE(24) !== plain.readUInt32BE(92))
    throw new Error('untrusted_page_count');
  if (declaredPages !== plain.length / PAGE)
    throw new Error('page_count_mismatch');
  return plain;
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
