"""Browser-behavior tests for the Echo conversation sessions chapter."""

from __future__ import annotations

import json
import html
from html.parser import HTMLParser
import re
import shutil

import pytest
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.presentation import (  # noqa: E402
    EchoConversationSession,
    EchoConversationSessions,
    EchoReportView,
    export_echo_report_html,
)


from qq_chat_analyzer.presentation.echo_report_template import ECHO_REPORT_APP_JS


class _ReportDOM(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.session_metric_groups = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "dl" and "session-fields" in attrs.get("class", "").split():
            self.session_metric_groups += 1


def test_exported_report_has_only_current_session_metric_groups_and_unique_ids(tmp_path):
    source = export_echo_report_html(
        EchoReportView(title="Fictional Echo"), tmp_path / "echo.html",
    ).read_text(encoding="utf-8")
    dom = _ReportDOM()
    dom.feed(source)
    assert len(dom.ids) == len(set(dom.ids))
    assert dom.session_metric_groups == 2  # Reply timing and session duration/messages.


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

eval(fs.readFileSync(0, "utf8"));

const result = {};
ids.forEach(function (id) {
  result[id] = { text: nodes[id].textContent, hidden: nodes[id].hidden };
});
process.stdout.write(JSON.stringify(result));
"""


def _sessions(
    *,
    session_count: int = 8,
    median_duration_seconds: float = 18 * 60,
    longest_duration_seconds: int = 4 * 60 * 60 + 37 * 60,
    average_message_count: float = 12.5,
    private_initiators: dict[str, object] | None = None,
    group_initiators: dict[str, object] | None = None,
    viewer_identity_reliable: bool = False,
    peak_start_hour: int | None = None,
    private_self_peak_start_hour: int | None = None,
    private_peer_peak_start_hour: int | None = None,
    private_reply_median_self_to_peer_seconds: float | None = None,
    private_reply_median_peer_to_self_seconds: float | None = None,
    session_character: str | None = None,
    loudest_longest_duration: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "threshold_seconds": 1800,
        "session_count": session_count,
        "average_duration_seconds": 1200.0,
        "median_duration_seconds": median_duration_seconds,
        "longest_duration_seconds": longest_duration_seconds,
        "average_message_count": average_message_count,
        "private_initiators": private_initiators,
        "group_initiators": group_initiators,
        "viewer_identity_reliable": viewer_identity_reliable,
        "peak_start_hour": peak_start_hour,
        "private_self_peak_start_hour": private_self_peak_start_hour,
        "private_peer_peak_start_hour": private_peer_peak_start_hour,
        "private_reply_median_self_to_peer_seconds": (
            private_reply_median_self_to_peer_seconds
        ),
        "private_reply_median_peer_to_self_seconds": (
            private_reply_median_peer_to_self_seconds
        ),
        "session_character": session_character,
        "loudest_longest_duration": loudest_longest_duration,
        "items": [],
    }


def _render_frontend(
    tmp_path,
    *,
    kind: str,
    sessions: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    payload = {
        "conversation": {"kind": kind, "name": "", "time_span": ""},
        "overview": {
            "has_data": sessions is not None,
            "total_message_count": 0,
            "participant_count": 0,
            "empty_description": "",
        },
        "activity": {"hourly": [], "weekday": []},
        "members": [],
    }
    if sessions is not None:
        payload["conversation_sessions"] = sessions
    dom = _ReportDOM()
    dom.feed(export_echo_report_html(
        EchoReportView(title="Fictional Echo"), tmp_path / "echo.html",
    ).read_text(encoding="utf-8"))
    environment = os.environ.copy()
    environment.update(
        {
            "ECHO_NODE_IDS": json.dumps(dom.ids),
            "ECHO_PAYLOAD": json.dumps(payload),
        }
    )
    completed = subprocess.run(
        ["node", "-e", NODE_RUNNER],
        check=True,
        capture_output=True,
        input=ECHO_REPORT_APP_JS,
        encoding="utf-8",
        env=environment,
    )
    return json.loads(completed.stdout)


def test_session_chapter_never_displays_stable_ids_or_technical_ratio(tmp_path) -> None:
    sessions = _sessions(
        private_initiators={
            "self_count": 1,
            "peer_count": 1,
            "unknown_count": 0,
            "self_to_peer_ratio": 999.123,
            "self_share": 0.5,
            "peer_share": 0.5,
            "unknown_share": 0.0,
        }
    )
    sessions["items"] = [
        {
            "start_timestamp": 1,
            "end_timestamp": 2,
            "duration_seconds": 1,
            "message_count": 2,
            "initiator": "self",
            "initiator_sender_key": "raw-stable-fictional-id",
        }
    ]

    rendered = _render_frontend(tmp_path, kind="private", sessions=sessions)
    visible_text = " ".join(str(node["text"]) for node in rendered.values())

    assert "raw-stable-fictional-id" not in visible_text
    assert "999.123" not in visible_text
    assert "self-to-peer" not in visible_text.lower()


@pytest.mark.slow_integration
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("kind,count", [("private", 8), ("group", 8), ("unknown", 8), ("group", 0), ("group", None)])
def test_production_report_offline_browser_behavior_and_layout(tmp_path: Path, width: int, kind: str, count: int | None) -> None:
    from qq_chat_analyzer.presentation import EchoExpressionCulture, EchoExpressionItem
    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    injected_name = '</script><script> window.echoInjected = true </script>'
    loudest = EchoConversationSession(
        start_timestamp=1700000000, end_timestamp=1700001080,
        duration_seconds=1080, message_count=20, initiator="self",
        participant_count=3, self_message_count=12, peer_message_count=8,
    )
    view = EchoReportView(
        title="Fictional Echo", has_data=True, conversation_kind=kind,
        conversation_sessions=None if count is None else EchoConversationSessions(
            threshold_seconds=1800, session_count=count, average_duration_seconds=1200,
            median_duration_seconds=1080, longest_duration_seconds=16620,
            average_message_count=12.5, private_self_count=3, private_peer_count=5,
            private_unknown_count=0, private_self_share=.375, private_peer_share=.625,
            private_unknown_share=0, private_self_peak_start_hour=9,
            private_reply_median_self_to_peer_seconds=12, session_character="Fictional character",
            group_top_initiator_name=injected_name, group_top_initiator_count=3,
            group_top_initiator_share=.375, peak_start_hour=20,
            viewer_identity_reliable=True, group_self_count=3, group_self_share=.375,
            loudest_most_messages=loudest, loudest_longest_duration=loudest,
            loudest_densest=loudest, loudest_most_participants=loudest,
            loudest_most_back_and_forth=loudest,
        ),
        time_span=injected_name, total_message_count=4, participant_count=2,
        expression_culture=EchoExpressionCulture(
            available=True, expression_message_count=4,
            top_expressions=(
                EchoExpressionItem("14", "Fictional smile", 2, "platform_face", asset_key="qq:14"),
                EchoExpressionItem("missing", "Fictional missing image", 2, "platform_face", asset_key="qq:fictional-missing"),
            ),
        ),
    )
    output = export_echo_report_html(view, tmp_path / "echo-report.html")
    source = output.read_text(encoding="utf-8")
    assert 'src="app.js"' not in source and 'href="style.css"' not in source
    probe = r"""<script>
    window.addEventListener("load", function () {
      const image = document.querySelector("#expression-top-list img");
      image.loading = "eager";
      setTimeout(function () {
        const result = {
          sessionVisible: !document.getElementById("conversation-sessions").hidden,
          metricGroups: document.querySelectorAll(".session-fields").length,
          movementVisible: !document.getElementById("session-movement").hidden,
          replyVisible: !document.getElementById("session-reply").hidden,
          median: document.getElementById("session-median-duration").textContent,
          sessionCharacter: document.getElementById("session-character").textContent,
          highnotes: Array.from(document.querySelectorAll(".highnote-card"))
            .filter(x => !x.hidden).map(x => x.id),
          viewerVisible: !document.getElementById("session-viewer-identity").hidden,
          top: document.getElementById("session-group-top").textContent,
          injected: Boolean(window.echoInjected),
          name: document.getElementById("cover-range").textContent,
          offline: Array.from(document.images).every(x => x.src.startsWith("data:")),
          imageLoaded: image.complete && image.naturalWidth > 0,
          fallback: document.querySelector("#expression-top-list .expression-fallback").textContent,
          overflow: document.documentElement.scrollWidth > window.innerWidth,
          overviewVisible: getComputedStyle(document.getElementById("overview")).display !== "none",
          expressionVisible: !document.getElementById("expression").hidden
        };
        image.src = "data:image/png;base64,broken";
        setTimeout(function () {
          result.brokenImageHidden = image.style.display === "none";
          const output = document.createElement("pre");
          output.id = "echo-browser-probe";
          output.textContent = JSON.stringify(result);
          document.body.appendChild(output);
        }, 500);
      }, 1000);
    });
    </script>"""
    output.write_text(source.replace("</body>", probe + "</body>"), encoding="utf-8")
    screenshot = tmp_path / "echo-layout.png"
    result = _run_browser([
        chromium, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
        f"--user-data-dir={tmp_path / 'browser-profile'}",
        "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
        "--virtual-time-budget=4000", f"--window-size={width},3000",
        f"--screenshot={screenshot}", "--dump-dom", output.as_uri(),
    ])
    assert result.returncode == 0, result.stderr
    dom = result.stdout.decode("utf-8")
    match = re.search(r'<pre id="echo-browser-probe">(.*?)</pre>', dom, re.S)
    assert match is not None, dom[-1000:]
    rendered = json.loads(html.unescape(match.group(1)))
    assert rendered == {
        "sessionVisible": count is not None and count > 0,
        "metricGroups": 2,
        "movementVisible": count is not None and count > 0 and kind in {"private", "group"},
        "replyVisible": count is not None and count > 0 and kind == "private",
        "median": "约 18 分钟" if count and kind in {"private", "group"} else "",
        "sessionCharacter": "Fictional character" if count and kind in {"private", "group"} else "",
        "highnotes": (["session-loudest-messages", "session-loudest-duration",
                       "session-loudest-participants" if kind == "group" else "session-loudest-densest",
                       "session-loudest-densest" if kind == "group" else "session-loudest-back-and-forth"]
                      if count and kind in {"private", "group"} else []),
        "viewerVisible": bool(count) and kind == "group",
        "top": ("你开启 3 轮 · TA 开启 5 轮" if kind == "private" else
                "最常发起聊天：" + injected_name + "（3 轮，37.5%）") if count and kind in {"private", "group"} else "",
        "injected": False, "name": injected_name, "offline": True,
        "imageLoaded": True, "fallback": "Fictional missing image",
        "overflow": False, "overviewVisible": True, "expressionVisible": True,
        "brokenImageHidden": True,
    }
    assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def _find_chromium() -> str | None:
    configured = os.environ.get("ECHO_CHROMIUM_PATH", "").strip()
    if configured:
        return configured
    candidates = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ) if os.name == "nt" else (
        "chromium", "chromium-browser", "google-chrome", "microsoft-edge",
    )
    return next(
        (path for path in candidates if Path(path).is_file() or shutil.which(path)),
        None,
    )


def _run_browser(command: list[str]) -> subprocess.CompletedProcess:
    """Bound the report probe and reap only its own browser on timeout."""
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        if os.name == "nt" else 0
    )
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
    )
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True, timeout=10, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.kill()
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def test_browser_probe_timeout_terminates_owned_process_tree(monkeypatch):
    calls = []

    class Process:
        pid = 4242

        def communicate(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("browser", timeout)
            return b"", b""

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: calls.append(command))
    with pytest.raises(subprocess.TimeoutExpired):
        _run_browser(["browser", "--dump-dom"])
    expected = [["taskkill", "/T", "/F", "/PID", "4242"]] if os.name == "nt" else ["kill"]
    assert calls == expected
