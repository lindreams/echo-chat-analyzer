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
