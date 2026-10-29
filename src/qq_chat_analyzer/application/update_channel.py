"""Fixed official Setup identity and feed; construction performs no IO.

User confirmation and complete shutdown evidence gate the existing A3 handoff.
No runtime input can select a different production feed.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from .installable_update_service import InstallableUpdateService, UpdateFeedConfig


# Keep the P1 official identity; the pinned CLI has packaged this ID successfully.
PRODUCTION_PACKAGE_ID = 'Lindreams.Echo'
PRODUCTION_CHANNEL = 'win-x64-stable'
PRODUCTION_REPOSITORY = 'https://cnb.cool/echo_mly/echo_releases'
PRODUCTION_SOURCE = PRODUCTION_REPOSITORY + '/-/releases/download/updates'
PRODUCTION_METADATA = PRODUCTION_SOURCE + '/echo-update.json'


def official_release_url(url: object) -> bool:
    """Accept only canonical stable release pages in our distribution repository."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (parsed.scheme == 'https' and parsed.netloc == 'cnb.cool'
            and re.fullmatch(r'/echo_mly/echo_releases/-/releases/tag/v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', parsed.path) is not None
            and not parsed.query and not parsed.fragment)


def production_feed() -> UpdateFeedConfig:
    from .installable_update_service import UpdateFeedConfig
    return UpdateFeedConfig(PRODUCTION_SOURCE, PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL)


def production_update_service() -> InstallableUpdateService:
    from .installable_update_service import InstallableUpdateService
    return InstallableUpdateService(feed=production_feed())
