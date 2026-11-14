// Self-built process only. No option accepts a PID, QQ path or real database.
import {fork} from 'node:child_process';
import {randomBytes, pbkdf2Sync} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {encode} from './qq_independent_codec.mjs';
import {PROFILE, KeySourceError} from './qq_key_source.mjs';
import {COMMAND, MAX_EVENT_BYTES, observeCdeResponse} from './qq_login_event_probe.mjs';

const scenarios = new Set(['matching', 'wrong_key', 'malformed', 'absent', 'wrong_session', 'stall']);
// Fixture encoder is independent of the observer's wire reader.
function varint(value) {
  const bytes = [];
  do { const byte = value & 127; value >>>= 7; bytes.push(byte | (value ? 128 : 0)); } while (value);
  return Buffer.from(bytes);
}
const scalar = (id, value) => Buffer.concat([varint(id * 8), varint(value)]);
const blob = (id, value) => Buffer.concat([varint(id * 8 + 2), varint(value.length), value]);
const send = value => new Promise((resolve, reject) => process.send(value, error => error ? reject(error) : resolve()));

function verifyAdmission() {
  for (const metadata of [{command: 'unrelated', direction: 'receive'}, {command: COMMAND, direction: 'send'}]) {
    const event = {...metadata, get payload() { assert.fail('non-target payload accessed'); }};
    assert.deepEqual(observeCdeResponse(event), {state: 'ignored'});
  }
  // These must fail before touching the database input; rejected target bytes
  // are cleared too. Duplicate key-bearing fields never use last-value-wins.
  const duplicate = Buffer.concat([scalar(1, 0xcde), scalar(2, 2), blob(4, Buffer.alloc(0)), blob(4, Buffer.alloc(0))]);
  for (const [payload, truncated, code] of [[Buffer.alloc(MAX_EVENT_BYTES + 1, 1), false, 'event_size_refused'],
    [Buffer.from([1]), true, 'incomplete_event'], [duplicate, false, 'ambiguous_event_field']]) {
    assert.throws(() => observeCdeResponse({command: COMMAND, direction: 'receive',
      error: 0, truncated, originalLength: payload.length, payload}), error => error.code === code);
    assert.ok(payload.every(byte => byte === 0));
  }
}

async function fixtureChild() {
  process.once('disconnect', () => process.exit(0)); // Parent disappearance never leaves a fixture running.
  process.once('message', async ({nonce, scenario}) => {
    const material = randomBytes(32).map(value => 0x61 + value % 26), salt = randomBytes(16);
    const raw = pbkdf2Sync(material, salt, 4000, 32, 'sha512');
    const plain = Buffer.alloc(4096);
    plain.write('SQLite format 3\0'); plain.writeUInt16BE(4096, 16); plain[20] = 48;
    const page = encode(plain, raw, salt);
    const eventKey = scenario === 'wrong_key' ? Buffer.from('fictional-wrong-key') : material;
    const nested = blob(1, eventKey), body = blob(2, nested);
    const payload = Buffer.concat([scalar(1, 0xcde), scalar(2, 2), scalar(3, 0), blob(4, body)]);
    const envelope = value => ({...value, pid: process.pid, nonce});
    try {
      await send(envelope({kind: 'page', page}));
      if (scenario === 'stall') {
        // Remain alive until the owner's deadline/Job terminates this fixture.
        await new Promise(() => { setInterval(() => {}, 1000); });
        return;
      }
      await send(envelope({kind: 'event', event: {command: 'fictional.unrelated', direction: 'receive'}}));
      if (scenario !== 'absent') {
        const event = {command: COMMAND, direction: 'receive', error: 0, truncated: false,
          payload: scenario === 'malformed' ? Buffer.from([0x22, 0xff]) : payload};
        event.originalLength = event.payload.length;
        await send({...envelope({kind: 'event', event}), nonce: scenario === 'wrong_session' ? 'different' : nonce});
      }
    } finally {
      for (const buffer of [material, salt, raw, plain, page, eventKey, nested, body, payload]) buffer.fill(0);
    }
    await send(envelope({kind: 'released'}));
    process.disconnect();
  });
}

export async function runFixture(scenario) {
  if (!scenarios.has(scenario)) throw new KeySourceError('invalid_fixture_case');
  if (scenario === 'matching') verifyAdmission();
  const nonce = randomBytes(16).toString('hex'); // Transport generation, not a QQ credential.
  const environment = {...process.env};
  delete environment.NODE_OPTIONS; delete environment.NODE_PATH;
  const child = fork(fileURLToPath(import.meta.url), ['--fixture-child'], {
    env: environment, execArgv: ['--max-old-space-size=64'], serialization: 'advanced', windowsHide: true,
    stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  let page, state = 'event_absent', code = null, events = 0, targets = 0, released = false;
  let stopped = false;
  const stop = failure => { if (!stopped) { stopped = true; code = failure; child.kill(); } };
  const timer = setTimeout(() => stop('event_deadline_reached'), scenario === 'stall' ? 300 : 3000);
  const exited = new Promise(resolve => {
    child.once('error', () => stop('fixture_transport_failed'));
    child.on('message', message => {
      if (stopped) return;
      try {
        if (++events > 8) throw new KeySourceError('event_count_limit');
        if (message.pid !== child.pid || message.nonce !== nonce) throw new KeySourceError('event_session_mismatch');
        if (message.kind === 'page') {
          if (page || !Buffer.isBuffer(message.page) || message.page.length !== 5120) throw new KeySourceError('fixture_transport_failed');
          page = message.page;
        } else if (message.kind === 'event' && page) {
          // The private IPC handle belongs to this exact child. No listening
          // socket or attach-to-existing-process mode exists.
          if (message.event.command === COMMAND && message.event.direction === 'receive' && ++targets > 1)
            throw new KeySourceError('target_event_limit');
          const result = observeCdeResponse(message.event, {version: '9.9.37-54395',
            profile: PROFILE, sessionGeneration: nonce, firstPage: page});
          if (result.state !== 'ignored') state = result.state;
        } else if (message.kind === 'released') released = true;
        else throw new KeySourceError('fixture_transport_failed');
      } catch (error) {
        if (Buffer.isBuffer(message.event?.payload)) message.event.payload.fill(0);
        stop(error instanceof KeySourceError ? error.code : 'event_processing_failed');
      }
    });
    child.once('close', exitCode => {
      clearTimeout(timer); page?.fill(0);
      if (!code && (!released || exitCode !== 0)) code = 'fixture_exit_unconfirmed';
      resolve({state: code ? 'refused' : state, code, target_events: targets,
        child_exited: true, cooperative_release: released, source: 'owned_fictional_child',
        qq_54395_observed: false, key_material_persisted: false});
    });
  });
  const interrupt = () => stop('cancelled');
  process.once('SIGINT', interrupt);
  child.send({nonce, scenario}, error => { if (error) stop('fixture_transport_failed'); });
  try { return await exited; }
  finally { process.removeListener('SIGINT', interrupt); }
}

if (process.argv[2] === '--fixture-child') await fixtureChild();
else if (fileURLToPath(import.meta.url) === process.argv[1]) {
  try { console.log(JSON.stringify(await runFixture(process.argv[2]))); }
  catch { console.log('{"state":"refused","code":"fixture_failed"}'); process.exitCode = 2; }
}
