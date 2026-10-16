// Local-only Direct DB snapshot lifecycle — runtime-side generation API (Phase 1).
//
// This helper never auto-decrypts and never accesses or serializes the
// passphrase.  It exposes a restricted EchoSnapshotApi with three methods
// (acquire / cleanup / recover) that own the plaintext snapshot lifecycle
// through an explicit generation + atomic-publish scheme:
//
//   <root>/generations/<id>/snapshot.db
//   <root>/generations/<id>/manifest.json
//
// The default <root> mirrors Python's canonical path
// ``runtime_directory.parent / output/qq_direct_db_phase35`` (four parent
// segments up from this file reach ``runtime/``).
//
// Privacy contract: status objects and log lines carry only stable codes,
// fixed stages, timestamps, opaque generation ids, and source-file size/
// change booleans. The identity value (QQ UIN), nicknames, message text, the
// passphrase and absolute paths never appear in a status object, log line or
// exception message.
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { unlinkSync, readFileSync } from 'node:fs';
import { createMergedEncryptedDatabase, finalizeStandaloneSnapshot, captureCodeHash, fileState as strongFileState } from './main_wal.mjs';
import { createWorkspace, workspaceCodeHash } from './workspace.mjs';

const snapshotCodeHash = createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex');
const FAILURE_STAGES = new Set(['source_location', 'workspace_isolation', 'shm_witness',
  'wal_identity', 'wal_header', 'wal_prefix', 'wal_checksum', 'commit_boundary',
  'main_identity', 'main_stability', 'checkpoint_witness', 'cleanup', 'lease', 'input_witness']);
const GUARD_STAGES = Object.freeze({
  source_unavailable: 'source_location', workspace_invalid: 'workspace_isolation',
  wal_replaced: 'wal_identity', wal_header_missing: 'wal_header',
  wal_format_unsupported: 'wal_header', wal_version_unsupported: 'wal_header',
  page_size_unsupported: 'wal_header', wal_header_checksum_invalid: 'wal_header',
  wal_boundary_truncated: 'wal_prefix', wal_boundary_changed: 'wal_prefix',
  wal_page_number_invalid: 'wal_prefix', wal_frame_salt_invalid: 'wal_prefix',
  wal_frame_checksum_invalid: 'wal_checksum', checksum_input_invalid: 'wal_checksum',
  wal_boundary_not_committed: 'commit_boundary', wal_has_no_complete_transaction: 'commit_boundary',
  committed_page_count_invalid: 'commit_boundary', wal_index_boundary_mismatch: 'commit_boundary',
  main_replaced: 'main_identity', main_format_unsupported: 'main_identity',
  main_size_invalid: 'main_identity', main_empty: 'main_identity',
  page_one_salt_mismatch: 'main_identity', new_page_missing_from_wal: 'wal_prefix',
  main_changed_during_read: 'main_stability', checkpoint_state_changed: 'checkpoint_witness',
});
const CONTEXT_GUARDS = new Set(['checkpoint_witness_missing', 'checkpoint_witness_torn',
  'checkpoint_witness_invalid', 'checkpoint_state_invalid', 'short_read',
  'input_witness_invalid_or_changed', 'cleanup_failed', 'lease_failed', 'workspace_busy']);
const FILE_GUARDS = Object.freeze({ ENOENT: 'file_missing', EACCES: 'access_denied',
  EPERM: 'access_denied', EBUSY: 'file_busy', EEXIST: 'output_exists', EIO: 'file_io_failed' });

