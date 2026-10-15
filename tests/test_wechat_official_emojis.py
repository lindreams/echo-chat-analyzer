"""Contract tests for the vendored official WeChat emoji dictionary."""

from __future__ import annotations

import sys
from pathlib import Path



PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.wechat_official_emojis import (  # noqa: E402
    OFFICIAL_WECHAT_EMOJI_NAMES,
    WECHAT_EMOJI_ALIASES,
    canonical_wechat_emoji_name,
)


def test_alias_map_only_normalizes_to_official_names() -> None:
    assert WECHAT_EMOJI_ALIASES
    assert set(WECHAT_EMOJI_ALIASES.values()) <= OFFICIAL_WECHAT_EMOJI_NAMES
    assert all(
        alias and "[" not in alias and "]" not in alias
        for alias in WECHAT_EMOJI_ALIASES
    )


def test_alias_lookup_is_case_insensitive_and_rejects_unknown_codes() -> None:
    assert canonical_wechat_emoji_name("Facepalm") == "捂脸"
    assert canonical_wechat_emoji_name("facepalm") == "捂脸"
    assert canonical_wechat_emoji_name("捂脸") == "捂脸"
    assert canonical_wechat_emoji_name("TODO") is None


#: English codes published for the current client whose canonical Chinese
#: names were previously missing from the alias map. Source: macOS client
#: ``newemoji-config.xml`` (key / cn-value / en-value), cross-checked against
#: the 109 codes measured on Android WeChat 8.0.48.
