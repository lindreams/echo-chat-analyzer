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
from qq_chat_analyzer.application.qq.qq_independent_service import _discovery_locations as actual_locations
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
from qq_chat_analyzer.providers.qq_independent.files import SourceError
from qq_chat_analyzer.providers.qq_independent.snapshot import bind_live_database_paths
from qq_chat_analyzer.providers.qq_independent.snapshot import authorized_group_partition, authorized_group_partitions


@pytest.mark.parametrize('fault',[
    None, 'zero_only', 'null_number', 'real_number', 'blob_number', 'object_conflict',
    'null_object', 'second_partition', 'mixed_key_storage', 'missing', 'zero_key',
    'legacy', 'legacy_zero',
])
def test_batch_partition_validation_preserves_single_session_proofs(tmp_path,fault):
    path=tmp_path/'fictional.db'
    has_object=fault not in ('legacy','legacy_zero')
    rows=[('partition-a',900000001,900000001,10),('partition-a',0,900000001,20),
          ('partition-b',900000002,900000002,30)]
    if fault=='zero_only':rows[0]=('partition-a',0,900000001,10)
    elif fault in ('null_number','real_number','blob_number','object_conflict','null_object'):
        number={'null_number':None,'real_number':900000001.0,'blob_number':b'900000001'}.get(fault,900000001)
        obj=None if fault=='null_object' else 900000002 if fault=='object_conflict' else 900000001
        rows.append(('partition-a',number,obj,40))
    elif fault=='second_partition':rows.append(('partition-c',900000001,900000001,40))
    elif fault=='mixed_key_storage':rows[:2]=[('123',900000001,900000001,10),(123,0,900000001,20)]
    elif fault=='missing':rows=rows[-1:]
    elif fault=='zero_key':rows[:2]=[('0',900000001,900000001,10),('0',0,900000001,20)]
    elif fault=='legacy':rows[1]=('partition-a',900000001,900000001,20)
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE group_msg_table ("40027","40030",'+('"40021",' if has_object else '')+'"40050","40800")')
        db.executemany('INSERT INTO group_msg_table VALUES ('+','.join('?' for _ in range(5 if has_object else 4))+')',
            [(*row,None) if has_object else (row[0],row[1],row[3],None) for row in rows])
        db.commit()
    original=path.read_bytes()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        # These proofs must never read a message body or weaken query_only.
        def guard(action,table,column,*_):
            if action==sqlite3.SQLITE_READ and column=='40800':return sqlite3.SQLITE_DENY
            if action==sqlite3.SQLITE_PRAGMA and table=='query_only' and column is not None:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(guard)
        valid=fault in (None,'zero_only','legacy')
        if valid:
            expected={g:authorized_group_partition(db,g,lambda _:None) for g in ('900000001','900000002')}
            assert authorized_group_partitions(db,expected)==expected
            assert expected['900000001'][1:]==(2,10,20)
        else:
            code='authorized_session_missing_or_ambiguous' if fault in ('second_partition','missing','zero_key') else 'authorized_partition_mismatch'
            for call in (lambda:authorized_group_partition(db,'900000001',lambda _:None),
                         lambda:authorized_group_partitions(db,['900000001','900000002'])):
                with pytest.raises(SourceError) as refused:call()
                assert refused.value.code==code
        assert db.execute('PRAGMA query_only').fetchone()==(1,)
    assert path.read_bytes()==original


def test_batch_partition_validation_handles_large_lists_and_cancellation(tmp_path):
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute('CREATE TABLE group_msg_table ("40027","40030","40021","40050")')
        groups=[str(900000000+i) for i in range(401)]
        db.executemany('INSERT INTO group_msg_table VALUES (?,?,?,?)',[(f'key-{g}',g,g,1) for g in groups])
        db.execute('PRAGMA query_only=ON')
        assert set(authorized_group_partitions(db,groups))==set(groups)
        assert authorized_group_partitions(db,[])=={}
        db.set_progress_handler(lambda:1,1)
        with pytest.raises(sqlite3.OperationalError,match='interrupted'):
            authorized_group_partitions(db,groups)


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
    monkeypatch.setattr(source,'_discovery_locations',lambda **_options:([tmp_path],[image]))
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
    monkeypatch.setattr(service,'_process_candidates',lambda **options:[] if options.get('include_children') else [{'ProcessId':123,'ExecutablePath':str(image)}])
    selection=source.QQIndependentSelection(image,account,'100000001',False)
    yield service,selection,dbroot
    assert service.shutdown() is ShutdownStatus.SUCCESS
    assert not list((tmp_path/'owned').glob('run-*')) if (tmp_path/'owned').exists() else True


def facade_for(service):
    return ChatAnalyzerFacade(qq_service=service,qq_connection_service=service,independent_qq=True,
                              analysis_service=AnalysisApplicationService())


