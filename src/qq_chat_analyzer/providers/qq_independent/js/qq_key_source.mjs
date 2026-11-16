// Research contract only. No real QQ provider, process access, files or network.
// Sources and consumers must be trusted, synchronous and bounded. A future
// native provider needs its own approved worker/Job and hard cancellation.
import {createHash, pbkdf2Sync} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {authenticateFirstPage} from './qq_independent_codec.mjs';

export const PROFILE = 'ntqq-sha1-4096-kdf4000';
const used = new WeakSet();
export class KeySourceError extends Error {
  constructor(code) { super(code); this.code = code; }
}
const refuse = code => { throw new KeySourceError(code); };
const synchronous = value => {
  if (value && typeof value.then === 'function') refuse('async_source_unsupported');
  return value;
};

/**
 * source.acquire(binding, control) -> {kind, material: Buffer, binding,
 *                                    isCurrent(): boolean}
 * source.close() -> true, including partially failed acquisition.
 *
 * binding = {version, sessionGeneration, profile, databaseFingerprint}.
 * Provider MUST independently establish that binding; echoing this request is
 * not evidence of provenance. Authentication proves page/key agreement only.
 * Material ownership transfers to this call. No secret may be cached/logged.
 * consume(raw32, withDatabaseKey) is scoped to this synchronous call.
 * withDatabaseKey(firstPage, consumeDatabase) authenticates a separately salted
 * DB using this same passphrase lease; it never returns raw material. Raw-key
 * leases cannot derive other DB keys. All calls share the original deadline.
 */
export function withAuthenticatedKey(source, request, consume = () => {}, {
  signal, deadline = performance.now() + 1000, now = () => performance.now(),
} = {}) {
  if (!source) refuse('trusted_source_unavailable');
  if (typeof source.acquire !== 'function' || typeof source.close !== 'function') refuse('invalid_source');
  if (used.has(source)) refuse('source_already_used');
  used.add(source); // No retry or concurrent/reentrant acquisition of this source.
  let lease, page, raw, consuming = false;
  const guard = () => {
    if (signal?.aborted) refuse('cancelled');
    const current = now();
    if (!Number.isFinite(deadline) || !Number.isFinite(current) || current >= deadline) refuse('deadline_reached');
  };
  try {
    guard();
    if (request?.version !== '9.9.37-54395' || request.profile !== PROFILE ||
        typeof request.sessionGeneration !== 'string' || !request.sessionGeneration.length ||
        request.sessionGeneration.length > 128 || typeof consume !== 'function' ||
        !Buffer.isBuffer(request.firstPage) || request.firstPage.length !== 5120 ||
        !request.firstPage.subarray(0, 16).equals(Buffer.from('SQLite header 3\0'))) refuse('invalid_request');
    page = Buffer.from(request.firstPage); // Freeze the observed input, no filesystem access.
    const binding = Object.freeze({version: request.version, profile: request.profile,
      sessionGeneration: request.sessionGeneration,
      databaseFingerprint: createHash('sha256').update(page).digest('hex')});
    lease = synchronous(source.acquire(binding, Object.freeze({signal, deadline, check: guard})));
    guard();
    if (!lease || !Buffer.isBuffer(lease.material) ||
        !['raw', 'passphrase'].includes(lease.kind) ||
        (lease.kind === 'raw' ? lease.material.length !== 32 :
          lease.material.length < 1 || lease.material.length > 4096) ||
        typeof lease.isCurrent !== 'function') refuse('invalid_key_material');
    if (!lease.binding || Object.keys(binding).some(k => lease.binding[k] !== binding[k])) refuse('source_binding_mismatch');
    if (synchronous(lease.isCurrent()) !== true) refuse('source_expired');
    // Same already-verified profile as qq_windows_source; no decoder changes.
    raw = lease.kind === 'raw' ? Buffer.from(lease.material) :
      pbkdf2Sync(lease.material, page.subarray(1024, 1040), 4000, 32, 'sha512');
    if (!authenticateFirstPage(page, raw)) refuse('key_not_authenticated');
    guard();
    if (synchronous(lease.isCurrent()) !== true) refuse('source_expired');
    const withDatabaseKey = (firstPage, consumeDatabase) => {
      if (!consuming) refuse('source_expired');
      guard();
      if (lease.kind !== 'passphrase') refuse('passphrase_required');
      if (synchronous(lease.isCurrent()) !== true) refuse('source_expired');
      // Reuse the same derivation, page binding, MAC and finally-wipe contract.
      // Only a child lease copy crosses into it; the event material stays here.
      return withAuthenticatedKey({
        acquire(binding) {
          return {kind: 'passphrase', material: Buffer.from(lease.material), binding,
            isCurrent: () => consuming && synchronous(lease.isCurrent()) === true};
        },
        close() { return true; },
      }, {...request, firstPage}, consumeDatabase, {signal, deadline, now});
    };
    consuming = true;
    try { synchronous(consume(raw, withDatabaseKey)); }
    finally { consuming = false; }
    guard();
    if (synchronous(lease.isCurrent()) !== true) refuse('source_expired');
    return {state: 'authenticated', scope: 'first_page_only', source_released: true};
  } catch (error) {
    // Never relay provider/consumer errors, which could contain credentials.
    if (error instanceof KeySourceError) throw error;
    refuse('key_source_failed');
  } finally {
    consuming = false;
    raw?.fill(0);
    page?.fill(0);
    if (Buffer.isBuffer(lease?.material)) lease.material.fill(0);
    try {
      if (synchronous(source.close()) !== true) refuse('source_cleanup_failed');
    } catch { refuse('source_cleanup_failed'); }
  }
}
