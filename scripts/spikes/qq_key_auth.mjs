// In-memory child of the bounded candidate worker. No key output or files.
import {readFileSync} from 'node:fs';
import {authenticateFirstPage} from './qq_independent_codec.mjs';
let input, page, keys = [];
try {
  input = readFileSync(0);
  if (input.length > 16384) throw new Error();
  const record = JSON.parse(input.toString('utf8'));
  page = Buffer.from(record.page, 'base64');
  if (page.length !== 5120 || !Array.isArray(record.keys) || record.keys.length > 16) throw new Error();
  keys = record.keys.map(value => {
    if (typeof value !== 'string' || !/^[0-9a-f]{64}$/i.test(value)) throw new Error();
    return Buffer.from(value, 'hex');
  });
  const matches = keys.reduce((sum, key) => sum + Number(authenticateFirstPage(page, key)), 0);
  console.log(JSON.stringify({matched: matches > 0, authenticated_candidates: matches}));
} catch {
  console.log('{"state":"refused","code":"authentication_worker_failed"}');
  process.exitCode = 2;
} finally {
  input?.fill(0); page?.fill(0);
  for (const key of keys) key.fill(0);
}
