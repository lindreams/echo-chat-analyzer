"""Fictional guided account acquisition, conversation analysis and ownership."""
import builtins
from contextlib import closing, contextmanager
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
        db.execute('CREATE TABLE c2c_msg_table ("40001" INTEGER,"40027" TEXT,"40030" INTEGER,"40021" INTEGER,"40033" INTEGER,"40050" INTEGER,"40800" BLOB)')
        for index,text in enumerate(texts):
            db.execute('INSERT INTO c2c_msg_table VALUES (?,?,?,?,?,?,?)',
                (100+index,'private-a',100000002,100000002,100000001+index%2,1760000000+index*86400,
                 synthetic_text_message_blob(text)))
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
    monkeypatch.setattr(source,'_discovery_locations',lambda:([tmp_path],[image]))
    def freeze(path,parent):
        child=parent/('qq-authorized-full-'+hashlib.sha256(path.name.encode()).hexdigest()[:32]); child.mkdir()
        (child/'owner.json').write_text(json.dumps({'kind':'echo-qq-full-read','version':1}))
        destination=child/'encrypted.db'; shutil.copyfile(path,destination)
        return {'snapshot':str(destination),'size':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}
    monkeypatch.setattr(source,'prepare',freeze)
    service=source.QQIndependentService(workspace=tmp_path/'owned')
    def capture(progress,external):
        if external.is_set(): raise SourceError('cancelled')
        from datetime import datetime,timedelta,timezone
        progress({'phase':'armed','remaining_login_ms':10000,'login_before_utc':(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()})
        selected=service._selection.account_directory/'nt_qq/nt_db'
        for role in ('message','group_info','profile_info'):
            frozen=freeze(selected/('nt_msg.db' if role=='message' else role+'.db'),service._root)
            service._frozen.append({'path':frozen['snapshot']})
            shutil.copyfile(frozen['snapshot'],service._root/(role+'.db'))
    monkeypatch.setattr(service,'_run_capture',capture)
    monkeypatch.setattr(service,'_process_candidates',lambda:[{'ProcessId':123,'ExecutablePath':str(image)}])
    selection=source.QQIndependentSelection(image,account,'100000001',False)
    yield service,selection,dbroot
    assert service.shutdown() is ShutdownStatus.SUCCESS
    assert not list((tmp_path/'owned').glob('run-*')) if (tmp_path/'owned').exists() else True


def facade_for(service):
    return ChatAnalyzerFacade(qq_service=service,qq_connection_service=service,independent_qq=True,
                              analysis_service=AnalysisApplicationService())


def test_profile_discovery_lists_metadata_only_and_requires_explicit_scope(prepared,tmp_path,monkeypatch):
    service,selection,dbroot=prepared;facade=facade_for(service)
    other=tmp_path/'100000002';shutil.copytree(dbroot,other/'nt_qq/nt_db')
    incomplete=tmp_path/'100000003'/'nt_qq/nt_db';incomplete.mkdir(parents=True)
    (incomplete/'nt_msg.db').write_bytes(b'fictional incomplete profile')
    original_open=Path.open;original_builtin_open=builtins.open
    def guard(path):
        if isinstance(path,(str,Path)):
            assert not any(Path(path).is_relative_to(account) for account in
                           (selection.account_directory,other,incomplete.parents[1])), 'discovery read account content'
    def path_open(path,*args,**kwargs):guard(path);return original_open(path,*args,**kwargs)
    def file_open(path,*args,**kwargs):guard(path);return original_builtin_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',path_open);monkeypatch.setattr(builtins,'open',file_open)
    result=facade.discover_independent_qq_profiles()
    assert result.accounts==(selection.account_directory,other)
    assert result.executables==(selection.executable,)
    assert service._root is None and not service.list_sessions()
    assert facade.discover_independent_qq_profiles(other).accounts==(other,)
    with pytest.raises(FacadeError) as refused:
        facade.discover_independent_qq_profiles(cancelled=lambda:True)
    assert refused.value.code=='analysis_cancelled'


def test_installation_metadata_reuses_registry_paths_without_running_commands(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from qq_chat_analyzer.application.qq import qq_auth_bridge as bridge
    registry=SimpleNamespace(HKEY_LOCAL_MACHINE=1,HKEY_CURRENT_USER=2,HKEY_CLASSES_ROOT=3)
    location=tmp_path/'Non default QQ'
    def values(_registry,_hive,key):
        if key.endswith('Uninstall\\QQ'):
            return {'InstallLocation':f'"{location}"',
                    'UninstallString':f'"{location / "Uninstall.exe"}" /silent',
                    'DisplayIcon':f'"{location / "QQ.exe"}",-1'}
        if key.endswith('App Paths\\QQ.exe'):
            return {'':f'"{location / "QQ.exe"}" --argument'}
        return {}
    monkeypatch.setattr(bridge,'_registry_values',values)
    assert set(bridge._registry_qq_install_candidates(registry))=={location/'QQ.exe'}


def test_program_discovery_filters_versions_and_broken_resources(prepared,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from qq_chat_analyzer.application.qq import qq_version
    service,selection,_=prepared
    old=tmp_path/'old/QQ.exe';old.parent.mkdir();old.write_bytes(b'old')
    broken=tmp_path/'broken/QQ.exe';broken.parent.mkdir();broken.write_bytes(b'broken')
    monkeypatch.setattr(source,'_discovery_locations',lambda:([],[selection.executable,old,broken,selection.executable]))
    def validate(path):
        if path==old:raise SourceError('exact_active_version_required')
        if path==broken:raise SourceError('module_identity_refused')
    monkeypatch.setattr(source,'resources_identity',validate)
    monkeypatch.setattr(qq_version,'read_qq_resources',lambda _:SimpleNamespace(version=(9,9,31,49738)))
    found=service.discover_local_profiles()
    assert found.executables==(selection.executable,)
    assert found.incompatible_executables==(old,)
    assert found.unverified_executables==(broken,)
    assert found.accounts==() and service._root is None


def test_unique_compatible_program_advances_without_file_picker(qt_app,prepared,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    service,selection,_=prepared;tasks=[];authorized=[]
    widget=QQWorkspace(facade_for(service),executor=lambda operation,**callbacks:tasks.append(operation))
    flow=widget._independent
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:pytest.fail('normal connection opened file picker'))
    monkeypatch.setattr(flow,'_authorize',lambda account:authorized.append(account) or False)
    flow._discovered(source.QQIndependentDiscovery((selection.account_directory,),(selection.executable,)))
    assert flow._image==selection.executable and authorized==[selection.account_directory]
    assert service._root is None
    widget.close()


def test_program_recovery_picker_starts_at_home_instead_of_working_directory(qt_app,prepared,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    service,_,_=prepared;starts=[]
    widget=QQWorkspace(facade_for(service))
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda _parent,_title,start,_filter: starts.append(start) or ('',''))
    widget._independent._recovery='program';widget._independent._settings()
    assert starts==[str(Path.home())] and Path(starts[0])!=Path.cwd()
    widget.close()


def test_discovery_respects_isolated_profile_instead_of_hkcu(monkeypatch,tmp_path):
    import os
    import winreg
    monkeypatch.setattr(winreg,'OpenKey',lambda *_args:pytest.fail('isolated discovery read native HKCU'))
    for name in ('ProgramFiles','ProgramFiles(x86)','ProgramW6432','LOCALAPPDATA'):
        monkeypatch.setenv(name,str(tmp_path/name))
    roots,images=source._discovery_locations()
    assert roots==[Path.home()/'Documents/Tencent Files',Path(os.environ['APPDATA'])/'Tencent/QQ']
    assert all(image.is_relative_to(tmp_path) for image in images)


def test_facade_complete_list_scoped_analysis_report_and_reuse(prepared,tmp_path):
    service,selection,_=prepared; facade=facade_for(service)
    facade.prepare_independent_qq(selection.executable,selection.account_directory)
    facade.start_qq_auth_flow()
    assert facade.list_sessions(ChatSource.QQ)==[]  # Declaration is a separate explicit gate.
    facade.confirm_independent_qq_account(selection.account)
    sessions=facade.list_sessions(ChatSource.QQ)
    assert len(sessions)==3
    group=next(s for s in sessions if s.session_id=='group:partition-a')
    private=next(s for s in sessions if s.session_id=='private:private-a')
    assert group.display_name=='Fictional orchard' and group.message_count==5
    assert private.display_name=='Profile B'
    assert facade.get_session_message_range(ChatSource.QQ,private.session_id)==(1760000000,1760259200)
    with service.acquired_session(group.session_id) as acquired:
        raw=json.loads(acquired.payload_path.read_text())
        assert len(raw['records'])==4 and 'SENTINEL' not in json.dumps(raw)
        assert raw['self']['basis']=='user_declared'
        assert service.names_summary['named_members']==2
        assert service.read_counts=={'database_rows':5,'provider_messages':4,
            'verified_missing_body_rows':1,'unclassified_exclusions':0}
    assert service._payload is None and list(service._root.glob('*.db'))
    for session in (group,private):
        outcome=facade.analyze_session(ChatSource.QQ,session.session_id,AnalysisConfig(output_directory=tmp_path/session.session_id.split(':')[0]))
        assert outcome.report_path is not None
        report=json.loads((outcome.report_path.parent/'echo-report.json').read_text(encoding='utf-8'))
        assert report['self_identity']=={'basis':'user_declared','system_authenticated':False}
        assert report['conversation']['kind']==session.session_type
        assert len(service.list_sessions())==3 and service._payload is None
    facade.disconnect_qq()
    assert service._root is None
    with pytest.raises(FacadeError):
        facade.analyze_session(ChatSource.QQ,group.session_id,AnalysisConfig(output_directory=tmp_path/'repeat'))


@pytest.mark.parametrize('bad_number,bad_object',[(900000002,900000001),(0,900000002),(None,900000001)])
def test_conflicting_or_unknown_partition_rows_refuse_and_clean(prepared,bad_number,bad_object):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40030"=?,"40021"=? WHERE "40001"=1',(bad_number,bad_object));db.commit()
    service.prepare(selection)
    service.capture()
    with pytest.raises(source.QQIndependentError): service.confirm_account(selection.account)
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
        service.prepare(source.QQIndependentSelection(selection.executable,selection.account_directory,'100000009'))
    service.prepare(selection)
    unknown=service._root/'do-not-delete.txt'; unknown.write_text('fictional unrelated asset')
    with pytest.raises(SourceError): service.disconnect()
    assert unknown.read_text()=='fictional unrelated asset'
    unknown.unlink()  # Remove only this test's own fault injection.


def test_cleanup_failure_retains_proof_until_sensitive_files_are_removed(prepared,monkeypatch):
    service,selection,_=prepared
    service.prepare(selection)
    root=service._root
    service.capture()
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


def test_formal_composition_and_navigation_are_passive(qt_app,monkeypatch):
    from qq_chat_analyzer.gui.app import build_facade
    from qq_chat_analyzer.gui.main_window import MainWindow
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    monkeypatch.setattr(source,'resources_identity',lambda _:pytest.fail('navigation inspected QQ'))
    monkeypatch.setattr(source,'runtime_files',lambda:pytest.fail('navigation touched runtime'))
    monkeypatch.setattr(source,'_discovery_locations',lambda:pytest.fail('passive navigation discovered profiles'))
    facade=build_facade();window=MainWindow(facade)
    try:
        window.show_qq_workspace()
        workspace=window.qq_workspace
        assert isinstance(workspace,QQWorkspace)
        assert facade.get_qq_qrcode_path() is None
        assert not hasattr(workspace,'_group')
        assert not workspace.session_panel.isEnabled()
        assert workspace._qq_connect_button.text()=='连接 QQ'
        assert workspace._qq_settings_button.isHidden()
        assert workspace._qq_qrcode_label.isHidden()
        from PySide6.QtWidgets import QLineEdit
        assert not workspace._connection_surface.findChildren(QLineEdit)
    finally:
        window.close();window.await_shutdown(10)


def test_unclassified_null_body_is_not_silently_excluded(prepared):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40012"=99 WHERE "40001"=41')
        db.commit()
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    with pytest.raises(source.QQIndependentError):
        with service.acquired_session('group:partition-a'):pytest.fail('unclassified row published')
    assert service._payload is None


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
        # The source remains owned by the Facade even while a worker is pending.
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


def test_gui_guided_flow_group_private_dates_reports_and_release(qt_app,prepared,monkeypatch,tmp_path):
    import time
    from qq_chat_analyzer.gui.main_window import MainWindow
    from PySide6.QtCore import QDate
    from dataclasses import replace
    service,selection,dbroot=prepared
    other=tmp_path/'100000003';other_db=other/'nt_qq/nt_db'
    shutil.copytree(dbroot,other_db)
    with closing(sqlite3.connect(other_db/'nt_msg.db')) as db:
        for table in ('group_msg_table','c2c_msg_table'):
            db.execute(f'UPDATE {table} SET "40033"=CASE "40033" WHEN 100000001 THEN 100000003 WHEN 100000002 THEN 100000004 ELSE "40033" END')
            db.execute(f'UPDATE {table} SET "40800"=? WHERE "40800" IS NOT NULL',
                       (synthetic_text_message_blob('SECOND_ACCOUNT_SENTINEL walking beside the orchard today'),))
        db.commit()
    with closing(sqlite3.connect(other_db/'group_info.db')) as db:
        for table in ('group_list','group_detail_info_ver1'):
            db.execute(f'UPDATE {table} SET "60007"=?',('Second account orchard',))
        db.commit()
    original_capture=service._run_capture
    progress_phases=[]
    def capture(report,external):
        original_capture(lambda value:(progress_phases.append(value['phase']),report(value)),external)
        report({'phase':'awaiting_exit','message':'Fictional QQ exit required'})
        report({'phase':'authenticating','message':'Fictional QQ has exited'})
    monkeypatch.setattr(service,'_run_capture',capture)
    def wait_for(predicate):
        end=time.monotonic()+10
        while not predicate() and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert predicate(), (statuses, dialogs, window.qq_workspace._qq_login_guide_label.text())
    window=MainWindow(facade_for(service))
    opened=[]
    window.show();qt_app.processEvents()
    window._report_opener=lambda path:opened.append(path) or True
    outcomes=[];window.qq_workspace.analysis_succeeded.connect(outcomes.append)
    statuses=[];window.qq_workspace.status_changed.connect(statuses.append)
    try:
        assert window.stack.currentWidget() is window.home_page
        window.home_page._qq_btn.click();w=window.qq_workspace
        assert w._qq_connect_button.isVisible() and service._root is None
        assert not statuses or '现在可以登录 QQ' not in statuses
        # Drive the actual standard account, consent and identity dialogs.
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QInputDialog,QMessageBox,QComboBox
        dialogs=[];selected=[other.name]
        def answer():
            modal=qt_app.activeModalWidget()
            if isinstance(modal,QInputDialog):
                combo=modal.findChild(QComboBox)
                if combo is not None:
                    assert combo.count()==2
                    combo.setCurrentText(selected[0])
                    dialogs.append('account')
                else:
                    assert '并非 QQ 系统认证' in modal.labelText()
                    assert modal.textValue()==selected[0]
                    assert 'armed' in progress_phases
                    dialogs.append('identity')
                modal.accept()
            elif isinstance(modal,QMessageBox):
                assert selected[0] in modal.text()
                dialogs.append('consent')
                modal.button(QMessageBox.StandardButton.Yes).click()
        dialog_timer=QTimer(window);dialog_timer.setInterval(5);dialog_timer.timeout.connect(answer);dialog_timer.start()
        w._qq_connect_button.click()
        wait_for(lambda:w._sessions_loaded and not w._independent.running)
        assert dialogs==['account','consent','identity']
        assert progress_phases==['armed'] and '现在可以登录 QQ' in statuses
        assert '请完全退出 QQ' in statuses and '正在读取聊天记录' in statuses
        assert w._progress_track.isHidden() and w._qq_qrcode_label.isHidden()
        assert w._qq_guide_label.isHidden() and w._connection_bar.isVisible()
        panel=w.session_panel
        assert panel._session_list.count()==3
        original=panel.build_config
        monkeypatch.setattr(panel,'build_config',lambda:replace(original(),output_directory=tmp_path/'gui-report'))
        from qq_chat_analyzer.gui.session_analysis_panel import SESSION_ID_ROLE
        for session_id in ('group:partition-a','private:private-a'):
            for index in range(panel._session_list.count()):
                if panel._session_list.item(index).data(SESSION_ID_ROLE)==session_id:panel._session_list.setCurrentRow(index);break
            wait_for(lambda:panel._message_range is not None)
            if session_id.startswith('private'):
                panel._scope_custom.setChecked(True)
                panel._start_date.setDate(QDate(2025,10,10));panel._end_date.setDate(QDate(2025,10,11))
            panel._analyze_button.click()
            wait_for(lambda:not panel._analysis_running)
            assert outcomes and outcomes[-1].report_path.is_file()
            assert outcomes[-1].echo_report_view.self_identity_basis=='user_declared'
            report=json.loads((outcomes[-1].report_path.parent/'echo-report.json').read_text(encoding='utf-8'))
            assert report['conversation']['kind']==('private' if session_id.startswith('private') else 'group')
            assert report['self_identity']=={'basis':'user_declared','system_authenticated':False}
            with service.acquired_session(session_id) as acquired:
                raw=acquired.payload_path.read_text()
                assert json.loads(raw)['self']['value']==other.name
                from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
                messages,_=parse_qq_db_rich_messages(json.loads(raw))
                assert all('SECOND_ACCOUNT_SENTINEL' in m.contents[0].text for m in messages)
        assert len(outcomes)==2 and outcomes[-1].echo_report_view.total_message_count==2
        assert opened==[outcome.report_path.resolve() for outcome in outcomes]
        window.show_qq_workspace()
        w._qq_disconnect_button.click();wait_for(lambda:not w._independent.running)
        assert service._root is None and not w._sessions_loaded
        selected[0]=selection.account
        w._qq_connect_button.click()
        wait_for(lambda:w._sessions_loaded and not w._independent.running)
        assert service._selection.account==selection.account
        assert dialogs==['account','consent','identity']*2
        dialog_timer.stop()
        with service.acquired_session('group:partition-a') as acquired:
            assert 'SECOND_ACCOUNT_SENTINEL' not in acquired.payload_path.read_text()
    finally:
        window.close();assert window.await_shutdown(10)


@pytest.mark.parametrize('completed',[False,True])
def test_gui_cancel_queued_or_completed_acquisition_cannot_publish_stale_state(qt_app,prepared,monkeypatch,completed):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from PySide6.QtWidgets import QMessageBox
    service,selection,_=prepared;tasks=[]
    from qq_chat_analyzer.gui.qq_independent_connection import QQIndependentConnection
    monkeypatch.setattr(QQIndependentConnection,'_authorize',lambda *a:True)
    def queued(operation,**callbacks):tasks.append((operation,callbacks))
    widget=QQWorkspace(facade_for(service),executor=queued)
    widget._qq_connect_button.click()
    operation,callbacks=tasks.pop(0)
    callbacks['on_success'](operation());callbacks['on_finished']()
    operation,callbacks=tasks.pop(0)
    result=operation(lambda _:None) if completed else None
    widget._qq_connect_button.click()
    if completed:callbacks['on_success'](result)
    else:
        with pytest.raises(FacadeError) as refused:operation(lambda _:None)
        callbacks['on_error'](refused.value.code,refused.value.public_message)
    callbacks['on_finished']()
    cleanup,callbacks=tasks.pop(0)
    callbacks['on_success'](cleanup());callbacks['on_finished']()
    assert service._root is None and not widget._sessions_loaded and not widget.session_panel.isEnabled()
    assert widget._qq_connect_button.isEnabled() and not tasks
    widget.close()


@pytest.mark.parametrize('fault',['normal_qq_exit_required','capture_refused','capture_deadline','cancel'])
def test_gui_failed_or_cancelled_capture_returns_to_selection_without_sessions(qt_app,prepared,monkeypatch,fault):
    import time
    from qq_chat_analyzer.gui.main_window import MainWindow
    service,selection,_=prepared;entered=Event()
    from PySide6.QtWidgets import QMessageBox
    from qq_chat_analyzer.gui.qq_independent_connection import QQIndependentConnection
    monkeypatch.setattr(QQIndependentConnection,'_authorize',lambda *a:True)
    def capture(report,external):
        report({'phase':'awaiting_exit','message':'Fictional exit is pending'})
        entered.set()
        if fault=='cancel':
            end=time.monotonic()+5
            while not service._cancelled(external.is_set) and time.monotonic()<end:time.sleep(.005)
            assert service._cancelled(external.is_set)
        raise SourceError(fault)
    monkeypatch.setattr(service,'_run_capture',capture)
    def wait_for(predicate):
        end=time.monotonic()+10
        while not predicate() and time.monotonic()<end:qt_app.processEvents();time.sleep(.005)
        assert predicate()
    window=MainWindow(facade_for(service))
    try:
        window.home_page._qq_btn.click();w=window.qq_workspace
        w._qq_connect_button.click()
        if fault=='cancel':wait_for(entered.is_set);w._qq_connect_button.click()
        wait_for(lambda:not w._independent.running)
        assert not w._sessions_loaded and service._root is None and not service.check_status().available
        from qq_chat_analyzer.gui.session_analysis_panel import SESSION_ID_ROLE
        listing=w.session_panel._session_list
        assert not any(listing.item(index).data(SESSION_ID_ROLE) for index in range(listing.count()))
        assert not w.session_panel.isEnabled()
        assert w._qq_connect_button.isEnabled()
        assert 'Traceback' not in w._qq_login_guide_label.text()
    finally:
        window.close();assert window.await_shutdown(10)


@pytest.mark.parametrize('outcome',['appears','ambiguous','cancel','timeout'])
def test_automatic_process_wait_never_opens_databases_or_starts_capture(prepared,monkeypatch,outcome):
    service,selection,_=prepared
    service.prepare(selection)
    event=Event();progress=[];calls=[]
    def candidates():
        calls.append(True)
        assert not list(service._root.glob('*.db'))
        if outcome=='cancel':event.set()
        return ([{},{}] if outcome=='ambiguous' else [{}] if outcome=='appears' else [])
    monkeypatch.setattr(service,'_process_candidates',candidates)
    clock=iter([0,121])
    if outcome=='timeout':
        from types import SimpleNamespace
        monkeypatch.setattr(source,'time',SimpleNamespace(monotonic=lambda:next(clock,121)))
    if outcome=='appears':
        service._wait_for_process(progress.append,event)
    else:
        with pytest.raises(source.QQIndependentError) as refused:
            service._wait_for_process(progress.append,event)
        assert refused.value.code=={'ambiguous':'qq_process_selection_required',
            'cancel':'analysis_cancelled','timeout':'qq_process_timeout'}[outcome]
    assert calls and progress==[{'phase':'waiting_for_qq'}]
    assert service._generation_handle is None and service._worker is None


@pytest.mark.parametrize('stop',['missing','consent','identity','wrong_identity'])
def test_formal_connection_recovers_without_publishing_sessions(qt_app,prepared,monkeypatch,stop):
    import time
    from PySide6.QtWidgets import QInputDialog
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.gui.qq_independent_connection import QQIndependentConnection
    service,selection,_=prepared
    if stop=='missing':monkeypatch.setattr(source,'_discovery_locations',lambda:([],[]))
    monkeypatch.setattr(QQIndependentConnection,'_authorize',lambda *a:stop!='consent')
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:('999999999',stop=='wrong_identity'))
    widget=QQWorkspace(facade_for(service))
    try:
        widget._qq_connect_button.click()
        end=time.monotonic()+5
        while widget._independent.running and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert not widget._independent.running and not widget._sessions_loaded
        assert service._root is None and widget._qq_connect_button.isEnabled()
        assert not widget.session_panel.isEnabled()
        assert widget._qq_settings_button.isHidden()==(stop in {'consent','identity'})
        if stop=='missing':assert service._selection is None
    finally:
        widget._closing=True;widget.cancel_connection();widget.close()


def test_wrong_declaration_and_private_ambiguity_refuse_before_list(prepared):
    service,selection,dbroot=prepared
    service.prepare(selection);service.capture()
    with pytest.raises(source.QQIndependentError):service.confirm_account('100000009')
    assert service._root is None and not service.list_sessions()
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE c2c_msg_table SET "40033"=100000003 WHERE "40001"=100');db.commit()
    service.prepare(selection);service.capture()
    with pytest.raises(source.QQIndependentError):service.confirm_account(selection.account)
    assert service._root is None and not service.list_sessions()


def test_explicit_account_switch_replaces_snapshot_without_reading_siblings(prepared,tmp_path,monkeypatch):
    service,selection,dbroot=prepared;facade=facade_for(service)
    other=tmp_path/'100000003';other_db=other/'nt_qq/nt_db'
    shutil.copytree(dbroot,other_db)
    with closing(sqlite3.connect(other_db/'nt_msg.db')) as db:
        for table in ('group_msg_table','c2c_msg_table'):
            db.execute(f'UPDATE {table} SET "40033"=CASE "40033" WHEN 100000001 THEN 100000003 WHEN 100000002 THEN 100000004 ELSE "40033" END')
            db.execute(f'UPDATE {table} SET "40800"=? WHERE "40800" IS NOT NULL',
                       (synthetic_text_message_blob('SECOND_ACCOUNT_SENTINEL'),))
        db.commit()
    # A third, unusable candidate must not affect either explicit selection.
    forbidden=tmp_path/'100000005';forbidden.mkdir()
    (forbidden/'unreadable.db').write_bytes(b'not a database')
    selected=selection.account_directory
    opened=[];original_open=Path.open;original_iterdir=Path.iterdir;original_builtin_open=builtins.open
    def guard(path):
        assert not path.is_relative_to(forbidden)
        for candidate in (selection.account_directory,other):
            if candidate!=selected:assert not path.is_relative_to(candidate)
    def open_selected(path,*args,**kwargs):
        guard(path);opened.append(path);return original_open(path,*args,**kwargs)
    def open_file(path,*args,**kwargs):
        if isinstance(path,(str,Path)):
            guard(Path(path));opened.append(Path(path))
        return original_builtin_open(path,*args,**kwargs)
    def list_selected(path):
        guard(path)
        assert path!=tmp_path, 'account discovery must not scan the accounts parent'
        return original_iterdir(path)
    monkeypatch.setattr(Path,'open',open_selected);monkeypatch.setattr(Path,'iterdir',list_selected)
    monkeypatch.setattr(builtins,'open',open_file)
    # A common parent is not authorization for all its account candidates.
    with pytest.raises(FacadeError):facade.prepare_independent_qq(selection.executable,tmp_path)
    facade.prepare_independent_qq(selection.executable,selected)
    facade.start_qq_auth_flow();facade.confirm_independent_qq_account(selection.account)
    first_root=service._root
    with service.acquired_session('group:partition-a') as acquired:
        assert 'SECOND_ACCOUNT_SENTINEL' not in acquired.payload_path.read_text()
    selected=other
    facade.prepare_independent_qq(selection.executable,selected)
    assert not first_root.exists() and facade.list_sessions(ChatSource.QQ)==[]
    facade.start_qq_auth_flow()
    assert facade.list_sessions(ChatSource.QQ)==[]
    facade.confirm_independent_qq_account(other.name)
    assert len(facade.list_sessions(ChatSource.QQ))==3
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
    from qq_chat_analyzer.rich_message import TextContent
    for session_id in ('group:partition-a','private:private-a'):
        with service.acquired_session(session_id) as acquired:
            payload=json.loads(acquired.payload_path.read_text())
            assert payload['self']=={'namespace':'qq_uin','value':other.name,'basis':'user_declared'}
            messages,_=parse_qq_db_rich_messages(payload)
            assert len(messages)==4 and {m.is_self for m in messages}=={True,False}
            assert all(m.contents==(TextContent('SECOND_ACCOUNT_SENTINEL'),) for m in messages)
            assert {m.sender.identity_id for m in messages}=={'100000003','100000004'}
    assert any(path.is_relative_to(selection.account_directory) for path in opened)
    assert any(path.is_relative_to(other) for path in opened)


def test_declaration_gate_keeps_unknown_sender_and_names_unknown(prepared):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40033"=0 WHERE "40001"=0');db.commit()
    with closing(sqlite3.connect(dbroot/'group_info.db')) as db:
        db.execute('DELETE FROM group_member3');db.commit()
    with closing(sqlite3.connect(dbroot/'profile_info.db')) as db:
        db.executescript('DELETE FROM profile_info_v2; DELETE FROM profile_info_v6;');db.commit()
    service.prepare(selection)
    with pytest.raises(source.QQIndependentError):service.confirm_account(selection.account)
    assert not service.list_sessions()
    service.capture()
    assert not service.list_sessions() and not service.check_status().available
    with pytest.raises(source.QQIndependentError):
        with service.acquired_session('group:partition-a'):pytest.fail('declaration required')
    # Authentication and a directory label alone cannot authorize self statistics.
    service.confirm_account(selection.account)
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
    with service.acquired_session('group:partition-a') as acquired:
        payload=json.loads(acquired.payload_path.read_text())
        assert payload['self']['basis']=='user_declared'
        messages,_=parse_qq_db_rich_messages(payload)
        assert [m.is_self for m in messages]==[None,False,True,False]
        assert messages[0].sender.identity_id is None and messages[0].sender.display_name==''
        assert service.names_summary['named_members']==0
        assert all(m.sender.nickname is None for m in messages)


def test_snapshot_cleanup_preserves_consumer_facade_error(prepared):
    service,selection,_=prepared
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    error=FacadeError(code='analysis_cancelled',public_message='Fictional cancellation')
    with pytest.raises(FacadeError) as refused:
        with service.acquired_session('group:partition-a'):
            raise error
    assert refused.value is error and service._root is None


def test_payload_cleanup_failure_blocks_reuse_and_retains_owner(prepared,monkeypatch):
    service,selection,_=prepared
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    root=service._root;unlink=Path.unlink
    def fail_payload(path,*args,**kwargs):
        if path==root/'payload.json':raise OSError('fictional payload cleanup failure')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',fail_payload)
    with pytest.raises(OSError):
        with service.acquired_session('group:partition-a'):pass
    assert (root/'owner.json').exists() and service._lease is not None
    with pytest.raises(source.QQIndependentError):service.list_sessions()
    monkeypatch.setattr(Path,'unlink',unlink)
    service.disconnect();assert not root.exists()


@pytest.mark.slow_integration
@pytest.mark.parametrize('fault',['none','metadata_key','account_key','shared_key','cancel','sidecar'])
def test_offline_worker_protocol_authenticates_only_after_exit(prepared,monkeypatch,tmp_path,fault):
    """Real Node protocol/codec and Windows locks; only QQ/native transport is fictional."""
    from types import SimpleNamespace
    from qq_chat_analyzer.providers.qq_independent import worker,snapshot
    from test_qq_direct_main_wal_poc import _reserve_48_bytes
    service,selection,dbroot=prepared
    seed=tmp_path/'seed';seed.mkdir()
    for name in ('nt_msg.db','group_info.db','profile_info.db'):
        destination=seed/name;_reserve_48_bytes(destination)
        with closing(sqlite3.connect(dbroot/name)) as original, closing(sqlite3.connect(destination)) as db:
            db.executescript('\n'.join(original.iterdump()))
    other=tmp_path/'100000002'/'nt_qq/nt_db';other.mkdir(parents=True)
    runtime=tmp_path/'fixture-runtime';runtime.mkdir()
    pins={}
    for name in ('echo_event_loader.exe','echo_event_54395.dll'):
        (runtime/name).write_bytes(b'fictional transport only')
        pins[name]=hashlib.sha256((runtime/name).read_bytes()).hexdigest()
    (runtime/'build-receipt.json').write_text(json.dumps({'build':'9.9.37-54395',
        'minhook_revision':'c3fcafdc10146beb5919319d0683e44e3c30d537','binaries':pins}))
    encoder=(Path(__file__).resolve().parents[1]/'scripts/spikes/qq_independent_codec.mjs').as_uri()
    shim=tmp_path/'native-fixture.mjs'
    shim.write_text('''import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {EventEmitter} from 'node:events';
import {PassThrough,Writable} from 'node:stream';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {randomBytes,pbkdf2Sync} from 'node:crypto';
import {encode} from ENCODER;
const secret=randomBytes(24).map(b=>97+b%26),buffers=[secret];
for(const name of ['nt_msg.db','group_info.db','profile_info.db']){
  const plain=readFileSync(join(SEED,name)),salt=randomBytes(16);
  const pass=FAULT==='account_key'||FAULT==='metadata_key'&&name==='profile_info.db'?randomBytes(24):secret;
  const key=pbkdf2Sync(pass,salt,4000,32,'sha512'),encrypted=encode(plain,key,salt);
  writeFileSync(join(SOURCE,name),encrypted);key.fill(0);encrypted.fill(0);
  if(pass!==secret)pass.fill(0);
  // Another account matches the captured credential, even when the selected
  // account does not. The product must never discover or try this sibling.
  const otherPass=['account_key','shared_key'].includes(FAULT)?secret:randomBytes(24);
  const otherKey=pbkdf2Sync(otherPass,salt,4000,32,'sha512'),otherEncrypted=encode(plain,otherKey,salt);
  writeFileSync(join(OTHER,name),otherEncrypted);
  plain.fill(0);otherKey.fill(0);otherEncrypted.fill(0);salt.fill(0);
  if(otherPass!==secret)otherPass.fill(0);
}
function field(n,b){return Buffer.concat([Buffer.from([n*8+2,b.length]),b]);}
const inner=field(1,secret),body=field(2,inner);
const packet=Buffer.concat([Buffer.from([8,0xde,0x19,16,2,24,0]),field(4,body)]);
buffers.push(inner,body,packet);secret.fill(0);
childProcess.spawn=()=>{
  const child=new EventEmitter();child.stdout=new PassThrough();
  child.kill=()=>{};child.stdin=new Writable({write(_data,_encoding,done){done();}});
  function emit(kind,payload){const head=Buffer.alloc(16);head.writeUInt32LE(0x32535145);head.writeUInt32LE(kind,4);head.writeUInt32LE(payload.length,8);child.stdout.write(Buffer.concat([head,payload]));}
  setImmediate(()=>{
    emit(1,Buffer.alloc(0));emit(2,packet);
    const stopped=Buffer.alloc(16);stopped.writeUInt32LE(1);stopped.writeUInt32LE(1,4);stopped.writeUInt32LE(1,12);
    emit(3,stopped);child.stdout.end();child.exitCode=0;child.emit('close',0);
  });return child;
};
syncBuiltinESMExports();
process.once('exit',()=>{for(const b of buffers)b.fill(0);});
'''.replace('ENCODER',json.dumps(encoder)).replace('SEED',json.dumps(str(seed)))
        .replace('SOURCE',json.dumps(str(dbroot))).replace('OTHER',json.dumps(str(other)))
        .replace('FAULT',json.dumps(fault)),encoding='utf-8')
    original_open=Path.open;original_iterdir=Path.iterdir;original_prepare=snapshot.prepare
    frozen_sources=[];outside_scope=[]
    def assert_scope(path):
        if path==tmp_path or path.is_relative_to(other.parents[1]):
            outside_scope.append(path)
            raise AssertionError('unauthorized account access')
    def scoped_open(path,*args,**kwargs):
        assert_scope(path)
        return original_open(path,*args,**kwargs)
    def scoped_iterdir(path):
        assert_scope(path)
        return original_iterdir(path)
    def scoped_prepare(path,parent):
        if path.parent!=dbroot:
            outside_scope.append(path)
            raise AssertionError('unauthorized snapshot')
        frozen_sources.append(path.name)
        return original_prepare(path,parent)
    monkeypatch.setattr(Path,'open',scoped_open);monkeypatch.setattr(Path,'iterdir',scoped_iterdir)
    monkeypatch.setattr(snapshot,'prepare',scoped_prepare)
    exited=False;statuses=[];cancel=Event()
    def assert_exited():
        assert exited, 'snapshot attempted before fictional QQ exit'
    monkeypatch.setattr(snapshot,'assert_qq_exited',assert_exited)
    api=SimpleNamespace(WaitForSingleObject=lambda _handle,_timeout:0 if exited else 258)
    @contextmanager
    def process(*_args,**_kwargs):yield api,7
    monkeypatch.setattr(worker,'verified_process',process)
    monkeypatch.setattr(worker,'process_creation_ticks',lambda *_:7)
    monkeypatch.setattr(worker,'loaded_module',lambda *_:(1,True))
    monkeypatch.setattr(worker,'runtime_files',lambda:(runtime,pins))
    monkeypatch.setattr(worker,'resources_identity',lambda image:(SimpleNamespace(wrapper_path=image),((str(image),'a'*64),)))
    popen=worker.subprocess.Popen;node=shutil.which('node')
    assert node
    children=[]
    def launch(command,**options):
        # No native executable or real QQ can be launched by this test.
        assert str(command[0])==str(runtime/'node.exe')
        options['stderr']=worker.subprocess.PIPE
        child=popen([node,'--import',shim.as_uri(),*command[1:]],**options);children.append(child);return child
    monkeypatch.setattr(worker,'subprocess',SimpleNamespace(Popen=launch,PIPE=worker.subprocess.PIPE,
        DEVNULL=worker.subprocess.DEVNULL,CREATE_NO_WINDOW=worker.subprocess.CREATE_NO_WINDOW))
    def observe(value):
        nonlocal exited
        statuses.append(value['phase'])
        if value['phase']=='awaiting_exit':
            assert not list(service._root.glob('*.db'))
            if fault=='cancel':cancel.set()
            else:exited=True
            if fault=='sidecar':Path(str(dbroot/'nt_msg.db')+'-wal').write_bytes(b'fictional sidecar')
    def capture(_progress,_external):
        try:
            worker.capture({'image':str(selection.executable),'pid':7,'created':7,
                'account_directory':str(selection.account_directory),'root':str(service._root)},cancel.is_set,observe)
        except Exception as error:
            if fault in ('none','shared_key'):pytest.fail(f"worker={type(error).__name__}, code={getattr(error,'code',None)}, phases={statuses}, node={children[-1].stderr.read().decode('utf-8',errors='replace')[-1500:]}")
            raise
    monkeypatch.setattr(service,'_run_capture',capture)
    service.prepare(selection)
    try:
        if fault in ('none','shared_key'):
            service.capture();service.confirm_account(selection.account)
            assert len(service.list_sessions())==3
            assert statuses.index('stopped')<statuses.index('awaiting_exit')<statuses.index('authenticating')
            with service.acquired_session('private:private-a') as acquired:
                assert len(json.loads(acquired.payload_path.read_text())['records'])==4
        else:
            with pytest.raises(source.QQIndependentError):service.capture()
            assert service._root is None and not service.list_sessions()
        if fault not in ('cancel','sidecar'):
            assert frozen_sources==['nt_msg.db','group_info.db','profile_info.db']
        assert not outside_scope
        assert children and all(child.poll() is not None for child in children)
    finally:
        for child in children:
            if child.poll() is None:child.kill();child.wait(timeout=3)
            child.stderr.close()


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
    service.capture();service.confirm_account(selection.account)
    session=next(s for s in facade.list_sessions(ChatSource.QQ) if s.session_id=='group:partition-a')
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
    assert service._payload is None and service._root is not None
