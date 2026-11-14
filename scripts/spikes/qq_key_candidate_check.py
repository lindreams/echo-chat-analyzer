"""Focused acceptance for the candidate tool. Only our new Python child.

Keys are random, held in memory/anonymous pipes, never fixture files or output.
This checks candidate capture, admission, MAC binding and cleanup, not decode.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from unittest.mock import patch


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        path = root / name
        path.mkdir()
        os.environ[name] = str(path)
    import qq_chat_analyzer
    project = Path(__file__).resolve().parents[2]
    assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
    from qq_windows_source import SourceError
    from qq_windows_process_probe import verified_process, process_creation_ticks, probe_modules
    import qq_key_candidate as tool
    from qq_chat_analyzer.runtime import windows_job

    work = root / "work"
    work.mkdir()
    db = root / "fixture/nt_msg.db"
    db.parent.mkdir()
    key, salt = os.urandom(32), os.urandom(16)
    node = shutil.which("node")
    assert node
    codec = Path(__file__).with_name("qq_independent_codec.mjs").as_uri()
    environment = os.environ.copy()
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    program = r"""
import {readFileSync} from 'node:fs';
import {encode} from CODEC;
const record=JSON.parse(readFileSync(0,'utf8'));
const plain=Buffer.alloc(4096); plain.write('SQLite format 3\0');
plain.writeUInt16BE(4096,16); plain[20]=48; plain.writeUInt32BE(1,28);
console.log(encode(plain,Buffer.from(record.key,'hex'),Buffer.from(record.salt,'hex')).toString('base64'));
""".replace("CODEC", json.dumps(codec))
    encoded = subprocess.run([node, "--input-type=module", "--eval", program],
        input=json.dumps({"key": key.hex(), "salt": salt.hex()}), capture_output=True,
        text=True, timeout=5, check=True, env=environment)
    db.write_bytes(base64.b64decode(encoded.stdout))
    child_code = r'''
import ctypes as C,json,os,sys
from ctypes import wintypes as W
record=json.loads(sys.stdin.readline())
api=C.WinDLL('kernel32',use_last_error=True)
api.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,W.DWORD,W.DWORD]; api.VirtualAlloc.restype=C.c_void_p
api.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,W.DWORD]; api.VirtualFree.restype=W.BOOL
address=api.VirtualAlloc(None,8192,0x3000,0x04)
if not address: raise RuntimeError('fixture allocation failed')
buffer=(C.c_ubyte*8192).from_address(address)
try:
 wrong=("x'"+'00'*32+record['salt']+"'").encode()
 valid=("x'"+record['key']+record['salt']+"'").encode()
 C.memmove(address+32,wrong,len(wrong))
 C.memmove(address+4080,valid,len(valid))
 print(json.dumps({'pid':os.getpid(),'image':sys._base_executable,'address':address}),flush=True)
 sys.stdin.read(1)
finally:
 C.memset(address,0,8192)
 if not api.VirtualFree(address,0,0x8000): raise RuntimeError('fixture release failed')
'''
    child = subprocess.Popen([sys.executable, "-u", "-c", child_code], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=environment)
    checks = []
    try:
        child.stdin.write(json.dumps({"key": key.hex(), "salt": salt.hex()}) + "\n")
        child.stdin.flush()
        owned = json.loads(child.stdout.readline())
        image = Path(owned["image"])
        with verified_process(owned["pid"], image) as (native, handle):
            created = process_creation_ticks(native, handle)
        assert probe_modules(owned["pid"], image, image)["process_handle_closed"]
        spec = {"pid": owned["pid"], "created_ticks": created, "executable": str(image),
                "module": str(image), "database": str(db), "window": {
                    "address": owned["address"], "size": 8192, "evidence": "owned_fixture"}}

        def refused(code, action):
            try:
                action()
                raise AssertionError("unexpected admission")
            except SourceError as error:
                assert error.code == code, error.code
            assert not list(work.iterdir())
            checks.append(code)

        with patch.object(tool, "verified_process", side_effect=AssertionError("must not open any process")):
            refused("bounded_key_context_missing", lambda: tool.run(dict(spec, window=None), work, approved=True, fixture=True))
            refused("window_limit", lambda: tool.run(dict(spec, window=dict(spec["window"], size=65537)), work, approved=True, fixture=True))
            assert tool.run(spec, work, fixture=True)["state"] == "planned"
        matched = tool.run(spec, work, approved=True, fixture=True)
        assert matched["state"] == "matched" and matched["candidates_tested"] == 2 and matched["authenticated_candidates"] == 1
        assert matched["memory_bytes_read"] == 8192 and matched["owned_worker_tree_released"]
        assert child.poll() is None and not list(work.iterdir())
        checks.append("capture_across_chunk_boundary_and_database_authentication")
        refused("process_generation_changed", lambda: tool.run(dict(spec, created_ticks=created+1), work, approved=True, fixture=True))
        original = db.read_bytes()
        damaged = bytearray(original)
        damaged[1200] ^= 1
        db.write_bytes(damaged)
        rejected = tool.run(spec, work, approved=True, fixture=True)
        assert rejected["state"] == "not_matched" and rejected["authenticated_candidates"] == 0
        assert rejected["owned_worker_tree_released"] and not list(work.iterdir())
        db.write_bytes(original)
        checks.append("same_salt_is_not_authentication")
        # Cancel AFTER native creation, so cleanup must release a real owned Job.
        event = threading.Event()
        launched = []
        launcher = windows_job.launch_owned_process
        def cancel_after_launch(*args, **kwargs):
            process = launcher(*args, **kwargs)
            launched.append(process)
            event.set()
            return process
        with patch.object(windows_job, "launch_owned_process", side_effect=cancel_after_launch):
            refused("cancelled", lambda: tool.run(spec, work, approved=True, fixture=True, cancel_event=event))
        assert launched and all(p.exit_verified and p.closed for p in launched)
        with patch.object(tool, "HARD_SECONDS", 0):
            refused("deadline_reached", lambda: tool.run(spec, work, approved=True, fixture=True))
        assert child.poll() is None
        public = json.dumps(matched)
        assert all(secret not in public for secret in (key.hex(), salt.hex(), str(image), str(db), str(owned["address"])))
        # Inspect only our fixture files: no candidate or raw-key artifact exists.
        for path in root.rglob("*"):
            if path.is_file():
                assert key.hex().encode() not in path.read_bytes()
    finally:
        child.communicate("\n", timeout=5)
    assert child.returncode == 0
    receipt = {"checks": checks, "real_qq_business_memory_accessed": False,
               "key_material_persisted": False, "qq_54395": "not_tested"}
    (root / "result.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
