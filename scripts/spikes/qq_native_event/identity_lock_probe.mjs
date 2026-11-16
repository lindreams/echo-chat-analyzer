// Metadata-only research caller of the existing guard/witness, never a snapshot.
import { acquireSourceGuard } from '../../qq_direct_db_snapshot/source_guard.mjs';
import { checkpointWitness } from '../../qq_direct_db_snapshot/main_wal.mjs';

let input = '', guard, result = { phase: 'lock_probe', locks_acquired: false,
  witness_valid: false, released: false, database_content_read: false };
process.stdin.setEncoding('utf8');
try {
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 16384) throw new Error('request_limit');
  }
  const request = JSON.parse(input); input = '';
  if (Object.keys(request).sort().join(',') !== 'main,wal' || request.wal !== request.main + '-wal') throw new Error('request_invalid');
  const signal = AbortSignal.timeout(10000);
  guard = await acquireSourceGuard(request.main, request.wal, { signal, deadline: performance.now()+8000 });
  result.locks_acquired = true;
  const witness = await checkpointWitness(request.main, () => {}, guard.readWitness);
  result.witness_valid = true;
  result.committed_boundary_present = witness.boundary > 0;
} catch (error) {
  const allowed = new Set(['source_guard_failed', 'checkpoint_witness_missing', 'checkpoint_witness_torn',
    'checkpoint_witness_invalid', 'checkpoint_state_invalid', 'short_read']);
  result.refusal = allowed.has(error?.code) ? error.code : 'lock_or_witness_unavailable';
}
finally {
  if (guard) {
    try { await guard.release(); result.released = true; }
    catch { result.refusal = 'source_release_unconfirmed'; }
  }
}
console.log(JSON.stringify(result));
process.exitCode = result.locks_acquired && result.witness_valid && result.released ? 0 : 1;