function traceAcquisitionDiagnostic(stage, error = null, generationId = null, witness = {}, failed = true) {
  try {
    if (!FAILURE_STAGES.has(stage)) return;
    let rawCode;
    try { rawCode = error?.code; } catch { /* A hostile getter is an unknown error. */ }
    const guard = typeof rawCode === 'string' && Object.hasOwn(GUARD_STAGES, rawCode) ? rawCode
      : CONTEXT_GUARDS.has(rawCode) ? rawCode
      : typeof rawCode === 'string' && Object.hasOwn(FILE_GUARDS, rawCode) ? FILE_GUARDS[rawCode]
      : 'unexpected_error';
    const failureStage = guard === 'workspace_invalid' && (stage === 'cleanup' || stage === 'lease')
      ? stage : GUARD_STAGES[guard] ?? stage;
    let fields = failed ? ` failure_stage=${failureStage} guard_code=${guard}` : ` capture_stage=${stage}`;
    for (const name of ['boundary', 'mxFrame', 'nBackfill', 'attempted']) {
      const value = witness[name];
      if (Number.isInteger(value) && value >= 0 && value <= 0xffffffff) fields += ` ${name}=${value}`;
    }
    for (const name of ['headerCopiesMatch', 'wal_index_headers_stable', 'nbackfill_stable',
      'attempted_stable', 'shm_identity_stable', 'dev_equal', 'ino_equal']) {
      if (typeof witness[name] === 'boolean') fields += ` ${name}=${witness[name]}`;
    }
    // Record provenance once at the initial detailed SHM witness, and on every failure.
    if (failed || (stage === 'shm_witness' && typeof witness.shm_identity_stable === 'boolean')) {
      for (const [name, value] of [['node_version', process.version], ['libuv_version', process.versions.uv]]) {
        if (typeof value === 'string' && /^v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(value)) fields += ` ${name}=${value}`;
      }
      fields += ` snapshot_code_hash=${snapshotCodeHash} capture_code_hash=${captureCodeHash} workspace_code_hash=${workspaceCodeHash}`;
    }
    const logFile = process.env.QCE_LOG_FILE;
    if (logFile) appendFileSync(logFile, `[${new Date().toISOString()}] [echo-snapshot] stage=acquisition_diagnostic${generationId ? ` generation_id=${generationId}` : ''}${fields}\n`);
  } catch { /* No diagnostic failure changes acquisition behavior. */ }
}

const SCHEMA_VERSION = 1;
const IDENTITY_NAMESPACE = 'qq_uin';
const DATABASE_NAME = 'snapshot.db';
const MANIFEST_NAME = 'manifest.json';
const SOURCE_DATABASE_NAME = 'nt_msg.db';

const DEFAULT_TIMEOUTS = Object.freeze({
  passphraseMs: 30000,
  identityMs: 30000,
  pollIntervalMs: 250,
});

// Stable, privacy-safe error codes.  These are the only values that may reach
// a status object alongside the opaque generation id.
const CODES = Object.freeze({
  PASSHRASE_UNAVAILABLE: 'passphrase_unavailable',
  DECRYPT_FAILED: 'decrypt_failed',
  SNAPSHOT_UNSTABLE: 'snapshot_unstable',
  IDENTITY_MISSING: 'identity_missing',
  IDENTITY_CHANGED: 'identity_changed',
  MANIFEST_FAILED: 'manifest_failed',
  PUBLISH_FAILED: 'publish_failed',
  CLEANUP_FAILED: 'cleanup_failed',
  GENERATION_NOT_FOUND: 'generation_not_found',
  RECOVER_FAILED: 'recover_failed',
});

const helperDirectory = dirname(fileURLToPath(import.meta.url));
const defaultRoot = resolve(
  helperDirectory,
  '..',
  '..',
  '..',
  '..',
  'output',
  'qq_direct_db_phase35',
);

function canonicalizeUin(value) {
  if (value === null || value === undefined || typeof value === 'boolean') {
    return null;
  }
  let text;
  if (typeof value === 'string') {
    text = value.trim();
  } else if (typeof value === 'number') {
    text = String(value);
  } else {
    return null;
  }
  if (!text || text === '0') {
    return null;
  }
  return text;
}

function fail(code) {
  return { ok: false, code, status: 'failed' };
}

function sleep(milliseconds) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds));
}

function now() {
  return globalThis.performance?.now?.() ?? Date.now();
}
function logDiagnostic(stage) {
  console.error(`qq_direct_db.diagnostic stage=${stage}`);
}

function traceStage(stage, generationId = null) {
  // The launcher already uses this file for timestamped runtime diagnostics.
  // Only fixed stage names are written; a logging failure must not affect data.
  const logFile = process.env.QCE_LOG_FILE;
  if (!logFile) return;
  try {
    const generation = generationId ? ` generation_id=${generationId}` : '';
    appendFileSync(logFile, `[${new Date().toISOString()}] [echo-snapshot] stage=${stage}${generation}\n`);
  } catch {
    // Best-effort diagnostics only.
  }
}

