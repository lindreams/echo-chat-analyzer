"""End-to-end tests for the local command-line analysis pipeline."""

from __future__ import annotations

import ast
import csv
import importlib.metadata
import json
from chat_input_test_data import (
    FICTIONAL_CHATLAB_EXPORT,
    FICTIONAL_DETAILED_EXPORT,
    detailed_payload,
)
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
STOPWORDS_PATH = PROJECT_ROOT / "stopwords.txt"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer import cli as cli_module
from qq_chat_analyzer.application import (
    AnalysisRequestDTO,
    AnalysisResultDTO,
    AnalysisStatus,
    ArtifactGenerationFailed,
    InputPathNotFound,
    InvalidAnalysisRequest,
    NoSupportedInput,
    WordFrequencyDTO,
)
from qq_chat_analyzer.cli import main


def test_main_adapts_cli_configuration_to_application_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "private-chat.json"
    output_directory = tmp_path / "private-output"
    stopwords_path = tmp_path / "private-stopwords.txt"
    font_path = str(tmp_path / "private-font.ttf")
    requests: list[AnalysisRequestDTO] = []

    class FakeAnalysisApplicationService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            """Accept the legacy artifact writer the CLI injects."""

        def execute(self, request: AnalysisRequestDTO) -> AnalysisResultDTO:
            requests.append(request)
            return AnalysisResultDTO(
                status=AnalysisStatus.COMPLETED,
                processed_message_count=4,
                valid_text_count=2,
                top_words=(WordFrequencyDTO(word="Python", count=3),),
            )

    monkeypatch.setattr(
        cli_module,
        "AnalysisApplicationService",
        FakeAnalysisApplicationService,
    )

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_directory),
            "--stopwords",
            str(stopwords_path),
            "--font-path",
            font_path,
            "--top",
            "9",
        ]
    )

    captured = capsys.readouterr()
    assert requests == [
        AnalysisRequestDTO(
            input_path=input_path,
            output_directory=output_directory,
            stopwords_path=stopwords_path,
            font_path=font_path,
            top=9,
        )
    ]
    assert exit_code == 0
    assert "处理消息数量: 4" in captured.out
    assert "有效文本数量: 2" in captured.out
    assert "Top 9" in captured.out
    assert "Python\t3" in captured.out
    assert captured.err == ""
    assert str(input_path) not in captured.out


