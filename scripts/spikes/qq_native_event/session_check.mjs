// Actual remote load into OUR OWN host, private IPC, then existing JS auth.
import {spawn} from 'node:child_process';
import {join} from 'node:path';
import {randomBytes, pbkdf2Sync} from 'node:crypto';
import assert from 'node:assert/strict';
import {encode} from '../qq_independent_codec.mjs';
import {connectOnce, verifiedBuild} from './connect.mjs';

const scenario = process.argv[3];
const scenarios = ['delivery', 'auth_refused', 'parse_refused', 'cancel', 'timeout', 'controller_exit', 'host_exit', 'identity_refused'];
let secret, salt, raw, plain, page, inner, body, packet, input, output;
const chunks = [];
try {
  assert.ok(scenarios.includes(scenario));
  const {root, receipt} = verifiedBuild(process.argv[2]);
  secret = randomBytes(32).map(b => 97+b%26); salt = randomBytes(16);
  raw = pbkdf2Sync(secret, salt, 4000, 32, 'sha512'); plain = Buffer.alloc(4096);
  plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48;
  page = encode(plain, raw, salt);
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
  let helper, armed = false;
  const result = await connectOnce({directory: root, target, firstPage: page,
    timeoutMs: scenario === 'timeout' ? 150 : 2000, signal: abort.signal,
    onHelper(child) { helper = child; },
    onStatus(status) {
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
  assert.equal(result.event_parsed, ['delivery', 'auth_refused'].includes(scenario) ? true : scenario === 'parse_refused' ? false : null);
  assert.equal(armed, scenario !== 'identity_refused');
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
  console.log(JSON.stringify({scenario, ...result, fixture_host_continued: scenario !== 'host_exit',
    fixture_unloaded: scenario !== 'host_exit', post_stop_target_calls: scenario === 'host_exit' ? 0 : 128,
    no_post_stop_forward: !result.event_seen || ['delivery', 'auth_refused', 'parse_refused'].includes(scenario),
    real_qq_accessed: false, raw_data_or_keys_persisted: false}));
} catch {
  console.log(JSON.stringify({state: 'refused', code: 'session_fixture_failed', scenario})); process.exitCode = 2;
} finally {
  for (const b of [secret, salt, raw, plain, page, inner, body, packet, input, output, ...chunks]) b?.fill(0);
}
