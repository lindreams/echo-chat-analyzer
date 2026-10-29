"""Presentation layer turning analysis reports into display-ready models."""

from __future__ import annotations

from .builders import (
    build_echo_report_view,
)
from .formatters import (
    format_active_period,
    format_count,
    format_duration,
    format_hour,
    format_weekday,
)
from .echo_serializer import (
    ECHO_REPORT_SCHEMA_VERSION,
    echo_report_to_dict,
    export_echo_report_html,
    export_echo_report_json,
)
from .expression_assets import (
    expression_asset_data_uri,
    resolve_wechat_asset_key,
    wechat_asset_index,
)
from .models import (
    ChartPoint,
    EchoConversationSession,
    EchoConversationSessions,
    EchoExpressionCombination,
    EchoExpressionCombinationMember,
    EchoExpressionCulture,
    EchoExpressionItem,
    EchoLanguageMember,
    EchoLanguageProfile,
    EchoMemberExpression,
    EchoMemberCard,
    EchoReportView,
    EchoSharedWord,
)


__all__ = [
    "ChartPoint",
    "EchoMemberCard",
    "EchoConversationSession",
    "EchoConversationSessions",
    "EchoExpressionCombination",
    "EchoExpressionCombinationMember",
    "EchoExpressionCulture",
    "EchoExpressionItem",
    "EchoLanguageMember",
    "EchoLanguageProfile",
    "EchoMemberExpression",
    "EchoReportView",
    "EchoSharedWord",
    "ECHO_REPORT_SCHEMA_VERSION",
    "build_echo_report_view",
    "echo_report_to_dict",
    "export_echo_report_html",
    "export_echo_report_json",
    "expression_asset_data_uri",
    "resolve_wechat_asset_key",
    "wechat_asset_index",
    "format_active_period",
    "format_count",
    "format_duration",
    "format_hour",
    "format_weekday",
]
