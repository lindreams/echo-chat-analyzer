// Actual remote load into OUR OWN host, private IPC, then existing JS auth.
import {spawn} from 'node:child_process';
import {join, dirname} from 'node:path';
import {readFileSync, writeFileSync, existsSync, unlinkSync, renameSync} from 'node:fs';
import {randomBytes, pbkdf2Sync, createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {encode} from '../qq_independent_codec.mjs';
import {connectOnce, verifiedBuild} from './connect.mjs';
import {decryptSnapshot, decryptMetadataSnapshots} from '../qq_full_read.mjs';

const scenario = process.argv[3];
const scenarios = ['delivery', 'auth_refused', 'parse_refused', 'cancel', 'timeout', 'controller_exit', 'host_exit', 'identity_refused'];
let secret, salt, raw, plain, page, inner, body, packet, input, output;
const chunks = [];
try {
  assert.ok(scenarios.includes(scenario));
  const {root, receipt} = verifiedBuild(process.argv[2]);
  secret = randomBytes(32).map(b => 97+b%26); salt = randomBytes(16);
  raw = pbkdf2Sync(secret, salt, 4000, 32, 'sha512'); plain = process.argv[4] ? readFileSync(process.argv[4]) : Buffer.alloc(4096);
  if (!process.argv[4]) { plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48; }
  page = encode(plain, raw, salt);
  let selection;
  if (process.argv[4]) {
    assert.equal(scenario, 'delivery');
    selection = {path: join(dirname(process.argv[4]), 'encrypted.db'), output: join(dirname(process.argv[4]), 'snapshot.db'),
      size: page.length, sha256: createHash('sha256').update(page).digest('hex')};
    writeFileSync(selection.path, page, {flag: 'wx'});
    const prefix = Buffer.from(page.subarray(0, 5120)); page.fill(0); page = prefix;
  }
  inner = Buffer.concat([Buffer.from([10, secret.length]), secret]);
  body = Buffer.concat([Buffer.from([18, inner.length]), inner]);
  packet = Buffer.concat([Buffer.from([8, 0xde, 0x19, 16, 2, 24, 0, 34, body.length]), body]);
  if (scenario === 'parse_refused') packet[0] = 0; // Invalid protobuf tag, not an authentication failure.
  input = Buffer.alloc(4+packet.length); input.writeUInt32LE(packet.length); packet.copy(input, 4);
  const env = {...process.env}; delete env.NODE_OPTIONS; delete env.NODE_PATH;
  const host = spawn(join(root, 'echo_qq_event_host.exe'), [`session-${scenario}`],
    {env, stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true});
  const hostExit = new Promise((resolveExit, reject) => { host.once('close', resolveExit); host.once('error', reject); });
  const hostTimer = setTimeout(() => host.kill(), 14000);
  let headerResolve;
  const metadata = new Promise(resolveHeader => { headerResolve = resolveHeader; });
  let total = 0;
  host.stdin.on('error', () => {});
  host.stdout.on('data', chunk => {
    total += chunk.length;
    if (total > 32) { chunk.fill(0); host.kill(); return; }
    chunks.push(chunk);
    if (total >= 16) headerResolve(Buffer.concat(chunks).subarray(0, 16));
  });
  host.stdin.write(input);
  const meta = await metadata;
  assert.equal(meta.readUInt32LE(0), 0x32535145);
  const target = {mode: 'fixture', version: '9.9.37-54395', pid: meta.readUInt32LE(4),
    created: meta.readBigUInt64LE(8)+(scenario === 'identity_refused' ? 1n : 0n),
    image: join(root, 'echo_qq_event_host.exe'), sha256: receipt.binaries['echo_qq_event_host.exe']};
  if (scenario === 'auth_refused') page[1050] ^= 1; // Authentication must fail; no alternate candidate.
  const abort = new AbortController();
  let helper, armed = false, stoppedBeforeConsume = false, consumes = 0, full, metadataVerified = false;
  const observedStatuses = [];
  const result = await connectOnce({directory: root, target, firstPage: page,
    timeoutMs: scenario === 'timeout' ? 150 : 2000, signal: abort.signal,
    consumerTimeoutMs: process.argv[5] === 'metadata' ? 120000 : 1000,
    onHelper(child) { helper = child; },
    consumeAuthenticatedKey(key, withDatabaseKey) {
      assert.equal(stoppedBeforeConsume, true); assert.equal(helper.exitCode, 0);
      consumes++;
      if (selection) {
        full = decryptSnapshot(selection, page, key);
        // The new sink must remove provisional plaintext for both a bad later
        // page and authenticated whole-page truncation, as the buffered path does.
        const original = readFileSync(selection.path);
        try {
          for (const failure of ['page_hmac_mismatch', 'page_count_mismatch']) {
            const bad = Buffer.from(failure === 'page_count_mismatch' ? original.subarray(0, -4096) : original);
            if (failure === 'page_hmac_mismatch') bad[1024+4096+100] ^= 1;
            const path = join(dirname(selection.path), failure+'.db');
            const output = join(dirname(selection.path), failure+'.sqlite');
            writeFileSync(path, bad, {flag: 'wx'});
            const sha256 = createHash('sha256').update(bad).digest('hex');
            assert.throws(() => decryptSnapshot({path, output, size: bad.length, sha256}, page, key),
              error => error.message === failure);
            assert.equal(existsSync(output), false); bad.fill(0);
          }
          const output = join(dirname(selection.path), 'wrong-key.sqlite');
          assert.throws(() => decryptSnapshot({...selection, output}, page, Buffer.alloc(32)),
            error => error.message === 'page_hmac_mismatch');
          assert.equal(existsSync(output), false);
          full.sink_refusals_and_partial_cleanup = true;
        } finally { original.fill(0); }
        if (process.argv[5] === 'metadata') {
          const selections = ['group_info', 'profile_info'].map((role, index) => {
            // A shared login passphrase does not imply shared raw DB keys.
            const databaseSalt = Buffer.alloc(16, 61+index);
            const databaseKey = pbkdf2Sync(secret, databaseSalt, 4000, 32, 'sha512');
            const bytes = encode(plain, databaseKey, databaseSalt);
            databaseKey.fill(0); databaseSalt.fill(0);
            const path = join(dirname(selection.path), role+'.db');
            writeFileSync(path, bytes, {flag: 'wx'});
            const item = {role, path, output: path+'.sqlite', size: bytes.length,
              sha256: createHash('sha256').update(bytes).digest('hex')};
            bytes.fill(0); return item;
          });
          // Reproduce the old mistake explicitly: the authenticated anchor raw
          // key fails the separately salted DB despite the shared passphrase.
          const ownPrefix = readFileSync(selections[0].path).subarray(0, 5120);
          const reusedOutput = selections[0].path+'.anchor-key.sqlite';
          try {
            assert.throws(() => decryptSnapshot({...selections[0], output: reusedOutput}, ownPrefix, key),
              error => error.message === 'page_hmac_mismatch');
            assert.equal(existsSync(reusedOutput), false);
          } finally { ownPrefix.fill(0); }
          const receipts = decryptMetadataSnapshots(selections, withDatabaseKey);
          assert.equal(receipts.length, 2);
          assert.ok(receipts.every(item => item.all_pages_authenticated && item.complete_image));
          // Retain only fictional plaintext for the Python owner's independent
          // SQLite integrity check after this process has wiped its secrets.
          for (const item of selections) renameSync(item.output, join(dirname(item.path), item.role+'.verified.sqlite'));
          // The anchor and first metadata MAC cannot authorize the second DB.
          // Later-page decoder evidence must survive the nested scope's error
          // sanitization, retaining authenticated/written counts separately.
          const original = readFileSync(selections[1].path);
          try {
            for (const failure of ['first_page', 'later_page']) {
              const bad = Buffer.from(original); bad[1024+(failure === 'first_page' ? 30 : 4096+100)] ^= 1;
              writeFileSync(selections[1].path, bad);
              selections[1].sha256 = createHash('sha256').update(bad).digest('hex'); bad.fill(0);
              const statuses = [];
              assert.throws(() => decryptMetadataSnapshots(selections, withDatabaseKey, status => statuses.push(status)),
                error => error.code === (failure === 'first_page' ? 'key_not_authenticated' : 'key_source_failed'));
              const failed = statuses.filter(status => status.phase === 'snapshot_failure');
              assert.equal(failed.length, 1); assert.equal(failed[0].role, 'profile_info');
              assert.equal(failed[0].failure, failure === 'first_page' ? 'database_key_refused' : 'page_hmac_mismatch');
              assert.equal(failed[0].authenticated_pages, failure === 'first_page' ? 0 : 1);
              assert.equal(failed[0].written_pages, failure === 'first_page' ? 0 : 1);
              assert.equal(failed[0].provisional_output_removed, true);
              assert.equal(existsSync(selections[0].output), true); // Outer TemporaryDirectory owns the first file.
              assert.equal(existsSync(selections[1].output), false);
              unlinkSync(selections[0].output);
            }
          } finally { original.fill(0); }
          assert.throws(() => decryptMetadataSnapshots(selections.slice(0, 1), withDatabaseKey));
          assert.throws(() => decryptMetadataSnapshots([...selections].reverse(), withDatabaseKey));
          assert.throws(() => decryptMetadataSnapshots([selections[0], {...selections[1], path: selections[0].path}], withDatabaseKey));
          assert.throws(() => decryptMetadataSnapshots(selections, key)); // Never silently fall back to anchor raw key.
          metadataVerified = true;
        }
      }
    },
    onStatus(status, timing) {
      observedStatuses.push({status, ...timing});
      assert.equal(timing.deadline_basis, 'conservative_request_start');
      assert.equal(Date.parse(timing.login_before_utc)-Date.parse(timing.request_started_utc), timing.observation_timeout_ms);
      assert.ok(Number.isInteger(timing.request_elapsed_ms) && timing.request_elapsed_ms >= 0);
      assert.equal(timing.remaining_login_ms, Math.max(0, timing.observation_timeout_ms-timing.request_elapsed_ms));
      if (status === 'stopped') stoppedBeforeConsume = true;
      if (status === 'armed') {
        armed = true;
        if (scenario === 'cancel') abort.abort();
        if (scenario === 'controller_exit') helper.kill();
      }
    }});
  if (scenario === 'identity_refused') host.stdin.write(Buffer.from([1]));
  const exitCode = await hostExit;
  clearTimeout(hostTimer); host.stdin.destroy(); output = Buffer.concat(chunks);
  assert.equal(result.authenticated, scenario === 'delivery');
  assert.equal(consumes, scenario === 'delivery' ? 1 : 0);
  assert.equal(result.event_parsed, ['delivery', 'auth_refused'].includes(scenario) ? true : scenario === 'parse_refused' ? false : null);
  assert.equal(armed, scenario !== 'identity_refused');
  assert.ok(JSON.stringify(result).length < 2048);
  const timing = result.observation_timing;
  assert.equal(timing.observation_timeout_ms, scenario === 'timeout' ? 150 : 2000);
  assert.equal(timing.armed_observed_utc !== null, armed);
  assert.equal(timing.target_observed_utc !== null, result.event_seen);
  assert.equal(timing.stopped_observed_utc !== null, stoppedBeforeConsume);
  if (stoppedBeforeConsume) {
    assert.ok(timing.armed_to_stop_ms >= 0);
    assert.equal(timing.armed_to_stop_ms, observedStatuses[1].request_elapsed_ms-observedStatuses[0].request_elapsed_ms);
  }
  if (scenario === 'timeout') assert.equal(timing.login_window_elapsed_at_stop, true);
  if (scenario === 'host_exit') {
    assert.equal(exitCode, 45); assert.equal(result.state, 'transport_refused');
  } else {
    assert.equal(exitCode, 0); assert.equal(output.length, 32);
    assert.equal(output.readUInt32LE(16), 0x32535145);
    assert.equal(output.readUInt32LE(20), 1); assert.equal(output.readUInt32LE(24), 1); assert.equal(output.readUInt32LE(28), 128);
    if (['controller_exit', 'identity_refused'].includes(scenario)) assert.equal(result.state, 'transport_refused');
    else {
      assert.equal(result.observation_stopped, true); assert.equal(result.inflight, 0);
      assert.equal(result.resources_retained_at_stop, true); // Stop acknowledgement precedes fixture-only full release.
      assert.equal(result.event_seen, ['delivery', 'auth_refused', 'parse_refused'].includes(scenario));
      assert.equal(result.state, {delivery: 'authenticated_event', auth_refused: 'authentication_refused', parse_refused: 'parse_refused', cancel: 'cancelled', timeout: 'no_target_event'}[scenario]);
    }
  }
  console.log(JSON.stringify({scenario, ...result, ...(full ? {full_snapshot: full} : {}),
    ...(metadataVerified ? {metadata_independent_authentication: true, metadata_second_source_refused: true} : {}),
    consumer_after_verified_stop: true, fixture_host_continued: scenario !== 'host_exit',
    observation_timing_verified: true,
    fixture_unloaded: scenario !== 'host_exit', post_stop_target_calls: scenario === 'host_exit' ? 0 : 128,
    no_post_stop_forward: !result.event_seen || ['delivery', 'auth_refused', 'parse_refused'].includes(scenario),
    real_qq_accessed: false, raw_data_or_keys_persisted: false}));
} catch {
  console.log(JSON.stringify({state: 'refused', code: 'session_fixture_failed', scenario})); process.exitCode = 2;
} finally {
  for (const b of [secret, salt, raw, plain, page, inner, body, packet, input, output, ...chunks]) b?.fill(0);
}
