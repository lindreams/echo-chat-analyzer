"""Research only: WCDB/SQLCipher <-> independent Node codec, fictional input only.

Run with the explicit Echo venv. Arguments: locally compiled reference.exe,
then a NEW output directory. No account discovery, account input or key reader.
"""
from __future__ import annotations

import hashlib
import ctypes
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


def main() -> None:
    reference = Path(sys.argv[1]).resolve(strict=True)
    root = Path(sys.argv[2]).resolve()
    reserve = int(sys.argv[3]) if len(sys.argv) > 3 else 48
    assert reserve in (48, 80)
    root.mkdir(parents=True, exist_ok=False)
    expected_dll = "c4108e53dbe6749eb4ec2881f6d322eb160a1c5020ac959fb8ffaeac5498ecab"
    assert hashlib.sha256(reference.with_name("WCDB.dll").read_bytes()).hexdigest() == expected_dll
    environment = os.environ.copy()
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        target = root / "isolated" / name
        target.mkdir(parents=True)
        environment[name] = str(target)
    environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    node = shutil.which("node")
    assert node
    codec = Path(__file__).with_name("qq_independent_codec.mjs").resolve().as_uri()
    counter = 0
    defaults = [
        "PRAGMA cipher_default_page_size=4096;",
        "PRAGMA cipher_default_kdf_iter=4000;",
        "PRAGMA cipher_default_hmac_algorithm=HMAC_SHA1;",
        "PRAGMA cipher_default_kdf_algorithm=PBKDF2_HMAC_SHA512;",
    ]

    def native(sql: list[str], *, success: bool = True, integrity_failure: bool = False) -> list[list[list[str]]]:
        nonlocal counter
        counter += 1
        result = subprocess.run(
            [str(reference), str(root / f"control-{counter}.db")],
            input="\n".join(sql) + "\n", encoding="utf-8", env=environment,
            capture_output=True, timeout=30,
        )
        if not success:
            assert result.returncode in (4, 5), "expected an explicit reference SQL failure"
            assert result.stderr.strip().startswith(("prepare_failed ", "step_failed "))
            return []
        if integrity_failure and result.returncode != 0:
            assert result.returncode in (4, 5), "reference process failure is not an integrity result"
            assert result.stderr.strip().startswith(("prepare_failed ", "step_failed "))
            return []
        assert result.returncode == 0, result.stderr
        statements, rows = [], []
        for line in result.stdout.splitlines():
            if line.startswith("ROW\t"):
                rows.append([bytes.fromhex(cell).decode("utf-8") for cell in line.split("\t")[1:]])
            elif line.startswith("END "):
                assert int(line[4:]) == len(statements) + 1
                statements.append(rows)
                rows = []
        assert len(statements) == len(sql) and not rows
        if integrity_failure:
            assert statements[-1] and statements[-1] != [["ok"]]
        return statements

    def attach(path: Path, key: str = "echo-fictional-spike-only") -> str:
        return f"ATTACH DATABASE '{path.as_posix()}' AS fixture KEY '{key}';"

    def javascript(program: str, *args: Path | str) -> str:
        result = subprocess.run(
            [node, "--input-type=module", "--eval", program, *(str(a) for a in args)],
            env=environment, capture_output=True, encoding="utf-8", timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    # SQLCipher itself creates every encrypted byte; no independent encoder here.
    encrypted = root / "reference-encrypted.db"
    if reserve == 80:
        # Bootstrap only an empty, one-page SQLite database with a larger
        # B-tree reserve. SQLCipher then creates the schema and ALL data pages;
        # its write rewrites page one too. No patched populated page geometry.
        seed = root / "empty-reserve80.sqlite"
        library = ctypes.CDLL("sqlite3.dll")  # Loaded by the explicit Python's sqlite3.
        library.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        library.sqlite3_file_control.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        library.sqlite3_exec.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        library.sqlite3_close.argtypes = [ctypes.c_void_p]
        connection = ctypes.c_void_p()
        assert library.sqlite3_open(os.fsencode(seed), ctypes.byref(connection)) == 0
        try:
            reserved = ctypes.c_int(reserve)
            assert library.sqlite3_file_control(connection, b"main", 38, ctypes.byref(reserved)) == 0
            assert library.sqlite3_exec(connection, b"PRAGMA page_size=4096; VACUUM;", None, None, None) == 0
        finally:
            assert library.sqlite3_close(connection) == 0
        assert seed.stat().st_size == 4096 and seed.read_bytes()[20] == reserve
        javascript(f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{encode}} from {json.dumps(codec)};
const salt=Buffer.alloc(16,23),key=pbkdf2Sync('echo-fictional-spike-only',salt,4000,32,'sha512');
writeFileSync(process.argv[2],encode(readFileSync(process.argv[1]),key,salt).subarray(1024),{{flag:'wx'}});
""", seed, encrypted)
        seed_ciphertext = encrypted.read_bytes()
    records = [(i, f"fictional-{i}-\u865a\u6784-\U0001f680" + "x" * 350, bytes([i]) * 700) for i in range(1, 25)]
    inserts = [f"INSERT INTO fixture.entries VALUES({i},CAST(X'{body.encode().hex()}' AS TEXT),X'{blob.hex()}');"
               for i, body, blob in records]
    settings = ["PRAGMA cipher_version;", "PRAGMA fixture.cipher_page_size;",
                "PRAGMA fixture.kdf_iter;", "PRAGMA fixture.cipher_hmac_algorithm;",
                "PRAGMA fixture.cipher_kdf_algorithm;", "PRAGMA fixture.cipher_use_hmac;"]
    rows_query = "SELECT id,hex(body),hex(payload) FROM fixture.entries ORDER BY id;"
    result = native(defaults + [attach(encrypted), "CREATE TABLE fixture.entries(id INTEGER PRIMARY KEY,body TEXT,payload BLOB);",
                               "BEGIN;"] + inserts + ["COMMIT;"] + settings +
                    ["PRAGMA fixture.integrity_check;", rows_query])
    actual_settings = [row[0][0] for row in result[-8:-2]]
    assert actual_settings[0] == "4.1.0 community"
    assert actual_settings[1:] == ["4096", "4000", "HMAC_SHA1", "PBKDF2_HMAC_SHA512", "1"]
    assert result[-2] == [["ok"]]
    expected = [[str(i), body.encode().hex().upper(), blob.hex().upper()] for i, body, blob in records]
    assert result[-1] == expected
    if reserve == 80:
        assert encrypted.read_bytes()[:4096] != seed_ciphertext
    wrapped = root / "synthetic-wrapped.db"
    wrapped.write_bytes(b"SQLite header 3\0".ljust(1024, b"\0") + encrypted.read_bytes())
    plain = root / "decoded.sqlite"
    decode = f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{decode}} from {json.dumps(codec)};
const [input,output,mode='correct']=process.argv.slice(1);
const bytes=readFileSync(input),salt=bytes.subarray(1024,1040);
const key=pbkdf2Sync(mode==='wrong-key'?'incorrect':'echo-fictional-spike-only',salt,4000,32,'sha512');
try {{
 const plain=decode(bytes,key,salt,mode==='wrong-hmac'?'sha512':'sha1');
 writeFileSync(output,plain,{{flag:'wx'}}); console.log('accepted');
}} catch(error) {{ console.log(error.message); }}
"""
    assert javascript(decode, wrapped, plain) == "accepted"
    pages = encrypted.stat().st_size // 4096
    assert pages > 2 and plain.read_bytes()[20] == reserve
    with closing(sqlite3.connect(plain.as_uri() + "?mode=ro", uri=True)) as database:
        assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert database.execute("SELECT * FROM entries ORDER BY id").fetchall() == records

    # The extra SQLite reserve is still ciphertext under the SHA1 codec.
    # Moving the IV to page_size-80, or skipping these bytes in MAC input,
    # must never become an accidental alternate authentication profile.
    if reserve == 80:
        for offset in (4016, 4048, 4064):  # Encrypted reserve, IV, HMAC.
            damaged = bytearray(wrapped.read_bytes())
            damaged[1024 + 4096 + offset] ^= 1
            path = root / f"damaged-footer-{offset}.db"
            path.write_bytes(damaged)
            assert javascript(decode, path, root / f"footer-{offset}.sqlite") == "page_hmac_mismatch"
            path.write_bytes(damaged[1024:])
            native(defaults + [attach(path), "PRAGMA fixture.integrity_check;"], integrity_failure=True)

    # The actual large QQ copy has an all-zero suffix. Prove the narrow
    # capacity rule against SQLCipher itself; this is not a damaged-page bypass.
    capacity = root / "reference-zero-capacity.db"
    capacity_pages = 3419  # Match the observed suffix length and cross the bounded-read batches.
    capacity.write_bytes(encrypted.read_bytes() + b"\0" * (capacity_pages * 4096))
    assert native(defaults + [attach(capacity), "PRAGMA fixture.integrity_check;", rows_query])[-2:] == [[["ok"]], expected]
    capacity_wrapped = root / "wrapped-zero-capacity.db"
    capacity_wrapped.write_bytes(b"SQLite header 3\0".ljust(1024, b"\0") + capacity.read_bytes())
    consumer = Path(__file__).with_name("qq_full_read.mjs").resolve().as_uri()
    assert javascript(f"""
import {{readFileSync,writeFileSync,existsSync}} from 'node:fs';
import {{pbkdf2Sync,createHash}} from 'node:crypto';
import assert from 'node:assert/strict';
import {{decryptSnapshot}} from {json.dumps(consumer)};
import {{decode}} from {json.dumps(codec)};
const [input,expected]=process.argv.slice(1), bytes=readFileSync(input), prefix=bytes.subarray(0,5120);
const key=pbkdf2Sync('echo-fictional-spike-only',bytes.subarray(1024,1040),4000,32,'sha512');
const selection=(path,output,data)=>({{path,output,size:data.length,sha256:createHash('sha256').update(data).digest('hex')}});
assert.throws(()=>decode(bytes,key),/page_hmac_mismatch/); // Default remains strict.
const output=input+'.sqlite'; let header;
const result=decryptSnapshot(selection(input,output,bytes),prefix,key,value=>{{header=value;}});
assert.equal(result.zero_capacity_pages,{capacity_pages}); assert.equal(result.decrypted_pages,header.header_pages);
assert.equal(result.physical_pages,header.header_pages+{capacity_pages}); assert.equal(header.header_counters_current,true);
assert.equal(header.freelist_first_trunk,readFileSync(expected).readUInt32BE(32));
assert.equal(header.freelist_pages,readFileSync(expected).readUInt32BE(36));
assert.equal(header.page_size,4096);assert.equal(header.reserved_bytes,{reserve});
assert.equal(header.write_version,readFileSync(expected)[18]);assert.equal(header.read_version,readFileSync(expected)[19]);
assert.ok(readFileSync(output).equals(readFileSync(expected)));
for (const kind of ['logical_corruption','zero_logical_page','nonzero_tail']) {{
 const damaged=Buffer.from(bytes);
 if (kind==='zero_logical_page') damaged.fill(0,1024+4096,1024+2*4096);
 else damaged[kind==='logical_corruption'?1024+4096+100:damaged.length-1]^=1;
 const path=input+'.'+kind, destination=path+'.sqlite';writeFileSync(path,damaged,{{flag:'wx'}});
 assert.throws(()=>decryptSnapshot(selection(path,destination,damaged),prefix,key),error=>{{
   assert.equal(error.stage,kind==='nonzero_tail'?'capacity_validation':'page_authentication');assert.equal(error.authenticatedPages,1);
   assert.ok(Number.isSafeInteger(error.elapsedMs) && error.elapsedMs>=0);
   if (kind==='nonzero_tail') return error.message==='nonzero_capacity_tail';
   assert.equal(error.page,2); assert.equal(error.pageAllZero,kind==='zero_logical_page');
   return error.message==='page_hmac_mismatch';
 }});
 assert.equal(existsSync(destination),false);
}}
key.fill(0);console.log('zero_capacity_and_refusals_passed');
""", capacity_wrapped, plain) == "zero_capacity_and_refusals_passed"
    with closing(sqlite3.connect(Path(str(capacity_wrapped) + ".sqlite").as_uri() + "?mode=ro", uri=True)) as database:
        assert database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]

    # Independently encrypted output is then consumed by the real SQLCipher engine.
    reverse = root / "node-encrypted.db"
    javascript(f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{encode}} from {json.dumps(codec)};
