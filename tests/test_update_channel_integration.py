"""P1 composition must keep installation closed until joint acceptance."""
import importlib

import pytest


def test_desktop_has_configured_update_feed_without_constructing_sdk(monkeypatch):
    import velopack
    from qq_chat_analyzer.gui.app import build_facade
    def forbidden(*args, **kwargs):
        raise AssertionError('Composition must remain offline and SDK-free')
    monkeypatch.setattr(velopack, 'UpdateManager', forbidden)
    facade = build_facade()
    assert facade.get_update_status().status == 'idle'
    result = facade.prepare_update_install()
    assert result.status == 'denied' and result.token is None


@pytest.mark.parametrize('approval', [1, 'true', object()])
def test_non_boolean_approval_never_opens_install_gate(approval):
    name = 'qq_chat_analyzer.application.update_channel'
    assert importlib.util.find_spec(name) is not None, 'P1 channel is not integrated'
    channel = importlib.import_module(name)
    class Inner:
        def prepare_install(self):
            raise AssertionError('A truthy value must not authorize installation')
        def handoff(self, *args):
            raise AssertionError('A truthy value must not authorize installation')
    service = channel.guard_install_handoff(Inner(), approved=approval)
    assert service.prepare_install().status == 'denied'
    assert service.handoff('fictional', object()).status == 'denied'
