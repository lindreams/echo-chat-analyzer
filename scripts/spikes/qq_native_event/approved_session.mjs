// No command-line paths or automatic discovery. An approved Python caller sends
// explicit selection + encrypted prefix over stdin, then may send one STOP byte.
import {connectOnce} from './connect.mjs';
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
      page = Buffer.from(input.subarray(4+n)); input.fill(0);
      const result = await connectOnce({...request, firstPage: page, signal: abort.signal,
        onStatus(state) { console.log(JSON.stringify({phase: state})); }});
      console.log(JSON.stringify({phase: 'result', ...result}));
    } catch { console.log('{"phase":"result","state":"session_refused","authenticated":false}'); process.exitCode = 2; }
    finally { page?.fill(0); input.fill(0); process.stdin.destroy(); }
  })();
});
process.stdin.on('end', () => { if (started) abort.abort(); else { input.fill(0); process.exitCode = 2; } });
process.stdin.on('error', () => abort.abort());
process.on('beforeExit', () => { if (!run) input.fill(0); });
