"""Fictional feeds only; no Echo installation or update execution."""
import importlib
import hashlib
import json
import sys
from threading import Event, Thread
from zipfile import ZipFile

import pytest
import velopack


def api():
    return importlib.import_module('qq_chat_analyzer.application.installable_update_service')


def asset(version='0.2.0'):
    return velopack.VelopackAsset('FictionalEcho', version, 'Full',
                                f'FictionalEcho-{version}-full.nupkg',
                                'a' * 40, 'b' * 64, 123, '', '')


class FakeManager:
    """SDK boundary double using actual pinned SDK DTOs."""
    def __init__(self):
        self.info = velopack.UpdateInfo(asset(), [], False)
        self.pending = None
        self.portable = False
        self.failure = None
        self.downloads = 0
        self.checks = 0
        self.hook = lambda: None

    def get_app_id(self):
        return 'FictionalEcho'

    def get_current_version(self):
        return '0.1.0'

    def get_is_portable(self):
        return self.portable

    def get_update_pending_restart(self):
        return self.pending

    def check_for_updates(self):
        self.checks += 1
        self.hook()
        if self.failure:
            raise self.failure
        return self.info

    def download_updates(self, info, progress_callback=None):
        assert info is self.info  # preserve the exact SDK metadata
        self.downloads += 1
        self.hook()
        for value in [-1, 20, 10, 140]:
            progress_callback(value)
        if self.failure:
            raise self.failure
        self.pending = info.TargetFullRelease


def service(tmp_path, manager=None, **kwargs):
    mod = api()
    manager = manager or FakeManager()
    config = mod.UpdateFeedConfig(source=tmp_path, package_id='FictionalEcho', channel='test')
    return mod.InstallableUpdateService(feed=config, manager_factory=lambda feed: manager,
                                       setup_runtime=lambda: True, **kwargs), manager


def test_no_update(tmp_path):
    svc, mgr = service(tmp_path)
    mgr.info = None
    assert svc.check().status == 'no_update'
    assert svc.download().error_code == 'check_required'


def test_download_progress_and_idempotence(tmp_path):
    svc, mgr = service(tmp_path)
    result = svc.check()
    assert result.status == 'available'
    assert result.current_version == '0.1.0'
    assert result.target_version == '0.2.0'
    values = []
    def observe(value):
        assert svc.get_status().status == 'downloading'
        values.append(value)
    result = svc.download(progress=observe)
    assert result.status == 'downloaded'
    assert result.progress == 100
    assert values == [0, 20, 99, 100]
    assert svc.get_status() == result
    assert svc.download() == result
    assert svc.check() == result
    assert mgr.downloads == 1
    assert mgr.checks == 1


@pytest.mark.parametrize('operation', ['check', 'download'])
def test_failure_is_safe_and_download_can_retry(tmp_path, operation):
    svc, mgr = service(tmp_path)
    if operation == 'download':
        svc.check()
    mgr.failure = RuntimeError('secret-like diagnostic must not escape')
    result = getattr(svc, operation)()
    assert result.status == 'failed'
    assert result.error_code == f'{operation}_failed'
    assert 'secret-like' not in result.public_message
    assert result.progress != 100
    mgr.failure = None
    assert (svc.download() if operation == 'download' else svc.check()).status in ('downloaded', 'available')


@pytest.mark.parametrize('first', ['check', 'download'])
def test_concurrent_requests_return_busy(tmp_path, first):
    svc, mgr = service(tmp_path)
    if first == 'download':
        svc.check()
    entered, release = Event(), Event()
    def hold():
        entered.set()
        assert release.wait(5)
    mgr.hook = hold
    results = []
    worker = Thread(target=lambda: results.append(getattr(svc, first)()))
    worker.start()
    try:
        assert entered.wait(5)
        assert svc.check().status == 'busy'
        assert svc.download().status == 'busy'
    finally:
        release.set()
        worker.join(5)
    assert results[0].status in ('available', 'downloaded')


def test_portable_cannot_download(tmp_path):
    svc, mgr = service(tmp_path)
    mgr.portable = True
    assert svc.check().status == 'unsupported'
    assert svc.download().status == 'unsupported'
    assert mgr.checks == mgr.downloads == 0


