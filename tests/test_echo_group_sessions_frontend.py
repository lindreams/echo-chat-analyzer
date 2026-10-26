"""Frontend tests for the Echo group conversation sessions 5-section narrative."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.presentation import (
    EchoConversationSessions,
    EchoReportView,
    export_echo_report_html,
)

class _EchoPageFlowParser(HTMLParser):
    """Collect top-level report pages as (section id, folio number)."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[dict[str, str | None]] = []
        self.pages: list[tuple[str, str]] = []
        self._capture_folio = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "section" and "page" in classes:
            self.stack.append({"id": attributes.get("id"), "folio": None})
        elif tag == "span" and "page-number" in classes and self.stack:
            self._capture_folio = True

    def handle_data(self, data: str) -> None:
        if self._capture_folio and self.stack:
            text = data.strip()
            if text:
                self.stack[-1]["folio"] = text
                self._capture_folio = False

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self.stack:
            page = self.stack.pop()
            if page["id"]:
                self.pages.append((page["id"], page["folio"] or ""))


def _echo_page_flow(html: str) -> list[tuple[str, str]]:
    parser = _EchoPageFlowParser()
    parser.feed(html)
    wanted = {"overview", "conversation-sessions", "rhythm", "voices"}
    return [(page_id, folio) for page_id, folio in parser.pages if page_id in wanted]


def test_merged_overview_stays_visible_before_sessions_and_voices(tmp_path: Path) -> None:
    """The first chapter owns rhythm; sessions and voices remain separate."""
    import sys

    sys.path.insert(0, "src")
    from qq_chat_analyzer.presentation import (
        EchoConversationSessions,
        EchoReportView,
        export_echo_report_html,
    )
    from qq_chat_analyzer.presentation.echo_report_template import (
        ECHO_REPORT_APP_JS,
        ECHO_REPORT_CSS,
        ECHO_REPORT_HTML_SKELETON,
    )

    expected_flow = [
        ("overview", "03"),
        ("conversation-sessions", "04"),
        ("voices", "05"),
    ]

    assert 'id="overview"' in ECHO_REPORT_HTML_SKELETON
    assert 'id="overview" hidden' not in ECHO_REPORT_HTML_SKELETON
    assert _echo_page_flow(ECHO_REPORT_HTML_SKELETON) == expected_flow

    view = EchoReportView(
        title="Fictional Echo",
        has_data=True,
        conversation_kind="group",
        conversation_sessions=EchoConversationSessions(
            threshold_seconds=1800,
            session_count=1,
            average_duration_seconds=60.0,
            median_duration_seconds=60.0,
            longest_duration_seconds=60,
            average_message_count=2.0,
        ),
    )
    output = export_echo_report_html(view, tmp_path / "echo-report.html")
    generated = output.read_text(encoding="utf-8")
    assert 'id="overview"' in generated
    assert 'id="overview" hidden' not in generated
    assert _echo_page_flow(generated) == expected_flow, _echo_page_flow(generated)

    assert "#overview { display: none" not in ECHO_REPORT_CSS
    assert 'setHidden("overview"' not in ECHO_REPORT_APP_JS
    assert "overview.hidden" not in ECHO_REPORT_APP_JS
