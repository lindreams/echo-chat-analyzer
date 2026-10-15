"""Frontend tests for the Echo group conversation sessions 5-section narrative."""

from __future__ import annotations

import json
import os
import subprocess
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

APP_PATH = PROJECT_ROOT / "frontend" / "echo_report" / "app.js"

SESSION_NODE_IDS = (
    "session-toc",
    "conversation-sessions",
    "session-lead",
    "session-median-duration",
    "session-longest-duration",
    "session-average-messages",
    "session-private-initiators",
    "session-self",
    "session-peer",

    "session-group-top",
    "session-beat",
    "session-beat-title",
    "session-self-peak-hour",
    "session-peer-peak-hour",
    "session-reply",
    "session-movement",
    "session-highnotes",
    "session-rest",
    "session-reply-self-to-peer",
    "session-reply-peer-to-self",
    "session-highnotes-title",
    "session-unknown-note",
    "session-threshold-note",
    "session-viewer-identity",
    "session-peak-hour",
    "session-character",
    "session-loudest-messages",
    "session-loudest-duration",
    "session-loudest-participants",
    "session-loudest-densest",
    "session-loudest-messages-text",
    "session-loudest-duration-text",
    "session-loudest-participants-text",
    "session-loudest-densest-text",
    "session-loudest-messages-time",
    "session-loudest-duration-time",
    "session-loudest-participants-time",
    "session-loudest-densest-time",
    "session-loudest-back-and-forth",
    "session-loudest-back-and-forth-text",
    "session-loudest-back-and-forth-time",
    "session-fields-old",
    "session-median-duration-old",
    "session-average-messages-old",
)
NODE_RUNNER = r"""
const fs = require("fs");

class FakeNode {
  constructor(id) {
    this.id = id || "";
    this.textContent = "";
    this.hidden = false;
    this.children = [];
    this.className = "";
    this.style = { setProperty: function () {} };
    this.classList = { add: function () {} };
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute() {}
  querySelector() { return null; }
}

const ids = JSON.parse(process.env.ECHO_NODE_IDS);
const nodes = {};
ids.forEach(function (id) { nodes[id] = new FakeNode(id); });

global.window = { ECHO_DATA: JSON.parse(process.env.ECHO_PAYLOAD) };
global.document = {
  title: "",
  documentElement: new FakeNode("html"),
  getElementById: function (id) { return nodes[id] || null; },
  querySelectorAll: function () { return []; },
  createElement: function () { return new FakeNode(""); }
};

eval(fs.readFileSync(process.env.ECHO_APP_PATH, "utf8"));

const result = {};
ids.forEach(function (id) {
  result[id] = { text: nodes[id].textContent, hidden: nodes[id].hidden };
});
process.stdout.write(JSON.stringify(result));
"""

def _read_css_sources():
    import sys

    sys.path.insert(0, "src")
    from qq_chat_analyzer.presentation.echo_report_template import ECHO_REPORT_CSS

    css_file = __file__.rsplit("tests", 1)[0] + "frontend/echo_report/style.css"
    css_content = open(css_file, "r", encoding="utf-8").read()
    return ECHO_REPORT_CSS, css_content


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


def test_overview_page_and_03_04_05_06_flow_regression(tmp_path: Path) -> None:
    """Overview must exist unhidden in the self-contained Echo, followed by
    sessions (04), rhythm (05), and voices (06)."""
    import sys

    sys.path.insert(0, "src")
    from qq_chat_analyzer.presentation import (
        EchoConversationSessions,
        EchoReportView,
        export_echo_report_html,
    )
    from qq_chat_analyzer.presentation.echo_report_template import (
        ECHO_REPORT_CSS,
        ECHO_REPORT_HTML_SKELETON,
    )

    html_file = __file__.rsplit("tests", 1)[0] + "frontend/echo_report/index.html"
    html_content = open(html_file, "r", encoding="utf-8").read()
    expected_flow = [
        ("overview", "03"),
        ("conversation-sessions", "04"),
        ("rhythm", "05"),
        ("voices", "06"),
    ]

    for html in (ECHO_REPORT_HTML_SKELETON, html_content):
        assert 'id="overview"' in html
        assert 'id="overview" hidden' not in html
        assert _echo_page_flow(html) == expected_flow, _echo_page_flow(html)

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

    template_css, file_css = _read_css_sources()
    for css in (ECHO_REPORT_CSS, template_css, file_css):
        assert "#overview { display: none" not in css

    app_js = (
        __file__.rsplit("tests", 1)[0]
        + "frontend/echo_report/app.js"
    )
    app_content = open(app_js, "r", encoding="utf-8").read()
    assert 'setHidden("overview"' not in app_content
    assert "overview.hidden" not in app_content
