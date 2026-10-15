"""Behavioral tests for jieba tokenization and stopword filtering."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.tokenizer import tokenize
from qq_chat_analyzer.wechat_official_emojis import WECHAT_EMOJI_ALIASES


def test_tokenizes_chinese_text_with_jieba() -> None:
    assert tokenize("我喜欢数据分析") == ["喜欢", "数据分析"]


def test_sentence_preserves_laughter_runs_and_separate_short_laughter() -> None:
    assert tokenize("今天哈哈哈哈哈继续学习，哈哈！哈哈哈？哈哈哈哈。") == [
        "今天", "哈哈哈哈哈", "继续", "学习", "哈哈", "哈哈哈", "哈哈哈哈",
    ]


def test_filters_trimmed_stopwords_and_ignores_blank_lines(
    tmp_path: Path,
) -> None:
    stopwords_path = tmp_path / "stopwords.txt"
    stopwords_path.write_text("  我  \n\n喜欢\n", encoding="utf-8")

    assert tokenize("我喜欢数据分析", str(stopwords_path)) == ["数据分析"]


def test_user_dictionary_keeps_custom_phrase_as_one_token(
    tmp_path: Path,
) -> None:
    user_dict_path = tmp_path / "user-dict.txt"
    user_dict_path.write_text("量子猫猫协议 100000 n\n", encoding="utf-8")

    assert tokenize(
        "量子猫猫协议",
        user_dict_path=str(user_dict_path),
    ) == ["量子猫猫协议"]


def test_empty_text_returns_empty_list() -> None:
    assert tokenize("") == []
    assert tokenize(" \t\n ") == []


def test_preserves_informative_ascii_and_hyphenated_tokens() -> None:
    text = "AI DK JJC CS61B 666 2026 fall-anchor"

    assert tokenize(text) == [
        "AI",
        "DK",
        "JJC",
        "CS61B",
        "666",
        "2026",
        "fall-anchor",
    ]


def test_url_tokens_are_ignored() -> None:
    assert tokenize("看看 https://b23.tv/abc 怎么样") == [
        "看看",
        "怎么样",
    ]
    assert tokenize("www.example.com") == []
    assert tokenize("明天一起 https://a.com 吃饭") == [
        "明天",
        "一起",
        "吃饭",
    ]


def test_ignores_expression_markers_for_language_tokens() -> None:
    tokens = tokenize("今天真的崩了[捂脸] [OK] 继续[旺柴]")

    assert "今天" in tokens
    assert "真的" in tokens
    assert "继续" in tokens
    assert "捂脸" not in tokens
    assert "旺柴" not in tokens
    assert "OK" not in tokens


@pytest.mark.parametrize("word", ("TODO", "AI", "Python"))
def test_bracketed_plain_english_words_are_not_expressions(word: str) -> None:
    assert word not in WECHAT_EMOJI_ALIASES
    assert tokenize(f"[{word}]") == [word]


def test_literal_english_words_without_brackets_are_preserved() -> None:
    assert tokenize("Laugh") == ["Laugh"]
    assert tokenize("Sob") == ["Sob"]
    assert tokenize("Lol") == ["Lol"]
    assert tokenize("Awesome") == ["Awesome"]
    assert tokenize("今天 Grin 一下") == ["今天", "Grin", "一下"]
