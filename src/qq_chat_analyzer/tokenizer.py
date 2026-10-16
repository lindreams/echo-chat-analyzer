"""Chinese tokenization and stopword filtering."""

from __future__ import annotations

import re
from collections.abc import Iterator, Set
from pathlib import Path

import jieba

from .wechat_official_emojis import wechat_expression_names
from .unicode_emoji import mask_emoji


_WORD_CONTENT_RE = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
_SINGLE_CHINESE_CHARACTER_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
_HYPHENATED_ASCII_RE = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+(?![A-Za-z0-9-])"
)
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s\uFF0C\u3002\uFF01\uFF1F\u3001\uFF1B\uFF1A]+",
    re.IGNORECASE,
)
_URL_PLACEHOLDER = "QQCHATURLPLACEHOLDER"
_SINGLE_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")
_SHORT_INTEGER_RE = re.compile(r"[0-9]{1,2}")
_DECK_QUANTITY_RE = re.compile(r"[0-9]+x", re.IGNORECASE)
_LAUGHTER_RE = re.compile(r"哈{2,}")
_GENERIC_EXPRESSION_PLACEHOLDER_RE = re.compile(
    r"\[(?:QQ表情|QQ贴图|微信表情|贴图|表情|动画表情)[^\]]*\]"
    r"|(?<![\u3400-\u9fffA-Za-z0-9])表情(?![\u3400-\u9fffA-Za-z0-9])",
    re.IGNORECASE,
)
_EXPRESSION_PLACEHOLDER_RE = re.compile(
    _GENERIC_EXPRESSION_PLACEHOLDER_RE.pattern
    + "|"
    + "|".join(
        re.escape(f"[{name}]")
        for name in wechat_expression_names()
    ),
    re.IGNORECASE,
)


def tokenize(
    text: str,
    stopwords_path: str | None = None,
    user_dict_path: str | None = None,
    *,
    stopwords: Set[str] | None = None,
) -> list[str]:
    """Tokenize text and remove stopped or low-information tokens."""
    if not isinstance(text, str) or not text.strip():
        return []

    _load_user_dictionary(user_dict_path)
    if stopwords is None:
        stopwords = load_stopwords(stopwords_path)
    # Mask expression markers before hyphen protection: a hyphenated bracket
    # code such as ``[Pooh-pooh]`` would otherwise be placeholder-protected
    # out of reach of the expression pattern and leak as a language token.
    expression_masked_text = _EXPRESSION_PLACEHOLDER_RE.sub(" ", mask_emoji(text))
    protected_text, protected_tokens = _protect_hyphenated_ascii(
        expression_masked_text
    )
    url_masked_text = _URL_RE.sub(_URL_PLACEHOLDER, protected_text)
    tokens: list[str] = []

    for raw_token in iter_text_tokens(url_masked_text):
        token = raw_token.strip()
        token = protected_tokens.get(token, token)
        if not token or token == _URL_PLACEHOLDER:
            continue
        if token.lower() in stopwords:
            continue
        if _WORD_CONTENT_RE.search(token) is None:
            continue
        if _is_single_chinese_character(token):
            continue
        if _is_low_information_token(token):
            continue
        tokens.append(token)

    return tokens


def iter_text_tokens(text: str) -> Iterator[str]:
    """Join adjacent laughter pieces without splitting words like 哈哈镜."""
    laughter: list[str] = []
    for token in jieba.lcut(text):
        if token == "哈" or _LAUGHTER_RE.fullmatch(token):
            laughter.append(token)
            continue
        if laughter:
            yield "".join(laughter)
            laughter.clear()
        yield token
    if laughter:
        yield "".join(laughter)


def iter_expression_placeholders(text: str) -> Iterator[str]:
    """Yield generic export placeholder markers that are not real expressions."""
    if not isinstance(text, str):
        return
    for match in _GENERIC_EXPRESSION_PLACEHOLDER_RE.finditer(text):
        yield match.group(0)


def _protect_hyphenated_ascii(text: str) -> tuple[str, dict[str, str]]:
    placeholder_prefix = "QQCHATHYPHENPLACEHOLDER"
    while placeholder_prefix in text:
        placeholder_prefix += "X"

    protected_tokens: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        placeholder = f"{placeholder_prefix}{len(protected_tokens)}TOKEN"
        protected_tokens[placeholder] = match.group(0)
        return placeholder

    protected_text = _HYPHENATED_ASCII_RE.sub(replace, text)
    return protected_text, protected_tokens


def load_stopwords(stopwords_path: str | None) -> set[str]:
    """Read stopwords for callers that reuse them within one analysis run."""
    if stopwords_path is None:
        return set()

    try:
        with Path(stopwords_path).open("r", encoding="utf-8") as file:
            return {
                line.strip().lower()
                for line in file
                if line.strip()
            }
    except (OSError, TypeError, UnicodeError):
        return set()


def _load_user_dictionary(user_dict_path: str | None) -> None:
    if user_dict_path is None:
        return

    try:
        path = Path(user_dict_path)
        if path.is_file():
            jieba.load_userdict(str(path))
    except (OSError, TypeError, UnicodeError, ValueError):
        return


def _is_single_chinese_character(token: str) -> bool:
    return (
        len(token) == 1
        and _SINGLE_CHINESE_CHARACTER_RE.fullmatch(token) is not None
    )


def _is_low_information_token(token: str) -> bool:
    """Return whether an ASCII token carries too little value for a word cloud."""
    return any(
        pattern.fullmatch(token) is not None
        for pattern in (
            _SINGLE_ASCII_LETTER_RE,
            _SHORT_INTEGER_RE,
            _DECK_QUANTITY_RE,
        )
    )
