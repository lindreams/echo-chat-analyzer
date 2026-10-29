"""Only synthetic data under pytest's isolated directory; no live installation."""
import json
import os
from pathlib import Path
import sys

import pytest

from qq_chat_analyzer.application.uninstall_data import cleanup_local_data, CleanupIncomplete

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows handle cleanup')


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


@pytest.fixture
def data(tmp_path):
    root = tmp_path / 'Echo-data'
    put(root, 'config/wechat.json', {'data_root': str(tmp_path / 'external-wechat'),
                                    'db_key': 'fictional-secret', 'future_secret': 'secret'})
    put(root, 'config/qq.json', {'runtime_directory': str(tmp_path / 'custom-qq'),
                                'runtime_mode': 'custom', 'napcat_bridge_url': 'credential-url'})
    put(root, 'logs/echo.log', 'fictional log')
    put(root, 'update-check.json', {'last_check': 1})
    put(root, 'reports/Echo_Report_20260101_120000/echo-report.html', 'fictional report')
    put(root, 'transient/chat-analyzer-output-aabbccdd/plaintext.txt', 'fictional temporary')
    put(tmp_path, 'external-wechat/original.db', 'untouched')
    put(tmp_path, 'custom-qq/cache.json', 'untouched')
    return root


@pytest.mark.parametrize('purge', [False, True])
def test_both_choices_clear_sensitive_data_and_protect_external_files(data, purge):
    cleanup_local_data(data, purge=purge)
    assert not list((data / 'logs').glob('*'))
    assert not (data / 'update-check.json').exists()
    assert not list((data / 'transient').glob('*'))
    assert (data.parent / 'external-wechat/original.db').read_text() == '"untouched"'
    assert (data.parent / 'custom-qq/cache.json').read_text() == '"untouched"'
    assert (data / 'reports/Echo_Report_20260101_120000/echo-report.html').exists() is not purge
    if not purge:
        assert json.loads((data / 'config/wechat.json').read_text()) == {
            'data_root': str(data.parent / 'external-wechat')}
        assert json.loads((data / 'config/qq.json').read_text()) == {
            'runtime_directory': str(data.parent / 'custom-qq'), 'runtime_mode': 'custom'}
    cleanup_local_data(data, purge=purge)  # Retry after completion is inert.


def legacy_snapshot(root, source='qq'):
    identifier = '12345678-1234-4234-8234-123456789abc'
    directory = root / 'data/snapshots' / source / identifier
    payload = put(directory, 'export.json', 'fictional old export')
    manifest = put(directory, 'manifest.json', {
        'id': identifier, 'source': source, 'session_id': 'fictional-session',
        'session_name': 'Fictional', 'session_type': 'private',
        'acquired_at': '2026-08-12T00:00:00+00:00', 'capture_scope': 'all_available',
        'coverage_start': None, 'coverage_end': None, 'message_count': 1,
        'data_size_bytes': payload.stat().st_size, 'storage_format': 'qce_json',
        'storage_path': payload.relative_to(root).as_posix(), 'payload_state': 'available',
    })
    return directory, manifest