def test_configured_root_replaces_stale_default_and_loads_all_conversations(qt_app,prepared,tmp_path,monkeypatch,caplog):
    import time,winreg
    from PySide6.QtWidgets import QInputDialog
    from qq_chat_analyzer.gui.main_window import MainWindow
    from qq_chat_analyzer.application.qq import qq_auth_bridge
    service,selection,dbroot=prepared
    custom=tmp_path/'custom-storage';account=custom/selection.account;database=account/'nt_qq/nt_db'
    shutil.copytree(dbroot,database)
    with closing(sqlite3.connect(database/'nt_msg.db')) as db:
        for i in range(23):
            db.execute('INSERT INTO group_msg_table VALUES (?,?,?,?,?,?,?,?,?)',
                (1000+i,'group-extra-'+str(i),900001000+i,900001000+i,100000001,1760000000+i,
                 synthetic_text_message_blob('Fictional extra conversation'),1,0))
        for i in range(24):
            db.execute('INSERT INTO c2c_msg_table VALUES (?,?,?,?,?,?,?)',
                (2000+i,'private-extra-'+str(i),100001000+i,100001000+i,100001000+i,1760000000+i,
                 synthetic_text_message_blob('Fictional extra private conversation')))
        db.commit()
    with closing(sqlite3.connect(database/'group_info.db')) as db:
        for i in range(23):
            for table in ('group_list','group_detail_info_ver1'):
                db.execute(f'INSERT INTO {table} VALUES (?,?)',(900001000+i,'Fictional group '+str(i)))
        db.commit()
    old=Path.home()/'Documents/Tencent Files'/selection.account/'nt_qq/nt_db';old.mkdir(parents=True)
    for name in ('nt_msg.db','group_info.db','profile_info.db'):(old/name).write_bytes(b'OLD_PARTIAL_DATABASE_MUST_NOT_BE_OPENED')
    common=tmp_path/'common';config=common/'Tencent/QQ/UserDataInfo.ini';config.parent.mkdir(parents=True)
    config.write_text('[UserDataSet]\nUserDataSavePathType=2\nUserDataSavePath='+str(custom)+'\n',encoding='utf-8-sig')
    def folders(_owner,kind,_token,_flags,buffer):
        assert kind in (0x28,0x2e)
        buffer.value=str(Path.home() if kind==0x28 else common);return 0
    monkeypatch.setattr(source.ctypes.windll.shell32,'SHGetFolderPathW',folders)
    def no_registry(*a):raise FileNotFoundError('fictional absent registry')
    monkeypatch.setattr(winreg,'OpenKey',no_registry)
    monkeypatch.setattr(qq_auth_bridge,'_qq_install_candidates',lambda:[selection.executable])
    for key in ('ProgramFiles','ProgramFiles(x86)','ProgramW6432','LOCALAPPDATA'):
        monkeypatch.setenv(key,str(tmp_path/key))
    monkeypatch.setattr(source,'_discovery_locations',actual_locations)
    assert actual_locations()[0]==[custom]
    assert facade_for(service).discover_independent_qq_profiles().accounts==(account,)
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:(selection.account,True))
    window=MainWindow(facade_for(service));window.show()
    try:
        window.home_page._qq_btn.click();workspace=window.qq_workspace;workspace._qq_connect_button.click()
        end=time.monotonic()+15
        while not workspace._sessions_loaded and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert workspace._sessions_loaded
        assert service._selection.account_directory==account and workspace.session_panel._session_list.count()==50
        sessions=service.list_sessions()
        assert sum(s.session_type=='group' for s in sessions)==25
        assert sum(s.session_type=='private' for s in sessions)==25
    finally:
        window.close();assert window.await_shutdown(10)


@pytest.mark.parametrize('value',['relative-path','',None])
def test_bad_configured_location_never_falls_back_to_old_database(tmp_path,value):
    config=tmp_path/'UserDataInfo.ini'
    config.write_text('[UserDataSet]\nUserDataSavePathType=2\n'+('UserDataSavePath='+value if value is not None else ''),encoding='utf-8')
    with pytest.raises(source.QQIndependentError) as refused:source._configured_data_root(config)
    assert refused.value.code=='qq_data_location_unverified'


def test_long_workspace_refuses_before_capture_or_private_files(prepared,tmp_path,monkeypatch):
    _,selection,_=prepared
    parent=tmp_path/('p'*120)
    service=source.QQIndependentService(workspace=parent)
    monkeypatch.setattr(service,'_run_capture',lambda *a:pytest.fail('capture started for unsupported path'))
    try:
        with pytest.raises(source.QQIndependentError) as refused:service.prepare(selection)
        assert refused.value.code=='qq_workspace_path_too_long'
        assert service._root is None and service._lease is None and not parent.exists()
    finally:service.shutdown()


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
    monkeypatch.setattr(source,'_discovery_locations',lambda **_options:([],[selection.executable,old,broken,selection.executable]))
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
    service,selection,_=prepared;tasks=[]
    widget=QQWorkspace(facade_for(service),executor=lambda operation,**callbacks:tasks.append(operation))
    flow=widget._independent
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:pytest.fail('normal connection opened file picker'))
    flow._discovered(source.QQIndependentDiscovery((selection.account_directory,),(selection.executable,)))
    assert flow._image==selection.executable and flow._account==selection.account_directory
    assert len(tasks)==1 and service._root is None
    widget.close()


