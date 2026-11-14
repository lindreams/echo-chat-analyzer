"""Focused synthetic acceptance for the independent source interface, not QQ.

Run with the verified Echo interpreter and source path; pass a NEW owned root.
Reuses existing fixture builders, codec, Provider and Adapter, with no account IO.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR"):
        target = root / name
        target.mkdir()
        os.environ[name] = str(target)
    project = Path(__file__).resolve().parents[2]
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
    sys.path.insert(0, str(project / "tests"))
    from qq_db_test_data import synthetic_text_message_blob
    from test_qq_direct_main_wal_poc import _reserve_48_bytes
    from qq_chat_analyzer.application.import_request import ImportRequest
    from qq_chat_analyzer.application.import_service import ImportService
    import qq_windows_source as source_module
    from qq_windows_source import SourceError, WindowsQQSource, doctor

    install = root / "fictional-qq/resources/app"
    install.mkdir(parents=True)
    executable = root / "fictional-qq/QQ.exe"
    executable.write_bytes(b"fictional, never executed")
    (install / "package.json").write_text(json.dumps({"version": "9.9.37-54395", "buildVersion": "54395"}))
    (install / "wrapper.node").write_bytes(b"fictional resource")
    assert doctor(executable)["qq_version"] == "9.9.37-54395"
    work = root / "work"
    work.mkdir()
    original = root / "fixture/nt_msg.db"
    original.parent.mkdir()
    _reserve_48_bytes(original)
    with closing(sqlite3.connect(original)) as database:
        for table in ("c2c_msg_table", "group_msg_table"):
            database.execute(f'''CREATE TABLE {table} (
                "40001" INTEGER PRIMARY KEY,"40027" TEXT,"40030" TEXT,
                "40033" TEXT,"40050" INTEGER,"40800" BLOB)''')
            database.execute(f"INSERT INTO {table} VALUES (1,'17','900000001','100000001',1800000000,?)",
                             (synthetic_text_message_blob("fictional garden"),))
        database.commit()
    source = WindowsQQSource(original.parent, work)
    assert source.locate()[0]["state"] == "plaintext_candidate"

    def refused(code, action):
        try:
            with action():
                raise AssertionError("unexpected connection")
        except SourceError as error:
            assert error.code == code, error.code
        assert not list(work.iterdir()), "owned connection data not cleaned"

    # Create encrypted source once using the existing encoder, not a new codec.
    encrypted = root / "sources/nt_qq_fictional/nt_db/nt_msg.db"
    encrypted.parent.mkdir(parents=True)
    codec = Path(__file__).with_name("qq_independent_codec.mjs").as_uri()
    node = shutil.which("node")
    assert node
    program = f"""
