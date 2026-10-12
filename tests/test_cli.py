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


@pytest.mark.slow_integration
def test_module_cli_help_guides_first_time_users() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC_ROOT)
    environment["PYTHONUTF8"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qq_chat_analyzer.cli",
            "--help",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    assert "余音 Echo" in result.stdout
    assert "本地 QQ / 微信聊天记录分析工具" in result.stdout
    assert "qqchat" not in result.stdout
    assert "最简单使用" in result.stdout
    assert 'echo-chat "聊天记录路径"' in result.stdout
    assert (
        r'echo-chat "C:\Users\你的用户名\Documents'
        r'\Echo\exports\qq-db.json"'
    ) in result.stdout
    assert "默认行为" in result.stdout
    assert "使用 default 默认过滤模式" in result.stdout
    assert "生成前 100 个高频词" in result.stdout
    assert "输出到 output/<聊天记录名称>/" in result.stdout
    assert "自动生成词云、高频词统计、发送者分析等结果" in result.stdout
    assert "更多用法" in result.stdout
    assert 'echo-chat "聊天记录路径" 过滤模式 数量' in result.stdout
    assert r'echo-chat "C:\xxx\group_xxx" default 200' in result.stdout
    assert "过滤模式" in result.stdout
    assert "default：默认模式" in result.stdout
    assert "topic：主题讨论模式" in result.stdout
    assert "culture：群聊文化模式" in result.stdout
    assert "多功能组合" in result.stdout
    assert r'echo-chat "C:\xxx\group_xxx" culture 200' in result.stdout
    assert "使用 culture 模式" in result.stdout
    assert "生成前 200 个高频词" in result.stdout
    assert "输出完整分析结果" in result.stdout
    assert "用法：" not in result.stdout
    assert "位置参数：" in result.stdout
    assert "高级参数：" in result.stdout
    assert "--stopwords" in result.stdout
    assert "--output-dir" in result.stdout
    assert "--font-path" in result.stdout
    assert "--top" in result.stdout
    assert "显示帮助并退出" in result.stdout
    assert "指定输出目录" in result.stdout
    assert "指定停用词文件" in result.stdout
    assert "指定中文字体文件" in result.stdout
    assert "指定高频词数量" in result.stdout
    assert "旧参数形式默认" not in result.stdout
    assert "优先于位置参数中的停用词策略" not in result.stdout
    assert "positional arguments:" not in result.stdout


@pytest.mark.slow_integration
def test_console_script_and_module_help_are_consistent() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SRC_ROOT)
    environment["PYTHONUTF8"] = "1"
    console_script_name = "echo-chat.exe" if os.name == "nt" else "echo-chat"
    console_script = Path(sys.executable).with_name(console_script_name)
    assert console_script.is_file(), "Install the project's current console entrypoints."

    console_result = subprocess.run(
        [str(console_script), "--help"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    module_result = subprocess.run(
        [sys.executable, "-m", "qq_chat_analyzer.cli", "--help"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert console_result.returncode == 0
    assert module_result.returncode == 0
    assert console_result.stdout == module_result.stdout


def test_registered_console_entrypoints_use_echo_brand() -> None:
    # Check the installed distribution, not stale source-tree egg-info that
    # PYTHONPATH may place ahead of the virtual environment's metadata.
    distribution = next(
        distribution
        for distribution in importlib.metadata.distributions(
            path=[sysconfig.get_path("purelib")]
        )
        if distribution.metadata["Name"] == "qq-chat-analyzer"
    )
    scripts = {
        entry.name: entry.value
        for entry in distribution.entry_points
        if entry.group == "console_scripts"
    }
    assert scripts == {
        "echo-chat": "qq_chat_analyzer.cli:main",
        "echo-gui": "qq_chat_analyzer.desktop:main",
    }


def test_missing_arguments_suggest_echo_command(capsys) -> None:
    assert main([]) == 2
    captured = capsys.readouterr()
    assert "echo-chat PATH" in captured.err
    assert "qqchat" not in captured.err


def test_simplified_arguments_use_default_profile_top_and_output() -> None:
    input_path = Path("data") / "fictional group"

    configuration = cli_module._parse_cli_configuration([str(input_path)])

    assert configuration.input_path == input_path
    assert configuration.stopwords_path == PROJECT_ROOT / "stopwords.txt"
    assert configuration.output_directory == Path("output") / "fictional group"
    assert configuration.top == 100


@pytest.mark.parametrize(
    ("profile", "expected_filename"),
    [
        ("topic", "stopwords_topic.txt"),
        ("culture", "stopwords_culture.txt"),
    ],
)
def test_simplified_profile_maps_to_existing_stopwords_file(
    profile: str,
    expected_filename: str,
) -> None:
    configuration = cli_module._parse_cli_configuration(
        ["fictional-chat.jsonl", profile, "200"]
    )

    assert configuration.stopwords_path == PROJECT_ROOT / expected_filename
    assert configuration.top == 200


def test_legacy_arguments_keep_previous_defaults() -> None:
    configuration = cli_module._parse_cli_configuration(
        ["--input", "fictional-chat.json"]
    )

    assert configuration.input_path == Path("fictional-chat.json")
    assert configuration.output_directory == Path("output")
    assert configuration.stopwords_path == Path("stopwords.txt")
    assert configuration.top == 50


def test_simplified_file_input_uses_filename_without_json_suffix() -> None:
    configuration = cli_module._parse_cli_configuration(
        ["fictional chat.jsonl"]
    )

    assert configuration.output_directory == Path("output") / "fictional chat"


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
    ("status", "expected_message"),
    [
        (AnalysisStatus.NO_VALID_TEXT, "没有有效文本"),
        (AnalysisStatus.NO_TOKENS, "有效文本未产生可统计词语"),
        (AnalysisStatus.EXPRESSION_ONLY, "已生成表达文化报告"),
    ],
)
def test_main_displays_empty_analysis_status_without_top_words(
    status: AnalysisStatus,
    expected_message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class EmptyAnalysisApplicationService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            """Accept the legacy artifact writer the CLI injects."""

        def execute(self, request: AnalysisRequestDTO) -> AnalysisResultDTO:
            return AnalysisResultDTO(
                status=status,
                processed_message_count=4,
                valid_text_count=2,
            )

    monkeypatch.setattr(
        cli_module,
        "AnalysisApplicationService",
        EmptyAnalysisApplicationService,
    )

    exit_code = main(["--input", str(tmp_path / "private-chat.json")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "处理消息数量: 4" in captured.out
    assert "有效文本数量: 2" in captured.out
    assert expected_message in captured.out
    assert "Top " not in captured.out
    assert captured.err == ""


def test_simplified_cli_path_with_spaces_uses_automatic_output_directory(
    detailed_input_path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_dir = tmp_path / "fictional group"
    input_dir.mkdir()
    shutil.copyfile(detailed_input_path, input_dir / "sample.json")
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            str(input_dir),
            "--font-path",
            str(_available_chinese_font()),
        ]
    )

    captured = capsys.readouterr()
    output_dir = tmp_path / "output" / "fictional group"
    assert exit_code == 0
    assert (output_dir / "word_frequency.csv").is_file()
    assert (output_dir / "wordcloud.png").is_file()
    assert (output_dir / "word_speaker_summary.csv").is_file()
    assert (output_dir / "word_speaker_frequency.csv").is_file()
    assert (output_dir / "word_top_speakers.png").is_file()
    assert "Top 100" in captured.out


def test_invalid_simplified_profile_returns_friendly_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["fictional-chat.json", "smart"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "profile" in captured.err
    assert "smart" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("invalid_top", ["many", "0", "-2"])
def test_invalid_simplified_top_returns_friendly_error(
    invalid_top: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["fictional-chat.json", "culture", invalid_top])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "top" in captured.err.lower()
    assert invalid_top in captured.err
    assert "Traceback" not in captured.err


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


def test_cli_does_not_directly_import_core_pipeline_modules() -> None:
    source = Path(cli_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    package_name = "qq_chat_analyzer"
    forbidden_modules = {
        f"{package_name}.analyzer",
        f"{package_name}.cleaner",
        f"{package_name}.exporters",
        f"{package_name}.parser",
        f"{package_name}.smart_profile",
        f"{package_name}.tokenizer",
    }
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level == 1:
            import_base = package_name
            if node.module:
                import_base = f"{import_base}.{node.module}"
        elif node.level == 0 and node.module:
            import_base = node.module
        else:
            continue

        imported_modules.add(import_base)
        imported_modules.update(
            f"{import_base}.{alias.name}" for alias in node.names
        )

    direct_core_imports = {
        imported_module
        for imported_module in imported_modules
        for forbidden_module in forbidden_modules
        if imported_module == forbidden_module
        or imported_module.startswith(f"{forbidden_module}.")
    }

    assert direct_core_imports == set()


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


def test_directory_input_ignores_one_invalid_json_file(
    detailed_input_path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copyfile(detailed_input_path, input_dir / "valid.json")
    (input_dir / "invalid.json").write_text("{not valid json", encoding="utf-8")
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(input_dir),
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
    assert "处理消息数量: 7" in captured.out
    assert (output_dir / "word_frequency.csv").is_file()
    assert (output_dir / "wordcloud.png").is_file()


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


def test_directory_input_recursively_discovers_jsonl(
    chatlab_input_path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chunks_dir = tmp_path / "export" / "chunks"
    chunks_dir.mkdir(parents=True)
    shutil.copyfile(chatlab_input_path, chunks_dir / "c000001.jsonl")
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "--input",
            str(tmp_path / "export"),
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


def test_missing_input_path_returns_clear_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_path = tmp_path / "missing.json"

    exit_code = main(["--input", str(missing_path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "输入路径不存在" in captured.err


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