def test_single_account_connects_without_consent_or_identity_prompts(qt_app,prepared,monkeypatch):
    import time
    from PySide6.QtWidgets import QInputDialog,QMessageBox
    from qq_chat_analyzer.gui.main_window import MainWindow
    service,selection,_=prepared
    def unexpected(*a,**k):pytest.fail('single-account connection opened a modal prompt')
    monkeypatch.setattr(QInputDialog,'getText',unexpected)
    monkeypatch.setattr(QInputDialog,'getItem',unexpected)
    monkeypatch.setattr(QMessageBox,'exec',unexpected)
    window=MainWindow(facade_for(service));window.show()
    try:
        window.home_page._qq_btn.click();w=window.qq_workspace
        assert not hasattr(w,'_qq_media_option')
        w._qq_connect_button.click()
        end=time.monotonic()+10
        while not w._sessions_loaded and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert w._sessions_loaded and w.session_panel._session_list.count()==3
        assert service._confirmed==selection.account and service._selection.recover_media is True
        assert w._status_label.text()=='可以重新打开 QQ'
    finally:
        window.close();assert window.await_shutdown(10)


def test_connection_guidance_replaces_old_phases_and_ignores_late_events(qt_app,prepared):
    from datetime import datetime,timedelta,timezone
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    service,_,_=prepared;tasks=[]
    widget=QQWorkspace(facade_for(service),executor=lambda operation,**callbacks:tasks.append((operation,callbacks)))
    widget.show();flow=widget._independent
    try:
        widget._qq_connect_button.click()
        operation,callbacks=tasks.pop(0)
        callbacks['on_success'](operation());callbacks['on_finished']()
        _,capture=tasks.pop(0)
        report=capture['on_progress']
        armed={'phase':'armed','remaining_login_ms':10000,
               'login_before_utc':(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()}
        for phase,action in [('preparation_exit','请先完全退出 QQ'),('waiting_for_qq','请打开 QQ，先不要登录')]:
            report({'phase':phase});assert widget._qq_guide_label.text()==action
        report(armed)
        assert widget._qq_guide_label.text()=='现在可以登录 QQ' and flow._timer.isActive()
        report({'phase':'unknown'})
        assert flow._timer.isActive()
        report({'phase':'stopped'})
        assert widget._qq_guide_label.text()=='已收到登录信息' and not flow._timer.isActive()
        report({'phase':'awaiting_exit'})
        note=widget._qq_login_guide_label.text()
        report(armed);report({'phase':'stopped'});flow._login_tick()
        assert widget._qq_guide_label.text()=='请完全退出 QQ' and widget._qq_login_guide_label.text()==note
        report({'phase':'authenticating'})
        report({'phase':'awaiting_exit'})
        assert widget._qq_guide_label.text()=='正在读取聊天记录'
        assert widget._qq_login_guide_label.text()=='请稍候，无需操作。'
        assert '未连接' not in widget.session_panel._session_list.item(0).text()
        capture['on_success'](service.get_snapshot());capture['on_finished']()
        assert widget._qq_guide_label.text()=='正在加载聊天列表'
        report(armed)
        assert widget._qq_guide_label.text()=='正在加载聊天列表' and not flow._timer.isActive()
        _,listing=tasks.pop(0)
        listing['on_success']([]);listing['on_finished']()
        assert widget._qq_guide_label.isHidden() and widget._qq_login_guide_label.isHidden()
        assert not widget._qq_guide_label.text() and not widget._qq_login_guide_label.text()
        assert widget._session_loading.isHidden() and widget._qq_qrcode_label.isHidden()
    finally:
        widget._closing=True;widget.cancel_connection();widget.close()


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


@pytest.mark.parametrize('extra',[None,'file','directory','link'])
def test_cleanup_accepts_only_empty_windows_profile_scaffolding(prepared,tmp_path,extra):
    service,selection,_=prepared;service.prepare(selection);service.capture()
    root=service._root;roaming=root/'USERPROFILE/AppData/Roaming';roaming.mkdir(parents=True)
    if extra:
        unexpected=roaming/'unexpected'
        if extra=='file':unexpected.write_bytes(b'fictional unknown asset')
        elif extra=='directory':unexpected.mkdir()
        else:
            import subprocess
            target=tmp_path/'protected';target.mkdir();(target/'keep.txt').write_text('fictional protected')
            subprocess.run(['cmd','/c','mklink','/J',str(unexpected),str(target)],check=True,capture_output=True)
        with pytest.raises(SourceError):service.disconnect()
        assert service._root==root and (root/'owner.json').is_file() and (root/'message.db').is_file()
        if extra=='file':unexpected.unlink()
        else:unexpected.rmdir()  # Only this test's injected empty dir/junction.
        if extra=='link':assert (target/'keep.txt').read_text()=='fictional protected'
    service.disconnect()
    assert service._root is None and not root.exists()


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
    monkeypatch.setattr(source,'_discovery_locations',lambda **_options:pytest.fail('passive navigation discovered profiles'))
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


@pytest.mark.parametrize('missing',['tables','columns'])
def test_missing_optional_name_tables_keep_authenticated_conversations_available(prepared,missing):
    service,selection,dbroot=prepared
    for filename,tables in (
        ('profile_info.db',('profile_info_v2','profile_info_v6')),
        ('group_info.db',('group_list','group_detail_info_ver1','group_member3')),
    ):
        with closing(sqlite3.connect(dbroot/filename)) as db:
            for table in tables:
                if missing=='tables':db.execute(f'DROP TABLE "{table}"')
                elif table.startswith('profile_info') or table=='group_member3':
                    db.execute(f'ALTER TABLE "{table}" DROP COLUMN "20002"')
            db.commit()
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    sessions=service.list_sessions()
    assert len(sessions)==3 and {s.session_type for s in sessions}=={'group','private'}
    with service.acquired_session('group:partition-a') as acquired:
        payload=json.loads(acquired.payload_path.read_text(encoding='utf-8'))
        assert 'Profile A' not in json.dumps(payload) and 'Card A' not in json.dumps(payload)


def test_sqlite_failure_diagnostics_keep_query_values_private(prepared,monkeypatch,caplog):
    service,selection,_=prepared;service.prepare(selection);service.capture()
    def failed(*_args):raise sqlite3.OperationalError('PRIVATE_SQL_FIELD_SENTINEL')
    monkeypatch.setattr(service,'_discover_sessions',failed)
    with pytest.raises(source.QQIndependentError) as refused:service.confirm_account(selection.account)
    assert refused.value.code=='qq_session_validation_failed' and service._root is None
    assert 'sqlite_code=' in caplog.text and 'site=failed' in caplog.text
    assert 'PRIVATE_SQL_FIELD_SENTINEL' not in caplog.text


def test_real_sqlite_metadata_failure_identifies_query_without_private_values(prepared,caplog):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'profile_info.db')) as db:
        db.create_collation('PRIVATE_COLLATION_SENTINEL',lambda a,b:(a>b)-(a<b))
        db.execute('ALTER TABLE profile_info_v2 RENAME TO original_profile')
        db.execute('CREATE TABLE profile_info_v2 ("1002" TEXT COLLATE PRIVATE_COLLATION_SENTINEL,"1000" TEXT,"20002" TEXT)')
        db.execute('INSERT INTO profile_info_v2 SELECT * FROM original_profile')
        db.execute('DROP TABLE original_profile');db.commit()
    service.prepare(selection);service.capture()
    with pytest.raises(source.QQIndependentError) as refused:service.confirm_account(selection.account)
    assert refused.value.code=='qq_session_validation_failed' and service._root is None
    assert 'database=profile_info table=profile_info_v2 fields=1002,1000,20002' in caplog.text
    assert 'file=metadata.py site=query' in caplog.text and 'reason=missing_collation' in caplog.text
    for private in ('PRIVATE_COLLATION_SENTINEL',selection.account,'Profile A','uid-a'):
        assert private not in caplog.text


