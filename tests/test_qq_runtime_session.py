"""The single owned bridge credential: mint, read, retire, never leak.

Fictional values only; no runtime, no QQ, no network.
"""
from __future__ import annotations

import re

from qq_chat_analyzer.application.qq.qq_runtime_session import (
    QQRuntimeSession,
    default_qq_runtime_session,
    is_bridge_credential,
    mint_bridge_credential,
)


def test_minted_credential_is_high_entropy_lowercase_hex():
    value = mint_bridge_credential()
    assert isinstance(value, str)
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert is_bridge_credential(value)


def test_each_launch_mints_a_new_credential_and_keeps_only_the_last():
    session = QQRuntimeSession()
    first = session.begin_launch()
    second = session.begin_launch()
    assert first != second
    assert is_bridge_credential(first) and is_bridge_credential(second)
    # Single slot: no credential history is retained.
    assert session.credential() == second
    assert session.retire(first) is None
    assert session.credential() == second


def test_retire_clears_the_current_credential():
    session = QQRuntimeSession()
    token = session.begin_launch()
    session.retire(token)
    assert session.credential() is None


def test_session_repr_never_contains_the_credential():
    session = QQRuntimeSession()
    token = session.begin_launch()
    assert token not in repr(session)
    assert token not in str(session)
    assert token not in f"{session}"
    assert "unset" in repr(QQRuntimeSession())


def test_default_session_credentials_are_retired_between_uses():
    session = default_qq_runtime_session()
    token = session.begin_launch()
    assert session.credential() == token
    session.retire(token)
    assert session.credential() is None
