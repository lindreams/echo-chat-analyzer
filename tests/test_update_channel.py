"""Trusted production composition; no real feed or installation is used."""
import importlib


def channel():
    name = 'qq_chat_analyzer.application.update_channel'
    assert importlib.util.find_spec(name) is not None, 'Production feed is not integrated'
    return importlib.import_module(name)


def test_production_composition_is_inert_and_uses_trusted_identity(monkeypatch):
    import velopack
    from qq_chat_analyzer.gui.app import build_facade
    mod = channel()
    monkeypatch.setenv('ECHO_UPDATE_SOURCE', 'https://example.invalid/untrusted')
    monkeypatch.setenv('ECHO_UPDATE_PACKAGE_ID', 'Untrusted')

    def forbidden(*args, **kwargs):
        raise AssertionError('Composition must not perform SDK IO')

    monkeypatch.setattr(velopack, 'UpdateManager', forbidden)
    facade = build_facade()
    assert facade.get_update_status().status == 'idle'
    feed = mod.production_feed()
    assert (feed.package_id, feed.channel, feed.source) == (
        'Lindreams.Echo', 'win-x64-stable',
        'https://cnb.cool/echo_mly/echo_releases/-/releases/download/updates')
    # The normal A3 preparation still requires a supported Setup and verified
    # package; wiring the feed must not authorize installation in a source run.
    assert facade.prepare_update_install().status == 'denied'
