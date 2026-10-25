"""Text cleaning helpers for normalized QQ chat messages."""

from __future__ import annotations

import re
import unicodedata


_IMAGE_PLACEHOLDER_RE = re.compile(
    r"\[(?:图片|图像|动画表情|CQ:image)(?:[：:,，][^\]]*)?\]",
    flags=re.IGNORECASE,
)
_REPLY_MARKER_RE = re.compile(
    r"\[(?:回复消息|回复)(?:[：:][^\]]*)?\]",
)
_MENTION_ALL_RE = re.compile(r"(?<!\w)@全体成员[：:]?")
_MENTION_RE = re.compile(
    r"(?<!\w)@[^\s@，。！？、:：;；]+[：:]?"
)
# WeChat terminates native mentions with U+2005; nicknames may contain spaces
# and punctuation. Chinese body text may touch @, while email local parts may not.
_WECHAT_NATIVE_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.%+\-])@[^\u2005\r\n@]+\u2005")
_WECHAT_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_.%+\-])@[^\s@，。！？、:：;；]+[：:]?")
_WECHAT_INTERNAL_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:wxid_[A-Za-z0-9_]+|wx_[A-Za-z0-9_]+)"
    r"(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_WECHAT_BARE_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])[a-z0-9]{12,}(?![A-Za-z0-9])"
)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
_WHITESPACE_CONTROL_RE = re.compile(r"[\t\n\r\f\v]+")
_REPEATED_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str, platform: str | None = None) -> str:
    """Remove chat structure while preserving the user's actual wording."""
    if not isinstance(text, str):
        return ""

    cleaned = _WECHAT_NATIVE_MENTION_RE.sub(" ", text) if platform == "wechat" else text
    cleaned = _IMAGE_PLACEHOLDER_RE.sub("", cleaned)
    cleaned = _REPLY_MARKER_RE.sub("", cleaned)
    cleaned = _MENTION_ALL_RE.sub("", cleaned)
    if platform == "wechat":
        cleaned = _WECHAT_MENTION_RE.sub(" ", cleaned)
    else:
        cleaned = _MENTION_RE.sub("", cleaned)
    if platform == "wechat":
        cleaned = _WECHAT_INTERNAL_ID_RE.sub(" ", cleaned)
        cleaned = _WECHAT_BARE_ID_RE.sub(" ", cleaned)
    cleaned = _ZERO_WIDTH_RE.sub("", cleaned)

    # Newlines and tabs separate words, so normalize them before removing
    # other control and formatting characters.
    cleaned = _WHITESPACE_CONTROL_RE.sub(" ", cleaned)
    cleaned = "".join(
        character
        for character in cleaned
        if unicodedata.category(character) not in {"Cc", "Cf"}
    )

    return _REPEATED_WHITESPACE_RE.sub(" ", cleaned).strip()