@pytest.mark.parametrize('purge', [False, True])
def test_old_version_data_uses_the_same_explicit_uninstall_choice(data, purge):
    from qq_chat_analyzer.application.qq.qq_auth_bridge import SNAPSHOT_DIAGNOSTIC_FILENAME
    legacy_snapshot(data)
    legacy_snapshot(data, 'wechat')
    backup = put(data, 'config/qq.json.bak', {
        'runtime_directory': str(data.parent / 'custom-qq'), 'qce_path': 'old-helper',
        'security_path': 'old-secret-path', 'base_url': 'old-credential-url',
    })
    put(data, 'config/wechat.json.test-backup', {'data_root': 'external', 'db_key': 'fictional-key'})
    put(data, 'runtime/qq/.qce-config/security.json', {'accessToken': 'fictional-token'})
    put(data, 'logs/desktop.log.1', 'fictional old desktop log')
    put(data, 'logs/' + SNAPSHOT_DIAGNOSTIC_FILENAME, 'fictional snapshot diagnostic')
    history = put(data, 'history/analysis_history.jsonl', {'analysis_id': 'fictional-history'})
    put(data, 'diagnostics/qq-snapshot-20261009-104309.log', 'fictional diagnostic')
    put(data, 'diagnostics/release-logs-20261008-223112/echo.log', 'fictional archived log')
    (data / 'validation').mkdir()
    outside = put(data.parent, 'LocalChatAnalyzer_backup/config/wechat.json', {'db_key': 'manual-copy'})

    cleanup_local_data(data, purge=purge)

    assert not (data / 'data').exists() and not (data / 'diagnostics').exists()
    assert not (data / 'validation').exists()
    assert not (data / 'runtime/qq/.qce-config').exists()
    assert not list((data / 'logs').glob('*'))
    assert outside.exists()  # A sibling/manual copy is not an application-owned root.
    if purge:
        assert not history.exists() and not backup.exists()
    else:
        assert history.exists()
        assert json.loads(backup.read_text()) == {'runtime_directory': str(data.parent / 'custom-qq')}
        assert json.loads((data / 'config/wechat.json.test-backup').read_text()) == {'data_root': 'external'}
    cleanup_local_data(data, purge=purge)


@pytest.mark.parametrize('damage', ['escape', 'unknown_snapshot', 'unknown_legacy', 'backup_link'])
def test_old_version_cleanup_refuses_unproven_assets(data, damage):
    directory, manifest = legacy_snapshot(data)
    outside = put(data.parent, 'unrelated/original.json', {'private': 'keep'})
    if damage == 'escape':
        proof = json.loads(manifest.read_text())
        proof['storage_path'] = '../unrelated/original.json'
        manifest.write_text(json.dumps(proof))
    elif damage == 'unknown_snapshot':
        put(directory, 'unrelated.txt', 'keep')
    elif damage == 'unknown_legacy':
        put(data, 'validation/unrecognized.json', {'private': 'keep'})
    else:
        os.link(outside, data / 'config/qq.json.bak')
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=True)
    assert outside.read_text() == '{"private": "keep"}'
    assert manifest.exists()


def test_interrupted_legacy_snapshot_cleanup_keeps_its_recovery_proof(data, monkeypatch):
    from qq_chat_analyzer.application import uninstall_data as module
    directory, manifest = legacy_snapshot(data)
    original = module._Object.remove
    def fail_payload(item):
        if item.path == directory / 'export.json':
            raise OSError('fictional sharing violation')
        original(item)
    monkeypatch.setattr(module._Object, 'remove', fail_payload)
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=False)
    assert manifest.exists()
    monkeypatch.setattr(module._Object, 'remove', original)
    cleanup_local_data(data, purge=False)
    assert not directory.exists()


def test_staged_old_snapshot_is_cleaned_without_reading_its_chat_payload(data):
    directory, _ = legacy_snapshot(data)
    staging = data / 'data/snapshots/.staging' / directory.name
    staging.parent.mkdir()
    directory.rename(staging)
    cleanup_local_data(data, purge=False)
    assert not staging.exists()


def test_log_filename_does_not_authorize_deleting_a_directory(data):
    outside = put(data, 'logs/desktop.log/unrecognized.txt', 'keep')
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=True)
    assert outside.exists()


def test_owned_runtime_and_crash_snapshot_are_cleaned_without_connecting(data):
    from qq_chat_analyzer.application.qq.qq_runtime_workspace import _proof
    root = data / 'runtime/qq'
    component = 'a' * 64
    directory = root / component
    directory.mkdir(parents=True)
    marker = put(root, component + '.owner.json', {})
    marker.write_text(json.dumps(_proof(root, directory, marker, component)))
    put(directory, 'config/credential.json', {'key': 'fictional'})
    snapshot = data / 'transient/qq-direct-db'
    put(snapshot, 'owner.json', {'kind': 'echo-qq-snapshot', 'version': 1})
    put(snapshot, 'lease.lock', '')
    put(snapshot, 'staging/owner.json', {'kind': 'echo-qq-snapshot', 'version': 1})
    put(snapshot, 'staging/snapshot.db', 'fictional plaintext')
    cleanup_local_data(data, purge=False)
    assert list(root.iterdir()) == []
    assert not snapshot.exists()