def test_source_and_unconfigured_never_construct_sdk(tmp_path):
    mod = api()
    def forbidden(feed):
        pytest.fail('SDK must not be constructed')
    svc = mod.InstallableUpdateService(manager_factory=forbidden)
    assert svc.check().status == 'unconfigured'
    assert svc.download().status == 'unconfigured'
    svc = mod.InstallableUpdateService(
        feed=mod.UpdateFeedConfig(tmp_path, 'FictionalEcho', 'test'),
        setup_runtime=lambda: False, manager_factory=forbidden)
    assert svc.check().status == 'unsupported'
    assert svc.download().status == 'unsupported'


def test_recovers_sdk_pending_without_network(tmp_path):
    svc, mgr = service(tmp_path)
    mgr.pending = asset()
    mgr.failure = RuntimeError('offline')
    assert svc.check().status == 'downloaded'
    assert svc.download().status == 'downloaded'
    assert mgr.checks == mgr.downloads == 0


def test_requires_matching_pending_package(tmp_path):
    svc, mgr = service(tmp_path)
    svc.check()
    original = mgr.download_updates
    def wrong(*args, **kwargs):
        original(*args, **kwargs)
        mgr.pending = asset('0.3.0')
    mgr.download_updates = wrong
    result = svc.download()
    assert result.status == 'failed'
    assert result.error_code == 'download_failed'
    assert result.progress < 100


def test_callback_failure_does_not_fail_download(tmp_path):
    svc, _ = service(tmp_path)
    svc.check()
    def broken(value):
        raise RuntimeError('UI callback')
    assert svc.download(progress=broken).status == 'downloaded'


@pytest.mark.parametrize('source', ['http://example.invalid/feed', 'https://u:p@example.invalid/feed',
                                  'https://example.invalid/feed?token=x', 'relative/path'])
def test_untrusted_feed_configuration_rejected(source):
    with pytest.raises(ValueError):
        api().UpdateFeedConfig(source, 'FictionalEcho', 'test')


def test_facade_default_and_injection(tmp_path):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    api()
    facade = ChatAnalyzerFacade()
    assert facade.check_installable_update().status == 'unconfigured'
    svc, _ = service(tmp_path)
    facade = ChatAnalyzerFacade(installable_update_service=svc)
    assert facade.check_installable_update().status == 'available'
    assert facade.download_update().status == 'downloaded'
    assert facade.get_update_status().status == 'downloaded'


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Setup SDK boundary')
@pytest.mark.parametrize('corrupt', [False, True])
def test_real_sdk_local_feed_without_installation(tmp_path, corrupt):
    mod = api()
    root, feed = tmp_path / 'fake-app', tmp_path / 'feed'
    current, packages = root / 'current', root / 'packages'
    for directory in (current, packages, feed):
        directory.mkdir(parents=True)
    def manifest(version):
        return ('<package><metadata><id>FictionalEcho</id>'
                f'<version>{version}</version><mainExe>Fictional.exe</mainExe>'
                '<channel>test</channel></metadata></package>')
    # Non-executable placeholder: no installer/updater is ever launched.
    updater = root / 'Update.exe'
    updater.write_bytes(b'fictional, non-executable updater')
    manifest_path = current / 'sq.version'
    manifest_path.write_text(manifest('0.1.0'), encoding='utf-8')
    package = feed / 'FictionalEcho-0.2.0-full.nupkg'
    with ZipFile(package, 'w') as archive:
        archive.writestr('FictionalEcho.nuspec', manifest('0.2.0'))
        archive.writestr('lib/app/readme.txt', 'Fictional test payload only')
        archive.writestr('lib/app/Squirrel.exe', b'fictional, non-executable updater')
    content = package.read_bytes()
    metadata = dict(PackageId='FictionalEcho', Version='0.2.0', Type='Full',
                    FileName=package.name, SHA1=hashlib.sha1(content).hexdigest(),
                    SHA256=hashlib.sha256(content).hexdigest(), Size=len(content),
                    NotesMarkdown='', NotesHtml='')
    (feed / 'releases.test.json').write_text(json.dumps({'Assets': [metadata]}), encoding='utf-8')
    if corrupt:
        package.write_bytes(b'corrupted fictional package')
    locator = velopack.VelopackLocatorConfig(str(root), str(updater), str(packages),
                                           str(manifest_path), str(current), False)
    # Exercise the production SDK factory including explicit source/options;
    # override only auto-location to avoid inspecting any real installation.
    real_constructor = velopack.UpdateManager
    from unittest.mock import patch
    def located(source, options=None, locator=None):
        return real_constructor(source, options=options, locator=locator)
    svc = mod.InstallableUpdateService(
        feed=mod.UpdateFeedConfig(feed, 'FictionalEcho', 'test'), setup_runtime=lambda: True)
    with patch.object(velopack, 'UpdateManager', located), \
            patch.object(sys, 'executable', str(current / 'Fictional.exe')), \
            patch.object(mod, '_setup_runtime', lambda: True):
        assert svc.check().status == 'available'
        values = []
        result = svc.download(progress=values.append)
        if corrupt:
            assert result.status == 'failed'
            assert result.progress < 100
            assert not (packages / package.name).exists()
        else:
            assert result.status == 'downloaded'
            assert values[0] == 0 and values[-1] == 100
            assert (packages / package.name).read_bytes() == content
            # Reconstruct a service: SDK pending metadata has empty hashes.
            recovered = mod.InstallableUpdateService(
                feed=mod.UpdateFeedConfig(feed, 'FictionalEcho', 'test'), setup_runtime=lambda: True)
            assert recovered.check().status == 'downloaded'


