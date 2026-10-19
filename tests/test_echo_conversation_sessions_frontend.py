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
    this.value = "";
    this.hidden = false;
    this.children = [];
    this.className = "";
    this.style = { setProperty: function () {} };
    this.classList = { add: function () {}, toggle: function () {} };
    this.dataset = {};
  }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  setAttribute() {}
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
    expression_culture: dict[str, object] | None = None,
    stickers: dict[str, object] | None = None,
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
        "expression_culture": expression_culture,
        "stickers": stickers,
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


def test_sticker_empty_unknown_and_group_visibility(tmp_path):
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    empty = echo_report_to_dict(build_echo_report_view(None, conversation_kind="private"))["stickers"]
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=empty)
    assert not rendered["stickers"]["hidden"] and not rendered["sticker-empty"]["hidden"]
    assert rendered["sticker-rankings"]["hidden"] and rendered["sticker-dynamic"]["hidden"]
    unknown = dict(empty, total_send_count=2, unknown_identity_count=2, unattributed_send_count=2)
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=unknown)
    assert not rendered["sticker-rankings"]["hidden"]
    assert rendered["sticker-dynamic"]["hidden"]
    assert rendered["sticker-total"]["text"] == "2 次"
    assert "sticker-note" not in rendered
    rendered = _render_frontend(tmp_path, kind="group", sessions=None, stickers=unknown)
    assert rendered["stickers"]["hidden"] and rendered["sticker-toc"]["hidden"]


def test_small_sticker_sample_keeps_counts_without_diagnostic_notices(tmp_path):
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict
    chapter = echo_report_to_dict(build_echo_report_view(None, conversation_kind="private"))["stickers"]
    chapter.update(total_send_count=5, unique_material_count=5, covered_message_count=5)
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=chapter)
    assert rendered["sticker-total"]["text"] == "5 次"
    assert not rendered["sticker-rankings"]["hidden"]
    assert rendered["sticker-empty"]["hidden"]
    assert not rendered["sticker-fields"]["hidden"]
    chapter["total_send_count"] = 0
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=chapter)
    assert "没有表情包发送" in rendered["sticker-empty"]["text"]
    assert rendered["sticker-fields"]["hidden"]
    assert rendered["sticker-rankings"]["hidden"]


