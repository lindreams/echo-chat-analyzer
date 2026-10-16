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
    source = tmp_path / 'source' / 'fictional.db'
    source.parent.mkdir()
    source.write_bytes(b'fictional source remains untouched')
    program = f"""
import {{createWorkspace}} from {json.dumps(MODULE)};
import * as fs from 'node:fs';
import * as path from 'node:path';
const root=process.argv[1], w=createWorkspace(root);
await w.acquireLease();w.assertSourceSeparate(process.argv[2]);w.recover();w.createStaging();
for (const name of ['merged.db','snapshot.db','snapshot.db-wal','snapshot.db-shm','snapshot.db-journal'])
  fs.writeFileSync(path.join(root,'staging',name),'fictional plaintext');
console.log('ready');process.stdin.resume();
"""
    process = subprocess.Popen(['node', '--input-type=module', '-e', program, str(root), str(source)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        assert not _run(root, 'workspace.recover();')["ok"]
        assert (root / 'staging/snapshot.db').read_bytes() == b'fictional plaintext'
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
    assert source.read_bytes() == b'fictional source remains untouched'


def test_cleanup_failure_retains_owner_and_blocks_new_stage(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, 'workspace.createStaging();')["ok"]
    unknown = root / 'staging/unknown.db'
    unknown.write_bytes(b'fictional')
    assert not _run(root, 'workspace.recover();workspace.createStaging();')["ok"]
    assert (root / 'staging/owner.json').exists() and unknown.exists()
    unknown.unlink()
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')["ok"]


@pytest.mark.parametrize('location', ['root', 'ancestor', 'staging', 'staging_entry'])
def test_junction_cannot_redirect_cleanup_to_source(tmp_path, location):
    import _winapi

    root = tmp_path / 'root'
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'snapshot.db').write_bytes(b'fictional user file')
    if location in ('staging', 'staging_entry'):
        operation = 'workspace.createStaging();' if location == 'staging_entry' else 'workspace.recover();'
        assert _run(root, operation)['ok']
        junction = root / 'staging'
        if location == 'staging_entry':
            junction = junction / 'snapshot.db'
    else:
        junction = root
        if location == 'ancestor':
            root = junction / 'nested'
    _winapi.CreateJunction(str(target), str(junction))
    try:
        assert not _run(root, 'workspace.recover();')["ok"]
        assert (target / 'snapshot.db').read_bytes() == b'fictional user file'
        assert not (target / 'owner.json').exists()
    finally:
        junction.rmdir()
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')['ok']


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


def test_discard_cleans_every_formal_staging_artifact(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, """
      workspace.createStaging();
      for (const name of ['merged.db','snapshot.db','snapshot.db-wal',
                          'snapshot.db-shm','snapshot.db-journal','manifest.json'])
        fs.writeFileSync(path.join(root,'staging',name),'fictional temporary artifact');
      workspace.discard();
    """)['ok']
    assert not (root / 'staging').exists()


def test_empty_staging_left_before_marker_creation_is_recovered(tmp_path):
    root = tmp_path / 'root'
    assert _run(root, 'workspace.recover();')['ok']
    (root / 'staging').mkdir()
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')['ok']
    assert not (root / 'staging').exists()


@pytest.mark.parametrize('location', ['same_directory', 'workspace_inside_source', 'source_inside_workspace'])
def test_source_overlap_is_rejected_without_modifying_source(tmp_path, location):
    source = tmp_path / 'source' / 'fictional.db'
    if location == 'same_directory':
        root = source.parent
    elif location == 'workspace_inside_source':
        root = source.parent / 'workspace'
    else:
        root = tmp_path / 'source'
        source = root / 'nested' / 'fictional.db'
    source.parent.mkdir(parents=True)
    source.write_bytes(b'fictional user source')
    operation = f'workspace.assertSourceSeparate({json.dumps(str(source))});workspace.recover();workspace.createStaging();'
    assert not _run(root, operation)['ok']
    assert not (root / 'staging').exists()
    assert source.read_bytes() == b'fictional user source'


def test_unknown_root_file_is_preserved_while_owned_stage_is_recovered(tmp_path):
    # Formal cleanup is scoped to validated subdirectories. Unlike the retired
    # PoC it tolerates unrelated root files; they must never become targets.
    root = tmp_path / 'root'
    root.mkdir()
    sentinel = root / 'unowned.db'
    sentinel.write_bytes(b'fictional unrelated file')
    assert _run(root, "workspace.createStaging();fs.writeFileSync(path.join(root,'staging','snapshot.db'),'fictional');workspace.recover();")['ok']
    assert sentinel.read_bytes() == b'fictional unrelated file'
    assert not (root / 'staging').exists()


@pytest.mark.parametrize('location', ['root', 'staging'])
@pytest.mark.parametrize('marker', ['{', '{"kind":"echo-main-wal-poc","version":1}', '{"kind":"echo-qq-snapshot","version":2}'])
def test_invalid_owner_preserves_all_artifacts_until_marker_restored(tmp_path, location, marker):
    root = tmp_path / 'root'
    assert _run(root, "workspace.createStaging();fs.writeFileSync(path.join(root,'staging','snapshot.db'),'fictional plaintext');")['ok']
    owner = (root if location == 'root' else root / 'staging') / 'owner.json'
    original = owner.read_bytes()
    owner.write_text(marker)
    assert not _run(root, 'workspace.recover();workspace.createStaging();')['ok']
    assert owner.read_text() == marker
    assert (root / 'staging/snapshot.db').read_bytes() == b'fictional plaintext'
    owner.write_bytes(original)
    assert _run(root, 'workspace.recover();workspace.createStaging();workspace.discard();')['ok']


@pytest.mark.parametrize('entry', ['snapshot.db', 'main.db', 'main.db-wal', 'nested'])
def test_unowned_or_unknown_staging_member_prevents_any_deletion(tmp_path, entry):
    root = tmp_path / 'root'
    assert _run(root, 'workspace.createStaging();')['ok']
    stage = root / 'staging'
    merged = stage / 'merged.db'
    merged.write_bytes(b'fictional owned artifact')
    unknown = stage / entry
    if entry == 'nested':
        unknown.mkdir()
    else:
        unknown.write_bytes(b'fictional unowned artifact')
    if entry == 'snapshot.db':
        # A familiar filename alone is insufficient proof of ownership.
        (stage / 'owner.json').unlink()
    assert not _run(root, 'workspace.recover();workspace.createStaging();')['ok']
    assert merged.read_bytes() == b'fictional owned artifact'
    if entry == 'nested':
        assert unknown.is_dir()
    else:
        assert unknown.read_bytes() == b'fictional unowned artifact'