function fileState(path) {
  try {
    const stat = statSync(path);
    return {
      present: stat.isFile(),
      bytes: stat.isFile() ? stat.size : 0,
      mtimeMs: stat.mtimeMs,
    };
  } catch {
    return { present: false, bytes: 0, mtimeMs: 0 };
  }
}

function sourceDatabaseState(databaseApi) {
  try {
    const getDirectory = databaseApi?.getNtDbDir;
    if (typeof getDirectory !== 'function') return null;
    const directory = getDirectory();
    if (typeof directory !== 'string' || !directory) return null;
    const database = join(directory, SOURCE_DATABASE_NAME);
    return {
      database: fileState(database),
      wal: fileState(`${database}-wal`),
      shm: fileState(`${database}-shm`),
    };
  } catch {
    return null;
  }
}

function stateChanged(before, after) {
  return before.present !== after.present ||
    before.bytes !== after.bytes ||
    before.mtimeMs !== after.mtimeMs;
}

function traceSourceDatabaseState(stage, state, before = null, generationId = null) {
  if (!state) return;
  const logFile = process.env.QCE_LOG_FILE;
  if (!logFile) return;
  const changed = before
    ? ` database_changed=${stateChanged(before.database, state.database)}` +
      ` wal_changed=${stateChanged(before.wal, state.wal)}` +
      ` shm_changed=${stateChanged(before.shm, state.shm)}`
    : '';
  const details =
    `generation_id=${generationId} ` +
    `database_present=${state.database.present} database_bytes=${state.database.bytes} ` +
    `wal_present=${state.wal.present} wal_bytes=${state.wal.bytes} ` +
    `shm_present=${state.shm.present} shm_bytes=${state.shm.bytes}`;
  try {
    appendFileSync(
      logFile,
      `[${new Date().toISOString()}] [echo-snapshot] stage=${stage} ${details}${changed}\n`,
    );
  } catch {
    // Best-effort diagnostics only.
  }
}

function traceInputWitness(before, after, generationId) {
  const logFile = process.env.QCE_LOG_FILE;
  if (!logFile) return;
  try {
    appendFileSync(
      logFile,
      `[${new Date().toISOString()}] [echo-snapshot] stage=decrypt_input_witness ` +
      `generation_id=${generationId} ` +
      `before_valid=${before !== null} after_valid=${after !== null} ` +
      `input_changed=${before !== after}\n`,
    );
  } catch {
    // Best-effort diagnostics only.
  }
}

/**
 * Normalize a caller-supplied generation id into a single path segment, or
 * return ``null`` when it cannot be a generation id.  ``cleanup`` must only
 * ever delete ``generations/<id>``, so separators and traversal segments are
 * rejected here rather than ever reaching the filesystem.
 */
