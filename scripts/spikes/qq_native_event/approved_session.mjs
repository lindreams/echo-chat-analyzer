// No command-line paths or automatic discovery. An approved Python caller sends
// explicit selection + encrypted prefix over stdin, then may send one STOP byte.
import {connectOnce} from './connect.mjs';
import {decryptSnapshot, decryptMetadataSnapshots, snapshotFailureReceipt} from '../qq_full_read.mjs';
import {writeSync} from 'node:fs';
const report = value => {
  const bytes = Buffer.from(JSON.stringify(value)+'\n');
  let at = 0;
  while (at < bytes.length) {
    const n = writeSync(1, bytes, at, bytes.length-at);
    if (!n) throw Error('status_pipe_closed');
    at += n;
  }
};
let input = Buffer.alloc(0), page, started = false, total = 0;
const abort = new AbortController();
let run;
process.on('SIGINT', () => abort.abort());
process.stdin.on('data', chunk => {
  if (started) { chunk.fill(0); abort.abort(); return; }
  total += chunk.length;
  if (total > 131072+5124) { chunk.fill(0); abort.abort(); process.exitCode = 2; process.stdin.destroy(); return; }
  const previous = input; input = Buffer.concat([input, chunk]); previous.fill(0); chunk.fill(0);
  if (input.length < 4) return;
  const n = input.readUInt32LE(0);
  if (!n || n > 131072) { input.fill(0); process.exitCode = 2; process.stdin.destroy(); return; }
  if (input.length < 4+n+5120) return;
  started = true;
  run = (async () => {
    try {
      const request = JSON.parse(input.subarray(4, 4+n).toString('utf8'));
      if (request.target.mode !== 'approved-qq' || input.length !== 4+n+5120) throw Error('selection_refused');
      request.target.created = BigInt(request.target.created);
      if (request.metadata && (request.snapshot || !Array.isArray(request.metadata) || request.metadata.length !== 2 ||
          request.metadata.some((item, index) => item.role !== ['group_info', 'profile_info'][index]))) throw Error('selection_refused');
      page = Buffer.from(input.subarray(4+n)); input.fill(0);
      let full, metadataResults;
      const result = await connectOnce({...request, firstPage: page, signal: abort.signal,
        consumerTimeoutMs: request.snapshot || request.metadata ? 120000 : 1000,
        consumeAuthenticatedKey: request.metadata ? (_anchorKey, withDatabaseKey) => {
          report({phase: 'authentication', event_seen: true, event_parsed: true, first_page_authenticated: true});
          metadataResults = decryptMetadataSnapshots(request.metadata, withDatabaseKey, report);
        } : request.snapshot ? key => {
          full = {first_page_authenticated: true, all_pages_authenticated: false};
          report({phase: 'authentication', event_seen: true, event_parsed: true, first_page_authenticated: true});
          try {
            Object.assign(full, decryptSnapshot(request.snapshot, page, key,
              header => report({phase: 'authenticated_header', ...header}), report));
            report({phase: 'decryption', ...full});
          }
          catch (error) {
            Object.assign(full, snapshotFailureReceipt(error));
            // Persist before the scoped-key wrapper deliberately suppresses
            // consumer exceptions; a later result/identity failure cannot erase it.
            report({phase: 'snapshot_failure', ...full});
            throw error;
          }
        } : undefined,
        onStatus(state, timing) { report({phase: state, ...timing}); }});
      report({phase: 'result', ...result, ...(request.snapshot ? {full_snapshot: full ?? {first_page_authenticated: false}} : {}),
        ...(request.metadata ? {metadata_snapshots: metadataResults ?? []} : {})});
    } catch { report({phase: 'result', state: 'session_refused', authenticated: false}); process.exitCode = 2; }
    finally { page?.fill(0); input.fill(0); process.stdin.destroy(); }
  })();
});
process.stdin.on('end', () => { if (started) abort.abort(); else { input.fill(0); process.exitCode = 2; } });
process.stdin.on('error', () => abort.abort());
process.on('beforeExit', () => { if (!run) input.fill(0); });