def test_session_sqlite_failure_keeps_formal_window_open(qt_app,prepared,monkeypatch):
    import time
    from PySide6.QtWidgets import QInputDialog
    from qq_chat_analyzer.gui.main_window import MainWindow
    service,selection,_=prepared
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:(selection.account,True))
    def failed(*_args):raise sqlite3.OperationalError('PRIVATE_SQL_SENTINEL')
    monkeypatch.setattr(service,'_discover_sessions',failed)
    window=MainWindow(facade_for(service));window.show()
    try:
        window.home_page._qq_btn.click();workspace=window.qq_workspace
        workspace._qq_connect_button.click()
        end=time.monotonic()+10
        while workspace._independent.running and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert not workspace._independent.running and window.isVisible()
        assert window.stack.currentWidget() is workspace and not workspace._sessions_loaded
        assert service._root is None and workspace._qq_connect_button.isEnabled()
        text=workspace._qq_login_guide_label.text()
        assert '会话身份存在冲突或资料无法读取' in text
        assert 'PRIVATE_SQL_SENTINEL' not in text and 'Traceback' not in text
    finally:
        window.close();assert window.await_shutdown(10)


@pytest.mark.parametrize('subtype',[0,1])
def test_private_verified_unavailable_body_keeps_valid_messages_and_report(prepared,tmp_path,subtype):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('ALTER TABLE c2c_msg_table ADD COLUMN "40011" INTEGER')
        db.execute('ALTER TABLE c2c_msg_table ADD COLUMN "40012" INTEGER')
        db.execute('INSERT INTO c2c_msg_table ("40001","40027","40030","40021","40033","40050","40800","40011","40012") VALUES (?,?,?,?,?,?,?,?,?)',
                   (999,'private-a',100000002,100000002,0,1760000060,None,1,subtype))
        db.commit()
    facade=facade_for(service)
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    with service.acquired_session('private:private-a') as acquired:
        payload=json.loads(acquired.payload_path.read_text(encoding='utf-8'))
        assert len(payload['records'])==4
        assert service.read_counts=={'database_rows':5,'provider_messages':4,
            'verified_missing_body_rows':1,'unclassified_exclusions':0}
    outcome=facade.analyze_session(ChatSource.QQ,'private:private-a',AnalysisConfig(output_directory=tmp_path/'report'))
    assert outcome.report_path.is_file() and outcome.echo_report_view.total_message_count==4
    assert outcome.echo_report_view.self_identity_basis=='user_declared'
    assert json.loads((outcome.report_path.parent/'echo-report.json').read_text(encoding='utf-8'))['conversation']['kind']=='private'


