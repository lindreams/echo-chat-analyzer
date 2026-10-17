"""Opt-in field evidence uses fictional snapshots and a strict output grammar."""
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import subprocess

import pytest

from qq_chat_analyzer.providers import qq_snapshot_integrity_probe as probe
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService, QQDirectSnapshotInvalid, QQDirectSnapshotCleanupFailed,
)
from qq_direct_db_testing import FakeSnapshotRuntime
from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeFailure


@pytest.fixture
def enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, '_claimed', False)
    monkeypatch.setattr(probe, '_pending', None)
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK', '1')
    output = tmp_path / 'result.json'
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK_OUTPUT', str(output))
    return output


@pytest.mark.parametrize(('message', 'category'), [
    ('NULL value in fictional_secret.body', 'constraint'),
    ('CHECK constraint failed in fictional_secret', 'constraint'),
    ('non-unique entry in index fictional_secret', 'constraint'),
    ('*** in database main ***\nMain freelist: freelist leaf count too big on page 4', 'freelist'),
    ('*** in database main ***\nOn tree page 2: 2 of 3 pages missing from overflow list', 'overflow'),
    ('*** in database main ***\nFragmentation of 9 bytes reported as 0 on page 2', 'cell_layout'),
    ('*** in database main ***\nPage 6 is never used', 'page_reference'),
    ('*** in database main ***\nPage 2: btreeInitPage() returns error code 11', 'btree'),
    ('fictional unrecognized sensitive SQL error', 'unknown'),
])
def test_error_text_is_classified_without_export(message, category):
    assert probe.classify_integrity_result(message) == category


@pytest.mark.parametrize('fault', ['ok', 'constraint', 'freelist', 'btree'])
def test_real_sqlite_faults_are_classified_before_cleanup(tmp_path, enabled, fault):
    generation = tmp_path / 'owned'
    generation.mkdir()
    database = generation / 'snapshot.db'
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('CREATE TABLE fictional_secret(body TEXT         )')
        connection.execute('INSERT INTO fictional_secret VALUES(?)', (None if fault == 'constraint' else 'safe',))
    if fault == 'constraint':
        # Equal-length fictional schema mutation: the record now violates
        # NOT NULL, without using writable_schema or an unsafe open mode.
        database.write_bytes(database.read_bytes().replace(b'body TEXT         ', b'body TEXT NOT NULL'))
    if fault in ('freelist', 'btree'):
        data = bytearray(database.read_bytes())
        if fault == 'freelist':
            data[32:36] = (99999).to_bytes(4, 'big')
            data[36:40] = (1).to_bytes(4, 'big')
        else:
            data[4096] = 255
        database.write_bytes(data)
    initial = 'ok' if fault == 'ok' else 'failed'
    probe.collect_integrity_probe(database, initial, {'status': 'unavailable', 'private': 'secret-key'})
    assert not enabled.exists()  # No persistent result until original cleanup.
    assert sorted(p.name for p in generation.iterdir()) == ['snapshot.db']
    shutil.rmtree(generation)
    probe.finish_integrity_probe(generation, True)
    text = enabled.read_text()
    result = json.loads(text)
    assert result['category'] == fault
    assert result['cleanup'] == 'confirmed' and result['repeat_matches']
    assert result['layout']['page_size'] == 4096
    assert result['layout']['header_count_matches']
    assert result['page_verification'] == {'status': 'unavailable'}
    assert not any(secret in text for secret in ('fictional', 'secret', str(tmp_path), 'snapshot.db', '99999'))
    first = enabled.read_bytes()
    probe.collect_integrity_probe(database, 'error', None)
    probe.finish_integrity_probe(generation, False)
    assert enabled.read_bytes() == first  # Once per process, never overwritten.


@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_service_publishes_only_after_cleanup_and_keeps_failure(tmp_path, enabled, cleanup_fails, caplog):
    source = tmp_path / 'fictional.db'
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute('CREATE TABLE fictional_secret(body TEXT         )')
        connection.execute('INSERT INTO fictional_secret VALUES(NULL)')
    source.write_bytes(source.read_bytes().replace(b'body TEXT         ', b'body TEXT NOT NULL'))
    runtime = FakeSnapshotRuntime(tmp_path / 'runtime', snapshot_path=source)
    runtime.manifest_overrides = {'integrity_probe': {'status': 'verified', 'private': 'secret-key'}}
    original_cleanup = runtime.cleanup

    def cleanup(generation_id):
        assert not enabled.exists()
        if cleanup_fails:
            raise QQSnapshotRuntimeFailure('fictional cleanup exception secret-key')
        original_cleanup(generation_id)

    runtime.cleanup = cleanup
    service = QQDirectDatabaseImportService(runtime_client=runtime)
    expected_error = QQDirectSnapshotCleanupFailed if cleanup_fails else QQDirectSnapshotInvalid
    with pytest.raises(expected_error):
        service.list_sessions()
    result = json.loads(enabled.read_text())
    assert result['category'] == 'constraint'
    assert result['page_verification'] == {'status': 'invalid'}
    assert result['cleanup'] == ('not_confirmed' if cleanup_fails else 'confirmed')
    assert not any(word in enabled.read_text() for word in ('secret', 'fictional', str(tmp_path)))
    assert not any(word in caplog.text for word in ('fictional_secret', 'secret-key', str(tmp_path)))


