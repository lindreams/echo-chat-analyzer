// Private binary pipes carry ONLY self-generated fictional data. Public stdout
// contains states only. There is no QQ PID, attach or real database option.
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {resolve, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomBytes, pbkdf2Sync, createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {encode} from '../qq_independent_codec.mjs';
import {PROFILE} from '../qq_key_source.mjs';
import {COMMAND, observeCdeResponse} from '../qq_login_event_probe.mjs';

const states = {delivery: 2, heap_delivery: 2, cancel: 4, timeout: 5, invalid_layout: 6, install_failure: 6,
  wrong_version: 6, busy_stop: 4, production_gate: 6};

async function run(directory, scenario) {
  assert.ok(Object.hasOwn(states, scenario));
  const root = resolve(directory);
  const receipt = JSON.parse(readFileSync(join(root, 'build-receipt.json'), 'utf8').replace(/^\uFEFF/, ''));
  assert.equal(receipt.build, '9.9.37-54395');
  assert.equal(receipt.minhook_revision, 'c3fcafdc10146beb5919319d0683e44e3c30d537');
  for (const name of ['echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll']) {
    assert.equal(createHash('sha256').update(readFileSync(join(root, name))).digest('hex'), receipt.binaries[name]);
  }
  const secret = randomBytes(32).map(b => 97 + b % 26), salt = randomBytes(16);
  const raw = pbkdf2Sync(secret, salt, 4000, 32, 'sha512');
  const plain = Buffer.alloc(4096);
  plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48;
  const page = encode(plain, raw, salt);
  const inner = Buffer.concat([Buffer.from([10, secret.length]), secret]);
  const body = Buffer.concat([Buffer.from([18, inner.length]), inner]);
  const packet = Buffer.concat([Buffer.from([8, 0xde, 0x19, 16, 2, 24, 0, 34, body.length]), body]);
  const length = Buffer.alloc(4); length.writeUInt32LE(packet.length);
  const input = Buffer.concat([length, packet]);
  const environment = {...process.env};
  delete environment.NODE_OPTIONS; delete environment.NODE_PATH;
  const child = spawn(join(root, 'echo_qq_event_host.exe'),
    [join(root, scenario === 'production_gate' ? 'echo_event_54395.dll' : 'echo_event_fixture.dll'), scenario],
    {env: environment, stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true});
  const chunks = [];
  let total = 0, stopped = false;
  const terminate = () => { stopped = true; child.kill(); };
  const timer = setTimeout(terminate, 5000);
  process.once('SIGINT', terminate);
  let output;
  try {
    const completed = new Promise((resolveExit, reject) => {
      child.once('error', reject);
      child.stdin.on('error', () => {}); // Exit status is the public failure evidence.
      child.stdout.on('data', chunk => {
        total += chunk.length;
        if (total > 8208) { chunk.fill(0); terminate(); }
        else chunks.push(chunk);
      });
      child.once('close', code => resolveExit(code));
    });
    child.stdin.end(input);
    const exitCode = await completed;
    assert.ok(!stopped && exitCode === 0); // Never expose raw native diagnostics.
    output = Buffer.concat(chunks);
    assert.ok(output.length >= 16 && output.readUInt32LE(0) === 0x314e5145);
    const n = output.readUInt32LE(4), observed = output.readUInt32LE(8);
    assert.equal(output.length, 16 + n); assert.equal(observed, states[scenario]);
    assert.equal(output.readUInt32LE(12), Number(scenario === 'busy_stop'));
    assert.equal(n > 0, scenario === 'delivery' || scenario === 'heap_delivery');
    let authenticated = false;
    if (n) {
      const result = observeCdeResponse({command: COMMAND, direction: 'receive', error: 0,
        truncated: false, originalLength: n, payload: output.subarray(16)},
        {version: '9.9.37-54395', profile: PROFILE,
          sessionGeneration: `owned-native-fixture-${child.pid}`, firstPage: page});
      assert.equal(result.state, 'authenticated_event'); authenticated = true;
    }
    return {scenario, native_state: observed, authenticated_event: authenticated,
      original_entry_restored: true, dll_unloaded: true, native_resources_released: true,
      host_continued: true, busy_unload_refused: scenario === 'busy_stop',
      source: 'owned_native_fixture', real_qq_accessed: false, raw_data_or_keys_persisted: false};
  } finally {
    clearTimeout(timer); process.removeListener('SIGINT', terminate);
    for (const buffer of [secret, salt, raw, plain, page, inner, body, packet, length, input, output, ...chunks]) buffer?.fill(0);
  }
}

if (fileURLToPath(import.meta.url) === process.argv[1]) {
  try { console.log(JSON.stringify(await run(process.argv[2], process.argv[3]))); }
  catch { console.log('{"state":"refused","code":"owned_native_check_failed"}'); process.exitCode = 2; }
}