@pytest.mark.parametrize('sender,body,native_type,subtype',[
    (100000001,None,1,0),(None,None,1,0),(0,b'',1,0),(0,'PRIVATE_BODY_SENTINEL',1,0),
    (0,None,2,0),(0,None,1,99),(0,None,None,0),
])
def test_private_unknown_body_shapes_still_refuse(prepared,sender,body,native_type,subtype):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('ALTER TABLE c2c_msg_table ADD COLUMN "40011" INTEGER')
        db.execute('ALTER TABLE c2c_msg_table ADD COLUMN "40012" INTEGER')
        db.execute('UPDATE c2c_msg_table SET "40033"=?,"40800"=?,"40011"=?,"40012"=? WHERE "40001"=100',
                   (sender,body,native_type,subtype));db.commit()
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    with pytest.raises(source.QQIndependentError) as refused:
        with service.acquired_session('private:private-a'):pytest.fail('unknown exclusion published')
    assert refused.value.code=='qq_analysis_unclassified_provider_exclusions' and service._root is None


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
    # QQ was already open (including a remaining child). Only a fully absent
    # generation permits the guide to ask for a fresh launch.
    existing=iter([True,False,True,False])
    def processes(**options):
        if options.get('include_children'):
            return [{'ProcessId':122}] if next(existing) else []
        return [{'ProcessId':123}]
    monkeypatch.setattr(service,'_process_candidates',processes)
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
        # Only the multi-account choice is modal; reading and self context
        # continue automatically after selecting that profile.
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
                    pytest.fail('connection requested an identity confirmation')
                modal.accept()
            elif isinstance(modal,QMessageBox):
                pytest.fail('connection requested an authorization dialog')
        dialog_timer=QTimer(window);dialog_timer.setInterval(5);dialog_timer.timeout.connect(answer);dialog_timer.start()
        w._qq_connect_button.click()
        wait_for(lambda:w._sessions_loaded and not w._independent.running)
        assert dialogs==['account']
        assert progress_phases==['armed'] and '现在可以登录 QQ' in statuses
        assert '请先完全退出 QQ' in statuses
        assert statuses.index('请先完全退出 QQ')<statuses.index('请打开 QQ，先不要登录')<statuses.index('现在可以登录 QQ')
        assert '请完全退出 QQ' in statuses and '正在读取聊天记录' in statuses
        assert w._progress_track.isHidden() and w._qq_qrcode_label.isHidden()
        assert w._qq_guide_label.isHidden() and w._connection_bar.isVisible()
        assert w._status_label.text()=='可以重新打开 QQ'
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
        assert dialogs==['account']*2
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
    def candidates(**options):
        if options.get('include_children'):return []
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


@pytest.mark.parametrize('outcome',['exit_then_open','cancel','timeout'])
def test_already_running_qq_requires_manual_exit_before_fresh_launch(prepared,monkeypatch,outcome):
    from types import SimpleNamespace
    service,selection,_=prepared;service.prepare(selection)
    progress=[];event=Event();checks=[]
    def candidates(**options):
        checks.append(options.get('include_children',False))
        assert service._worker is None and service._generation_handle is None
        if not options.get('include_children'):return [{'ProcessId':456}]
        if outcome=='cancel':event.set()
        return [{}] if outcome!='exit_then_open' or len(checks)==1 else []
    monkeypatch.setattr(service,'_process_candidates',candidates)
    clock=iter([0,121])
    if outcome=='timeout':monkeypatch.setattr(source,'time',SimpleNamespace(monotonic=lambda:next(clock,121)))
    if outcome=='exit_then_open':
        service._wait_for_process(progress.append,event)
        assert progress==[{'phase':'preparation_exit'},{'phase':'waiting_for_qq'}]
        assert checks==[True,True,False]
    else:
        with pytest.raises(source.QQIndependentError) as refused:
            service.capture(progress=progress.append,cancel_event=event,wait_for_process=True)
        assert refused.value.code==('analysis_cancelled' if outcome=='cancel' else 'qq_preparation_exit_timeout')
        assert progress==[{'phase':'preparation_exit'}] and all(checks)
        assert service._root is None and not service._busy
    if service._root:assert not list(service._root.glob('*.db'))


@pytest.mark.parametrize('stop',['missing','account_cancel'])
def test_formal_connection_recovers_without_publishing_sessions(qt_app,prepared,monkeypatch,stop):
    import time
    from PySide6.QtWidgets import QInputDialog
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    service,selection,_=prepared
    if stop=='missing':monkeypatch.setattr(source,'_discovery_locations',lambda **_options:([],[]))
    if stop=='account_cancel':
        other=selection.account_directory.parent/'100000003'
        shutil.copytree(selection.account_directory,other)
        monkeypatch.setattr(QInputDialog,'getItem',lambda *a,**k:('',False))
    widget=QQWorkspace(facade_for(service))
    try:
        widget._qq_connect_button.click()
        end=time.monotonic()+5
        while widget._independent.running and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert not widget._independent.running and not widget._sessions_loaded
        assert service._root is None and widget._qq_connect_button.isEnabled()
        assert not widget.session_panel.isEnabled()
        assert widget._qq_settings_button.isHidden()==(stop!='missing')
        if stop=='missing':assert service._selection is None
    finally:
        widget._closing=True;widget.cancel_connection();widget.close()


