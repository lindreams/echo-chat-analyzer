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

import {decode,authenticateFirstPage} from '../../src/qq_chat_analyzer/providers/qq_independent/js/qq_independent_codec.mjs';
export {decode,authenticateFirstPage};
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