@pytest.mark.parametrize("known_sender", [True, False])
def test_expression_chapter_uses_display_count_and_member_availability(tmp_path, known_sender):
    from qq_chat_analyzer.message import ChatMessage
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    messages = [ChatMessage(
        timestamp=1704099600 + index * 120, sender="Fictional A" if known_sender else "",
        sender_id="fictional-a" if known_sender else None, conversation_type="private",
        message_type="text", text=text, platform="qq",
    ) for index, text in enumerate(("⌚", "⌚", "⏳"))]
    view = build_echo_report_view(_build_reports(messages, []), expression_source="qq")
    culture = echo_report_to_dict(view)["expression_culture"]
    assert culture["expression_message_count"] == 3
    assert culture["unique_expression_count"] == 2
    assert [item["display_text"] for item in culture["top_expressions"]] == ["⌚"]
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, expression_culture=culture)
    assert rendered["expression"]["hidden"] is (not known_sender)
    assert rendered["expression-toc"]["hidden"] is (not known_sender)
    if known_sender:
        assert rendered["expression-message-count"]["text"] == "3 条"
        assert rendered["expression-unique-count"]["text"] == "1 种"


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


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind,senders,limit", [
    ("private", 2, 10), ("group", 3, 10), ("group", 10, 5), ("group", 100, 3),
])
def test_sticker_chapter_offline_images_rankings_and_member_comparison(tmp_path, kind, senders, limit):
    width = 1280
    from dataclasses import replace
    import hashlib
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.analysis.stickers import StickerConversationReport, StickerMaterialUsage, StickerParticipant
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict
    from test_sticker_data import image_bytes

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    raw = image_bytes("PNG")
    original = verify_fetched_media(raw, media_key="first", expected_md5=hashlib.md5(raw).hexdigest())
    preview = verify_fetched_media(raw, media_key="second", expected_md5="0" * 32)
    report = StickerConversationReport(
        "qq", "fiction-room", kind, 102, 97 + 7 * (senders - 2), 1 + 7 * (senders - 2), 2,
        members=(StickerParticipant("a", True, 60, 50), StickerParticipant("b", False, 40, 45),
                 *(StickerParticipant(f"c{i:03}", None, 0, 7) for i in range(senders - 2))),
        materials=(
            StickerMaterialUsage("first", "first", 36, (("a", 20), ("b", 15)), 1),
            StickerMaterialUsage("second", "second", 20, (("a", 10), ("b", 10))),
            StickerMaterialUsage("mine", "mine", 10, (("a", 10),)),
            StickerMaterialUsage("theirs", "theirs", 10, (("b", 10),)),
        ) + tuple(StickerMaterialUsage(f"extra-{i:02d}", f"extra-{i:02d}", 2, (("a", 1), ("b", 1))) for i in range(10)),
    )
    view = build_echo_report_view(AnalysisReports(stickers=(report,)), conversation_kind=kind,
                                  sticker_media=(original, preview, replace(original, media_key="mine", status="unsafe")))
    view = replace(view, total_message_count=120)  # Include all three qualification notes at full display density.
    chapter = echo_report_to_dict(view)["stickers"]
    images = [asset for asset in chapter["assets"].values() if asset["data_uri"]]
    assert len(images) == 2  # Even retained bytes cannot override a failed status.
    assert {asset["status"] for asset in images} == {"available", "preview"}
    output = export_echo_report_html(view, tmp_path / "echo-stickers.html")
    source = output.read_text(encoding="utf-8")
    probe = r'''<style>.page:not(#stickers) { display:none !important; }</style><script>
    window.addEventListener("load", function () {
      setTimeout(function () {
        const sheet = document.getElementById("stickers");
        const rect = sheet.getBoundingClientRect();
        const image = sheet.querySelector("img");
        const result = {
          visible: !sheet.hidden, count: document.querySelectorAll("#stickers.page").length,
          width: rect.width, height: rect.height,
          tops: sheet.querySelectorAll("#sticker-members .sticker-top-list li").length,
          offline: Array.from(sheet.querySelectorAll("img")).every(x => x.src.startsWith("data:image/")),
          loaded: image && image.complete && image.naturalWidth > 0,
          missing: sheet.querySelectorAll(".sticker-image:not(.has-image)").length,
          overflow: document.documentElement.scrollWidth > window.innerWidth,
          preview: sheet.textContent.includes("预览"),
          diagnostics: /可靠成员|已知|未知|素材 \d|招牌|资格|阈值|排序口径|身份判定/.test(sheet.innerText),
          imageWidth: sheet.querySelector(".sticker-image").getBoundingClientRect().width
        };
        const memberList = sheet.querySelector("#sticker-members .sticker-top-list");
        const button = sheet.querySelector("#sticker-members .sticker-expand");
        const member = window.ECHO_DATA.stickers.members[0];
        result.expandHidden = button.hidden;
        result.expandLabel = button.textContent;
        if (!button.hidden) { button.click(); }
        result.expanded = [...memberList.children].map(x => [x.dataset.assetKey, Number(x.dataset.count)]);
        result.expected = member.top_materials.map(x => [x.asset_key, x.count]);
        result.expandedState = button.getAttribute("aria-expanded");
        const positions = [...memberList.children].map(x => x.getBoundingClientRect());
        result.memberRows = [...new Set(positions.map(x => Math.round(x.top)))].length;
        result.memberColumns = positions.filter(x => Math.round(x.top) === Math.round(positions[0].top)).length;
        result.memberImageWidths = [...memberList.querySelectorAll(".sticker-image")].map(x => x.getBoundingClientRect().width);
        if (!button.hidden) { button.click(); }
        result.collapsed = memberList.children.length;
        if (window.ECHO_DATA.stickers.conversation_kind === "group") {
          const boxes = [...document.querySelectorAll("#sticker-member-options input")];
          result.pickerCount = boxes.length;
          boxes[1].click(); boxes[2].click();
          result.comparedMembers = sheet.querySelectorAll(".sticker-member").length;
          result.noRate = [...sheet.querySelectorAll(".sticker-member")][2].innerText;
          const search = document.getElementById("sticker-member-search");
          search.value = window.ECHO_DATA.stickers.members[1].label;
          search.dispatchEvent(new Event("input"));
          result.searchCount = document.querySelectorAll("#sticker-member-options input").length;
          result.searchChecked = document.querySelector("#sticker-member-options input").checked;
          search.value = ""; search.dispatchEvent(new Event("input"));
          result.retainedSelections = [...document.querySelectorAll("#sticker-member-options input")].filter(x => x.checked).length;
          const rankings = document.getElementById("sticker-group-rankings");
          const blocks = [...rankings.children];
          const bounds = () => blocks.map(x => ({top:x.getBoundingClientRect().top, width:x.getBoundingClientRect().width}));
          result.defaultGroupBounds = bounds();
          blocks[1].querySelector("button").click();
          result.sharedExpandedBounds = bounds();
          blocks[0].querySelector("button").click();
          result.bothExpandedBounds = bounds();
          result.groupExpandedCounts = blocks.map(x => x.querySelectorAll("li").length);
          blocks[1].querySelector("button").click();
          result.totalExpandedBounds = bounds();
          result.pickerBorder = getComputedStyle(document.getElementById("sticker-member-picker")).borderBottomWidth;
        }
        image.src = "data:image/png;base64,broken";
        setTimeout(function () {
          result.brokenFallback = image.hidden && !image.parentNode.classList.contains("has-image");
          const node = document.createElement("pre");
          node.id = "sticker-probe"; node.textContent = JSON.stringify(result);
          node.hidden = true; window.parent.document.body.appendChild(node);
        }, 300);
      }, 800);
    });</script>'''
    page = source.replace("</body>", probe + "</body>")
    output.write_text(page, encoding="utf-8")
    result = _run_browser([
        chromium, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
        f"--user-data-dir={tmp_path / 'sticker-browser'}", "--disable-background-networking",
        "--host-resolver-rules=MAP * ~NOTFOUND", "--virtual-time-budget=2500",
        f"--window-size={width},1200", f"--screenshot={tmp_path / 'stickers.png'}", "--dump-dom", output.as_uri(),
    ])
    assert result.returncode == 0, result.stderr
    match = re.search(r'<pre id="sticker-probe" hidden="">(.*?)</pre>', result.stdout.decode("utf-8"), re.S)
    assert match is not None
    rendered = json.loads(html.unescape(match.group(1)))
    assert rendered["visible"] and rendered["count"] == 1
    assert not rendered["overflow"] and not rendered["diagnostics"]
    assert rendered["imageWidth"] >= 100
    assert rendered["tops"] == (6 if kind == "private" else 3)
    assert rendered["expanded"] == rendered["expected"] and len(rendered["expanded"]) == limit
    assert rendered["expandHidden"] == (limit == 3)
    if limit > 3:
        assert rendered["expandLabel"] == f"展开 Top {limit}"
    assert rendered["expandedState"] == ("true" if limit > 3 else "false")
    assert rendered["collapsed"] == 3
    assert rendered["memberColumns"] == min(limit, 5)
    assert rendered["memberRows"] == (2 if limit == 10 else 1)
    assert all(110 <= value <= 120 for value in rendered["memberImageWidths"])
    if kind == "group":
        assert rendered["pickerCount"] == senders
        assert rendered["groupExpandedCounts"] == [10, 10]
        assert rendered["comparedMembers"] == 3
        assert rendered["searchCount"] == 1 and rendered["searchChecked"]
        assert rendered["retainedSelections"] == 3
        assert "共发送 7 次" in rendered["noRate"] and "每 100" not in rendered["noRate"]
        default, shared, both, total = (rendered[key] for key in (
            "defaultGroupBounds", "sharedExpandedBounds", "bothExpandedBounds", "totalExpandedBounds"))
        assert default[0]["top"] == default[1]["top"]
        assert shared[1]["top"] < shared[0]["top"] and total[0]["top"] < total[1]["top"]
        assert both[0]["top"] < both[1]["top"]
        assert all(pair[0]["width"] == pair[1]["width"] > default[0]["width"] for pair in (shared, both, total))
        assert rendered["pickerBorder"] == "0px"
    assert rendered["loaded"] and rendered["offline"] and rendered["missing"] >= 2
    assert rendered["brokenFallback"] and rendered["preview"]
    assert rendered["width"] == 1040 and rendered["height"] >= 980


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind", ["private", "group"])
def test_saved_qq_media_report_loads_actual_images_offline(tmp_path, kind, caplog):
    import hashlib
    from test_qq_direct_database_facade import _fetch_facade
    from test_sticker_data import image_bytes
    from qq_chat_analyzer.application.facade import AnalysisConfig, ChatSource

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    caplog.set_level("INFO")
    raw = image_bytes("GIF", animated=True) if kind == "group" else image_bytes("PNG")
    digest = b"\xab" * 16 if kind == "group" else hashlib.md5(raw).digest()
    facade, _, _ = _fetch_facade(tmp_path, digest=digest, content=raw,
                                group_sender="10087" if kind == "group" else None)
    session_id = "group:group-partition" if kind == "group" else "private:private-partition"
    outcome = facade.analyze_session(ChatSource.QQ, session_id, AnalysisConfig(output_directory=tmp_path / "initial"))
    # Normal generation is final: no material dialog, manual fetch or second export.
    source = outcome.report_path.read_text(encoding="utf-8")
    probe = r'''<style>.page:not(#stickers) {display:none !important;}</style>
    <script>window.addEventListener("load", function () {setTimeout(function () {
      const chapter = document.getElementById("stickers"); chapter.scrollIntoView();
      const images = [...chapter.querySelectorAll("img")];
      const result = {loaded: images.length > 0 && images.every(x => x.complete && x.naturalWidth > 0),
        offline: images.every(x => x.src.startsWith("data:image/")),
        states: Object.values(window.ECHO_DATA.stickers.assets).map(x => x.status),
        preview: chapter.textContent.includes("预览"), count: window.ECHO_DATA.stickers.total_send_count};
      const pre = document.createElement("pre"); pre.id = "saved-media-probe";
      pre.hidden = true; pre.textContent = JSON.stringify(result); document.body.appendChild(pre);
    }, 500);});</script>'''
    page = tmp_path / "saved-media-probe.html"
    page.write_text(source.replace("</body>", probe + "</body>"), encoding="utf-8")
    browser = _run_browser([
        chromium, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking",
        "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={tmp_path / 'browser-profile'}",
        "--virtual-time-budget=2000", "--window-size=1280,1100",
        f"--screenshot={tmp_path / 'saved-media.png'}", "--dump-dom", page.as_uri(),
    ])
    assert browser.returncode == 0
    match = re.search(r'<pre id="saved-media-probe" hidden="">(.*?)</pre>', browser.stdout.decode("utf-8"), re.S)
    assert match is not None
    rendered = json.loads(html.unescape(match.group(1)))
    assert rendered["loaded"] and rendered["offline"] and rendered["count"] == 1
    assert rendered["states"] == (["preview"] if kind == "group" else ["available"])
    assert rendered["preview"] == (kind == "group")
    timing = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[analysis-timing]")]
    assert any("stage=sticker_report_export " in line for line in timing)
    assert all(str(tmp_path) not in line for line in timing)
    (tmp_path / "timings.json").write_text(json.dumps(timing, indent=2), encoding="utf-8")


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
