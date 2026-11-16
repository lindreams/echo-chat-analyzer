"""One offline geometry check: SQLCipher-created fictional 896 MiB input.

Explicit reference executable and NEW local output directory only. Never accepts
account data or a key. No plaintext/fixture remains after successful verification.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


def main():
    reference = Path(sys.argv[1]).resolve(strict=True)
    root = Path(sys.argv[2]).resolve()
    assert hashlib.sha256(reference.with_name("WCDB.dll").read_bytes()).hexdigest() == "c4108e53dbe6749eb4ec2881f6d322eb160a1c5020ac959fb8ffaeac5498ecab"
    root.mkdir(exist_ok=False)
    environment = os.environ.copy()
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        target = root / name
        target.mkdir(); environment[name] = str(target)
    environment.pop("NODE_OPTIONS", None); environment.pop("NODE_PATH", None)
    node = shutil.which("node"); assert node
    reserve80_seed = Path(sys.argv[3]).resolve(strict=True) if len(sys.argv) > 3 else None
    logical, capacity, page = 225957, 3419, 4096
    # One leaf + N overflow pages + database header; use the B-tree reserve,
    # choose minimum local payload so every overflow page is completely used.
    reserve = 80 if reserve80_seed else 48
    usable = page - reserve
    local = (usable - 12) * 32 // 255 - 23
    payload_bytes = (logical - 2) * (usable - 4) + local - 6
    encrypted, wrapped, output = (root / name for name in ("fictional-encrypted.db", "fictional-wrapped.db", "snapshot.db"))
    if reserve80_seed:
        assert reserve80_seed.stat().st_size == 4096 and reserve80_seed.read_bytes()[20] == reserve
        codec = Path(__file__).with_name("qq_independent_codec.mjs").resolve().as_uri()
        program = f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{encode}} from {json.dumps(codec)};
const salt=Buffer.alloc(16,23),key=pbkdf2Sync('echo-fictional-spike-only',salt,4000,32,'sha512');
writeFileSync(process.argv[2],encode(readFileSync(process.argv[1]),key,salt).subarray(1024),{{flag:'wx'}});
"""
        subprocess.run([node, "--input-type=module", "--eval", program, str(reserve80_seed), str(encrypted)],
            env=environment, check=True, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    sql = ["PRAGMA cipher_default_page_size=4096;", "PRAGMA cipher_default_kdf_iter=4000;",
        "PRAGMA cipher_default_hmac_algorithm=HMAC_SHA1;", "PRAGMA cipher_default_kdf_algorithm=PBKDF2_HMAC_SHA512;",
        f"ATTACH DATABASE '{encrypted.as_posix()}' AS fixture KEY 'echo-fictional-spike-only';",
        "PRAGMA fixture.cache_size=-4096;", "CREATE TABLE fixture.payload(body BLOB);",
        f"INSERT INTO fixture.payload VALUES(zeroblob({payload_bytes}));", "PRAGMA fixture.page_count;",
        "PRAGMA fixture.integrity_check;"]
    started = time.monotonic()
    result = subprocess.run([str(reference), str(root / "control.db")], input="\n".join(sql)+"\n",
        env=environment, capture_output=True, encoding="ascii", timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, "fictional reference generation failed"
    assert encrypted.stat().st_size == logical * page, "fixture geometry differs"
    assert "ROW\t6f6b\n" in result.stdout, "reference full integrity did not pass"
    digest = hashlib.sha256()
    with encrypted.open("rb") as source, wrapped.open("xb") as target:
        prefix = b"SQLite header 3\0".ljust(1024, b"\0")
        target.write(prefix); digest.update(prefix)
        while block := source.read(1024*1024):
            target.write(block); digest.update(block)
        for _ in range(capacity):
            block = b"\0" * page; target.write(block); digest.update(block)
    reader = Path(__file__).with_name("qq_full_read.mjs").resolve().as_uri()
    key_scope = Path(__file__).with_name("qq_key_source.mjs").resolve().as_uri()
    program = f"""
import {{openSync,readSync,closeSync}} from 'node:fs';
import assert from 'node:assert/strict';
import {{decryptSnapshot}} from {json.dumps(reader)};
import {{withAuthenticatedKey,PROFILE}} from {json.dumps(key_scope)};
const [input,output,size,sha256]=process.argv.slice(1),fd=openSync(input,'r'),first=Buffer.alloc(5120);
assert.equal(readSync(fd,first,0,5120,0),5120);closeSync(fd);
const started=performance.now(),records=[],secret=Buffer.from('echo-fictional-spike-only');
try {{
 let result;
 const lease=withAuthenticatedKey({{
  acquire(binding) {{return {{kind:'passphrase',material:secret,binding,isCurrent:()=>true}};}},close:()=>true
 }},{{version:'9.9.37-54395',profile:PROFILE,sessionGeneration:'fictional-scale',firstPage:first}},key=>{{
  result=decryptSnapshot({{path:input,output,size:Number(size),sha256}},first,key,
   header=>records.push({{phase:'authenticated_header',...header}}),status=>records.push(status));
 }},{{deadline:started+120000}});
 assert.equal(lease.source_released,true);assert.ok(secret.equals(Buffer.alloc(secret.length)));
 assert.equal(result.decrypted_pages,{logical});assert.equal(result.zero_capacity_pages,{capacity});
 assert.equal(result.physical_pages,{logical+capacity});
 assert.equal(records.find(record=>record.phase==='authenticated_header').reserved_bytes,{reserve});
 console.log(JSON.stringify({{...result,records,key_scope_released:lease.source_released,consumer_elapsed_ms:Math.floor(performance.now()-started),
  peak_rss_bytes:process.resourceUsage().maxRSS*1024}}));
}} finally {{secret.fill(0);first.fill(0);}}
"""
    result = subprocess.run([node, "--max-old-space-size=512", "--input-type=module", "--eval", program,
        str(wrapped), str(output), str(wrapped.stat().st_size), digest.hexdigest()], env=environment,
        capture_output=True, encoding="ascii", timeout=140, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, "fictional large consumer failed"
    receipt = json.loads(result.stdout)
    # Includes both fingerprint passes, decode, writes and finalization. This
    # must fit the OUTER key lease too, not just the decoder's 120s timer.
    assert receipt["consumer_elapsed_ms"] < 120000
    with closing(sqlite3.connect(output.as_uri()+"?mode=ro&immutable=1", uri=True)) as database:
        assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert database.execute("SELECT length(body) FROM payload").fetchall() == [(payload_bytes,)]
    receipt.update(reference_integrity="ok", sqlite_integrity="ok", blob_length_verified=True,
        total_elapsed_ms=int((time.monotonic()-started)*1000), real_qq_accessed=False)
    # Only exact files created by this run; leave receipt + isolated directories
    # for review. On failure retain fixtures locally to avoid destroying evidence.
    for path in (encrypted, wrapped, output, root / "control.db"):
        path.unlink()
    (root / "result.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="ascii")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
