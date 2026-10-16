// Formal snapshot ownership and Windows OS lease. The lease spans capture,
// publication and consumption; kernel handle closure permits stale recovery.
import { spawn } from 'node:child_process';
import { closeSync, existsSync, lstatSync, mkdirSync, openSync, readFileSync, readdirSync, rmdirSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createHash } from 'node:crypto';

export const workspaceCodeHash = createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex');

const OWNER = { kind: 'echo-qq-snapshot', version: 1 };
const FILES = new Set(['owner.json', 'merged.db', 'snapshot.db', 'manifest.json',
  'snapshot.db-wal', 'snapshot.db-shm', 'snapshot.db-journal']);

function busy() { const error = new Error('workspace_busy'); error.code = 'workspace_busy'; return error; }
function reject() { const error = new Error('workspace_invalid'); error.code = 'workspace_invalid'; throw error; }
function noLinks(path) {
  for (let current = resolve(path); ; current = dirname(current)) {
    try { if (lstatSync(current).isSymbolicLink()) reject(); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (dirname(current) === current) break;
  }
}
function owner(path) {
  noLinks(path);
  return JSON.stringify(JSON.parse(readFileSync(path, 'utf8'))) === JSON.stringify(OWNER);
}

export function createWorkspace(rootDirectory) {
  const root = resolve(rootDirectory);
  const staging = join(root, 'staging');
  const generations = join(root, 'generations');
  let lease = null;

  async function acquireLease() {
    noLinks(root);
    mkdirSync(root, { recursive: true });
    noLinks(join(root, 'lease.lock'));
    if (lease) {
      if (lease.exitCode === null && lease.signalCode === null && !lease.killed) return;
      await release();
    }
    // A fixed program receives the path only through the environment. No shell
    // interpolation, PID liveness guessing or persistent lock-file deletion.
    const command = "$ErrorActionPreference='Stop'; try { $f=[IO.File]::Open($env:ECHO_SNAPSHOT_LEASE,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); [Console]::WriteLine('ready'); [Console]::Out.Flush(); [Console]::In.ReadLine() | Out-Null; $f.Dispose() } catch { exit 1 }";
    // Windows PowerShell is an OS component; a desktop launcher's PATH need
    // not include its nested directory. Resolve it independently of PATH.
    const powershell = join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    const child = spawn(powershell, ['-NoProfile', '-NonInteractive', '-Command', command], {
      windowsHide: true, stdio: ['pipe', 'pipe', 'ignore'],
      env: { ...process.env, ECHO_SNAPSHOT_LEASE: join(root, 'lease.lock') },
    });
    // Keep ownership even if readiness times out. A kill request is not proof
    // that the OS handle has closed, and a retry must not race this child.
    lease = child;
    child.stdin.on('error', () => {});
    try {
      await new Promise((done, failed) => {
        const timer = setTimeout(() => failed(busy()), 5000);
        let received = '';
        child.once('error', () => { clearTimeout(timer); failed(busy()); });
        child.once('exit', () => { clearTimeout(timer); failed(busy()); });
        child.stdout.on('data', bytes => {
          received += bytes.toString();
          if (received.trim() === 'ready') { clearTimeout(timer); done(); }
        });
      });
    } catch (error) {
      await release();
      throw error;
    }
    child.unref(); child.stdin.unref(); child.stdout.unref();
    const marker = join(root, 'owner.json');
    if (existsSync(marker)) { if (!owner(marker)) reject(); }
    else writeFileSync(marker, JSON.stringify(OWNER), { flag: 'wx', mode: 0o600 });
  }

  async function release() {
    const child = lease;
    if (!child) return;
    if (child.pid !== undefined && child.exitCode === null && child.signalCode === null) {
      await new Promise((done, failed) => {
        let timer = setTimeout(() => {
          try { child.kill(); }
          catch { failed(busy()); return; }
          // Retain ownership and fail closed if even termination has no exit
          // evidence. A later release may finish; no new holder can bypass it.
          timer = setTimeout(() => failed(busy()), 2000);
        }, 2000);
        child.once('exit', () => { clearTimeout(timer); done(); });
        child.stdin.end('\n');
      });
    }
    if (lease === child) lease = null;
  }

  function validateDirectory(directory, kind, generationId) {
    noLinks(directory);
    if (!existsSync(directory)) return [];
    if (!lstatSync(directory).isDirectory()) reject();
    const entries = readdirSync(directory);
    if (!entries.length) return [];
    if (kind === 'staging') {
      if (!owner(join(directory, 'owner.json'))) reject();
    } else if (kind === 'generation' && existsSync(join(directory, 'owner.json'))) {
      // A kill during cleanup can leave only the marker after manifest removal.
      if (!owner(join(directory, 'owner.json'))) reject();
    } else if (kind === 'generation') {
      const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
      if (manifest.schema_version !== 1 || manifest.generation_id !== generationId ||
          manifest.state !== 'ready' || manifest.database !== 'snapshot.db' ||
          manifest.identity?.namespace !== 'qq_uin' || typeof manifest.identity.value !== 'string') reject();
    }
    for (const name of entries) {
      const path = join(directory, name);
      noLinks(path);
      if (!lstatSync(path).isFile()) reject();
      if (kind === 'legacy') {
        if (name !== 'self_identity.json' && !/^nt_msg\.[a-zA-Z0-9_-]+\.plaintext\.db(?:-(?:wal|shm|journal))?$/.test(name)) reject();
      } else if (!FILES.has(name) || (kind === 'generation' && name === 'merged.db')) reject();
    }
    return entries;
  }

  function removeDirectory(directory, entries) {
    if (!existsSync(directory)) return;
    // Keep proof of ownership until all data is gone, including on a kill.
    for (const name of entries) if (name !== 'owner.json' && name !== 'manifest.json') unlinkSync(join(directory, name));
    for (const name of ['manifest.json', 'owner.json']) if (entries.includes(name)) unlinkSync(join(directory, name));
    rmdirSync(directory);
  }

  function recover() {
    const plans = [[staging, validateDirectory(staging, 'staging')]];
    noLinks(generations);
    if (existsSync(generations)) {
      if (!lstatSync(generations).isDirectory()) reject();
      for (const id of readdirSync(generations)) {
        const dir = join(generations, id);
        plans.push([dir, validateDirectory(dir, 'generation', id)]);
      }
    }
    const legacy = join(root, 'decrypted');
    plans.push([legacy, validateDirectory(legacy, 'legacy')]);
    // Validate everything before deleting anything.
    for (const [dir, entries] of plans) removeDirectory(dir, entries);
    if (existsSync(generations)) rmdirSync(generations);
  }

  function createStaging() {
    mkdirSync(staging);
    const marker = join(staging, 'owner.json');
    let fd = null;
    let ownedMarker = false;
    try {
      fd = openSync(marker, 'wx', 0o600);
      ownedMarker = true;
      writeFileSync(fd, JSON.stringify(OWNER));
      closeSync(fd); fd = null;
    } catch (error) {
      if (fd !== null) { try { closeSync(fd); } catch {} }
      if (ownedMarker) unlinkSync(marker);
      if (!readdirSync(staging).length) rmdirSync(staging);
      throw error;
    }
  }
  function discard() { removeDirectory(staging, validateDirectory(staging, 'staging')); }
  function cleanup(id) {
    const dir = join(generations, id);
    if (!existsSync(dir)) return false;
    removeDirectory(dir, validateDirectory(dir, 'generation', id));
    return true;
  }
  function assertSourceSeparate(source) {
    noLinks(source);
    // Windows case aliases must not bypass source/workspace isolation.
    const comparisonPath = path => process.platform === 'win32' ? path.toLowerCase() : path;
    const directory = comparisonPath(resolve(dirname(source)));
    const workspace = comparisonPath(root);
    const sourcePath = comparisonPath(resolve(source));
    if (workspace === directory || workspace.startsWith(directory + '\\') ||
        workspace.startsWith(directory + '/') || sourcePath.startsWith(workspace + '\\') ||
        sourcePath.startsWith(workspace + '/')) reject();
  }
  function assertLease() {
    if (!lease || lease.exitCode !== null || lease.signalCode !== null || lease.killed) reject();
  }
  return { acquireLease, release, recover, createStaging, discard, cleanup, assertSourceSeparate, assertLease };
}
