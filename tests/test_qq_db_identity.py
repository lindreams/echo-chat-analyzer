"""Unit coverage for the QQ Direct DB canonical self identity."""

from __future__ import annotations

import pytest

from qq_chat_analyzer.qq_db_identity import (
    QQ_DB_SELF_NAMESPACE,
    canonical_qq_uin,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("100000001", "100000001"), (100000001, "100000001"), (0, None), (True, None)],
)
def test_canonical_qq_uin(raw: object, expected: str | None) -> None:
    assert canonical_qq_uin(raw) == expected


def test_canonical_qq_uin_rejects_non_scalar() -> None:
    assert canonical_qq_uin([]) is None
    assert canonical_qq_uin({}) is None
    assert canonical_qq_uin(object()) is None
