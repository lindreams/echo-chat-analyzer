"""匿名输出本地聊天记录的 Smart Profile 调试统计。"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.candidates import Candidate
from qq_chat_analyzer.decision_engine import create_filter_decisions
from qq_chat_analyzer.detectors import (
    detect_interactive_bot_candidates,
    detect_robot_candidates,
    detect_template_candidates,
)
from qq_chat_analyzer.application import (
    ApplicationServiceError,
    ImportRequest,
    ImportService,
)
from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.filter_pipeline import FilterPipeline


METRIC_LABELS = (
    ("mention_count", "触发次数"),
    ("response_count", "响应次数"),
    ("response_rate", "响应率"),
    ("unique_trigger_source_count", "不同触发来源数量"),
    ("response_template_score", "响应模板集中度"),
)


class _PrivacySafeArgumentParser(argparse.ArgumentParser):
    """避免参数错误时回显用户输入。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print("错误：命令行参数无效。", file=sys.stderr)
        raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    """运行只输出匿名聚合数字的 Smart Profile 调试报告。"""
    parser = _PrivacySafeArgumentParser(
        prog="匿名自动化画像调试",
        description="Echo 匿名 Smart Profile 调试分析",
    )
    parser.add_argument(
        "input_path",
        metavar="聊天记录位置",
        help="当前支持的聊天记录 JSON/JSONL 文件或目录。",
    )
    arguments = parser.parse_args(argv)

    try:
        raw_message_count, parsed_messages = _load_parsed_messages(
            Path(arguments.input_path)
        )
    except (OSError, TypeError, ValueError, ApplicationServiceError):
        print(
            "错误：未找到可处理的 JSON 或 JSONL 输入。",
            file=sys.stderr,
        )
        return 2

    try:
        robot_candidates = detect_robot_candidates(parsed_messages)
        template_candidates = detect_template_candidates(parsed_messages)
        interactive_candidates = detect_interactive_bot_candidates(
            parsed_messages
        )
        automation_decisions = create_filter_decisions(
            interactive_candidates
        )
        decisions = create_filter_decisions([*robot_candidates, *template_candidates])
        filtering_result = FilterPipeline().apply_filter_decisions(parsed_messages, decisions)

        _print_report(
            raw_message_count=raw_message_count,
            parsed_message_count=len(parsed_messages),
            robot_candidate_count=len(robot_candidates),
            template_candidate_count=len(template_candidates),
            interactive_candidates=interactive_candidates,
            automation_ignore_count=sum(
                decision.action == "ignore"
                for decision in automation_decisions
            ),
            automation_review_count=sum(
                decision.action == "review"
                for decision in automation_decisions
            ),
            filtered_message_count=len(filtering_result.filtered_messages),
            kept_message_count=len(filtering_result.kept_messages),
        )
    except Exception:
        print("错误：匿名分析失败。", file=sys.stderr)
        return 1
    return 0


def _load_parsed_messages(input_path: Path) -> tuple[int, list[ChatMessage]]:
    outcome = ImportService().execute(ImportRequest(input_path))
    if outcome.result.format is None and not outcome.messages:
        raise ValueError("Unsupported input format")
    return outcome.processed_message_count, list(outcome.messages)


def _print_report(
    *,
    raw_message_count: int,
    parsed_message_count: int,
    robot_candidate_count: int,
    template_candidate_count: int,
    interactive_candidates: Sequence[Candidate],
    automation_ignore_count: int,
    automation_review_count: int,
    filtered_message_count: int,
    kept_message_count: int,
) -> None:
    print("输入统计")
    print("------------")
    print(f"原始消息数量: {raw_message_count}")
    print(f"解析消息数量: {parsed_message_count}")
    print()

    print("检测结果")
    print("------------")
    print(f"机器人候选数量: {robot_candidate_count}")
    print(f"模板候选数量: {template_candidate_count}")
    print(f"交互机器人候选数量: {len(interactive_candidates)}")
    print()

    print("交互机器人行为证据")
    print("------------")
    if not interactive_candidates:
        print("候选数量: 0")
    for index, candidate in enumerate(interactive_candidates, start=1):
        print(f"候选 {index}")
        print("类型: 交互式自动化来源")
        print(f"置信度: {_format_number(candidate.score)}")
        metrics = candidate.metadata.get("metrics")
        for metric_name, label in METRIC_LABELS:
            print(
                f"{label}: "
                f"{_format_metric(metrics, metric_name)}"
            )
        print()

    print("交互机器人决策")
    print("------------")
    print(f"自动过滤数量: {automation_ignore_count}")
    print(f"人工审核数量: {automation_review_count}")
    print()

    print("完整 Smart Profile 结果")
    print("------------")
    print(f"过滤消息数量: {filtered_message_count}")
    print(f"保留消息数量: {kept_message_count}")


def _format_metric(
    metrics: object,
    metric_name: str,
) -> str:
    if not isinstance(metrics, Mapping):
        return "不可用"
    return _format_number(metrics.get(metric_name))


def _format_number(value: object) -> str:
    if type(value) is int:
        return str(value)
    if type(value) is float and math.isfinite(value):
        return str(value)
    return "不可用"


if __name__ == "__main__":
    raise SystemExit(main())
