// Research-only restricted native transport -> EXISTING event authenticator.
// No QQ discovery, database path, network, raw logging or real-process CLI.
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {createHash, randomBytes} from 'node:crypto';
import {COMMAND, observeCdeResponse} from './qq_login_event_probe.mjs';
import {PROFILE, KeySourceError} from './qq_key_source.mjs';

const MAGIC = 0x32535145, BUILD = '9.9.37-54395';
const binaries = ['echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll', 'echo_event_loader.exe'];
export function verifiedBuild(directory, productionPins) {
  const root = resolve(directory);
  const receipt = JSON.parse(readFileSync(join(root, 'build-receipt.json'), 'utf8').replace(/^\uFEFF/, ''));
  if (receipt.build !== BUILD || receipt.minhook_revision !== 'c3fcafdc10146beb5919319d0683e44e3c30d537') throw Error('build_refused');
  for (const name of productionPins ? ['echo_event_54395.dll','echo_event_loader.exe'] : binaries) {
    if (productionPins && receipt.binaries[name] !== productionPins[name]) throw Error('build_refused');
    if (createHash('sha256').update(readFileSync(join(root, name))).digest('hex') !== receipt.binaries[name]) throw Error('build_refused');
  }
  return {root, receipt};
}

/** target must be explicitly approved/selected outside this transport. Only
 * fixture mode may be used without a separate real-QQ approval. A matching MAC
 * attests the supplied first page, not a whole database/WAL or safe QQ operation.
 * The caller owns firstPage and must wipe it after this Promise settles.
 */