def test_gui_cleanup_failure_stops_retries_without_suggesting_another_path(qt_app,prepared):
    import time
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    service,selection,_=prepared;service.prepare(selection)
    unknown=service._root/'unknown.txt';unknown.write_text('fictional protected asset')
    widget=QQWorkspace(facade_for(service))
    try:
        widget._independent.release()
        end=time.monotonic()+5
        while widget._independent.running and time.monotonic()<end:
            qt_app.processEvents();time.sleep(.005)
        assert not widget._independent.running
        assert not widget._qq_connect_button.isEnabled()
        assert widget._qq_settings_button.isHidden() and not widget.session_panel.isEnabled()
        assert '暂勿重复连接' in widget._qq_login_guide_label.text()
        assert unknown.read_text()=='fictional protected asset'
    finally:
        unknown.unlink()  # Only this test's explicitly created fault.
        widget.close()


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


@pytest.mark.parametrize('body,kind',[(None,'null'),('PRIVATE_BODY_SENTINEL','text'),(b'','empty_blob')])
def test_analysis_exclusion_reason_reaches_gui_boundary_and_cleans(prepared,tmp_path,caplog,body,kind):
    service,selection,dbroot=prepared
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE c2c_msg_table SET "40800"=? WHERE "40001"=100',(body,));db.commit()
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    facade=facade_for(service)
    with pytest.raises(FacadeError) as refused:
        facade.analyze_session(ChatSource.QQ,'private:private-a',AnalysisConfig(output_directory=tmp_path/'report'))
    assert refused.value.code=='qq_analysis_unclassified_provider_exclusions'
    assert refused.value.code in refused.value.public_message
    assert 'stage=analysis_exclusions session_kind=private body_kind='+kind in caplog.text
    assert 'stage=analysis_export failure_code=unclassified_provider_exclusions' in caplog.text
    assert service._root is None and not service.check_status().available
    assert not list((tmp_path/'report').rglob('echo-report.json'))
    for private in ('PRIVATE_BODY_SENTINEL',selection.account,str(dbroot)):
        assert private not in caplog.text and private not in refused.value.public_message


@pytest.mark.parametrize('error,code',[
    (SourceError('metadata_member_scope_mismatch'),'metadata_member_scope_mismatch'),
    (SourceError('PRIVATE_ERROR_SENTINEL'),'worker_internal_error'),
    (sqlite3.OperationalError('PRIVATE_ERROR_SENTINEL'),'sqlite_error'),
    (ValueError('PRIVATE_ERROR_SENTINEL'),'unexpected_error'),
])
def test_analysis_failure_diagnostics_preserve_only_closed_codes(prepared,monkeypatch,caplog,error,code):
    service,selection,_=prepared
    service.prepare(selection);service.capture();service.confirm_account(selection.account)
    def fail(*a):raise error
    monkeypatch.setattr(service,'_materialize',fail)
    with pytest.raises(source.QQIndependentError) as refused:
        with service.acquired_session('private:private-a'):pytest.fail('failed export published')
    assert refused.value.code=='qq_analysis_'+code
    assert 'failure_code='+code in caplog.text
    assert 'PRIVATE_ERROR_SENTINEL' not in caplog.text and 'PRIVATE_ERROR_SENTINEL' not in refused.value.public_message
    assert service._root is None


