"""Tests for the QQ connection lifecycle manager.

All data here is fictional. The manager must never raise and never start a
runtime just to answer a status question.
"""

from __future__ import annotations

import importlib

import pytest


def _connection_module():
    return importlib.import_module("qq_chat_analyzer.application.qq.qq_connection_manager")


def _status(
    *,
    available=False,
    runtime_running=False,
    qq_online=False,
    version=None,
    message="",
    action_hint="",
):
    module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_connection_service"
    )
    return module.QQConnectionStatus(
        available=available,
        runtime_running=runtime_running,
        qq_online=qq_online,
        version=version,
        message=message,
        action_hint=action_hint,
    )


class _StubConnectionService:
    def __init__(self, status=None, error=None):
        self._status = status
        self._error = error
        self.check_calls = 0

    def check_status(self):
        self.check_calls += 1
        if self._error is not None:
            raise self._error
        return self._status


class _StubSetupService:
    def __init__(self, connect_status=None, error=None, runtime_status=None):
        self._connect_status = connect_status
        self._error = error
        self._runtime_status = runtime_status
        self.connect_calls = 0
        self.start_runtime_calls = 0
        self.get_runtime_status_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self._error is not None:
            raise self._error
        return self._connect_status

    def start_runtime(self):
        self.start_runtime_calls += 1
        raise AssertionError("status checks must not start the runtime")

    def get_runtime_status(self):
        self.get_runtime_status_calls += 1
        return self._runtime_status


def _manager(setup_service=None, connection_service=None):
    return _connection_module().QQConnectionManager(
        setup_service=setup_service,
        connection_service=connection_service,
    )


def test_get_snapshot_never_starts_the_runtime() -> None:
    setup = _StubSetupService()
    service = _StubConnectionService(_status(available=True))

    _manager(setup_service=setup, connection_service=service).get_snapshot()

    assert setup.connect_calls == 0
    assert setup.start_runtime_calls == 0


def test_auth_waiting_does_not_hide_runtime_fatal_failure() -> None:
    module = _connection_module()
    runtime = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_runtime_manager"
    )
    setup = _StubSetupService(
        runtime_status=runtime.QQRuntimeStatus(
            state=runtime.QQRuntimeState.ERROR,
            available=False,
        )
    )
    service = _StubConnectionService(
        _status(available=False, runtime_running=False, qq_online=False)
    )
    manager = _manager(
        setup_service=setup,
        connection_service=service,
    )
    manager.begin_auth_waiting()

    snapshot = manager.get_snapshot()

    assert snapshot.state is module.ConnectionState.ERROR
    assert snapshot.action_hint


def test_connect_returns_waiting_auth_without_waiting_for_login() -> None:
    module = _connection_module()
    setup = _StubSetupService(
        connect_status=_status(
            available=True,
            runtime_running=True,
            qq_online=True,
        )
    )
    service = _StubConnectionService(
        _status(
            available=False,
            runtime_running=True,
            qq_online=False,
        )
    )

    snapshot = _manager(
        setup_service=setup,
        connection_service=service,
    ).connect()

    assert setup.connect_calls == 0
    assert snapshot.state is module.ConnectionState.WAITING_AUTH
