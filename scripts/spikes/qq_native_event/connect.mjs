// Research-only restricted native transport -> EXISTING event authenticator.
// No QQ discovery, database path, network, raw logging or real-process CLI.
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {createHash, randomBytes} from 'node:crypto';
import {COMMAND, observeCdeResponse} from '../qq_login_event_probe.mjs';
import {PROFILE, KeySourceError} from '../qq_key_source.mjs';

const MAGIC = 0x32535145, BUILD = '9.9.37-54395';
const binaries = ['echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll', 'echo_event_loader.exe'];
export function verifiedBuild(directory) {
  const root = resolve(directory);
  const receipt = JSON.parse(readFileSync(join(root, 'build-receipt.json'), 'utf8').replace(/^\uFEFF/, ''));
  if (receipt.build !== BUILD || receipt.minhook_revision !== 'c3fcafdc10146beb5919319d0683e44e3c30d537') throw Error('build_refused');
  for (const name of binaries) {
    if (createHash('sha256').update(readFileSync(join(root, name))).digest('hex') !== receipt.binaries[name]) throw Error('build_refused');
  }
  return {root, receipt};
}

/** target must be explicitly approved/selected outside this transport. Only
 * fixture mode may be used without a separate real-QQ approval. A matching MAC
 * attests the supplied first page, not a whole database/WAL or safe QQ operation.
 * The caller owns firstPage and must wipe it after this Promise settles.
 */
export async function connectOnce({directory, target, firstPage, timeoutMs = 120000, signal, onStatus = () => {}, onHelper = () => {}}) {
  const {root} = verifiedBuild(directory);
  if (!['fixture', 'approved-qq'].includes(target?.mode) || target.version !== BUILD ||
      !Number.isInteger(target.pid) || target.pid < 1 || target.pid > 0xffffffff ||
      typeof target.created !== 'bigint' || target.created < 1n || target.created > 0xffffffffffffffffn ||
      typeof target.image !== 'string' || !/^[a-f0-9]{64}$/.test(target.sha256 ?? '') ||
      !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000 ||
      !Buffer.isBuffer(firstPage) || firstPage.length !== 5120 || signal?.aborted) throw Error('session_refused');
  const header = Buffer.alloc(48);
  header.writeUInt32LE(MAGIC); header.writeUInt32LE(54395, 4); header.writeUInt32LE(timeoutMs, 8);
  Buffer.from(target.sha256, 'hex').copy(header, 16);
  const env = {...process.env}; delete env.NODE_OPTIONS; delete env.NODE_PATH;
  const child = spawn(join(root, 'echo_event_loader.exe'), [`--${target.mode}`, String(target.pid), String(target.created),
    target.image, join(root, target.mode === 'fixture' ? 'echo_event_fixture.dll' : 'echo_event_54395.dll'), BUILD],
    {env, stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true});
  let pending = Buffer.alloc(0), total = 0, phase = 0, eventSeen = false, authenticated = false, stopped = false;
  let transportFailed = false, aborted = false, finish;
  let parsed = null;
  const generation = randomBytes(32).toString('hex'); // Session label, never key material.
  const cancel = () => { aborted = true; authenticated = false; child.stdin.write(Buffer.from([1])); };
  const refuse = () => { transportFailed = true; cancel(); };
  const abort = () => cancel();
  signal?.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(() => { transportFailed = true; child.kill(); }, timeoutMs+9000); // Our helper ONLY, never QQ.
  child.stdin.on('error', () => { transportFailed = true; });
  const completed = new Promise(resolveExit => {
    child.once('error', () => { transportFailed = true; });
    child.once('close', code => resolveExit(code));
  });
  child.stdout.on('data', chunk => {
    try {
      total += chunk.length;
      if (total > 8256 || phase === 3) { refuse(); return; }
      const previous = pending;
      pending = Buffer.concat([previous, chunk]); previous.fill(0);
      while (pending.length >= 16) {
        const magic = pending.readUInt32LE(0), kind = pending.readUInt32LE(4), n = pending.readUInt32LE(8);
        if (magic !== MAGIC || pending.readUInt32LE(12) || n > 8192) { refuse(); return; }
        if (pending.length < 16+n) break;
        const payload = pending.subarray(16, 16+n);
        if (kind === 1 && phase === 0 && n === 0) { phase = 1; onStatus('armed'); }
        else if (kind === 2 && phase === 1 && n) {
          phase = 2; eventSeen = true;
          if (!aborted && !signal?.aborted) {
            try {
              authenticated = observeCdeResponse({command: COMMAND, direction: 'receive', error: 0,
                truncated: false, originalLength: n, payload},
                {version: BUILD, profile: PROFILE, sessionGeneration: generation, firstPage}, {signal}).state === 'authenticated_event';
              parsed = authenticated ? true : null;
            } catch (error) {
              authenticated = false;
              // These existing typed failures distinguish the requested stages
              // without exposing exception text or duplicating the parser.
              if (error instanceof KeySourceError) {
                if (error.code === 'key_not_authenticated') parsed = true;
                else if (['incomplete_event', 'event_size_refused', 'invalid_event_wire', 'event_field_limit',
                  'ambiguous_event_field', 'unexpected_response', 'passphrase_event_missing', 'invalid_passphrase_event'].includes(error.code)) parsed = false;
              }
            }
          }
        } else if (kind === 3 && (phase === 1 || phase === 2) && n === 16) {
          finish = {reads_stopped: payload.readUInt32LE(0) === 1, hook_disabled: payload.readUInt32LE(4) === 1,
            inflight: payload.readUInt32LE(8), resources_retained_at_stop: payload.readUInt32LE(12) === 1};
          stopped = finish.reads_stopped && finish.hook_disabled;
          phase = 3; onStatus(stopped ? 'stopped' : 'stop_unconfirmed');
        } else { refuse(); return; }
        const rest = Buffer.from(pending.subarray(16+n)); pending.fill(0); pending = rest;
        if (phase === 3 && pending.length) { refuse(); return; }
      }
    } catch { refuse(); }
    finally { chunk.fill(0); }
  });
  try {
    child.stdin.write(header); onHelper(child); // Test harness may fault only this owned helper.
    const code = await completed;
    const clean = code === 0 && !transportFailed && stopped && !pending.length && phase === 3;
    return {state: clean ? (aborted ? 'cancelled' : authenticated ? 'authenticated_event' : eventSeen ? (parsed === false ? 'parse_refused' : 'authentication_refused') : 'no_target_event') : 'transport_refused',
      event_seen: eventSeen, event_parsed: parsed, authenticated: clean && authenticated && !aborted,
      observation_stopped: clean, component_unloaded: false, ...finish,
      authentication_scope: clean && authenticated && !aborted ? 'first_page_only' : 'none'};
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort); header.fill(0); pending.fill(0);
    child.stdin.destroy();
  }
}