def test_disabled_probe_never_opens_database_or_writes(tmp_path, enabled, monkeypatch):
    monkeypatch.delenv('ECHO_QQ_INTEGRITY_CHECK')
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **k: pytest.fail('opt-out opened SQLite'))
    probe.collect_integrity_probe(tmp_path / 'missing.db', 'failed', None)
    probe.finish_integrity_probe(tmp_path, True)
    assert not enabled.exists()


def test_output_collision_and_unrelated_cleanup_are_preserved(tmp_path, enabled):
    generation = tmp_path / 'owned'
    probe.collect_integrity_probe(generation / 'missing.db', 'error', None)
    probe.finish_integrity_probe(tmp_path / 'unrelated', True)
    assert not enabled.exists()
    enabled.write_bytes(b'fictional other owner')
    probe.finish_integrity_probe(generation, True)
    assert enabled.read_bytes() == b'fictional other owner'


@pytest.mark.parametrize('verification', [
    {'status': ['private']},
    {'status': 'verified', 'pages': True},
    {'status': 'unavailable', 'raw_error': 'private'},
    {'status': 'unstable', 'path': 'private'},
])
def test_manifest_cannot_inject_private_fields(verification):
    result = probe._page_verification(verification)
    assert result in ({'status': 'invalid'}, {'status': 'unavailable'}, {'status': 'unstable'})


@pytest.mark.slow_integration
@pytest.mark.skipif(shutil.which('powershell.exe') is None, reason='Windows candidate launcher')
@pytest.mark.parametrize('reached', [True, False])
def test_one_run_launcher_isolates_echo_and_exposes_only_safe_result(tmp_path, reached):
    candidate = tmp_path / 'fictional candidate'
    candidate.mkdir()
    (candidate / 'Echo').mkdir()
    (candidate / 'Echo/Echo.exe').write_bytes(b'fictional executable never launched')
    script = candidate / 'Run-QQ-Integrity-Check.ps1'
    shutil.copyfile(Path(__file__).parents[1] / 'scripts/qq_integrity_candidate' / script.name, script)
    # Replace only process creation: execute the real launcher and validate its
    # child environment before a fictional process returns. No GUI/QQ starts.
    driver = tmp_path / 'driver.ps1'
    driver.write_text('''
param([string]$Launcher)
$ErrorActionPreference='Stop'
$OriginalLocal=$env:LOCALAPPDATA
function Start-Process {
 param($FilePath,$WorkingDirectory,$WindowStyle,[switch]$PassThru)
 if($WindowStyle -ne 'Hidden' -or $env:ECHO_QQ_INTEGRITY_CHECK -ne '1') {throw 'invalid launch'}
 if($env:LOCALAPPDATA -eq $OriginalLocal -or -not $env:LOCALAPPDATA.StartsWith($WorkingDirectory)) {throw 'not isolated'}
 if(-not $env:ECHO_QQ_INTEGRITY_CHECK_OUTPUT.StartsWith($WorkingDirectory)) {throw 'wrong output'}
 REPORT
 $Process=New-Object PSObject
 $Process | Add-Member ScriptMethod WaitForExit {}
 return $Process
}
& $Launcher
'''.replace(' REPORT', " Set-Content -LiteralPath $env:ECHO_QQ_INTEGRITY_CHECK_OUTPUT -Encoding ASCII -Value '{\"probe\":\"qq-integrity-1\",\"category\":\"btree\",\"cleanup\":\"confirmed\"}'" if reached else ''), encoding='ascii')
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                '-File', str(driver), str(script)], capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    results = list(candidate.glob('check-*/integrity-result.json'))
    assert len(results) == 1
    result = json.loads(results[0].read_text())
    if reached:
        assert result['category'] == 'btree' and result['cleanup'] == 'confirmed'
    else:
        assert result['initial_check'] == 'not_reached' and result['cleanup'] == 'not_observed'
    assert b'Send ONLY integrity-result.json' in completed.stdout