def test_foreign_installation_and_malformed_candidate_denied(tmp_path):
    svc, mgr = service(tmp_path)
    mgr.get_app_id = lambda: 'ForeignApp'
    assert svc.check().status == 'unsupported'
    svc, mgr = service(tmp_path)
    invalid = asset()
    invalid.FileName = '../escape.nupkg'
    mgr.info = velopack.UpdateInfo(invalid, [], False)
    assert svc.check().status == 'failed'
    assert svc.download().error_code == 'check_required'


@pytest.mark.parametrize('method', ['check_installable_update', 'download_update', 'get_update_status'])
def test_facade_normalizes_injected_service_exceptions(method):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, FacadeError
    class Broken:
        def check(self):
            raise RuntimeError('private details')
        def download(self, **kwargs):
            raise RuntimeError('private details')
        def get_status(self):
            raise RuntimeError('private details')
    with pytest.raises(FacadeError) as error:
        getattr(ChatAnalyzerFacade(installable_update_service=Broken()), method)()
    assert 'private details' not in error.value.public_message


def test_check_failure_invalidates_old_candidate(tmp_path):
    svc, mgr = service(tmp_path)
    assert svc.check().status == 'available'
    mgr.failure = OSError('offline')
    assert svc.check().status == 'failed'
    assert svc.download().error_code == 'check_required'


def test_sdk_location_failure_returns_failure(tmp_path):
    mod = api()
    def missing(feed):
        raise RuntimeError('not installed: private filesystem path')
    svc = mod.InstallableUpdateService(
        feed=mod.UpdateFeedConfig(tmp_path, 'FictionalEcho', 'test'),
        manager_factory=missing, setup_runtime=lambda: True)
    assert svc.check().error_code == 'check_failed'
    assert svc.download().error_code == 'download_failed'


def test_download_requires_setup_proof_again(tmp_path):
    svc, mgr = service(tmp_path)
    svc.check()
    mgr.portable = True
    assert svc.download().status == 'unsupported'
    assert mgr.downloads == 0


def test_failed_pending_read_never_reports_complete_progress(tmp_path):
    svc, mgr = service(tmp_path)
    svc.check()
    assert svc.download().status == 'downloaded'
    def broken():
        raise OSError('cache unavailable')
    mgr.get_update_pending_restart = broken
    result = svc.check()
    assert result.status == 'failed'
    assert result.progress < 100