import {{readFileSync,writeFileSync}} from 'node:fs';
import {{pbkdf2Sync}} from 'node:crypto';
import {{encode}} from {json.dumps(codec)};
const salt=Buffer.alloc(16,17);
const key=pbkdf2Sync('fictional-source-only',salt,4000,32,'sha512');
writeFileSync(process.argv[2],encode(readFileSync(process.argv[1]),key,salt),{{flag:'wx'}});
"""
    environment = os.environ.copy()
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    subprocess.run([node, "--input-type=module", "--eval", program, str(original), str(encrypted)],
                   env=environment, capture_output=True, check=True, timeout=30)
    source = WindowsQQSource(root / "sources", work)
    located = source.locate()
    assert len(located) == 1 and located[0]["state"] == "key_required" and not located[0]["authenticated"]
    refused("key_required", lambda: source.connect())
    key = root / "fictional-key.json"
    key.write_text(json.dumps({"kind": "passphrase", "value": "fictional-source-only"}))
    before = hashlib.sha256(encrypted.read_bytes()).hexdigest()
    with source.connect(key_file=key) as provider:
        sessions = provider.list_sessions(self_uin="100000001")
        assert {s.session_type for s in sessions} == {"private", "group"}
        for session in sessions:
            payload = root / f"{session.session_type}.json"
            provider.materialize_session_payload(session, payload, self_uin="100000001")
            imported = ImportService().execute(ImportRequest(input_path=payload, platform="qq"))
            assert len(imported.messages) == 1 and imported.messages[0].text == "fictional garden"
            assert imported.rich_messages[0].is_self is True
    assert not list(work.iterdir())
    assert hashlib.sha256(encrypted.read_bytes()).hexdigest() == before
    key.write_text(json.dumps({"kind": "passphrase", "value": "wrong-fictional-key"}))
    refused("decode_rejected", lambda: source.connect(key_file=key))
    sidecar = Path(str(encrypted) + "-wal")
    sidecar.write_bytes(b"fictional sidecar, never replayed")
    refused("frozen_main_required", lambda: source.connect())
    sidecar.unlink()  # This exact fixture belongs to this script.
    second = root / "sources/nt_qq_second/nt_db/nt_msg.db"
    second.parent.mkdir(parents=True)
    second.write_bytes(encrypted.read_bytes())
    refused("database_selection_required", lambda: source.connect())
    assert len(source.locate()) == 2

    # Host-style layout and active sidecars: inventory must never connect or
    # read beyond database magic, even when main-only connection would refuse.
    host_root = root / "fictional-host"
    host_db = host_root / "123456789/nt_qq/nt_db/nt_msg.db"
    host_db.parent.mkdir(parents=True)
    host_db.write_bytes(encrypted.read_bytes())
    for suffix in ("-wal", "-shm"):
        Path(str(host_db) + suffix).write_bytes(b"fictional sidecar: must not be opened")
    host_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in host_db.parent.iterdir()}
    from unittest.mock import patch
    original_reader = source_module._read_unchanged
    reads = []
    def magic_only(path, *, prefix_bytes=None):
        assert prefix_bytes == 16 and path.name == "nt_msg.db"
        reads.append(prefix_bytes)
        return original_reader(path, prefix_bytes=prefix_bytes)
    original_environment = dict(os.environ)
    with patch.object(source_module, "local_host_locations", return_value=([executable], {"documents_tencent": host_root})), \
            patch.object(source_module, "_read_unchanged", side_effect=magic_only), \
            patch.object(WindowsQQSource, "connect", side_effect=AssertionError("inventory must not connect")):
        host_inventory = source_module.inspect_local_host(work)
    assert dict(os.environ) == original_environment
    assert reads == [16] and not list(work.iterdir())
    observed = host_inventory["data_roots"][0]["databases"][0]
    assert observed["layout"] == "{account}/nt_qq/nt_db/nt_msg.db"
    assert observed["container"] == "qq_wrapped_candidate" and observed["candidate_page_alignment"]
    assert observed["sidecars"]["wal"]["present"] and observed["sidecars"]["shm"]["present"]
    assert observed["connection_readiness"] == "frozen_input_not_proven"
    public_json = json.dumps(host_inventory)
    assert all(private not in public_json for private in (str(root), "123456789", "fictional garden", "fictional-source-only"))
    assert host_before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in host_db.parent.iterdir()}
    if os.name == "nt":
        with patch.object(source_module.os.path, "lexists", side_effect=AssertionError("must reject before filesystem access")):
            refused_network = source_module.inventory([], {"documents_tencent": Path(r"\\fictional-server\private")}, work)
        assert refused_network["data_roots"][0]["state"] == "local_path_required"
        from qq_windows_process_probe import probe_modules
        # Only the Python child we create, never an existing process or QQ.
        child = subprocess.Popen([sys.executable, "-u", "-c",
            "import json,os,sys; print(json.dumps([os.getpid(),sys._base_executable]),flush=True); sys.stdin.read(1)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        try:
            child_pid, child_image = json.loads(child.stdout.readline())
            module = Path(child_image)
            module_probe = probe_modules(child_pid, Path(child_image), module)
            assert module_probe["expected_module_loaded"] and module_probe["process_handle_closed"]
            try:
                probe_modules(child_pid, executable, module)
                raise AssertionError("must refuse wrong executable identity")
            except SourceError as error:
                assert error.code == "process_identity_mismatch"
        finally:
            child.communicate("\n", timeout=5)
        assert child.returncode == 0
    receipt = {"doctor_and_bounded_discovery": "passed", "missing_key": "refused",
               "existing_codec_provider_adapter": "passed", "wrong_key": "refused",
               "sidecars": "refused", "ambiguous_selection": "refused",
               "source_unchanged": True, "temporary_connection_data_cleaned": True,
               "host_inventory_magic_only_and_redaction": "passed",
               "owned_python_child_module_probe": "passed" if os.name == "nt" else "not_run",
               "qq_54395": "not_tested", "real_account_accessed": False}
    (root / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
