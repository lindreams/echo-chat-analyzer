"""Desktop NapCat defaults and connection lifecycle; all runtimes fictional."""
from pathlib import Path
from types import SimpleNamespace
import json
import hashlib
import re

import pytest

from qq_chat_analyzer.application.qq import qq_environment_config as env
from qq_chat_analyzer.application.qq.qq_connection_service import QQConnectionService
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseImportService, _group_member_data
from qq_chat_analyzer.application.qq.qq_provider_factory import default_provider_builder
from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQProvider, NapCatStatus, NapCatFriend, NapCatGroup
from qq_chat_analyzer.gui import app


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    directory=tmp_path/'runtime/qq-napcat-candidate'
    for name in ['napcat.mjs','NapCatWinBootMain.exe','NapCatWinBootHook.dll','plugins/napcat-plugin-echo/index.mjs','plugins/napcat-plugin-echo/bridge.mjs']:
        path=directory/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fictional')
    monkeypatch.setattr(env,'default_qq_runtime_directory',lambda:directory,raising=False)
    monkeypatch.setattr(env,'user_data_dir',lambda:tmp_path)
    monkeypatch.delenv('ECHO_QQ_RUNTIME',raising=False)
    metadata = tmp_path / 'metadata'
    metadata.mkdir()
    names = ['napcat.mjs','plugins/napcat-plugin-echo/index.mjs','plugins/napcat-plugin-echo/bridge.mjs','config/plugins.json']
    (directory/'config').mkdir()
    (directory/'config/plugins.json').write_bytes(b'{"napcat-plugin-echo":true}\n')
    hashes = {n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in names}
    (metadata/'pins.json').write_text(json.dumps({'upstream':{'version':'4.18.18'},
        'napcatPatch':{'path':'napcat.mjs','patchedSha256':hashes['napcat.mjs']},
        'templates':[{'target':n,'sha256':hashes[n]} for n in names if n.startswith('plugins/')],
        'pluginConfigSha256':hashes['config/plugins.json']}),encoding='utf-8')
    (metadata/'windows_runtime_manifest.json').write_text(json.dumps({'qqPins':'pins.json',
        'requirements':[{'path':'qq-napcat-candidate/'+n,'type':'file'} for n in names]}),encoding='utf-8')
    from qq_chat_analyzer import resources
    original_resource = resources.resource_path
    monkeypatch.setattr(resources,'resource_path',lambda p:metadata/Path(p).name if str(p)=='scripts/windows_runtime_manifest.json' else original_resource(p))
    return directory


def status(online=True, passphrase=False, uin='12345678'):
    return NapCatStatus(True,online,{'uin':uin,'uid':'u_self','nickname':'Self'},True,passphrase,True)


def test_default_desktop_uses_candidate_and_shared_config(candidate, monkeypatch):
    factory=app._qq_provider_factory()
    config=factory.config_loader.load_or_default()
    assert config.runtime_directory==candidate
    assert config.napcat_bridge_url=='http://127.0.0.1:40655'
    provider = factory.create()
    assert isinstance(provider,NapCatQQProvider)
    service=app._optional_qq_service(factory)
    assert service._config_loader is factory.config_loader
    paths = factory.config_loader.runtime_paths()
    provider._credential_source = "c" * 64
    def fictional_status(url, body, timeout):
        assert json.loads(body)["method"] == "Core.status"
        return 200, json.dumps({"ok": True, "result": {
            "rpc_auth": "bearer-v1", "boot_id": "b" * 64,
            "runtime_id": paths.runtime_id, "self_info": {},
            "bridge_ready": True, "qq_online": False, "database_api_ready": True,
            "passphrase_ready": False, "snapshot_api_ready": True,
        }})
    monkeypatch.setattr(provider, "_request", fictional_status)
    assert service._require_runtime_client()._base_url==config.napcat_bridge_url
    setup=app._optional_qq_setup_service(factory,app._optional_qq_connection_service(factory))
    assert setup._config_loader is factory.config_loader
    assert setup.check_setup().runtime_available


def test_missing_candidate_never_falls_back_to_qce(candidate, tmp_path, monkeypatch):
    (candidate/'napcat.mjs').unlink()
    old=tmp_path/'qq';old.mkdir();qce=old/'qce-server.exe';qce.write_text('fictional')
    monkeypatch.setattr(env,'bundled_qq_runtime_available',lambda:True)
    factory=app._qq_provider_factory()
    assert isinstance(factory.create(),NapCatQQProvider)
    config=factory.config_loader.load_or_default()
    assert config.runtime_directory==candidate




def test_login_and_direct_db_readiness_are_separate(monkeypatch):
    provider=NapCatQQProvider()
    def forbidden(*args, **kwargs):
        pytest.fail('Default Desktop must not use QCE health or token')
    monkeypatch.setattr(provider, 'health_check', forbidden, raising=False)
    monkeypatch.setattr(provider, 'resolve_token', forbidden, raising=False)
    monkeypatch.setattr(provider,'status',lambda:status())
    service=QQConnectionService(provider)
    result=service.check_status()
    assert result.available and result.runtime_running
    assert not result.direct_db_ready
    monkeypatch.setattr(provider,'status',lambda:status(passphrase=True))
    assert service.check_status().direct_db_ready
    monkeypatch.setattr(provider,'status',lambda:status(uin='u_uid'))
    assert not service.check_status().available
    monkeypatch.setattr(provider,'status',lambda:status(online=False))
    assert not service.check_status().available


