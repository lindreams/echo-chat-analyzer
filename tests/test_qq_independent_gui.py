"""Scoped acquisition regression and a fail-closed, passive desktop entry.

The explicit account/group fixture does not prove automatic desktop discovery.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from threading import Event

import pytest
from test_gui import qt_app

from qq_db_test_data import synthetic_text_message_blob
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource, AnalysisConfig, FacadeError
from qq_chat_analyzer.application.qq import qq_independent_service as source
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
from qq_chat_analyzer.providers.qq_independent.files import SourceError
from qq_chat_analyzer.providers.qq_independent.snapshot import bind_live_database_paths


def test_live_database_path_binding_requires_independent_owner_and_unique_scope(tmp_path):
    root = tmp_path/'100000001'/'nt_qq'/'nt_db'
    root.mkdir(parents=True)
    main = root/'nt_msg.db'
    paths = [main, Path(str(main)+'-wal'), Path(str(main)+'-shm')]
    for path in paths:
        path.touch()
    assert bind_live_database_paths(paths, b'100000001') == main
    # Reject conflicts before probing a second account's filesystem.
    other = tmp_path/'100000002'/'nt_qq'/'nt_db'/'nt_msg.db'
    for evidence, owner, reason in (
        (paths, b'100000002', 'database_account_mismatch'),
        (paths+[other], b'100000001', 'database_binding_not_unique'),
        ([], b'100000001', 'database_binding_not_unique'),
        (paths, b'0100000001', 'independent_owner_reference_required'),
        (paths, b'unknown', 'independent_owner_reference_required'),
        ([Path('100000001/nt_qq/nt_db/nt_msg.db')], b'100000001', 'database_path_shape_unknown'),
    ):
        with pytest.raises(SourceError) as refused:
            bind_live_database_paths(evidence, owner)
        assert refused.value.code == reason
    paths[-1].unlink()
    with pytest.raises(FileNotFoundError):
        bind_live_database_paths(paths, b'100000001')


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    account=tmp_path/'100000001'; dbroot=account/'nt_qq/nt_db'; dbroot.mkdir(parents=True)
    image=tmp_path/'QQ.exe'; image.write_bytes(b'fictional program')
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('CREATE TABLE group_msg_table ("40001" INTEGER,"40027" TEXT,"40030" INTEGER,"40021" INTEGER,"40033" INTEGER,"40050" INTEGER,"40800" BLOB,"40011" INTEGER,"40012" INTEGER)')
        texts=('Orchard seedlings need gentle rain tomorrow','The telescope reveals a distant planet',
               'Guitar practice sounds pleasant after supper','Walking beside the lake brings peaceful thoughts')
        for index,text in enumerate(texts):
            sender=100000001+index%2
            db.execute('INSERT INTO group_msg_table VALUES (?,?,?,?,?,?,?,?,?)',
                       (index,'partition-a',900000001 if index%2 else 0,900000001,sender,1760000000+index*60,
                        synthetic_text_message_blob(text),1,0))
        db.execute('INSERT INTO group_msg_table VALUES (?,?,?,?,?,?,?,?,?)',(41,'partition-a',0,900000001,0,1759999940,None,1,1))
        # An unrelated partition must never reach the payload or name query.
        db.execute('INSERT INTO group_msg_table VALUES (?,?,?,?,?,?,?,?,?)',(42,'partition-b',900000002,900000002,100000003,1760003000,
                   synthetic_text_message_blob('OTHER_GROUP_SENTINEL'),1,0))
        db.commit()
    with closing(sqlite3.connect(dbroot/'group_info.db')) as db:
        db.executescript('CREATE TABLE group_list ("60001" INTEGER,"60007" TEXT);'
                        'CREATE TABLE group_detail_info_ver1 ("60001" INTEGER,"60007" TEXT);'
                        'CREATE TABLE group_member3 ("60001" INTEGER,"1002" INTEGER,"1000" TEXT,"64003" TEXT,"20002" TEXT);')
        for table in ('group_list','group_detail_info_ver1'):
            db.execute(f'INSERT INTO {table} VALUES (?,?)',(900000001,'Fictional orchard'))
        db.executemany('INSERT INTO group_member3 VALUES (?,?,?,?,?)',[(900000001,100000001,'uid-a','Card A','Nick A'),
            (900000001,100000002,'uid-b','Card B','Nick B'),(900000002,100000003,'uid-c','OTHER_NAME_SENTINEL','OTHER_NAME_SENTINEL')]); db.commit()
    with closing(sqlite3.connect(dbroot/'profile_info.db')) as db:
        for table in ('profile_info_v2','profile_info_v6'):
            db.execute(f'CREATE TABLE {table} ("1002" INTEGER,"1000" TEXT,"20002" TEXT)')
            db.executemany(f'INSERT INTO {table} VALUES (?,?,?)',[(100000001,'uid-a','Profile A'),(100000002,'uid-b','Profile B')])
        db.commit()
    monkeypatch.setattr(source,'resources_identity',lambda _:None)
    monkeypatch.setattr(source,'runtime_files',lambda:None)
    def freeze(path,parent):
        child=parent/('qq-authorized-full-'+hashlib.sha256(path.name.encode()).hexdigest()[:32]); child.mkdir()
        (child/'owner.json').write_text(json.dumps({'kind':'echo-qq-full-read','version':1}))
        destination=child/'encrypted.db'; shutil.copyfile(path,destination)
        return {'snapshot':str(destination),'size':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
    monkeypatch.setattr(source,'prepare',freeze)
    service=source.QQIndependentService(workspace=tmp_path/'owned')
    def capture(progress,external):
        if external.is_set(): raise SourceError('cancelled')
        progress('armed')
        for frozen in service._frozen: shutil.copyfile(frozen['path'],frozen['output'])
    monkeypatch.setattr(service,'_run_capture',capture)
    selection=source.QQIndependentSelection(image,account,'100000001','900000001',False)
    yield service,selection,dbroot
    assert service.shutdown() is ShutdownStatus.SUCCESS
    assert not list((tmp_path/'owned').glob('run-*')) if (tmp_path/'owned').exists() else True


def facade_for(service):
    return ChatAnalyzerFacade(qq_service=service,qq_connection_service=service,independent_qq=True,
                              analysis_service=AnalysisApplicationService())


def test_scoped_facade_names_scope_analysis_report_and_one_shot_cleanup(prepared,tmp_path):
    service,selection,_=prepared; facade=facade_for(service)
    service.prepare(selection)
    facade.start_qq_auth_flow()
    sessions=facade.list_sessions(ChatSource.QQ)
    assert len(sessions)==1 and sessions[0].display_name=='Fictional orchard'
    assert sessions[0].message_count==5
    raw=json.loads(service._payload.read_text())
    assert len(raw['records'])==4  # The NULL-body native record is not a chat.
    assert 'SENTINEL' not in json.dumps(raw)
    assert {r.get('sender',{}).get('groupCard') for r in raw['records']}=={None,'Card B'}
    assert service.names_summary['named_members']==2
    assert service.read_counts=={'database_rows':5,'provider_messages':4,
                                 'verified_missing_body_rows':1,'unclassified_exclusions':0}
    assert not list(service._root.glob('*.db'))
    outcome=facade.analyze_session(ChatSource.QQ,sessions[0].session_id,AnalysisConfig(output_directory=tmp_path/'report'))
    assert outcome is not None
    assert outcome.report_path is not None, (outcome.result.status,outcome.result.diagnostic_counts)
    report=outcome.report_path.parent/'echo-report.json'
    assert report.is_file() and 'Card B' in report.read_text(encoding='utf-8')
    assert not service.list_sessions() and service._root is None
    with pytest.raises(FacadeError):
        facade.analyze_session(ChatSource.QQ,sessions[0].session_id,AnalysisConfig(output_directory=tmp_path/'repeat'))


@pytest.mark.parametrize('bad_number,bad_object',[(900000002,900000001),(0,900000002),(None,900000001)])
def test_conflicting_or_unknown_partition_rows_refuse_and_clean(prepared,bad_number,bad_object):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40030"=?,"40021"=? WHERE "40001"=1',(bad_number,bad_object));db.commit()
    service.prepare(selection)
    with pytest.raises(source.QQIndependentError): service.capture()
    assert service._root is None and not service.list_sessions()


def test_cancel_during_capture_and_failed_integrity_remove_all_private_files(prepared,monkeypatch):
    service,selection,_=prepared
    service.prepare(selection)
    cancelled=Event(); cancelled.set()
    with pytest.raises(source.QQIndependentError): service.capture(cancel_event=cancelled)
    assert service._root is None
    service.prepare(selection)
    monkeypatch.setattr(service,'_run_capture',lambda *_:(service._root/'message.db').write_bytes(b'broken'))
    with pytest.raises(source.QQIndependentError): service.capture()
    assert service._root is None


def test_scope_rejection_and_cleanup_never_adopt_unknown_directory(prepared,tmp_path):
    service,selection,_=prepared
    with pytest.raises(source.QQIndependentError):
        service.prepare(source.QQIndependentSelection(selection.executable,selection.account_directory,'100000009',selection.group))
    service.prepare(selection)
    unknown=service._root/'do-not-delete.txt'; unknown.write_text('fictional unrelated asset')
    with pytest.raises(SourceError): service.disconnect()
    assert unknown.read_text()=='fictional unrelated asset'
    unknown.unlink()  # Remove only this test's own fault injection.


def test_cleanup_failure_retains_proof_until_sensitive_files_are_removed(prepared,monkeypatch):
    service,selection,_=prepared
    service.prepare(selection)
    root=service._root
    encrypted=Path(service._frozen[0]['path'])
    unlink=Path.unlink

    def fail_owned_data(path,*args,**kwargs):
        if path==encrypted:
            raise OSError('fictional deletion failure')
        return unlink(path,*args,**kwargs)

    monkeypatch.setattr(Path,'unlink',fail_owned_data)
    with pytest.raises(OSError):
        service.disconnect()
    assert (root/'owner.json').is_file()
    assert (encrypted.parent/'owner.json').is_file() and encrypted.is_file()
    monkeypatch.setattr(Path,'unlink',unlink)
    service.disconnect()
    assert not root.exists()


def test_unconfirmed_worker_exit_retains_owner_and_blocks_replacement(prepared):
    service,selection,_=prepared
    service.prepare(selection)
    root=service._root

    class OwnedJob:
        failed=True
        closed=False
        def terminate_tree(self):
            if self.failed:raise OSError('fictional Job failure')
        def active_process_count(self):return 0
        def close_after_readers(self,*_args,**_kwargs):self.closed=True

    job=OwnedJob()
    service._worker=job
    with pytest.raises(OSError):service.disconnect()
    assert service._root==root and service._lease is not None
    with pytest.raises(OSError):service.prepare(selection)
    assert service._worker is job and (root/'owner.json').exists()
    job.failed=False
    service.disconnect()
    assert job.closed and service._worker is None and not root.exists()


def test_media_scope_is_account_bound_and_missing_cache_is_optional(prepared):
    service,selection,_=prepared
    service.prepare(selection)
    assert service._media_roots()==()
    root=selection.account_directory/'nt_qq/nt_data'
    original=root/'Pic/2026-01/Ori';original.mkdir(parents=True)
    face=root/'Emoji/marketface';face.mkdir(parents=True)
    (root/'Pic/unrelated').mkdir()
    assert set(service._media_roots())=={original,face}


def test_shutdown_blocks_new_facade_acquisition(prepared):
    service,selection,_=prepared; facade=facade_for(service)
    service.prepare(selection)
    result=facade.shutdown()
    assert result.steps[0].status is ShutdownStatus.SUCCESS
    assert service._root is None
    with pytest.raises(FacadeError):facade.list_sessions(ChatSource.QQ)


def test_formal_composition_selects_no_qr_workspace_and_navigation_is_passive(qt_app,monkeypatch):
    from qq_chat_analyzer.gui.app import build_facade
    from qq_chat_analyzer.gui.main_window import MainWindow
    from qq_chat_analyzer.gui.qq_independent_workspace import QQIndependentWorkspace
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit, QPushButton
    monkeypatch.setattr(source,'resources_identity',lambda _:pytest.fail('navigation inspected QQ'))
    monkeypatch.setattr(source,'runtime_files',lambda:pytest.fail('navigation touched runtime'))
    facade=build_facade(); window=MainWindow(facade)
    try:
        assert isinstance(window.qq_workspace,QQIndependentWorkspace)
        window.show_qq_workspace()
        assert facade.get_qq_qrcode_path() is None
        workspace = window.qq_workspace
        assert not workspace.findChildren(QLineEdit, options=Qt.FindChildOption.FindDirectChildrenOnly)
        assert not hasattr(workspace, '_account') and not hasattr(workspace, '_group')
        assert not hasattr(workspace, '_account_directory') and not hasattr(workspace, '_executable')
        assert not hasattr(facade, 'prepare_independent_qq')
        assert not workspace._session_panel.isEnabled()
        assert '暂不可用' in workspace._status.text()
        assert '请勿为此重新登录' in workspace._status.text()
        assert not any(button.isEnabled() for button in workspace.findChildren(QPushButton))
    finally:
        window.close(); window.await_shutdown(10)


def test_unclassified_null_body_is_not_silently_excluded(prepared):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40012"=99 WHERE "40001"=41')
        db.commit()
    service.prepare(selection)
    with pytest.raises(source.QQIndependentError):
        service.capture()
    assert service._root is None


def test_idle_expiry_releases_the_lease_and_payload(prepared,monkeypatch):
    import time
    service,selection,_=prepared
    monkeypatch.setattr(source,'_TTL',.05)
    service.prepare(selection)
    deadline=time.monotonic()+2
    while service._root is not None and time.monotonic()<deadline:
        time.sleep(.01)
    assert service._root is None and service._lease is None
    assert not service.list_sessions()


def test_gui_close_during_capture_drains_and_cleans(qt_app,prepared,monkeypatch):
    import time
    from threading import Thread
    from qq_chat_analyzer.gui.main_window import MainWindow
    service,selection,_=prepared
    entered=Event()

    def blocked_capture(_progress,external):
        entered.set()
        deadline=time.monotonic()+3
        while not service._cancelled(external.is_set) and time.monotonic()<deadline:
            time.sleep(.01)
        assert service._cancelled(external.is_set), 'GUI failed to cancel its capture'
        raise SourceError('cancelled')

    monkeypatch.setattr(service,'_run_capture',blocked_capture)
    service.prepare(selection)
    window=MainWindow(facade_for(service))
    errors=[]
    def capture():
        try:
            service.capture()
        except source.QQIndependentError as error:
            errors.append(error.code)
    capture_thread=Thread(target=capture)
    try:
        # Existing experimental acquisition still belongs to the Facade;
        # closing the unavailable entry must drain it safely.
        capture_thread.start()
        deadline=time.monotonic()+3
        while not entered.is_set() and time.monotonic()<deadline:
            qt_app.processEvents();time.sleep(.01)
        assert entered.is_set()
        window.close()
        assert window.await_shutdown(10)
        capture_thread.join(3)
        assert not capture_thread.is_alive() and len(errors)==1
        assert service._root is None and not service._busy
    finally:
        window.close()
        capture_thread.join(3)


def test_blocked_workspace_cannot_promote_experimental_group_to_session_list(qt_app,prepared):
    from qq_chat_analyzer.gui.qq_independent_workspace import QQIndependentWorkspace
    service,selection,_=prepared
    service.prepare(selection)
    service.capture()
    widget=QQIndependentWorkspace(facade_for(service),executor=lambda *_args,**_kwargs:pytest.fail('close queued work'))
    widget.refresh_connection_status(load_sessions_on_ready=True)
    assert not widget._session_panel.isEnabled()
    assert '暂不可用' in widget._status.text()
    widget._closing=True
    widget.cancel_connection()
    assert widget._cancel.is_set() and service._cancel.is_set()
    widget.close()


@pytest.mark.parametrize('unknown',[False,True])
def test_uninstaller_reuses_ownership_and_refuses_active_or_unknown_data(prepared,tmp_path,unknown):
    from qq_chat_analyzer.application.uninstall_data import cleanup_local_data,CleanupIncomplete
    _,selection,_=prepared
    data=tmp_path/'Echo-data'
    service=source.QQIndependentService(workspace=data/'qq-independent')
    service.prepare(selection)
    run=service._root
    try:
        with pytest.raises(CleanupIncomplete):
            cleanup_local_data(data,purge=False)
        assert run.exists()  # Its live owner must retain the encrypted copy.
        # Simulate process death releasing only the OS lease, leaving proof.
        service._lease.__exit__(None,None,None)
        service._lease=None
        if unknown:
            alien=run/'unrelated.txt'
            alien.write_text('fictional unrelated asset')
            with pytest.raises(CleanupIncomplete):
                cleanup_local_data(data,purge=False)
            assert alien.exists()
            alien.unlink()
        cleanup_local_data(data,purge=False)
        assert not (data/'qq-independent').exists()
        service._root=None
    finally:
        service.shutdown()


def test_independent_account_media_reaches_final_html_with_animation(prepared,tmp_path,monkeypatch):
    from dataclasses import replace
    from test_qq_db_rich_contents import _body,_scalar,_bytes
    from test_qq_marketface_media import send,write_cache,local_only_worker
    from qq_chat_analyzer.application.qq import qq_marketface_media as media
    service,selection,dbroot=prepared
    selection=replace(selection,recover_media=True)
    cache=selection.account_directory/'nt_qq/nt_data/Emoji/marketface'
    item=send()
    write_cache(cache,item)
    segment=_scalar(45002,11)+_scalar(80810,item.resource_pack_id)+_bytes(80903,bytes.fromhex(item.resource_id))
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40800"=? WHERE "40001"=0',
                   (synthetic_text_message_blob('Orchard seedlings need gentle rain tomorrow')+_body(segment),))
        db.commit()
    # Spawn the existing local-only seam; no real CDN or QQ can be contacted.
    monkeypatch.setattr(media,'_worker',local_only_worker)
    facade=facade_for(service)
    service.prepare(selection)
    service.capture()
    session=facade.list_sessions(ChatSource.QQ)[0]
    outcome=facade.analyze_session(ChatSource.QQ,session.session_id,
                                 AnalysisConfig(output_directory=tmp_path/'animated-report'))
    assert outcome.report_path is not None
    assert len(outcome.result.stickers.sends)==1
    assets=outcome.echo_report_view.stickers.assets
    assert len(assets)==1 and assets[0].status in ('available','preview')
    reference=assets[0].data_uri
    assert reference.startswith('media/') and reference.endswith('.gif')
    assert reference in outcome.report_path.read_text(encoding='utf-8')
    from PIL import Image
    with Image.open(outcome.report_path.parent/reference) as animation:
        assert animation.n_frames==2
    assert service._root is None