function normalizeGenerationId(generationId) {
  let value = generationId;
  if (value && typeof value === 'object') {
    value = value.generation_id ?? value.generationId;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const id = value.trim();
  if (!id || id === '.' || id === '..') {
    return null;
  }
  if (id.includes('/') || id.includes('\\')) {
    return null;
  }
  return id;
}

export function createEchoSnapshotApi(core, options = {}) {
  const {
    rootDirectory = defaultRoot,
    timeouts = {},
    sourceDatabaseName = SOURCE_DATABASE_NAME,
    onCapturePhase = () => {},
  } = options;

  const passphraseMs = timeouts.passphraseMs ?? DEFAULT_TIMEOUTS.passphraseMs;
  const identityMs = timeouts.identityMs ?? DEFAULT_TIMEOUTS.identityMs;
  const pollIntervalMs = timeouts.pollIntervalMs ?? DEFAULT_TIMEOUTS.pollIntervalMs;

  const generationsDirectory = join(rootDirectory, 'generations');
  const stagingDirectory = join(rootDirectory, 'staging');
  const workspace = createWorkspace(rootDirectory);

  // Single-flight mutex: every mutating operation is serialized on one promise
  // chain, so decrypt can never run concurrently (max concurrency = 1).
  let lockTail = Promise.resolve();
  let activeGenerationId = null;
  function withLock(task, releaseOnFailure = false) {
    const guarded = async () => {
      try {
        const result = await task();
        if (!result.ok && releaseOnFailure) await workspace.release();
        return result;
      } catch (error) {
        traceAcquisitionDiagnostic('cleanup', error);
        await workspace.release();
        return fail(CODES.CLEANUP_FAILED);
      }
    };
    const run = lockTail.then(guarded, guarded);
    lockTail = run.then(
      () => {},
      () => {},
    );
    return run;
  }

  async function cleanSlate() {
    let failureStage = 'lease';
    try {
      // Establish the snapshot root first so a broken root is a hard,
      // fail-closed error rather than a silent no-op.
      await workspace.acquireLease();
      failureStage = 'cleanup';
      workspace.recover();
      return { ok: true };
    } catch (error) {
      traceAcquisitionDiagnostic(failureStage, error);
      return { ok: false };
    }
  }

  let databaseApiSeen = false;

  async function waitForDatabaseApi() {
    const deadline = now() + passphraseMs;
    let firstPollRecorded = false;
    let nextProgressTrace = now() + 5000;
    traceStage('passphrase_wait_started');
    while (now() < deadline) {
      const api = core?.apis?.DatabaseApi;
      if (api && typeof api.hasPassphrase === 'function') {
        databaseApiSeen = true;
        try {
          const ready = api.hasPassphrase() === true;
          if (ready) {
            if (!firstPollRecorded) traceStage('passphrase_wait_polled');
            // The DatabaseApi namespace Proxy's unknown-method fallback also
            // exposes a callable `then`. Returning that Proxy directly from an
            // async function makes Promise resolution treat it as a thenable;
            // the fallback ignores resolve/reject, so this wait never settles.
            return { databaseApi: api };
          }
        } catch {
          // Transient read failure; retry within the bounded window.
        }
      }
      if (!firstPollRecorded) {
        traceStage('passphrase_wait_polled');
        firstPollRecorded = true;
      }
      await sleep(pollIntervalMs);
      if (now() >= nextProgressTrace) {
        traceStage('passphrase_wait_tick');
        nextProgressTrace = now() + 5000;
      }
    }
    return null;
  }

  async function waitForIdentity() {
    const deadline = now() + identityMs;
    while (now() < deadline) {
      const value = canonicalizeUin(core?.selfInfo?.uin);
      if (value !== null) {
        return value;
      }
      await sleep(pollIntervalMs);
    }
    return null;
  }

  function discardStaging() {
    try {
      workspace.discard();
      return true;
    } catch (error) {
      traceAcquisitionDiagnostic('cleanup', error);
      return false;
    }
  }

  async function acquire() {
    traceStage('acquire_queued');
    return withLock(async () => {
      traceStage('acquire_entered');
      // 1. Fail-closed cleanup: no decryption may start unless every previous
      //    generation, staging dir and legacy plaintext artifact is gone.
      const slate = await cleanSlate();
      if (!slate.ok) {
        traceStage('slate_failed');
        return fail(CODES.CLEANUP_FAILED);
      }
      traceStage('slate_ready');
      activeGenerationId = null;

      // 2. Bounded wait for the in-process DatabaseApi and its passphrase.
      const databaseApiResult = await waitForDatabaseApi();
      if (!databaseApiResult) {
        traceStage(databaseApiSeen ? 'passphrase_not_ready' : 'database_api_not_ready');
        logDiagnostic(
          databaseApiSeen ? 'passphrase_not_ready' : 'database_api_not_ready',
        );
        return fail(CODES.PASSHRASE_UNAVAILABLE);
      }
      const { databaseApi } = databaseApiResult;
      traceStage('passphrase_ready');

      // 3. Bounded wait for a canonical self identity *before* decryption.
      const identityBefore = await waitForIdentity();
      if (identityBefore === null) {
        traceStage('identity_not_ready');
        logDiagnostic('identity_not_ready');
        return fail(CODES.IDENTITY_MISSING);
      }
      traceStage('identity_ready');

      const generationId = randomUUID();
      const generationDirectory = join(generationsDirectory, generationId);
      const stagingDatabase = join(stagingDirectory, DATABASE_NAME);
      const stagingManifest = join(stagingDirectory, MANIFEST_NAME);
      const stagingMerged = join(stagingDirectory, 'merged.db');

      // 4. Decrypt into a staging generation on the same filesystem.
      try {
        workspace.createStaging();
      } catch {
        logDiagnostic('publish_failed');
        return fail(discardStaging() ? CODES.PUBLISH_FAILED : CODES.CLEANUP_FAILED);
      }

      // The hardened capture fixes B and verifies SHM, main and the complete
      // WAL prefix. NapCat only receives the validated, owned merged image.
      let failureStage = 'source_location';
      let captureWitness = {};
      let capturedPages;
      try {
        const directory = databaseApi.getNtDbDir();
        if (typeof directory !== 'string' || !directory) {
          const error = new Error('source_unavailable'); error.code = 'source_unavailable'; throw error;
        }
        const mainPath = join(directory, sourceDatabaseName);
        failureStage = 'workspace_isolation';
        workspace.assertSourceSeparate(mainPath);
        failureStage = 'shm_witness';
        const capture = createMergedEncryptedDatabase({
          mainPath, walPath: `${mainPath}-wal`, outputPath: stagingMerged,
          onPhase: onCapturePhase,
          onDiagnostic: ({ failureStage: stage, ...witness }) => {
            failureStage = stage;
            captureWitness = witness;
            traceAcquisitionDiagnostic(stage, null, generationId, witness, false);
          },
        });
        capturedPages = capture.pages;
        traceStage('main_wal_boundary_verified', generationId);
        traceStage('main_wal_capture_complete', generationId);
      } catch (error) {
        traceAcquisitionDiagnostic(failureStage, error, generationId, captureWitness);
        const cleaned = discardStaging();
        traceStage('snapshot_unstable', generationId);
        return fail(cleaned ? CODES.SNAPSHOT_UNSTABLE : CODES.CLEANUP_FAILED);
      }

      let decrypted = false;
      const sourceStateBefore = sourceDatabaseState(databaseApi);
      traceSourceDatabaseState('decrypt_source_before', sourceStateBefore, null, generationId);
      const inputBefore = strongFileState(stagingMerged);
      if (inputBefore === null) {
        traceInputWitness(inputBefore, null, generationId);
        traceAcquisitionDiagnostic('input_witness', { code: 'input_witness_invalid_or_changed' }, generationId);
        const cleaned = discardStaging();
        traceStage('snapshot_unstable', generationId);
        return fail(cleaned ? CODES.SNAPSHOT_UNSTABLE : CODES.CLEANUP_FAILED);
      }
      traceStage('decrypt_started');
      try {
        decrypted = Boolean(
          await databaseApi.decryptDatabase(stagingMerged, stagingDatabase),
        );
      } catch {
        decrypted = false;
      }
      const inputAfter = strongFileState(stagingMerged);
      traceStage('decrypt_finished');
      try { workspace.assertLease(); }
      catch (error) { traceAcquisitionDiagnostic('lease', error, generationId); return fail(CODES.CLEANUP_FAILED); }
      traceInputWitness(inputBefore, inputAfter, generationId);
      traceSourceDatabaseState(
        'decrypt_source_after',
        sourceDatabaseState(databaseApi),
        sourceStateBefore,
        generationId,
      );
      // 5. The owned staging merge must stay stable across decryption. Invalid
      // witnesses never establish stability, including null on both sides.
      if (inputAfter === null || inputBefore !== inputAfter) {
        traceAcquisitionDiagnostic('input_witness', { code: 'input_witness_invalid_or_changed' }, generationId);
        const cleaned = discardStaging();
        traceStage('snapshot_unstable', generationId);
        return fail(cleaned ? CODES.SNAPSHOT_UNSTABLE : CODES.CLEANUP_FAILED);
      }

      if (!decrypted || !existsSync(stagingDatabase)) {
        const cleaned = discardStaging();
        logDiagnostic('decrypt_failed');
        return fail(cleaned ? CODES.DECRYPT_FAILED : CODES.CLEANUP_FAILED);
      }

      // Decryption has returned, the independently captured input stayed fixed,
      // and our workspace lease excludes another producer/consumer. Finalize
      // only this staging output before the generation becomes visible.
      try { finalizeStandaloneSnapshot(stagingDatabase, capturedPages); }
      catch {
        logDiagnostic('decrypt_failed');
        return fail(discardStaging() ? CODES.DECRYPT_FAILED : CODES.CLEANUP_FAILED);
      }

      // No encrypted intermediate may enter a published generation.
      try { unlinkSync(stagingMerged); }
      catch { discardStaging(); return fail(CODES.CLEANUP_FAILED); }

      // 6. The canonical self identity must still exist and be unchanged.
      const identityAfter = canonicalizeUin(core?.selfInfo?.uin);
      if (identityAfter === null) {
        return fail(discardStaging() ? CODES.IDENTITY_MISSING : CODES.CLEANUP_FAILED);
      }
      if (identityAfter !== identityBefore) {
        return fail(discardStaging() ? CODES.IDENTITY_CHANGED : CODES.CLEANUP_FAILED);
      }

      // 7. Manifest and database belong to the same generation.  The identity
      //    value is written to disk only and never logged or returned.
      const manifest = {
        schema_version: SCHEMA_VERSION,
        generation_id: generationId,
        state: 'ready',
        database: DATABASE_NAME,
        identity: {
          namespace: IDENTITY_NAMESPACE,
          value: identityAfter,
        },
      };
      try {
        writeFileSync(stagingManifest, JSON.stringify(manifest, null, 2), 'utf8');
      } catch {
        return fail(discardStaging() ? CODES.MANIFEST_FAILED : CODES.CLEANUP_FAILED);
      }

      // 8. Atomic publish: rename the complete staging directory into place.
      try {
        mkdirSync(generationsDirectory, { recursive: true });
        renameSync(stagingDirectory, generationDirectory);
      } catch {
        const cleaned = discardStaging();
        logDiagnostic('publish_failed');
        return fail(cleaned ? CODES.PUBLISH_FAILED : CODES.CLEANUP_FAILED);
      }

      traceStage('generation_ready', generationId);
      activeGenerationId = generationId;

      return { ok: true, generation_id: generationId, status: 'ready' };
    }, true);
  }

  async function cleanup(generationId) {
    return withLock(async () => {
      const id = normalizeGenerationId(generationId);
      if (id === null) {
        return fail(CODES.GENERATION_NOT_FOUND);
      }
      const directory = join(generationsDirectory, id);
      // An unrelated cleanup request cannot release a consumer's root lease.
      if (activeGenerationId !== null && id !== activeGenerationId) {
        return fail(CODES.GENERATION_NOT_FOUND);
      }
      try {
        await workspace.acquireLease();
        if (!existsSync(directory)) {
          return fail(CODES.GENERATION_NOT_FOUND);
        }
        workspace.cleanup(id);
        activeGenerationId = null;
        return { ok: true, status: 'cleaned' };
      } catch {
        return fail(CODES.CLEANUP_FAILED);
      } finally {
        await workspace.release();
      }
    });
  }

  async function recover() {
    traceStage('recover_queued');
    return withLock(async () => {
      traceStage('recover_entered');
      const slate = await cleanSlate();
      if (slate.ok) activeGenerationId = null;
      await workspace.release();
      if (!slate.ok) {
        traceStage('recover_failed');
        return fail(CODES.RECOVER_FAILED);
      }
      traceStage('recover_finished');
      return { ok: true, status: 'recovered' };
    });
  }

  return { acquire, cleanup, recover };
}

export function registerEchoSnapshotApi(runtimeCore, options = {}) {
  const api = createEchoSnapshotApi(runtimeCore, options);
  if (runtimeCore && typeof runtimeCore === 'object') {
    if (!runtimeCore.apis || typeof runtimeCore.apis !== 'object') {
      runtimeCore.apis = {};
    }
    runtimeCore.apis.EchoSnapshotApi = api;
  }
  return api;
}