export async function connectOnce({directory, productionPins, target, firstPage, timeoutMs = 120000, signal, onStatus = () => {}, onHelper = () => {},
  consumeAuthenticatedKey, consumerTimeoutMs = 1000, prepareAuthentication}) {
  const {root} = verifiedBuild(directory, productionPins);
  if (!['fixture', 'approved-qq'].includes(target?.mode) || target.version !== BUILD ||
      !Number.isInteger(target.pid) || target.pid < 1 || target.pid > 0xffffffff ||
      typeof target.created !== 'bigint' || target.created < 1n || target.created > 0xffffffffffffffffn ||
      typeof target.image !== 'string' || !/^[a-f0-9]{64}$/.test(target.sha256 ?? '') ||
      !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120000 ||
      (!(Buffer.isBuffer(firstPage) && firstPage.length === 5120) &&
        !(firstPage === undefined && typeof prepareAuthentication === 'function' && typeof consumeAuthenticatedKey === 'function')) || signal?.aborted ||
      (consumeAuthenticatedKey !== undefined && typeof consumeAuthenticatedKey !== 'function') ||
      !Number.isInteger(consumerTimeoutMs) || consumerTimeoutMs < 1 || consumerTimeoutMs > 120000) throw Error('session_refused');
  const header = Buffer.alloc(48);
  header.writeUInt32LE(MAGIC); header.writeUInt32LE(54395, 4); header.writeUInt32LE(timeoutMs, 8);
  Buffer.from(target.sha256, 'hex').copy(header, 16);
  const env = {...process.env}; delete env.NODE_OPTIONS; delete env.NODE_PATH;
  // This precedes native setup, so the login deadline is conservative, not
  // native expiry or a fresh timeout starting when the controller sees armed.
  const requestStartedUtc = Date.now(), requestStarted = performance.now();
  let armedTiming, stoppedTiming, targetObservedUtc;
  const timing = () => {
    const elapsed = Math.floor(performance.now()-requestStarted);
    return {observed_utc: new Date().toISOString(), request_elapsed_ms: elapsed,
      request_started_utc: new Date(requestStartedUtc).toISOString(),
      login_before_utc: new Date(requestStartedUtc+timeoutMs).toISOString(),
      deadline_basis: 'conservative_request_start', observation_timeout_ms: timeoutMs,
      remaining_login_ms: Math.max(0, timeoutMs-elapsed)};
  };
  const child = spawn(join(root, 'echo_event_loader.exe'), [`--${target.mode}`, String(target.pid), String(target.created),
    target.image, join(root, target.mode === 'fixture' ? 'echo_event_fixture.dll' : 'echo_event_54395.dll'), BUILD],
    {env, stdio: ['pipe', 'pipe', 'ignore'], windowsHide: true});
  let pending = Buffer.alloc(0), total = 0, phase = 0, eventSeen = false, authenticated = false, stopped = false;
  let transportFailed = false, aborted = false, finish;
  let parsed = null;
  let keyScopeFailure;
  let diagnosticFailure;
  let deferredPayload;
  const authenticate = payload => {
    try {
      authenticated = observeCdeResponse({command: COMMAND, direction: 'receive', error: 0,
        truncated: false, originalLength: payload.length, payload},
        {version: BUILD, profile: PROFILE, sessionGeneration: generation, firstPage},
        {signal, deadline: performance.now()+consumerTimeoutMs}, consumeAuthenticatedKey ? (key, withDatabaseKey) => {
          parsed = true; // Consumer failure must not erase successful parsing.
          consumeAuthenticatedKey(key, withDatabaseKey);
        } : undefined).state === 'authenticated_event';
      parsed = authenticated ? true : null;
    } catch (error) {
      authenticated = false;
      if (error instanceof KeySourceError) {
        // Local fixed KeySourceError codes only; never an exception message.
        const safeCodes=['deadline_reached','cancelled','source_expired','source_cleanup_failed',
          'key_source_failed','key_not_authenticated','passphrase_required','incomplete_event','event_size_refused',
          'invalid_event_wire','event_field_limit','ambiguous_event_field','unexpected_response',
          'passphrase_event_missing','invalid_passphrase_event','invalid_request','invalid_key_material',
          'source_binding_mismatch','trusted_source_unavailable','invalid_source','source_already_used','async_source_unsupported'];
        diagnosticFailure ??= safeCodes.includes(error.code)?error.code:'key_source_failed';
        if (['deadline_reached', 'cancelled', 'source_expired', 'source_cleanup_failed',
          'key_source_failed', 'key_not_authenticated', 'passphrase_required'].includes(error.code)) keyScopeFailure = error.code;
        if (error.code === 'key_not_authenticated') parsed = true;
        else if (['incomplete_event', 'event_size_refused', 'invalid_event_wire', 'event_field_limit',
          'ambiguous_event_field', 'unexpected_response', 'passphrase_event_missing', 'invalid_passphrase_event'].includes(error.code)) parsed = false;
      }
    }
  };
  const generation = randomBytes(32).toString('hex'); // Session label, never key material.
  const cancel = () => { aborted = true; authenticated = false; child.stdin.write(Buffer.from([1])); };
  const refuse = code => { diagnosticFailure ??= code; transportFailed = true; cancel(); };
  const abort = () => cancel();
  signal?.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(() => { diagnosticFailure ??= 'loader_timeout'; transportFailed = true; child.kill(); }, timeoutMs+9000); // Our helper ONLY, never QQ.
  child.stdin.on('error', () => { diagnosticFailure ??= 'transport_write_failed'; transportFailed = true; });
  const completed = new Promise(resolveExit => {
    child.once('error', () => { diagnosticFailure ??= 'loader_spawn_failed'; transportFailed = true; });
    child.once('close', code => resolveExit(code));
  });
  child.stdout.on('data', chunk => {
    try {
      total += chunk.length;
      if (total > 8256 || phase === 3) { refuse('transport_limit'); return; }
      const previous = pending;
      pending = Buffer.concat([previous, chunk]); previous.fill(0);
      while (pending.length >= 16) {
        const magic = pending.readUInt32LE(0), kind = pending.readUInt32LE(4), n = pending.readUInt32LE(8);
        if (magic !== MAGIC || pending.readUInt32LE(12) || n > 8192) { refuse('transport_header_refused'); return; }
        if (pending.length < 16+n) break;
        const payload = pending.subarray(16, 16+n);
        if (kind === 1 && phase === 0 && n === 0) {
          phase = 1; armedTiming = timing(); onStatus('armed', armedTiming);
        }
        else if (kind === 2 && phase === 1 && n) {
          phase = 2; eventSeen = true; targetObservedUtc = new Date().toISOString();
          if (!aborted && !signal?.aborted) {
            // Full reads start only AFTER native Stop and helper-exit evidence.
            // At most one bounded event stays in memory; no key survives auth.
            if (consumeAuthenticatedKey) deferredPayload = Buffer.from(payload);
            else authenticate(payload);
          }
        } else if (kind === 3 && (phase === 1 || phase === 2) && n === 16) {
          finish = {reads_stopped: payload.readUInt32LE(0) === 1, hook_disabled: payload.readUInt32LE(4) === 1,
            inflight: payload.readUInt32LE(8), resources_retained_at_stop: payload.readUInt32LE(12) === 1};
          stopped = finish.reads_stopped && finish.hook_disabled;
          phase = 3; stoppedTiming = timing();
          onStatus(stopped ? 'stopped' : 'stop_unconfirmed', stoppedTiming);
        } else { refuse('transport_sequence_refused'); return; }
        const rest = Buffer.from(pending.subarray(16+n)); pending.fill(0); pending = rest;
        if (phase === 3 && pending.length) { refuse('transport_trailing_data'); return; }
      }
    } catch { refuse('transport_parse_refused'); }
    finally { chunk.fill(0); }
  });
  try {
    child.stdin.write(header); onHelper(child); // Test harness may fault only this owned helper.
    const code = await completed;
    clearTimeout(timer);
    const clean = code === 0 && !transportFailed && stopped && !pending.length && phase === 3;
    if (clean && !aborted && !signal?.aborted && deferredPayload) {
      // Only the bounded event is retained while the caller proves QQ exit
      // and freezes the explicitly authorized inputs. No raw key lease exists.
      if (prepareAuthentication) {
        firstPage = await prepareAuthentication();
        if (!Buffer.isBuffer(firstPage) || firstPage.length !== 5120 || signal?.aborted) throw Error('session_refused');
      }
      authenticate(deferredPayload);
    }
    return {state: clean ? (aborted ? 'cancelled' : authenticated ? 'authenticated_event' : eventSeen ? (parsed === false ? 'parse_refused' : 'authentication_refused') : 'no_target_event') : 'transport_refused',
      event_seen: eventSeen, event_parsed: parsed, authenticated: clean && authenticated && !aborted,
      observation_timing: {request_started_utc: new Date(requestStartedUtc).toISOString(),
        login_before_utc: new Date(requestStartedUtc+timeoutMs).toISOString(),
        deadline_basis: 'conservative_request_start', observation_timeout_ms: timeoutMs,
        armed_observed_utc: armedTiming?.observed_utc ?? null,
        target_observed_utc: targetObservedUtc ?? null,
        stopped_observed_utc: stoppedTiming?.observed_utc ?? null,
        armed_to_stop_ms: armedTiming && stoppedTiming ? stoppedTiming.request_elapsed_ms-armedTiming.request_elapsed_ms : null,
        login_window_elapsed_at_stop: stoppedTiming ? stoppedTiming.remaining_login_ms === 0 : null},
      observation_stopped: clean, component_unloaded: false, ...finish,
      ...(keyScopeFailure ? {key_scope_failure: keyScopeFailure} : {}),
      failure_code: diagnosticFailure ?? (code !== 0 ? 'loader_exit_nonzero' : !stopped ? 'observation_unconfirmed'
        : pending.length || phase !== 3 ? 'transport_sequence_refused' : aborted ? 'cancelled'
        : !eventSeen ? 'no_target_event' : !authenticated ? 'authentication_refused' : undefined),
      loader_exit_code: Number.isInteger(code)?code:null,
      authentication_scope: clean && authenticated && !aborted ? 'first_page_only' : 'none'};
  } finally {
    clearTimeout(timer); signal?.removeEventListener('abort', abort); header.fill(0); pending.fill(0); deferredPayload?.fill(0);
    child.stdin.destroy();
  }
}
