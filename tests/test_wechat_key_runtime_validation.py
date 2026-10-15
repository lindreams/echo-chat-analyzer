from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_wechat_key_runtime", ROOT / "scripts" / "validate_wechat_key_runtime.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)

from qq_chat_analyzer.application.wechat.wechat_environment_config import WeChatEnvironmentConfig


class Loader:
    def __init__(self, config): self.config = config
    def load(self): return self.config


class Key:
    def acquire(self): return "ab12" * 16


class Session:
    session_id = "fictional@chatroom"


class Provider:
    def list_sessions(self): return [Session()]
    def read_session_rows(self, session_id, limit=1): return []


def test_fake_key_and_provider_complete_chain():
    config = WeChatEnvironmentConfig(data_root=Path("fictional"))
    report = module.validate_wechat_key_runtime(
        config_loader=Loader(config),
        key_service=Key(),
        provider_factory=object(),
        provider_builder=lambda received: Provider(),
    )
    assert report.ok
    assert report.key_acquired
    assert report.database_open
    assert report.session_count == 1
