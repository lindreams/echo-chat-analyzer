// Shared by snapshot and bridge in the pinned plugin layout. Callers own the
// existing fixed-field privacy policy; this helper only owns file retention.
import {appendFileSync, renameSync, statSync} from 'node:fs';

const MAX_BYTES = 5 * 1024 * 1024;
const BACKUPS = 3;

export function appendDiagnostic(line) {
  const file = process.env.QCE_LOG_FILE;
  if (!file) return;
  try {
    try {
      const current = statSync(file);
      if (current.isFile() && current.size > 0 &&
          current.size + Buffer.byteLength(line, 'utf8') >= MAX_BYTES) {
        for (let index = BACKUPS - 1; index >= 1; index--) {
          try { renameSync(`${file}.${index}`, `${file}.${index + 1}`); }
          catch (error) { if (error.code !== 'ENOENT') throw error; }
        }
        // Preserve an existing oversized diagnostic intact on the first roll.
        renameSync(file, `${file}.1`);
      }
    } catch {
      // A Windows reader may lock a file. Keep appending and retry later;
      // never unlink/truncate history as a fallback for a failed rename.
    }
    appendFileSync(file, line, 'utf8');
  } catch { /* Diagnostics cannot change acquisition behavior. */ }
}