const salt=Buffer.from('00112233445566778899aabbccddeeff','hex');
const key=pbkdf2Sync('echo-fictional-spike-only',salt,4000,32,'sha512');
writeFileSync(process.argv[2],encode(readFileSync(process.argv[1]),key,salt).subarray(1024),{{flag:'wx'}});
""", plain, reverse)
    back = native(defaults + [attach(reverse), "PRAGMA fixture.integrity_check;", rows_query])
    assert back[-2:] == [[["ok"]], expected]
    raw = hashlib.pbkdf2_hmac("sha512", b"echo-fictional-spike-only", bytes.fromhex("00112233445566778899aabbccddeeff"), 4000, 32)
    raw_attach = f'''ATTACH DATABASE '{reverse.as_posix()}' AS fixture KEY "x'{raw.hex()}00112233445566778899aabbccddeeff'";'''
    assert native(defaults + [raw_attach, rows_query])[-1] == expected
    native(defaults + [attach(encrypted, "incorrect"), rows_query], success=False)
    native([*defaults, "PRAGMA cipher_default_kdf_iter=4001;", attach(encrypted), rows_query], success=False)
    for mode, reason in [("wrong-key", "page_hmac_mismatch"), ("wrong-hmac", "page_hmac_mismatch")]:
        out = root / f"{mode}.sqlite"
        assert javascript(decode, wrapped, out, mode) == reason and not out.exists()
    for page in range(pages):
        damaged = bytearray(wrapped.read_bytes())
        damaged[1024 + page * 4096 + 100] ^= 1
        path = root / f"damaged-page-{page + 1}.db"
        path.write_bytes(damaged)
        out = root / f"rejected-page-{page + 1}.sqlite"
        assert javascript(decode, path, out) == "page_hmac_mismatch" and not out.exists()
        # Reference checks the same corruption, including all non-schema pages.
        path.write_bytes(damaged[1024:])
        if page == 0:
            native(defaults + [attach(path), rows_query], success=False)
        else:
            native(defaults + [attach(path), "PRAGMA fixture.integrity_check;"], integrity_failure=True)
    truncated = root / "partial-page.db"
    truncated.write_bytes(wrapped.read_bytes()[:-1])
    assert javascript(decode, truncated, root / "partial-page.sqlite") == "invalid_size"
    # Page HMAC alone cannot detect missing pages. Refuse the authenticated
    # header/file-size mismatch before publishing; retain the SQLite check too.
    missing = root / "missing-page.db"
    missing.write_bytes(wrapped.read_bytes()[:-4096])
    missing_plain = root / "missing-page.sqlite"
    assert javascript(decode, missing, missing_plain) == "page_count_mismatch"
    assert not missing_plain.exists()
    sqlite_missing = root / "sqlite-missing-page.sqlite"
    sqlite_missing.write_bytes(plain.read_bytes()[:-4096])
    try:
        with closing(sqlite3.connect(sqlite_missing.as_uri() + "?mode=ro", uri=True)) as database:
            valid = database.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    except sqlite3.DatabaseError:
        valid = False
    assert not valid
    # An authenticated but stale page count cannot establish completeness.
    javascript(f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{encode,decode}} from {json.dumps(codec)};
const plain=readFileSync(process.argv[1]),salt=Buffer.alloc(16,17);
const key=pbkdf2Sync('echo-fictional-spike-only',salt,4000,32,'sha512');
plain.writeUInt32BE((plain.readUInt32BE(24)^1)>>>0,92);
const wrapped=encode(plain,key,salt);
    for (const capacity of [false,true]) {{
     try {{ decode(wrapped,key,salt,'sha1',()=>{{}},{{allowZeroCapacity:capacity}}); throw new Error('stale header accepted'); }}
     catch(error) {{ if(error.message!=='untrusted_page_count') throw error; }}
    }}
""", plain)
    receipt = {"reference": actual_settings, "sqlite_reserved_bytes": reserve, "cipher_footer_bytes": 48, "wcdb_sha256": expected_dll,
               "node_version": subprocess.check_output([node, "--version"], env=environment, text=True).strip(),
               "sqlite_version": sqlite3.sqlite_version, "pages": pages, "records": len(records),
               "sqlcipher_to_node_to_sqlite": "passed", "node_to_sqlcipher": "passed",
               "raw_key_plus_salt": "passed",
               "all_pages_corruption_rejected_by_both": True,
               "wrong_key_and_profile_rejected": True, "partial_page_rejected": True,
               "whole_page_truncation": "codec rejects before output; standard SQLite also rejects",
               "untrusted_page_count": "rejected",
               "authenticated_zero_capacity": "reference SQLCipher accepts; independent output identical; SQLite integrity ok",
               "capacity_does_not_hide_logical_corruption_or_nonzero_tail": True,
               "zero_logical_page_rejected_with_exact_coordinate": True,
               "qq_54395": "not_tested"}
    (root / "result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
