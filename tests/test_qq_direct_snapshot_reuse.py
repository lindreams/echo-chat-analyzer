"""Real Windows lease + real bridge + real generation; all data fictional."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from test_napcat_qq_provider import runtime, provider, RUNTIME_ID
from test_qq_direct_main_wal_poc import _reserve_48_bytes, _run
from test_qq_direct_database_facade import _fetch_facade, _fictional_png, _message_blob
from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource, AnalysisConfig
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService, QQDirectDatabaseShuttingDown,
)
from qq_chat_analyzer.application.qq.qq_provider_factory import QQReconnectRequired
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeFailure

pytestmark = pytest.mark.slow_integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def leased_source(tmp_path, runtime, monkeypatch):
    # Reuse the established fictional group/PIC facts and actual crypto fixture.
    plain = tmp_path / 'plaintext-qq.db'
    _reserve_48_bytes(plain)
    raw = _fictional_png()
    original, media, _ = _fetch_facade(tmp_path, digest=hashlib.md5(raw).digest(),
                                      content=raw, group_sender='10087')
    original._qq_service_if_present().shutdown()
    with sqlite3.connect(plain) as db:
        for key, message_id, sender in [('group-partition', 203, '10086'),
                                        ('group-partition', 202, '10087'),
                                        ('other-group', 301, '10086')]:
            db.execute('''INSERT INTO group_msg_table
                ("40001","40027","40030","40033","40050","40800") VALUES(?,?,?,?,?,?)''',
                (message_id, key, '12345001', sender, 1760000002, _message_blob('fictional hello message')))
    source = tmp_path / 'source'
    source.mkdir()
    selected = tmp_path / 'selected.db'
    with closing(sqlite3.connect(plain)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE group_msg_table SET "40050"="40050"+1')
        writer.commit()
        with closing(sqlite3.connect(selected)) as backup:
            writer.backup(backup)
        _run('fixture', plain, Path(f'{plain}-wal'), source / 'nt_msg.db', source / 'nt_msg.db-wal')
    root, marker = tmp_path / 'workspace', tmp_path / 'operations.txt'
    clock = tmp_path / 'clock.txt'
    clock.write_text('0')
    options = dict(runtime_id=RUNTIME_ID, selfUin='10086', marker=marker,
                   snapshotModule=(ROOT / 'scripts/qq_direct_db_snapshot/snapshot.mjs').as_uri(),
                   snapshotRoot=str(root), sourceDirectory=str(source), plaintext=str(selected), clockFile=str(clock))
    base = runtime('direct-db', **options)
    metadata = provider(base)
    metadata.status()
    client = metadata.snapshot_client(root)
    service = QQDirectDatabaseImportService(runtime_client=client,
                                           provider_factory=SimpleNamespace(create=lambda: metadata))
    facade = ChatAnalyzerFacade(qq_service=service, analysis_service=AnalysisApplicationService(),
                               qq_connection_service=original._qq_connection_service,
                               stopwords_directory=ROOT)
    counts = {'acquire': 0, 'quick_check': 0}
    ready_times = []
    acquire, check = client.acquire, QQDatabaseProvider.quick_check
    def counted_acquire():
        counts['acquire'] += 1
        result = acquire()
        ready_times.append(time.perf_counter())
        return result
    def counted_check(*args, **kwargs):
        counts['quick_check'] += 1
        return check(*args, **kwargs)
    monkeypatch.setattr(client, 'acquire', counted_acquire)
    monkeypatch.setattr(QQDatabaseProvider, 'quick_check', counted_check)
    case = SimpleNamespace(service=service, client=client, facade=facade, counts=counts,
                          root=root, base=base, runtime=runtime, clock=clock, media=media, marker=marker,
                          options=options, ready_times=ready_times)
    yield case
    service.shutdown()
    case.client.recover()
    assert not list((root / 'generations').glob('*'))


def generations(case):
    return list((case.root / 'generations').glob('*'))


def test_list_then_group_reuses_real_generation_and_report_matches_fresh(leased_source, tmp_path, monkeypatch, record_property):
    case = leased_source
    start = time.perf_counter()
    sessions = case.facade.list_sessions(ChatSource.QQ)
    listing = time.perf_counter() - start
    generation, = generations(case)
    database = generation / 'snapshot.db'
    disk_bytes = sum(p.stat().st_size for p in generation.iterdir())
    # OS handles, rather than timestamps, enforce immutability.
    for path in (database, generation / 'manifest.json'):
        with pytest.raises(OSError):
            path.open('r+b')
        with pytest.raises(OSError):
            path.unlink()
    assert case.counts == {'acquire': 1, 'quick_check': 1}
    seen, reports = [], []
    read = QQDatabaseProvider.read_session_payload
    def capture(self, *args, **kwargs):
        payload = read(self, *args, **kwargs)
        seen.append((self._database_path.parent.name, payload))
        return payload
    monkeypatch.setattr(QQDatabaseProvider, 'read_session_payload', capture)
    from qq_chat_analyzer.presentation import echo_serializer
    export = echo_serializer.export_echo_report_html
    def capture_report(view, path, **kwargs):
        reports.append(view)
        return export(view, path, **kwargs)
    monkeypatch.setattr('qq_chat_analyzer.application.analysis_service.export_echo_report_html', capture_report)
    retained_at = time.perf_counter()
    lease_granted_at = case.service._retained_snapshot.retained_at
    cleaned_at = []
    cleanup = case.client.cleanup
    def timed_cleanup(generation_id):
        result = cleanup(generation_id)
        cleaned_at.append(time.perf_counter())
        return result
    monkeypatch.setattr(case.client, 'cleanup', timed_cleanup)
    from qq_chat_analyzer.application.analysis_phase import AnalysisPhase
    ready_at = []
    def phase(value):
        if value is AnalysisPhase.ANALYZING_REPORT:
            ready_at.append(time.perf_counter())
    reused = case.facade.analyze_session(ChatSource.QQ, 'group:group-partition',
        AnalysisConfig(output_directory=tmp_path / 'reused'), on_phase=phase)
    extra = time.perf_counter() - retained_at
    assert seen[0][0] == generation.name
    assert [record['record_id'] for record in seen[0][1]['records']] == ['201', '202', '203']
    assert case.counts == {'acquire': 1, 'quick_check': 1}
    assert not generation.exists()
    retained_seconds = cleaned_at[0] - retained_at
    assert any(asset.data_uri for asset in reports[0].stickers.assets)
    fresh_started = time.perf_counter()
    fresh = case.facade.analyze_session(ChatSource.QQ, 'group:group-partition',
        AnalysisConfig(output_directory=tmp_path / 'fresh'), on_phase=phase)
    assert seen[1][0] != generation.name and seen[0][1] == seen[1][1]
    assert reused.result.processed_message_count == fresh.result.processed_message_count
    assert reports[0] == reports[1]  # Statistics, sender identity and image bytes.
    assert case.counts == {'acquire': 2, 'quick_check': 2}
    metrics = dict(list_seconds=listing, extra_report_seconds=extra,
                   extra_acquisition_seconds=ready_at[0] - retained_at, plaintext_bytes=disk_bytes,
                   fresh_acquisition_seconds=ready_at[1] - fresh_started,
                   plaintext_ready_to_cleanup_seconds=cleaned_at[0] - case.ready_times[0],
                   lease_granted_to_cleanup_seconds=cleaned_at[0] - lease_granted_at,
                   retained_seconds=retained_seconds, acquire_after_list=1, quick_check_after_list=1,
                   acquire_after_reused_report=1, quick_check_after_reused_report=1,
                   acquire_after_fresh_report=2, quick_check_after_fresh_report=2)
    record_property('snapshot_reuse_metrics', json.dumps(metrics))
    print('fictional same-generation metrics:', json.dumps(metrics))


def test_lease_is_single_use_for_consecutive_groups(leased_source):
    case = leased_source
    case.service.list_sessions()
    generation, = generations(case)
    with case.service.acquired_session('group:group-partition'):
        assert not generation.exists()
    with case.service.acquired_session('group:other-group'):
        pass
    assert case.counts == {'acquire': 2, 'quick_check': 2}


@pytest.mark.parametrize('transition', ['onLoginConnected', 'onLoginDisConnected',
    'onLogoutSucceed', 'SelfOffline', 'KickedOffLine', 'missing_observer'])
def test_native_connection_transition_or_unknown_observer_prevents_reuse(leased_source, transition):
    case = leased_source
    if transition == 'missing_observer':
        case.options['noConnectionObserver'] = True
        case.base = case.runtime.restart(case.base, mode='direct-db', **case.options)
        metadata = provider(case.base)
        metadata.status()
        # This test starts before acquisition; bind the original connection.
        case.client = metadata.snapshot_client(case.root)
        case.service._runtime_client = case.client
        case.service._provider_factory = SimpleNamespace(create=lambda: metadata)
        acquire = case.client.acquire
        def counted_acquire():
            case.counts['acquire'] += 1
            return acquire()
        case.client.acquire = counted_acquire
    case.service.list_sessions()
    previous = generations(case)
    if transition != 'missing_observer':
        # Online and UIN remain unchanged, so status sampling cannot catch this.
        action = 'offlineEvent' if transition in ('SelfOffline', 'KickedOffLine') else 'loginTransition'
        case.runtime.control(case.base, {action: transition})
    else:
        assert not previous
    with case.service.acquired_session('group:group-partition'):
        pass
    assert case.counts == {'acquire': 2, 'quick_check': 2}
    assert not generations(case)


@pytest.mark.parametrize('change', ['account', 'runtime_expired', 'missing_lease'])
def test_invalid_lease_freshly_acquires_never_uses_previous(leased_source, change):
    case = leased_source
    case.service.list_sessions()
    previous, = generations(case)
    if change == 'account':
        case.runtime.control(case.base, {'selfUin': '10088'})
    elif change == 'runtime_expired':
        case.clock.write_text('120001')
    else:
        case.client.cleanup(previous.name)
    with case.service.acquired_session('group:group-partition') as result:
        assert result.self_uin == ('10088' if change == 'account' else '10086')
    assert not previous.exists()
    assert case.counts == {'acquire': 2, 'quick_check': 2}


def test_expiry_releases_idle_plaintext_without_another_request(leased_source, monkeypatch):
    import qq_chat_analyzer.application.qq.qq_direct_database_import_service as module
    monkeypatch.setattr(module, 'SNAPSHOT_REUSE_SECONDS', 0.05)
    case = leased_source
    case.service.list_sessions()
    deadline = time.monotonic() + 10
    while generations(case):
        assert time.monotonic() < deadline
        threading.Event().wait(0.01)
    with case.service.acquired_session('group:group-partition'):
        pass
    assert case.counts == {'acquire': 2, 'quick_check': 2}


@pytest.mark.parametrize('ending', ['cancel_list', 'cancel_analysis', 'exception', 'shutdown', 'reconnect'])
def test_cleanup_on_cancel_failure_shutdown_and_reconnect(leased_source, ending):
    case = leased_source
    cancelled = threading.Event()
    if ending == 'cancel_list':
        read = case.service._named_sessions
        def cancel(*args, **kwargs):
            result = read(*args, **kwargs)
            cancelled.set()
            return result
        case.service._named_sessions = cancel
    case.service.list_sessions(cancelled=cancelled.is_set)
    if ending == 'cancel_analysis':
        with pytest.raises(QQDirectDatabaseShuttingDown):
            with case.service.acquired_session('group:group-partition', cancelled=lambda: True):
                pytest.fail('cancelled acquisition yielded')
    elif ending == 'exception':
        with pytest.raises(RuntimeError):
            with case.service.acquired_session('group:group-partition'):
                raise RuntimeError('fictional consumer failure')
    elif ending == 'shutdown':
        assert case.service.shutdown() is ShutdownStatus.SUCCESS
    elif ending == 'reconnect':
        case.service.release_retained_snapshot()
        with pytest.raises(QQReconnectRequired):
            case.service.list_sessions()
        assert case.counts == {'acquire': 1, 'quick_check': 1}
        case.service.prepare_reconnect()
    assert not generations(case)


def test_concurrent_refresh_and_analysis_serialize_generation_ownership(leased_source, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    case = leased_source
    case.service.list_sessions()
    entered, release = threading.Event(), threading.Event()
    original = QQDatabaseProvider.read_session_payload
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(QQDatabaseProvider, 'read_session_payload', blocked)
    def analyze():
        with case.service.acquired_session('group:group-partition'):
            pass
    with ThreadPoolExecutor(3) as pool:
        analysis = pool.submit(analyze)
        assert entered.wait(10)
        refresh = pool.submit(case.service.list_sessions)
        refresh2 = pool.submit(case.service.list_sessions)
        assert not refresh.done() and not refresh2.done()
        release.set()
        analysis.result(15)
        refresh.result(15)
        refresh2.result(15)
    assert case.counts == {'acquire': 3, 'quick_check': 3}
    assert len(generations(case)) == 1
    case.service.release_retained_snapshot()
    assert not generations(case)


def test_identity_unknown_and_fresh_failure_cannot_fallback(leased_source, monkeypatch):
    case = leased_source
    case.service.list_sessions()
    previous, = generations(case)
    case.runtime.control(case.base, {'selfUin': '0'})
    attempted = []
    def fail():
        attempted.append(True)
        raise QQSnapshotRuntimeFailure()
    monkeypatch.setattr(case.client, 'acquire', fail)
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectSnapshotAcquireFailed
    with pytest.raises(QQDirectSnapshotAcquireFailed):
        with case.service.acquired_session('group:group-partition'):
            pytest.fail('old snapshot was used as fallback')
    assert attempted == [True] and not previous.exists()


def test_cancel_during_reused_read_releases_snapshot(leased_source, monkeypatch):
    case = leased_source
    case.service.list_sessions()
    cancel = threading.Event()
    original = QQDatabaseProvider.read_session_payload
    def read(*args, **kwargs):
        payload = original(*args, **kwargs)
        cancel.set()
        return payload
    monkeypatch.setattr(QQDatabaseProvider, 'read_session_payload', read)
    with pytest.raises(QQDirectDatabaseShuttingDown):
        with case.service.acquired_session('group:group-partition', cancelled=cancel.is_set):
            pytest.fail('cancelled acquisition yielded')
    assert not generations(case)
    assert case.counts == {'acquire': 1, 'quick_check': 1}


def test_restarted_worker_never_receives_old_lease_or_cleanup(leased_source):
    case = leased_source
    case.service.list_sessions()
    previous, = generations(case)
    case.runtime.restart(case.base, mode='direct-db', **case.options)
    with pytest.raises(QQReconnectRequired):
        with case.service.acquired_session('group:group-partition'):
            pytest.fail('old Worker generation was reused')
    assert previous.exists()  # A stale client cannot clean the new Worker.
    fresh = provider(case.base)
    fresh.status()
    case.client = fresh.snapshot_client(case.root)
    case.service.prepare_reconnect()
    case.service._runtime_client = case.client
    case.service._provider_factory = SimpleNamespace(create=lambda: fresh)
    case.service.start()  # Explicit new connection recovers the old orphan.
    assert not previous.exists()


@pytest.mark.parametrize('fault', ['guard_exit', 'sidecar'])
def test_snapshot_handle_guard_rejects_lost_proof_and_releases(tmp_path, fault):
    import subprocess
    (tmp_path / 'snapshot.db').write_bytes(b'fictional owned snapshot')
    (tmp_path / 'manifest.json').write_text('{}')
    program = """
import fs from 'node:fs';
import cp from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
let owned;
const spawn=cp.spawn;
cp.spawn=(...args)=>{owned=spawn(...args);return owned;};
syncBuiltinESMExports();
const {pinSnapshot}=await import(process.argv[1]);
const path=process.argv[2], fault=process.argv[3];
const guard=await pinSnapshot(path);
await guard.check();
let renameBlocked=false;
try {fs.renameSync(path,path+'.moved'); fs.renameSync(path+'.moved',path);}
catch {renameBlocked=true;}
if(fault==='guard_exit') {
  owned.ref();
  const closed=new Promise(resolve=>owned.once('close',resolve));
  owned.kill(); await closed;
} else fs.writeFileSync(path+'/snapshot.db-wal','fictional');
let refused=false;
try {await guard.check();} catch {refused=true;}
await guard.release();
fs.unlinkSync(path+'/snapshot.db');
console.log(JSON.stringify({refused,renameBlocked}));
"""
    result = subprocess.run(['node', '--input-type=module', '-e', program,
        (ROOT / 'scripts/qq_direct_db_snapshot/snapshot_guard.mjs').as_uri(), str(tmp_path), fault],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'refused': True, 'renameBlocked': True}