@pytest.mark.parametrize(
    ("application_error", "expected_exit_code", "expected_message"),
    [
        (InputPathNotFound(), 2, "输入路径不存在"),
        (NoSupportedInput(), 2, "未找到可处理的 JSON 或 JSONL 文件"),
        (InvalidAnalysisRequest(), 2, "分析请求无效"),
        (ArtifactGenerationFailed(), 1, "生成输出失败"),
    ],
)
def test_main_maps_application_errors_without_exposing_private_paths(
    application_error: Exception,
    expected_exit_code: int,
    expected_message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_input_path = tmp_path / "private-chat.json"

    class FailingAnalysisApplicationService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            """Accept the legacy artifact writer the CLI injects."""

        def execute(self, request: AnalysisRequestDTO) -> AnalysisResultDTO:
            raise application_error

    monkeypatch.setattr(
        cli_module,
        "AnalysisApplicationService",
        FailingAnalysisApplicationService,
    )

    exit_code = main(["--input", str(private_input_path)])

    captured = capsys.readouterr()
    assert exit_code == expected_exit_code
    assert expected_message in captured.err
    assert str(private_input_path) not in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


@pytest.mark.slow_integration
def test_module_cli_file_input_generates_outputs_without_printing_chat(
    detailed_input_path,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "fictional-chat.json"
    shutil.copyfile(detailed_input_path, input_path)
    output_dir = tmp_path / "generated-output"
    font_path = _available_chinese_font()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC_ROOT)
    environment["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qq_chat_analyzer.cli",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--stopwords",
            str(STOPWORDS_PATH),
            "--font-path",
            str(font_path),
            "--top",
            "10",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    assert (output_dir / "word_frequency.csv").is_file()
    assert (output_dir / "wordcloud.png").is_file()
    assert "处理消息数量: 7" in result.stdout
    assert "有效文本数量: 3" in result.stdout
    assert "今天一起学习 Python 数据分析" not in result.stdout
    assert "好呀，下午两点开始吧" not in result.stdout


def test_cli_generates_word_speaker_csvs_for_fictional_senders(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "fictional-multi-sender.json"
    input_path.write_text(
        json.dumps(
            detailed_payload([
                    {
                        "timestamp": 1767317100,
                        "sender": {"nickname": "小青"},
                        "type": "text",
                        "content": {"text": "Python Python 数据分析"},
                    },
                    {
                        "timestamp": 1767317101,
                        "sender": {"nickname": "小白"},
                        "type": "text",
                        "content": {"text": "Python 数据分析"},
                    },
                ]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--stopwords",
            str(STOPWORDS_PATH),
            "--font-path",
            str(_available_chinese_font()),
            "--top",
            "5",
        ]
    )

    captured = capsys.readouterr()
    summary_path = output_dir / "word_speaker_summary.csv"
    frequency_path = output_dir / "word_speaker_frequency.csv"
    chart_path = output_dir / "word_top_speakers.png"

    assert exit_code == 0
    assert (output_dir / "word_frequency.csv").is_file()
    assert (output_dir / "wordcloud.png").is_file()
    assert summary_path.is_file()
    assert frequency_path.is_file()
    assert chart_path.is_file()
    with Image.open(chart_path) as image:
        assert image.width > 0
        assert image.height > 0

    with summary_path.open("r", encoding="utf-8-sig", newline="") as file:
        summary_rows = list(csv.DictReader(file))
    assert {
        "word": "Python",
        "total_count": "3",
        "top_speaker": "小青",
        "top_speaker_count": "2",
        "top_speaker_share_percent": "66.67",
    } in summary_rows

    with frequency_path.open("r", encoding="utf-8-sig", newline="") as file:
        frequency_rows = list(csv.DictReader(file))
    assert [
        row
        for row in frequency_rows
        if row["word"] == "Python"
    ] == [
        {"word": "Python", "speaker": "小青", "count": "2"},
        {"word": "Python", "speaker": "小白", "count": "1"},
    ]

    assert "Python Python 数据分析" not in captured.out
    assert "Python 数据分析" not in captured.out
    assert "小青" not in captured.out
    assert "小白" not in captured.out


def test_smart_profile_filtered_messages_do_not_enter_word_frequency(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "fictional-smart-profile.json"
    messages = [
        {
            "timestamp": 1767317200 + index,
            "sender": {"nickname": "虚构自动播报器"},
            "type": "text",
            "content": {"text": "BOTNOISE BOTNOISE"},
        }
        for index in range(10)
    ]
    messages.append(
        {
            "timestamp": 1767317210,
            "sender": {"nickname": "虚构普通用户"},
            "type": "text",
            "content": {"text": "HUMANTOPIC Python"},
        }
    )
    input_path.write_text(
        json.dumps(detailed_payload(messages), ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--stopwords",
            str(STOPWORDS_PATH),
            "--font-path",
            str(_available_chinese_font()),
            "--top",
            "10",
        ]
    )

    captured = capsys.readouterr()
    output_filenames = [
        "word_frequency.csv",
        "wordcloud.png",
        "word_speaker_summary.csv",
        "word_speaker_frequency.csv",
        "word_top_speakers.png",
    ]
    for filename in output_filenames:
        assert (output_dir / filename).is_file()

    with (output_dir / "word_frequency.csv").open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        frequency_rows = list(csv.DictReader(file))

    words = [row["word"] for row in frequency_rows]
    assert "HUMANTOPIC" in words
    assert "Python" in words
    assert "BOTNOISE" not in words
    assert "BOTNOISE" not in captured.out
    assert "虚构自动播报器" not in captured.out


def test_jsonl_file_input_generates_outputs_without_printing_chat(
    chatlab_input_path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "fictional-chat.jsonl"
    shutil.copyfile(chatlab_input_path, input_path)
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--stopwords",
            str(STOPWORDS_PATH),
            "--font-path",
            str(_available_chinese_font()),
            "--top",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "处理消息数量: 4" in captured.out
    assert "有效文本数量: 2" in captured.out
    assert "量子课程今天开课" not in captured.out
    assert "下午继续研究算法" not in captured.out
    assert (output_dir / "word_frequency.csv").is_file()
    assert (output_dir / "wordcloud.png").is_file()


def test_no_valid_text_does_not_create_output_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "system-only.json"
    input_path.write_text(
        json.dumps(
            detailed_payload([
                    {
                        "timestamp": 1767317000,
                        "sender": {"nickname": "系统"},
                        "type": "system",
                        "content": {"text": "虚构系统通知"},
                    }
                ]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "没有有效文本" in captured.out
    assert not (output_dir / "word_frequency.csv").exists()
    assert not (output_dir / "wordcloud.png").exists()
    assert not (output_dir / "word_speaker_summary.csv").exists()
    assert not (output_dir / "word_speaker_frequency.csv").exists()
    assert not (output_dir / "word_top_speakers.png").exists()


def _available_chinese_font() -> Path:
    windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        windows_fonts / "msyh.ttc",
        windows_fonts / "msyhbd.ttc",
        windows_fonts / "simhei.ttf",
        windows_fonts / "simsun.ttc",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    pytest.skip("No Chinese font is available for the CLI test.")


@pytest.fixture
def detailed_input_path(tmp_path):
    path = tmp_path / "fixture-detailed.json"
    path.write_text(json.dumps(FICTIONAL_DETAILED_EXPORT, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def chatlab_input_path(tmp_path):
    path = tmp_path / "fixture-chatlab.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in FICTIONAL_CHATLAB_EXPORT), encoding="utf-8")
    return path
