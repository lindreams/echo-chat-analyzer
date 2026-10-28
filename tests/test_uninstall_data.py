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
