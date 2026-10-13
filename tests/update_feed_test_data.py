"""Inert fictional SDK file source; never runs an installer or updater."""
import hashlib
import json
from zipfile import ZipFile

import velopack

from qq_chat_analyzer.application.installable_update_service import (
    InstallableUpdateService, UpdateFeedConfig,
)


def local_feed_service(tmp_path, *, corrupt=False):
    root, feed = tmp_path / 'fictional-app', tmp_path / 'feed'
    current, packages = root / 'current', root / 'packages'
    for directory in (current, packages, feed):
        directory.mkdir(parents=True)

    def manifest(version):
        return ('<package><metadata><id>FictionalEcho</id>'
                f'<version>{version}</version><mainExe>Fictional.exe</mainExe>'
                '<channel>test</channel></metadata></package>')

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

    def manager(config):
        return velopack.UpdateManager(str(config.source),
            options=velopack.UpdateOptions(False, -1, config.channel), locator=locator)

    service = InstallableUpdateService(feed=UpdateFeedConfig(feed, 'FictionalEcho', 'test'),
                                     manager_factory=manager, setup_runtime=lambda: True)
    return service, packages / package.name, package, content
