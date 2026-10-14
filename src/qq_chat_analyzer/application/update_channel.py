"""Fixed production update channel for Echo (Qt-free).

This module is the single, trusted source of the production Velopack identity
and feed. It is intentionally literal: the packId, channel and source are
compile-time constants and are never derived from environment variables, chat
content, GUI text input, or the legacy GitHub Release page.

Construction is inert. It performs no network, filesystem or SDK work; a worker
must run check/download later, exactly like the existing update core.

Safety boundary (unapproved auto-install)
-----------------------------------------
Velopack 1.2.161 still has an unresolved wait-failure / timeout "continue
installing" risk in ``wait_exit_then_apply_updates`` (see
``docs/research/2026-10-13-a3-install-handoff.md``). Wiring the production feed
into the composition root would otherwise make the update dialog expose the
unverified install handoff to real Setup users as soon as a Full package is
downloaded. ``PRODUCTION_INSTALL_HANDOFF_APPROVED`` therefore stays ``False`` and
``guard_install_handoff`` denies ``prepare_install``/``handoff`` for the
production channel until a human approves the fix. This is the single testable
switch; it is not an environment variable and must not be flipped by GUI input.

The download/cache/install algorithms in ``installable_update_service`` are not
modified here; the gate only decides whether the production service is allowed
to start the unapproved install path.
"""
from __future__ import annotations

from .installable_update_service import (
    InstallableUpdater,
    InstallableUpdateResult,
    InstallHandoffResult,
    UpdateFeedConfig,
)

#: Production Setup packId (must match the packaged Setup manifest and feed).
PRODUCTION_PACKAGE_ID = "Lindreams.Echo"

#: Production channel published as ``releases.<channel>.json`` on the feed.
PRODUCTION_CHANNEL = "win-x64-stable"

#: Official release repository used as the Velopack HTTPS feed.
PRODUCTION_SOURCE = "https://github.com/lindreams/echo-chat-analyzer"

#: Human approval switch for the production auto-install handoff. Do NOT set to
#: True until the Velopack 1.2.161 wait-failure/timeout risk is resolved.
PRODUCTION_INSTALL_HANDOFF_APPROVED = False

#: Shown when a user requests an install that is not yet approved.
INSTALL_NOT_APPROVED_MESSAGE = (
    "当前版本暂未开放应用内自动安装，请查看发布页面手动更新。"
)


def production_feed() -> UpdateFeedConfig:
    """Return the one fixed production feed configuration."""
    return UpdateFeedConfig(PRODUCTION_SOURCE, PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL)


class InstallHandoffGate:
    """Composition-root policy gate around a configured ``InstallableUpdateService``.

    It forwards feed inspection, check and download unchanged, but denies the
    install handoff unless the production install path has been approved. It
    never starts an installer and does not touch the core's download or cache
    verification algorithms.
    """

    def __init__(self, service: InstallableUpdater, *, approved: bool) -> None:
        self._service = service
        self.install_handoff_approved = approved

    def check(self) -> InstallableUpdateResult:
        return self._service.check()

    def download(self, *, progress=None) -> InstallableUpdateResult:
        return self._service.download(progress=progress)

    def get_status(self) -> InstallableUpdateResult:
        return self._service.get_status()

    def prepare_install(self) -> InstallHandoffResult:
        if self.install_handoff_approved is not True:
            return InstallHandoffResult(
                "denied", public_message=INSTALL_NOT_APPROVED_MESSAGE
            )
        return self._service.prepare_install()

    def handoff(self, token: str, shutdown) -> InstallHandoffResult:
        if self.install_handoff_approved is not True:
            return InstallHandoffResult(
                "denied", public_message=INSTALL_NOT_APPROVED_MESSAGE
            )
        return self._service.handoff(token, shutdown)


def guard_install_handoff(
    service: InstallableUpdater, *, approved: bool | None = None
) -> InstallHandoffGate:
    """Wrap ``service`` with the install-handoff policy gate.

    ``approved`` defaults to ``PRODUCTION_INSTALL_HANDOFF_APPROVED``. Tests may
    pass an explicit value; production must not override the module constant.
    """
    return InstallHandoffGate(
        service,
        approved=(
            PRODUCTION_INSTALL_HANDOFF_APPROVED if approved is None else approved
        ),
    )


def production_update_service() -> InstallHandoffGate:
    """Build the production installable update service injected by the GUI.

    A configured ``InstallableUpdateService`` on the fixed production feed,
    wrapped by the install-handoff gate. Construction performs no I/O.
    """
    from .installable_update_service import InstallableUpdateService

    return guard_install_handoff(InstallableUpdateService(feed=production_feed()))
