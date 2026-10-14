"""Fixed official Setup identity and feed; construction performs no IO.

User confirmation and complete shutdown evidence gate the existing A3 handoff.
No runtime input can select a different production feed.
"""
from .installable_update_service import InstallableUpdateService, UpdateFeedConfig


# Keep the P1 official identity; the pinned CLI has packaged this ID successfully.
PRODUCTION_PACKAGE_ID = 'Lindreams.Echo'
PRODUCTION_CHANNEL = 'win-x64-stable'
PRODUCTION_SOURCE = 'https://github.com/lindreams/echo-chat-analyzer'


def production_feed() -> UpdateFeedConfig:
    return UpdateFeedConfig(PRODUCTION_SOURCE, PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL)


def production_update_service() -> InstallableUpdateService:
    return InstallableUpdateService(feed=production_feed())