def test_unknown_runtime_and_unknown_root_file_are_retained(data):
    unknown = put(data, 'runtime/qq/unknown/private.txt', 'keep')
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=True)
    assert unknown.read_text() == '"keep"'


def test_unknown_root_file_prevents_a_false_cleanup_success(data):
    unknown = put(data, 'unrecognized.json', {'key': 'fictional unknown'})
    before = (data / 'config/wechat.json').read_bytes()
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=False)
    assert unknown.exists() and (data / 'config/wechat.json').read_bytes() == before


def test_hardlinked_settings_never_modify_external_target(data):
    config = data / 'config/wechat.json'
    outside = data.parent / 'external-config.json'
    config.rename(outside)
    os.link(outside, config)
    before = outside.read_bytes()
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=False)
    assert outside.read_bytes() == before


@pytest.mark.slow_integration
def test_junction_in_cleanup_tree_never_deletes_external_target(data):
    import subprocess
    link = data / 'transient/chat-analyzer-output-12345678'
    outside = data.parent / 'external-wechat'
    result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
    assert result.returncode == 0
    try:
        with pytest.raises(CleanupIncomplete):
            cleanup_local_data(data, purge=True)
        assert (outside / 'original.db').read_text() == '"untouched"'
    finally:
        os.rmdir(link)


def test_partial_failure_keeps_snapshot_proof_for_retry(data, monkeypatch):
    from qq_chat_analyzer.application import uninstall_data as module
    snapshot = data / 'transient/qq-direct-db'
    for name in ('owner.json', 'staging/owner.json'):
        put(snapshot, name, {'kind': 'echo-qq-snapshot', 'version': 1})
    put(snapshot, 'lease.lock', '')
    put(snapshot, 'staging/snapshot.db', 'fictional plaintext')
    original = module._Object.remove
    def fail(item):
        if item.path.name == 'snapshot.db':
            raise OSError('fictional locked database')
        original(item)
    monkeypatch.setattr(module._Object, 'remove', fail)
    with pytest.raises(CleanupIncomplete):
        cleanup_local_data(data, purge=False)
    assert (snapshot / 'staging/owner.json').exists()
    monkeypatch.setattr(module._Object, 'remove', original)
    cleanup_local_data(data, purge=False)
    assert not snapshot.exists()


def test_crashed_report_publication_reuses_identity_proof_and_cleans_media(data):
    from qq_chat_analyzer.application.report_staging import _identity
    root = data / 'reports'
    staging = root / ('.echo-report-' + 'c' * 32)
    staging.mkdir()
    marker = put(root, staging.name + '.owner.json', {})
    marker.write_text(json.dumps({'schema': 'echo-report-staging.v1', 'staging': staging.name,
        'root_identity': _identity(root.stat()), 'directory_identity': _identity(staging.stat()),
        'marker_identity': _identity(marker.stat())}))
    put(staging, 'echo-report.html', 'fictional temporary report')
    put(staging, 'media/' + 'a' * 64 + '.png', 'fictional asset')
    cleanup_local_data(data, purge=False)
    assert not staging.exists() and not marker.exists()
    assert (root / 'Echo_Report_20260101_120000').exists()


def test_directory_replacement_is_denied_while_cleanup_pins_ancestors(data, monkeypatch):
    from qq_chat_analyzer.application import uninstall_data as module
    original = module._Object.remove
    attempted = []
    def attempt_replacement(item):
        if item.path.name == 'plaintext.txt':
            try:
                item.path.parent.rename(item.path.parent.with_name('replacement'))
            except PermissionError:
                attempted.append('blocked')
            else:
                pytest.fail('Pinned directory was replaced')
        original(item)
    monkeypatch.setattr(module._Object, 'remove', attempt_replacement)
    cleanup_local_data(data, purge=False)
    assert attempted == ['blocked']