def test_buffered_snapshot_reader_preserves_authentication_and_fault_cleanup(tmp_path,monkeypatch):
    import subprocess
    node=shutil.which('node')
    if node is None:pytest.skip('Node.js required for the production decoder')
    monkeypatch.delenv('NODE_OPTIONS',raising=False);monkeypatch.delenv('NODE_PATH',raising=False)
    script=Path(__file__).resolve().parents[1]/'scripts/spikes/qq_full_read_diagnostics_check.mjs'
    result=subprocess.run([node,str(script),str(tmp_path)],capture_output=True,text=True,encoding='utf-8',
        check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    receipt=json.loads(result.stdout)
    assert receipt['snapshot_diagnostic_faults']=='passed'
    assert receipt['buffered_pages_byte_identical'] and receipt['cached_input_reverified']
    assert receipt['primary_error_survives_cleanup_failure'] and receipt['real_qq_accessed'] is False


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
@pytest.mark.parametrize('fault',['none','metadata_key','account_key','shared_key','cancel','sidecar','native_exit','wire'])
def test_offline_worker_protocol_authenticates_only_after_exit(prepared,monkeypatch,tmp_path,caplog,fault):
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
    if(FAULT==='native_exit'){child.stdout.end();child.exitCode=45;child.emit('close',45);return;}
    if(FAULT==='wire'){child.stdout.write(Buffer.alloc(16));child.stdout.end();child.exitCode=0;child.emit('close',0);return;}
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
        assert statuses[-1]=='authenticating', 'exit instruction leaked into snapshot copying'
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
        elif value['phase']=='authenticating':
            assert exited and not frozen_sources
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
            with pytest.raises(source.QQIndependentError) as refused:service.capture()
            expected={'metadata_key':'key_not_authenticated','account_key':'key_not_authenticated',
                      'cancel':'cancelled','sidecar':'frozen_main_required','native_exit':'loader_exit_nonzero',
                      'wire':'transport_header_refused'}[fault]
            assert refused.value.code=='qq_capture_'+expected
            if fault=='native_exit':assert 'loader_exit_code=45' in caplog.text
            assert service._root is None and not service.list_sessions()
        if fault not in ('cancel','sidecar','native_exit','wire'):
            assert frozen_sources==['nt_msg.db','group_info.db','profile_info.db']
        assert not outside_scope
        assert children and all(child.poll() is not None for child in children)
    finally:
        for child in children:
            if child.poll() is None:child.kill();child.wait(timeout=3)
            child.stderr.close()


@pytest.mark.parametrize('fault,expected',[
    ('reported','page_hmac_mismatch'),('unknown','worker_internal_error'),
    ('exit','worker_exit_nonzero'),('missing','worker_result_missing'),
    ('invalid_json','protocol_invalid_json'),('unverified','worker_result_missing')])
def test_capture_worker_error_reaches_facade_without_private_fields(prepared,monkeypatch,caplog,fault,expected):
    import io
    from types import SimpleNamespace
    from qq_chat_analyzer.runtime import windows_job
    service,selection,_=prepared;service.prepare(selection)
    monkeypatch.setattr(service,'_run_capture',source.QQIndependentService._run_capture.__get__(service))
    monkeypatch.setattr(service,'_select_process',lambda:(123,7))
    api=SimpleNamespace(CreateEventW=lambda *a:7,SetEvent=lambda *a:True,CloseHandle=lambda *a:True)
    monkeypatch.setattr(source,'event_api',lambda:api)
    frames={'reported':json.dumps({'phase':'failed','verified':False,'failure_code':'page_hmac_mismatch','failure_stage':'profile_info','private':'PRIVATE_KEY_SENTINEL'}),
        'unknown':json.dumps({'phase':'failed','failure_code':'PRIVATE_KEY_SENTINEL','failure_stage':{'secret':'PRIVATE_PATH_SENTINEL'}}),
        'invalid_json':'PRIVATE_PATH_SENTINEL',
        'unverified':json.dumps({'phase':'completed','verified':False})}
    class Job:
        stdout=io.StringIO(frames.get(fault,'')+'\n' if fault in frames else '')
        closed=False
        def set_external_readers(self,*a):pass
        def terminate_tree(self):pass
        def active_process_count(self):return 0
        def wait(self,**k):return 2 if fault=='exit' else 0
        def close_after_readers(self,*a,**k):self.closed=True
    job=Job();monkeypatch.setattr(windows_job,'launch_owned_process',lambda *a,**k:job)
    with pytest.raises(FacadeError) as refused:facade_for(service).start_qq_auth_flow()
    assert refused.value.code=='qq_capture_'+expected and expected in refused.value.public_message
    assert job.closed and service._root is None and service._worker is None
    for secret in ('PRIVATE_KEY_SENTINEL','PRIVATE_PATH_SENTINEL',str(selection.account_directory)):
        assert secret not in caplog.text and secret not in refused.value.public_message


@pytest.mark.parametrize('field,expected',[
    ('authenticated','authentication_unconfirmed'),('complete','image_incomplete'),
    ('observation_stopped','observation_unconfirmed'),('reads_stopped','reads_unconfirmed'),
    ('hook_disabled','hook_unconfirmed'),('inflight','inflight_unconfirmed'),
    ('missing','node_result_missing'),('exit','node_exit_nonzero'),('snapshot','snapshot_not_sent')])
def test_node_result_rejections_keep_the_specific_failed_check(prepared,monkeypatch,field,expected):
    import io
    from types import SimpleNamespace
    from qq_chat_analyzer.providers.qq_independent import worker
    service,selection,_=prepared
    result={'phase':'result','authenticated':True,'complete':True,'observation_stopped':True,
            'reads_stopped':True,'hook_disabled':True,'inflight':0}
    if field in result:result[field]=1 if field=='inflight' else False
    class Child:
        stdin=io.BytesIO()
        stdout=io.StringIO('' if field=='missing' else json.dumps(result)+'\n')
        def wait(self,**k):return 2 if field=='exit' else 0
        def poll(self):return 0
        def kill(self):pass
    api=SimpleNamespace(WaitForSingleObject=lambda *a:0)
    @contextmanager
    def process(*a,**k):yield api,7
    monkeypatch.setattr(worker,'verified_process',process)
    monkeypatch.setattr(worker,'runtime_files',lambda:(selection.executable.parent,{}))
    monkeypatch.setattr(worker,'resources_identity',lambda image:(SimpleNamespace(wrapper_path=image),((str(image),'a'*64),)))
    monkeypatch.setattr(worker,'loaded_module',lambda *a:(1,True))
    monkeypatch.setattr(worker,'process_creation_ticks',lambda *a:7)
    monkeypatch.setattr(worker.subprocess,'Popen',lambda *a,**k:Child())
    with pytest.raises(SourceError) as refused:
        worker.capture({'image':str(selection.executable),'pid':123,'created':7},lambda:False,lambda _:None)
    assert refused.value.code==expected


@pytest.mark.parametrize('fault,expected',[('known','normal_qq_exit_required'),('unknown','worker_internal_error'),('os','permission_denied')])
def test_worker_main_serializes_only_safe_error_codes(prepared,monkeypatch,capsys,fault,expected):
    from types import SimpleNamespace
    from qq_chat_analyzer.providers.qq_independent import worker
    from qq_chat_analyzer.providers.qq_independent.diagnostics import failure_record
    _,selection,_=prepared
    service=source.QQIndependentService(workspace=selection.executable.parent/'qq-independent')
    service.prepare(selection)
    request={'kind':'echo-qq-independent-capture-v1','root':str(service._root),
        'account_directory':str(selection.account_directory),'cancel_event':'Local\\EchoQQIndependentStop-'+'a'*32}
    (service._root/'request.json').write_text(json.dumps(request),encoding='ascii')
    monkeypatch.setattr(worker,'event_api',lambda:SimpleNamespace(OpenEventW=lambda *a:7,CloseHandle=lambda *a:True))
    def fail(_request,_cancelled,status):
        status({'phase':'awaiting_exit'})
        if fault=='known':raise SourceError('normal_qq_exit_required')
        if fault=='unknown':raise SourceError('PRIVATE_KEY_SENTINEL')
        raise PermissionError('PRIVATE_PATH_SENTINEL')
    monkeypatch.setattr(worker,'capture',fail)
    try:
        assert worker.main(str(service._root))==2
        text=capsys.readouterr().out;record=json.loads(text.splitlines()[-1])
        assert record==failure_record(code=expected,stage='exit')
        assert 'PRIVATE_' not in text and selection.account not in text
        try:raise SourceError('page_hmac_mismatch')
        except SourceError:
            try:raise SourceError('source_cleanup_failed')
            except SourceError as error:
                assert failure_record(error)['cause_code']=='page_hmac_mismatch'
    finally:service.shutdown()


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
    from test_qq_db_rich_contents import _body,_scalar,_bytes
    from test_qq_marketface_media import send,write_cache,local_only_worker
    from test_sticker_data import image_bytes
    from qq_chat_analyzer.application.qq import qq_marketface_media as media
    service,selection,dbroot=prepared
    cache=selection.account_directory/'nt_qq/nt_data/Emoji/marketface'
    item=send()
    write_cache(cache,item)
    segment=_scalar(45002,11)+_scalar(80810,item.resource_pack_id)+_bytes(80903,bytes.fromhex(item.resource_id))
    original=image_bytes('GIF',animated=True);digest=hashlib.md5(original).hexdigest()
    pic=selection.account_directory/'nt_qq/nt_data/Pic/2026-01/Ori';pic.mkdir(parents=True)
    (pic/(digest+'.gif')).write_bytes(original)
    missing=image_bytes('PNG');missing_digest=hashlib.md5(missing).hexdigest()
    # An original in another account is not authorized as a fallback.
    sibling=selection.account_directory.parent/'100000003/nt_qq/nt_data/Pic/2026-01/Ori'
    sibling.mkdir(parents=True);(sibling/(missing_digest+'.png')).write_bytes(missing)
    with closing(sqlite3.connect(dbroot/'nt_msg.db')) as db:
        db.execute('UPDATE group_msg_table SET "40800"=? WHERE "40001"=0',
                   (synthetic_text_message_blob('Orchard seedlings need gentle rain tomorrow')+_body(segment),))
        for index,md5 in ((1,digest),(2,missing_digest)):
            custom=_scalar(45002,2)+_scalar(45003,1)+_bytes(45406,bytes.fromhex(md5))+_scalar(45418,1)
            db.execute('UPDATE group_msg_table SET "40800"=? WHERE "40001"=?',
                       (synthetic_text_message_blob('Fictional custom picture in this conversation')+_body(custom),index))
        db.commit()
    # Spawn the existing local-only seam; no real CDN or QQ can be contacted.
    monkeypatch.setattr(media,'_worker',local_only_worker)
    facade=facade_for(service)
    monkeypatch.setattr(facade,'_qq_connected_provider',lambda *a:pytest.fail('offline media tried the live QQ API'))
    facade.prepare_independent_qq(selection.executable,selection.account_directory)
    assert service._selection.recover_media is True
    service.capture();service.confirm_account(selection.account)
    session=next(s for s in facade.list_sessions(ChatSource.QQ) if s.session_id=='group:partition-a')
    outcome=facade.analyze_session(ChatSource.QQ,session.session_id,
                                 AnalysisConfig(output_directory=tmp_path/'animated-report'))
    assert outcome.report_path is not None
    assert len(outcome.result.stickers.sends)==3
    assets=outcome.echo_report_view.stickers.assets
    assert len(assets)==3
    ready=[a for a in assets if a.status in ('available','preview')]
    absent=[a for a in assets if a.status=='missing']
    assert len(ready)==2 and len(absent)==1 and not absent[0].data_uri
    assert all(a.reason!='report_media_source_unavailable' for a in assets)
    from PIL import Image
    for asset in ready:
        reference=asset.data_uri
        assert reference.startswith('media/') and reference.endswith('.gif')
        assert reference in outcome.report_path.read_text(encoding='utf-8')
        with Image.open(outcome.report_path.parent/reference) as animation:
            assert animation.n_frames==2
    assert service._payload is None and service._root is not None
