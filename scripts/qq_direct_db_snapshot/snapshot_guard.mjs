// Read handles prove immutability; TTL and stat telemetry do not.
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {lstatSync, existsSync} from 'node:fs';

const failure = () => Object.assign(new Error('snapshot_guard_failed'), {code: 'workspace_invalid'});
export async function pinSnapshot(directory) {
  if (process.platform !== 'win32') throw failure();
  const database = join(directory, 'snapshot.db'), manifest = join(directory, 'manifest.json');
  const child = spawn(join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
    ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
      fileURLToPath(new URL('./snapshot_guard.ps1', import.meta.url))],
    {windowsHide: true, stdio: ['pipe', 'pipe', 'ignore']});
  child.stdin.on('error', () => {});
  let pending, ended = false;
  const lines = createInterface({input: child.stdout});
  const buffered = [];
  const deliver = value => {
    if (pending) { const next = pending; pending = null; next(value); }
    else buffered.push(value);
  };
  lines.on('line', line => deliver(line.length < 100 ? line : 'failed'));
  const exited = new Promise(resolve => {
    child.once('error', () => { ended = true; deliver('failed'); resolve(); });
    child.once('close', () => { ended = true; deliver('failed'); resolve(); });
  });
  async function next(command) {
    if (ended) throw failure();
    if (command) child.stdin.write(command + '\n');
    if (buffered.length) return buffered.shift();
    let timer;
    try {
      return await new Promise((resolve, reject) => {
        pending = resolve;
        timer = setTimeout(() => { pending = null; reject(failure()); }, 5000);
      });
    } finally { clearTimeout(timer); }
  }
  async function release() {
    child.stdin.end('release\n');
    async function wait(milliseconds) {
      let timer;
      try { return await Promise.race([exited.then(() => true), new Promise(resolve => {
        timer = setTimeout(() => resolve(false), milliseconds);
      })]); }
      finally { clearTimeout(timer); }
    }
    if (!await wait(5000)) {
      child.kill();
      if (!await wait(2000)) throw Object.assign(failure(), {snapshotPin: {release}});
    }
    // Observed exit proves OS handles closed even after an abnormal guard exit.
    lines.close();
  }
  const identity = () => [database, manifest].map(path => {
    const value = lstatSync(path, {bigint: true});
    if (!value.isFile() || value.isSymbolicLink() || value.nlink !== 1n) throw failure();
    return value.ino.toString();
  }).join(':');
  try {
    child.stdin.write(JSON.stringify({database, manifest}) + '\n');
    const pinned = await next();
    if (!/^\d+:\d+$/.test(pinned) || pinned !== identity()) throw failure();
    // An idle retained lease must not keep a stopped Worker alive. Parent exit
    // closes stdin; the helper disposes both file handles on EOF.
    child.unref(); child.stdin.unref(); child.stdout.unref();
    return {
      async check() {
        if (await next('check') !== pinned || identity() !== pinned ||
            ['-wal', '-shm', '-journal'].some(suffix => existsSync(database + suffix))) throw failure();
      },
      release,
    };
  } catch (error) {
    await release();
    throw error;
  }
}
