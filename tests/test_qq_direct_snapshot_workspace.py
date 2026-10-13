"""Formal Windows snapshot lease and ownership, with fictional artifacts."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

PROJECT = Path(__file__).parents[1]
MODULE = (PROJECT / 'scripts/qq_direct_db_snapshot/workspace.mjs').as_uri()
pytestmark = pytest.mark.slow_integration


def test_recover_without_powershell_on_path_still_validates_owned_files(tmp_path):
    # Windows PowerShell lives below System32, which need not be on PATH.
    # Resolve Node before restricting PATH so only the lease lookup is tested.
    node = shutil.which('node')
    root = tmp_path / 'fictional 工作区'
    stage = root / 'staging'
    stage.mkdir(parents=True)
    (root / 'owner.json').write_text('{"kind":"echo-qq-snapshot","version":1}')
    (stage / 'owner.json').write_text('{"kind":"echo-qq-snapshot","version":1}')
    (stage / 'snapshot.db').write_bytes(b'fictional plaintext')
    log = tmp_path / 'diagnostic.log'
    environment = {
        **os.environ,
        'PATH': str(Path(os.environ['SystemRoot']) / 'System32'),
        'QCE_LOG_FILE': str(log),
    }
    snapshot = (PROJECT / 'scripts/qq_direct_db_snapshot/snapshot.mjs').as_uri()
    program = f"""
import {{createEchoSnapshotApi}} from {json.dumps(snapshot)};
console.log(JSON.stringify(await createEchoSnapshotApi({{}}, {{rootDirectory:process.argv[1]}}).recover()));
"""

    def recover():
        result = subprocess.run(
            [node, '--input-type=module', '-e', program, str(root)],
            env=environment, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert recover() == {'ok': True, 'status': 'recovered'}
    assert not stage.exists()
    assert 'stage=recover_finished' in log.read_text()

    # Fixing executable discovery must not bypass ownership validation.
    stage.mkdir()
    (stage / 'owner.json').write_text('{"kind":"echo-qq-snapshot","version":1}')
    unknown = stage / 'unknown.txt'
    unknown.write_bytes(b'fictional unrelated file')
    assert recover() == {'ok': False, 'code': 'recover_failed', 'status': 'failed'}
    assert unknown.read_bytes() == b'fictional unrelated file'
    assert 'failure_stage=cleanup guard_code=workspace_invalid' in log.read_text()


def _run(root, operation):
    program = f"""
import {{createWorkspace}} from {json.dumps(MODULE)};
import fs from 'node:fs';
import {{syncBuiltinESMExports}} from 'node:module';
import * as path from 'node:path';
const root=process.argv[1], workspace=createWorkspace(root);
try {{
  await workspace.acquireLease();
  {operation}
  console.log(JSON.stringify({{ok:true}}));
}} catch {{console.log(JSON.stringify({{ok:false}}));}}
finally {{await workspace.release();}}
"""
    result = subprocess.run(['node', '--input-type=module', '-e', program, str(root)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_owned_stage_recovery_and_unknown_stage_preservation(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, "workspace.recover();workspace.createStaging();fs.writeFileSync(path.join(root,'staging','merged.db'),'fictional');")["ok"]
    assert _run(root, 'workspace.recover();')["ok"]
    assert not (root / 'staging').exists()
    stage = root / 'staging'
    stage.mkdir()
    (stage / 'unknown.txt').write_text('fictional user file')
    assert not _run(root, 'workspace.recover();')["ok"]
    assert (stage / 'unknown.txt').read_text() == 'fictional user file'


def test_live_owner_blocks_other_process_and_kill_allows_stale_recovery(tmp_path):
    root = tmp_path / 'root'
    program = f"""
import {{createWorkspace}} from {json.dumps(MODULE)};
import * as fs from 'node:fs';
import * as path from 'node:path';
const root=process.argv[1], w=createWorkspace(root);
await w.acquireLease();w.recover();w.createStaging();
fs.writeFileSync(path.join(root,'staging','snapshot.db'),'fictional plaintext');
console.log('ready');process.stdin.resume();
"""
    process = subprocess.Popen(['node', '--input-type=module', '-e', program, str(root)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        assert not _run(root, 'workspace.recover();')["ok"]
        assert (root / 'staging/snapshot.db').exists()
    finally:
        process.kill()
        process.communicate(timeout=10)
    # The child holding the OS handle exits when its inherited stdin reaches EOF.
    import time
    recovered = False
    for _ in range(5):
        recovered = _run(root, 'workspace.recover();')["ok"]
        if recovered:
            break
        time.sleep(0.1)
    assert recovered
    assert not (root / 'staging').exists()


def test_cleanup_failure_retains_owner_and_blocks_new_stage(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, 'workspace.createStaging();')["ok"]
    unknown = root / 'staging/unknown.db'
    unknown.write_bytes(b'fictional')
    assert not _run(root, 'workspace.recover();workspace.createStaging();')["ok"]
    assert (root / 'staging/owner.json').exists() and unknown.exists()
    unknown.unlink()
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')["ok"]


def test_staging_junction_is_never_followed(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, 'workspace.recover();')["ok"]
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'snapshot.db').write_bytes(b'fictional user file')
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(root / 'staging'), str(target)], capture_output=True)
    assert result.returncode == 0
    try:
        assert not _run(root, 'workspace.recover();')["ok"]
        assert (target / 'snapshot.db').read_bytes() == b'fictional user file'
    finally:
        (root / 'staging').rmdir()


def test_os_delete_failure_keeps_marker_until_successful_recovery(tmp_path):
    import ctypes
    from ctypes import wintypes
    root = tmp_path / 'root'
    assert _run(root, "workspace.createStaging();fs.writeFileSync(path.join(root,'staging','snapshot.db'),'fictional');")["ok"]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(root / 'staging/snapshot.db'), 0x80000000, 1, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    try:
        assert not _run(root, 'workspace.discard();')["ok"]
        assert (root / 'staging/owner.json').exists()
        assert not _run(root, 'workspace.recover();workspace.createStaging();')["ok"]
    finally:
        kernel.CloseHandle(handle)
    assert _run(root, 'workspace.recover();')["ok"]
    assert not (root / 'staging').exists()


def test_generation_cleanup_interrupted_after_manifest_removal_recovers(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, "workspace.createStaging();fs.mkdirSync(path.join(root,'generations'));fs.renameSync(path.join(root,'staging'),path.join(root,'generations','fictional-generation'));")["ok"]
    # The atomic publication retains the stage marker. A kill after deleting
    # manifest but before deleting owner must remain recoverable.
    assert _run(root, 'workspace.recover();')["ok"]
    assert not (root / 'generations').exists()


def test_stage_marker_write_failure_removes_only_its_partial_marker(tmp_path):
    root = tmp_path / 'root'
    result = _run(root, """
      const original=fs.writeFileSync;
      fs.writeFileSync=(target,...args)=>{original(target,'partial marker');throw new Error('fictional write failure');};
      syncBuiltinESMExports();
      workspace.createStaging();
    """
    )
    assert not result['ok']
    assert not (root / 'staging').exists()
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')['ok']