def test_metadata_no_qce_pagination_and_members_preserve_identity(monkeypatch):
    provider=NapCatQQProvider();calls=[]
    def groups():calls.append('groups');return [NapCatGroup('23456789','Group',2)]
    def friends():calls.append('friends');return [NapCatFriend('u_friend','34567890','Nick','Remark')]
    monkeypatch.setattr(provider,'list_groups',groups);monkeypatch.setattr(provider,'list_friends',friends)
    service=QQDirectDatabaseImportService(provider_factory=SimpleNamespace(create=lambda:provider))
    assert service._metadata_names()==({'23456789':'Group'},{'34567890':'Remark'})
    assert calls==['groups','friends']
    mapped=_group_member_data({'result':{'infos':{'u_friend':{'uin':'34567890','uid':'u_friend','nick':'Nick','cardName':'Card'}}}})
    assert mapped['names']=={'34567890':'Card'}


def test_connection_state_machine_reuses_retries_and_relogin(candidate,monkeypatch):
    from qq_chat_analyzer.application.qq import qq_auth_bridge as auth_module
    from qq_chat_analyzer.application.qq.qq_auth_bridge import QQAuthBridge
    from qq_chat_analyzer.application.qq.qq_setup_service import QQSetupService
    from qq_chat_analyzer.application.qq.qq_runtime_manager import QQRuntimeStatus,QQRuntimeState
    from qq_chat_analyzer.application.connection_models import ConnectionState
    monkeypatch.setattr(auth_module, "find_conflicting_qq_pids", lambda owned: [])
    provider=NapCatQQProvider();current=[status(online=False)]
    monkeypatch.setattr(provider,'status',lambda:current[0])
    config=env.QQEnvironmentConfig(runtime_directory=candidate,runtime_mode='custom')
    runtime=SimpleNamespace(get_status=lambda:QQRuntimeStatus(QQRuntimeState.STOPPED,True),stop=lambda:QQRuntimeStatus(QQRuntimeState.STOPPED,True))
    setup=QQSetupService(config_loader=SimpleNamespace(load_or_default=lambda:config),runtime_manager=runtime)
    launched=[]
    def forbidden():
        pytest.fail('NapCat authorization must not prepare QCE/security.json')
    auth=QQAuthBridge(setup_service=setup,connection_service=QQConnectionService(provider),window_launcher=lambda:launched.append(1))
    assert auth.start_auth_flow().state is ConnectionState.WAITING_AUTH
    assert auth.start_auth_flow().state is ConnectionState.WAITING_AUTH
    assert len(launched)==1
    # Cancel before login, then retry through the same state machine.
    assert auth.disconnect().state is ConnectionState.DISCONNECTED
    assert auth.start_auth_flow().state is ConnectionState.WAITING_AUTH
    assert len(launched)==2
    current[0]=status(passphrase=True)
    assert auth.get_snapshot().state is ConnectionState.CONNECTED
    current[0]=status(online=False)
    auth.disconnect()
    assert auth.start_auth_flow().state is ConnectionState.WAITING_AUTH
    assert len(launched)==3
    current[0]=status(uin='45678901')
    assert auth.get_snapshot().state is ConnectionState.CONNECTED


@pytest.mark.parametrize("parent_value", [None, ""])
def test_native_launcher_uses_detected_qq_and_never_qce(candidate,tmp_path,monkeypatch,parent_value):
    from qq_chat_analyzer.application.qq import qq_auth_bridge as auth
    variable = "NAPCAT_DISABLE_FFMPEG_DOWNLOAD"
    if parent_value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, parent_value)
    qq=tmp_path/'QQ.exe';qq.write_bytes(b'fictional')
    package=tmp_path/'resources/app/package.json';package.parent.mkdir(parents=True);package.write_text('{"name":"QQ","version":"9.9.36-53644","buildVersion":"53644","main":"index.js"}')
    (package.parent/'wrapper.node').write_bytes(b'fictional native resource')
    seen=[]
    process=SimpleNamespace(pid=12345,poll=lambda:None)
    target, attribute = (auth, 'launch_owned_process') if auth.os.name == 'nt' else (auth.subprocess, 'Popen')
    monkeypatch.setattr(target, attribute, lambda command,**options:seen.append((command,options)) or process)
    config=env.QQEnvironmentConfig(qq_install_path=qq,runtime_directory=candidate,runtime_mode='custom')
    assert auth.default_auth_window_launcher(config)() is process
    command,options=seen[0]
    assert command[:3]==[str(candidate/'NapCatWinBootMain.exe'),str(qq),str(candidate/'NapCatWinBootHook.dll')]
    assert 'qce-server' not in ' '.join(command)
    assert options['env']['NAPCAT_MAIN_PATH']==str(candidate/'napcat.mjs')
    assert options['env']['ECHO_BRIDGE_PORT']=='40655'
    # A custom runtime is launched by Echo too, so it gets a credential as well:
    # authentication is not a managed-only feature, only the identity binding is.
    assert re.fullmatch(r'[0-9a-f]{64}', options['env']['ECHO_BRIDGE_TOKEN'])
    assert 'ECHO_RUNTIME_ID' not in options['env']
    assert options['env'].get(variable) == '1'
    assert auth.os.environ.get(variable) == parent_value


def test_napcat_setup_waiting_status_does_not_claim_qce(candidate):
    from qq_chat_analyzer.application.qq.qq_setup_service import QQSetupService
    from qq_chat_analyzer.application.qq.qq_runtime_manager import QQRuntimeStatus, QQRuntimeState
    config = env.QQEnvironmentConfig(runtime_directory=candidate, runtime_mode='custom')
    running = QQRuntimeStatus(QQRuntimeState.RUNNING, True)
    runtime = SimpleNamespace(get_status=lambda: running)
    setup = QQSetupService(
        config_loader=SimpleNamespace(load_or_default=lambda: config),
        config_writer=SimpleNamespace(write=lambda config: None),
        runtime_manager=runtime,
    )
    result = setup.connect()
    assert result.runtime_running
    assert not result.available and not result.direct_db_ready
