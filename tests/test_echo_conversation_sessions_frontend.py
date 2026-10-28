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

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])


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


@pytest.mark.parametrize("variation,merged", [
    ("same-round", True), ("different-time", False),
    ("unknown-time", False), ("different-count", False),
])
def test_session_highnotes_merge_only_confirmed_same_round(tmp_path, variation, merged):
    round_a = dict(start_timestamp=1700000000, end_timestamp=1700001080,
                   duration_seconds=1080, message_count=20, participant_count=2)
    round_b = dict(round_a)
    if variation == "different-time":
        round_b.update(start_timestamp=1700010000, end_timestamp=1700011080)
    elif variation == "unknown-time":
        round_a.update(start_timestamp=None, end_timestamp=None)
        round_b.update(start_timestamp=None, end_timestamp=None)
    elif variation == "different-count":
        round_b["message_count"] = 21
    sessions = _sessions(loudest_longest_duration=round_b)
    sessions["loudest_most_messages"] = round_a
    rendered = _render_frontend(tmp_path, kind="private", sessions=sessions)
    assert not rendered["session-loudest-messages"]["hidden"]
    assert rendered["session-loudest-duration"]["hidden"] is merged
    assert rendered["session-loudest-messages-text"]["text"] == "20 条消息 · 18 分钟"


@pytest.mark.parametrize("self_count,peer_count,unknown_count,visible", [
    (3, 5, 0, True), (3, 3, 2, True), (0, 0, 8, True),
    (3, 3, None, False), (3, 3, 1, False),
])
def test_session_opening_visual_keeps_unknown_rounds_separate(tmp_path, self_count, peer_count, unknown_count, visible):
    sessions = _sessions(private_initiators=dict(
        self_count=self_count, peer_count=peer_count, unknown_count=unknown_count))
    rendered = _render_frontend(tmp_path, kind="private", sessions=sessions)
    assert not rendered["session-summary"]["hidden"]
    assert rendered["session-round-count"]["text"] == "8"
    assert rendered["session-start-graphic"]["hidden"] is not visible
    if visible:
        assert rendered["session-start-unknown-label"]["hidden"] is (unknown_count == 0)
        if unknown_count:
            assert rendered["session-start-unknown-label"]["text"] == f"未确认 · {unknown_count} 轮"


def test_session_reply_visual_distinguishes_instant_from_missing(tmp_path):
    sessions = _sessions(private_reply_median_self_to_peer_seconds=0,
                         private_reply_median_peer_to_self_seconds=None)
    rendered = _render_frontend(tmp_path, kind="private", sessions=sessions)
    assert not rendered["session-reply"]["hidden"]
    assert not rendered["session-reply-self-track"]["hidden"]
    assert rendered["session-reply-peer-track"]["hidden"]
    assert rendered["session-reply-peer-to-self"]["text"] == "暂无足够样本"


@pytest.mark.parametrize("counts,selected,share", [
    ([91] + [1] * 9, 1, "91%"),
    ([50] + [1] * 10, 2, "85%"),
    ([5], None, None),
])
def test_group_concentration_uses_complete_round_counts_and_actual_selection(tmp_path, counts, selected, share):
    sessions = _sessions(session_count=len(counts))
    sessions["items"] = [{"message_count": count} for count in counts]
    rendered = _render_frontend(tmp_path, kind="group", sessions=sessions)
    assert rendered["session-concentration"]["hidden"] is (selected is None)
    if selected is not None:
        assert rendered["session-concentration-percent"]["text"] == share
        assert f"{selected} / {len(counts)} 轮" in rendered["session-concentration-caption"]["text"]


@pytest.mark.parametrize("kind", ["private", "group"])
def test_session_without_opening_or_reply_data_has_no_empty_visual_panel(tmp_path, kind):
    rendered = _render_frontend(tmp_path, kind=kind, sessions=_sessions())
    assert not rendered["session-summary"]["hidden"]
    assert rendered["session-beat"]["hidden"]
    assert rendered["session-reply"]["hidden"]
    assert rendered["session-duet"]["hidden"]
    assert rendered["session-highnotes"]["hidden"]


def test_sticker_empty_unknown_and_group_visibility(tmp_path):
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    empty = echo_report_to_dict(build_echo_report_view(None, conversation_kind="private"))["stickers"]
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=empty)
    assert not rendered["stickers"]["hidden"] and not rendered["sticker-empty"]["hidden"]
    assert rendered["sticker-rankings"]["hidden"] and rendered["sticker-memories"]["hidden"]
    assert "没有表情包发送" in rendered["sticker-empty"]["text"]
    assert rendered["sticker-fields"]["hidden"]
    small = dict(empty, total_send_count=5, unique_material_count=5, covered_message_count=5)
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=small)
    assert rendered["sticker-total"]["text"] == "5"
    assert not rendered["sticker-rankings"]["hidden"]
    assert rendered["sticker-empty"]["hidden"]
    assert not rendered["sticker-fields"]["hidden"]
    unknown = dict(empty, total_send_count=2, unknown_identity_count=2, unattributed_send_count=2)
    rendered = _render_frontend(tmp_path, kind="private", sessions=None, stickers=unknown)
    assert not rendered["sticker-rankings"]["hidden"]
    assert rendered["sticker-memories"]["hidden"] and "sticker-memories-toc" not in rendered
    assert rendered["sticker-total"]["text"] == "2"
    assert "sticker-note" not in rendered
    rendered = _render_frontend(tmp_path, kind="group", sessions=None, stickers=unknown)
    assert rendered["stickers"]["hidden"] and rendered["sticker-toc"]["hidden"]


@pytest.mark.parametrize("kind,total,shared,mine,theirs,sides,expected", [
    pytest.param("private", 70, 12, 8, 7, "both",
                 "12", id="full-counts-beyond-top-five"),
    pytest.param("private", 2, 0, 0, 0, "both",
                 "0", id="known-zero"),
    pytest.param("private", 70, None, 8, 7, "both", None, id="shared-null"),
    pytest.param("private", 70, "missing", 8, 7, "both", None, id="shared-missing"),
    pytest.param("private", 70, 12, None, 7, "both", None, id="self-exclusive-null"),
    pytest.param("private", 70, 12, 8, "missing", "both", None, id="peer-exclusive-missing"),
    pytest.param("private", 70, 12, 8, 7, "peer-unknown", None, id="unreliable-peer"),
    pytest.param("private", 70, 12, 8, 7, "peer-missing", None, id="missing-peer"),
    pytest.param("private", 0, 0, 0, 0, "both", None, id="no-sends"),
    pytest.param("group", 70, 12, 8, 7, "both", None, id="group"),
])
def test_private_sticker_comparison_uses_only_available_full_counts(
    tmp_path, kind, total, shared, mine, theirs, sides, expected,
):
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    chapter = echo_report_to_dict(build_echo_report_view(None, conversation_kind=kind))["stickers"]
    chapter.update(total_send_count=total, unique_material_count=27)
    if shared != "missing":
        chapter["shared_material_count"] = shared
    else:
        chapter.pop("shared_material_count", None)
    chapter["members"] = [
        {"label": "我", "send_count": 40, "message_count": 80,
         "unique_material_count": 20, "per_hundred_messages": 50,
         "top_materials": [{"asset_key": f"self-{i}", "count": 2} for i in range(5)]},
        {"label": "TA", "send_count": 30, "message_count": 60,
         "unique_material_count": 19, "per_hundred_messages": 50,
         "top_materials": [{"asset_key": f"peer-{i}", "count": 2} for i in range(5)]},
    ]
    for member, count in zip(chapter["members"], (mine, theirs)):
        if count != "missing":
            member["exclusive_material_count"] = count
    if sides == "peer-unknown":
        chapter["members"][1]["send_count"] = None
    elif sides == "peer-missing":
        chapter["members"].pop()

    rendered = _render_frontend(tmp_path, kind=kind, sessions=None, stickers=chapter)
    assert "sticker-comparison" in rendered, "missing compact sticker comparison paragraph"
    row = rendered["sticker-comparison"]
    assert row["hidden"] is (expected is None)
    assert row["text"] == (expected or "")
    assert rendered["sticker-exclusive-split"]["text"] == (f"仅我 {mine} / 仅 TA {theirs}" if expected is not None else "")


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
@pytest.mark.parametrize("kind,count,width", [
    ("private", 8, 1280), ("private", 8, 390),
    ("group", 8, 1280), ("group", 8, 390),
    ("unknown", 8, 1280), ("group", 0, 1280), ("group", None, 1280),
])
def test_production_report_offline_browser_behavior_and_layout(tmp_path: Path, width: int, kind: str, count: int | None) -> None:
    from qq_chat_analyzer.presentation import ChartPoint, EchoExpressionCulture, EchoExpressionItem
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
            private_reply_median_self_to_peer_seconds=12, private_reply_median_peer_to_self_seconds=36,
            session_character="Fictional character",
            start_hour_distribution=(ChartPoint("09:00-09:59", 2), ChartPoint("20:00-20:59", 6)),
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
          movementVisible: !document.getElementById("session-movement").hidden,
          replyVisible: !document.getElementById("session-reply").hidden,
          concentrationVisible: !document.getElementById("session-concentration").hidden,
          concentrationBodyVisible: !document.getElementById("session-concentration-body").hidden,
          concentrationTitle: document.getElementById("session-concentration-title").textContent,
          groupHighlightsNested: document.getElementById("session-concentration").contains(document.getElementById("session-highnotes")),
          median: document.getElementById("session-median-duration").textContent,
          sessionCharacter: document.getElementById("session-character").textContent,
          highnotes: Array.from(document.querySelectorAll(".highnote-card"))
            .filter(x => !x.hidden).map(x => x.id),
          highlightLabels: Array.from(document.querySelectorAll(".highnote-card:not([hidden]) .highnote-badge"))
            .map(x => x.textContent.replace(/[♪𝅝♫♬]/gu, "")),
          highlightDetails: Array.from(document.querySelectorAll(".highnote-card:not([hidden]) .highnote-detail"))
            .map(x => x.textContent),
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
        const bounds=id=>{const r=document.getElementById(id).getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
        result.visuals={width:innerWidth,summary:!document.getElementById("session-summary").hidden,
          beat:bounds("session-beat"),reply:bounds("session-reply"),hours:bounds("session-hours"),
          hourCount:document.querySelectorAll(".session-hour-column").length,
          openingWidths:["self","peer","unknown"].map(x=>{const node=document.getElementById("session-start-"+x);
            return node.getBoundingClientRect().width/node.parentElement.getBoundingClientRect().width*100||0;}),
          replyWidths:["self","peer"].map(x=>{const node=document.getElementById("session-reply-"+x+"-track");
            return parseFloat(getComputedStyle(node,"::before").width)/node.getBoundingClientRect().width*100||0;}),
          clipped:[...document.querySelectorAll("#conversation-sessions h3,#conversation-sessions .session-fields>div,.session-beat-lead,.highnote-card")]
            .filter(x=>x.getBoundingClientRect().width&&x.scrollWidth>x.clientWidth+1).map(x=>x.id||x.className)};
        const highlights=[...document.querySelectorAll('.highnote-card:not([hidden])')];
        result.visuals.singleHighlightFills=highlights.length!==1||Math.abs(highlights[0].getBoundingClientRect().width-highlights[0].parentElement.getBoundingClientRect().width)<1;
        const second=document.getElementById(window.ECHO_DATA.conversation.kind==="private"?"session-reply":"session-hours");
        const first=document.getElementById("session-beat"), wasHidden=first.hidden;
        result.visuals.singlePanelFills=true;
        if(!second.hidden){first.hidden=true;
          result.visuals.singlePanelFills=Math.abs(second.getBoundingClientRect().width-document.getElementById("session-duet").getBoundingClientRect().width)<1;
          first.hidden=wasHidden;}
        image.src = "data:image/png;base64,broken";
        setTimeout(function () {
          result.brokenImageHidden = image.style.display === "none";
          const output = document.createElement("pre");
          output.id = "echo-browser-probe";
          output.textContent = JSON.stringify(result);
          window.parent.document.body.appendChild(output);
        }, 500);
      }, 1000);
    });
    </script>"""
    page = source.replace("</body>", probe + "</body>")
    output.write_text(f'<body style="margin:0"><iframe style="border:0;width:{width}px;height:3000px" '
                      f'srcdoc="{html.escape(page, quote=True)}"></iframe></body>', encoding="utf-8")
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
    visuals = rendered.pop("visuals")
    assert visuals["width"] == width and not visuals["clipped"], visuals
    assert visuals["singlePanelFills"]
    assert visuals["singleHighlightFills"]
    known = bool(count) and kind in {"private", "group"}
    assert visuals["summary"] is known
    assert visuals["hourCount"] == (24 if known and kind == "group" else 0)
    if known:
        assert visuals["openingWidths"] == pytest.approx([37.5, 62.5, 0], abs=.05)
        other = visuals["reply"] if kind == "private" else visuals["hours"]
        if width > 720:
            assert visuals["beat"]["right"] <= other["left"]
            assert visuals["beat"]["top"] == pytest.approx(other["top"])
        else:
            assert visuals["beat"]["bottom"] <= other["top"]
        if kind == "private":
            assert visuals["replyWidths"] == pytest.approx([100/3, 100], abs=.05)
    assert rendered == {
        "sessionVisible": count is not None and count > 0,
        "movementVisible": count is not None and count > 0 and kind in {"private", "group"},
        "replyVisible": count is not None and count > 0 and kind == "private",
        "concentrationVisible": bool(count) and kind == "group",
        "concentrationBodyVisible": False,
        "concentrationTitle": "几次聊得尽兴" if count and kind == "group" else "热闹聚在哪里",
        "groupHighlightsNested": bool(count) and kind == "group",
        "median": "约 18 分钟" if count and kind in {"private", "group"} else "",
        "sessionCharacter": "Fictional character" if count and kind in {"private", "group"} else "",
        "highnotes": (["session-loudest-messages"]
                      if count and kind in {"private", "group"} else []),
        "highlightLabels": ["话最多", "聊最久"]
                           if count and kind in {"private", "group"} else [],
        "highlightDetails": (["3 人参与"] if kind == "group" else [])
                            if count and kind in {"private", "group"} else [],
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
@pytest.mark.parametrize("width", [1280, 390])
def test_group_concentration_from_real_sessions_fits_the_right_column(tmp_path, width):
    from qq_chat_analyzer.message import ChatMessage
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.presentation import build_echo_report_view

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    messages = [ChatMessage(
        timestamp=1700000000 + round_index * 6000 + offset * (40 if round_index == 149 else 2),
        sender="" if round_index < 150 else "虚构成员",
        sender_id=None if round_index < 150 else "fictional-member",
        message_type="text", text="虚构聊天消息", conversation_type="group",
    ) for round_index, count in enumerate([91] * 149 + [90, 2] + [1] * 1349) for offset in range(count)]
    view = build_echo_report_view(_build_reports(messages, []), conversation_kind="group")
    page = export_echo_report_html(view, tmp_path / "concentration.html")
    probe = r"""<style>.page:not(#conversation-sessions){display:none!important}</style>
    <script>addEventListener('load',()=>{
      const box=id=>{const r=document.getElementById(id).getBoundingClientRect();
        return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
      const result={beat:box('session-beat'),hours:box('session-hours'),card:box('session-concentration'),
        visible:!document.getElementById('session-concentration').hidden,
        percent:document.getElementById('session-concentration-percent').textContent,
        dots:document.querySelectorAll('.session-concentration-dot').length,
        filled:document.querySelectorAll('.session-concentration-dot.is-filled').length,
        highlights:[...document.querySelectorAll('.highnote-card:not([hidden])')].map(x=>box(x.id)),
        highlightsNested:document.getElementById('session-concentration').contains(document.getElementById('session-highnotes')),
        secondaryHidden:['participants','densest','back-and-forth'].every(x=>document.getElementById('session-loudest-'+x).hidden),
        overflow:document.documentElement.scrollWidth>innerWidth,
        fits:[...document.querySelectorAll('#session-concentration p')].every(x=>x.scrollWidth<=x.clientWidth+1)};
      const pre=document.createElement('pre');pre.id='concentration-probe';pre.hidden=true;
      pre.textContent=JSON.stringify(result);parent.document.body.append(pre);
    });</script>"""
    source = page.read_text(encoding="utf-8").replace("</body>", probe + "</body>")
    page.write_text(f'<body style="margin:0"><iframe style="border:0;width:{width}px;height:1400px" '
                    f'srcdoc="{html.escape(source, quote=True)}"></iframe></body>', encoding="utf-8")
    completed = _run_browser([chromium, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={width},1400",
        f"--screenshot={tmp_path / 'concentration.png'}", "--dump-dom", page.as_uri()])
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="concentration-probe" hidden="">(.*?)</pre>', completed.stdout.decode("utf-8"), re.S)
    assert match is not None, completed.stdout[-1000:]
    result = json.loads(html.unescape(match.group(1)))
    assert result["visible"] and result["percent"] == "91%"
    assert result["dots"] == 100 and result["filled"] == 91
    assert result["fits"] and not result["overflow"]
    assert result["highlightsNested"] and result["secondaryHidden"]
    assert len(result["highlights"]) == 2
    first, second = result["highlights"]
    assert first["bottom"] <= second["top"]
    assert result["card"]["left"] <= first["left"] == second["left"]
    assert first["right"] == second["right"] <= result["card"]["right"]
    if width > 720:
        assert result["beat"]["right"] <= result["card"]["left"]
        assert result["hours"]["bottom"] <= result["card"]["top"]
        assert result["hours"]["left"] == pytest.approx(result["card"]["left"])
    else:
        assert result["beat"]["bottom"] <= result["hours"]["top"]
        assert result["hours"]["bottom"] <= result["card"]["top"]


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind,senders,limit", [
    ("private", 2, 5), ("group", 3, 10), ("group", 10, 5), ("group", 100, 3),
])
def test_sticker_chapter_offline_images_rankings_and_member_comparison(tmp_path, kind, senders, limit):
    width = 1280
    from dataclasses import replace
    import hashlib
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.analysis.stickers import (
        StickerConversationReport, StickerHabit, StickerMaterialUsage, StickerParticipant,
    )
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
        habits=(StickerHabit("a", "first", 20, 20, 12, 90, 8, .4,
                             "2025-01-01", "2025-04-01", ()),),
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
          offline: Array.from(sheet.querySelectorAll("img")).every(x => x.src.startsWith("data:image/") || x.src.startsWith(new URL("media/", document.baseURI).href)),
          loaded: image && image.complete && image.naturalWidth > 0,
          missing: sheet.querySelectorAll(".sticker-image:not(.has-image)").length,
          overflow: document.documentElement.scrollWidth > window.innerWidth,
          preview: sheet.textContent.includes("预览"),
          diagnostics: /可靠成员|已知|未知|素材 \d|资格|阈值|排序口径|身份判定|按出现天数与活跃周挑选/.test(sheet.innerText),
          signatureCount: sheet.querySelectorAll("#sticker-members .sticker-signature").length,
          signatureText: (sheet.querySelector(".sticker-signature") || {}).innerText || "",
          signatureImage: Boolean(sheet.querySelector(".sticker-signature img")),
          imageWidth: sheet.querySelector(".sticker-image").getBoundingClientRect().width
        };
        const comparison = document.getElementById("sticker-comparison");
        result.comparisonHidden = comparison.hidden;
        result.comparisonText = comparison.textContent;
        if (!comparison.hidden) {
          const comparisonRect = comparison.getBoundingClientRect();
          result.comparisonInside = sheet.querySelector("#sticker-fields").contains(comparison);
          result.exclusiveText = document.getElementById("sticker-exclusive-split").textContent;
          result.comparisonLines = comparisonRect.height / parseFloat(getComputedStyle(comparison).lineHeight);
        }
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
        result.memberDisplay = getComputedStyle(memberList).display;
        result.memberScrollable = memberList.scrollWidth > memberList.clientWidth;
        result.overflow = result.overflow || document.documentElement.scrollWidth > window.innerWidth;
        result.memberImageWidths = [...memberList.querySelectorAll(".sticker-image")].map(x => x.getBoundingClientRect().width);
        if (!button.hidden) { button.click(); }
        result.collapsed = memberList.children.length;
        const rowCount = (list) => new Set(
          [...list.children].map(x => Math.round(x.getBoundingClientRect().top))
        ).size;
        if (window.ECHO_DATA.stickers.conversation_kind === "private") {
          result.privateSharedAbsent = !document.querySelector("#sticker-shared-list");
          result.memoriesHidden = document.getElementById("sticker-memories").hidden &&
            !document.getElementById("sticker-memories-toc");
        }
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
          const layout = () => {
            result.overflow = result.overflow || document.documentElement.scrollWidth > window.innerWidth;
            return blocks.map(x => {
              const list = x.querySelector(".sticker-top-list");
              return {rows:rowCount(list), scrollable:list.scrollWidth > list.clientWidth,
                display:getComputedStyle(list).display};
            });
          };
          result.defaultGroupBounds = bounds();
          blocks[1].querySelector("button").click();
          result.sharedExpandedBounds = bounds();
          const sharedList = blocks[1].querySelector(".sticker-top-list");
          result.groupSharedRows = rowCount(sharedList);
          result.groupSharedScrollable = sharedList.scrollWidth > sharedList.clientWidth;
          result.groupSharedImageWidths = [...sharedList.querySelectorAll(".sticker-image")].map(
            x => x.getBoundingClientRect().width);
          blocks[0].querySelector("button").click();
          result.bothExpandedBounds = bounds();
          result.bothExpandedLayout = layout();
          result.groupExpandedCounts = blocks.map(x => x.querySelectorAll("li").length);
          blocks[1].querySelector("button").click();
          result.totalExpandedBounds = bounds();
          result.totalExpandedLayout = layout();
          blocks[0].querySelector("button").click();
          blocks[0].querySelector("button").click();
          blocks[1].querySelector("button").click();
          result.reverseExpandedLayout = layout();
          blocks.forEach(x => x.querySelector("button").click());
          result.recollapsedRows = blocks.map(x => rowCount(x.querySelector(".sticker-top-list")));
          result.overflowAfterExpansion = document.documentElement.scrollWidth > window.innerWidth;
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
    assert not rendered["overflow"]
    if kind == "group":
        for key in ("bothExpandedLayout", "reverseExpandedLayout"):
            assert rendered[key] == [{"rows": 1, "scrollable": True, "display": "flex"}] * 2
    assert rendered["signatureCount"] == (1 if kind == "group" else 0)
    if kind == "group":
        assert rendered["signatureImage"]
        for text in ("招牌表情包", "20 次", "出现在 12 天", "活跃 8 周", "跨度 90 天",
                     "2025.01.01 – 2025.04.01"):
            assert text in rendered["signatureText"]
    default_count = 5 if kind == "private" else 3
    assert rendered["imageWidth"] >= (64 if kind == "private" else 100)
    assert rendered["tops"] == (10 if kind == "private" else 3)
    assert rendered["expanded"] == rendered["expected"] and len(rendered["expanded"]) == limit
    assert rendered["expandHidden"] == (limit <= default_count)
    if limit > default_count:
        assert rendered["expandLabel"] == f"展开 Top {limit}"
    assert rendered["expandedState"] == ("true" if limit > default_count else "false")
    assert rendered["collapsed"] == default_count
    assert rendered["memberColumns"] == (limit if kind == "group" else 5)
    assert rendered["memberRows"] == 1
    minimum_image_width = 64 if kind == "private" else 110
    assert all(minimum_image_width <= value <= 120 for value in rendered["memberImageWidths"])
    if kind == "private":
        assert rendered["privateSharedAbsent"] and rendered["memoriesHidden"]
        assert not rendered["comparisonHidden"]
        assert rendered["comparisonText"] == "12" and rendered["exclusiveText"] == "仅我 1 / 仅 TA 1"
        assert rendered["comparisonInside"] and rendered["comparisonLines"] == pytest.approx(1)
    if kind == "group":
        assert rendered["comparisonHidden"] and rendered["comparisonText"] == ""
        assert rendered["memberDisplay"] == ("flex" if limit > default_count else "grid")
        assert rendered["memberScrollable"] == (limit == 10)
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
        assert rendered["groupSharedRows"] == 1
        assert rendered["groupSharedScrollable"]
        assert rendered["totalExpandedLayout"][0] == {"rows": 1, "scrollable": True, "display": "flex"}
        assert rendered["recollapsedRows"] == [1, 1]
        assert not rendered["overflowAfterExpansion"]
        assert all(110 <= value <= 120 for value in rendered["groupSharedImageWidths"])
        assert rendered["pickerBorder"] == "0px"
    assert not rendered["diagnostics"]
    assert rendered["loaded"] and rendered["offline"] and rendered["missing"] >= 2
    assert rendered["brokenFallback"] and rendered["preview"]
    assert rendered["width"] == 1040
    if kind == "group":
        assert rendered["height"] >= 980
    else:
        assert rendered["height"] < 980


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
        offline: images.every(x => x.src.startsWith("data:image/") || x.src.startsWith(new URL("media/", document.baseURI).href)),
        states: Object.values(window.ECHO_DATA.stickers.assets).map(x => x.status),
        preview: chapter.textContent.includes("预览"), count: window.ECHO_DATA.stickers.total_send_count};
      const pre = document.createElement("pre"); pre.id = "saved-media-probe";
      pre.hidden = true; pre.textContent = JSON.stringify(result); document.body.appendChild(pre);
    }, 500);});</script>'''
    # Open a moved package, independent of the live provider or original path.
    moved = tmp_path / "offline-copy"
    shutil.copytree(outcome.report_directory, moved)
    page = moved / "echo-report.html"
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


@pytest.mark.slow_integration
@pytest.mark.parametrize("scene,leaders,width", [
    ("combined", ["reunion", "style"], 1280), ("zero", [], 1280),
    ("one", ["relay"], 1280), ("three", ["trend", "relay", "shared", "trend"], 1280),
    ("many", ["reunion", "relay", "shared"] + ["reunion"] * 5, 1280),
    ("combined", ["reunion", "style"], 390),
])
def test_private_memories_are_an_independent_offline_chapter_on_desktop(tmp_path, scene, leaders, width):
    import hashlib
    from sticker_feature_samples import Messages, indexed, many_sticker_stories
    from test_sticker_features_batch2 import combined_scene, short_relay
    from test_sticker_data import image_bytes
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    sample = Messages("visual-three" if scene == "three" else "visual-zero")
    if scene == "three":
        for day in range(21):
            for i in range(3):
                sample.add(day, "A", f"phase{day//7}", seconds=i)
        for i in range(8):
            sample.add(21, "A" if i % 2 == 0 else "B", f"reply{i}", seconds=i*20)
        for day in (23, 25):
            for side in ("A", "B"):
                for i in range(4):
                    sample.add(day, side, "shared", seconds=i + (300 if side == "B" else 0))
    else:
        sample.add(0, "A", "plain", text="private-body-sentinel")
        sample.add(1, "B", "other")
    rows = (combined_scene() if scene == "combined" else short_relay() if scene == "one"
            else many_sticker_stories() if scene == "many" else sample.ordered())
    index = indexed(rows, positions=range(len(rows)))
    features = analyze_private_stickers(index)
    media = ()
    if scene == "combined":
        raw = image_bytes("GIF", animated=True)
        media = (verify_fetched_media(raw, media_key=features.shared_habits[0].media_key,
                                     expected_md5=hashlib.md5(raw).hexdigest()),)
    view = build_echo_report_view(AnalysisReports(stickers=(index.report,), private_stickers=features),
        conversation_kind="private", sticker_media=media)
    payload = echo_report_to_dict(view)
    memories = payload["sticker_memories"]
    assert [m["findings"][0]["kind"] for m in memories] == leaders
    output = export_echo_report_html(view, tmp_path / "memories.html")
    source = output.read_text(encoding="utf-8")
    probe = r'''<style>.page:not(#stickers) {display:none !important;}</style>
    <script>window.addEventListener("load", () => {setTimeout(() => {
      const a=document.getElementById("stickers"), b=document.getElementById("sticker-memories");
      const bounds=x=>{const r=x.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height};};
      const stories=[...b.querySelectorAll("article")], images=[...b.querySelectorAll("img")];
      const result={inside:a.contains(b),visible:!a.hidden,memoriesHidden:b.hidden,
        pages:a.querySelectorAll(".page").length,
        toc:[...document.querySelectorAll('a[href="#stickers"],a[href="#sticker-memories"]')].filter(x=>!x.hidden).map(x=>x.getAttribute("href")),
        title:document.getElementById("sticker-title").textContent,
        stats:[...a.querySelectorAll(".sticker-fields dd")].filter(x=>x.offsetParent).map(x=>getComputedStyle(x).fontSize),
        habitPairs:[...b.querySelectorAll(".memory-habit-pair")].map(x=>({bounds:bounds(x),children:[...x.children].map(bounds)})),
        staffs:[...a.querySelectorAll(".sticker-staff")].map(x=>({favorites:!!x.closest("#sticker-rankings"),relay:!!x.closest(".is-relay")})),
        stories:stories.map(story=>({compact:story.classList.contains("is-compact"),
          findings:[...story.querySelectorAll("[data-finding]")].map(x=>({kind:x.dataset.finding,text:x.innerText,
            windows:[...x.querySelectorAll(".memory-trend-row")].map(bounds)})),
          art:[...story.querySelectorAll(".memory-art")].filter(x=>!x.closest(".memory-relay")).map(x=>({key:x.dataset.assetKey,...bounds(x)})),
          turns:[...story.querySelectorAll(".memory-relay li")].map(x=>({text:x.innerText,...bounds(x),
            key:x.querySelector(".memory-art").dataset.assetKey,
            side:bounds(x.querySelector(".memory-turn-side")),image:bounds(x.querySelector(".sticker-image"))}))
        })),
        tops:[...a.querySelectorAll("#sticker-members .sticker-member")].map(x=>({bounds:bounds(x),
          entries:[...x.querySelectorAll("li")].map(bounds)})),
        common:[...a.querySelectorAll(".sticker-common")].map(x=>x.closest("li").dataset.assetKey),
        sharedAbsent:!document.querySelector("#sticker-shared-list"),
        imageCount:images.length,loaded:images.every(x=>x.complete&&x.naturalWidth>0),
        sameResource:new Set(images.map(x=>x.currentSrc)).size===1,
        nativeSave:images.every(x=>x.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true}))),
        offline:images.every(x=>x.src.startsWith("data:image/")||x.src.startsWith(new URL("media/",document.baseURI).href)),
        missing:b.querySelectorAll(".sticker-image:not(.has-image)").length,
        overflow:document.documentElement.scrollWidth>innerWidth,
        viewport:innerWidth,
        tail:bounds(a).bottom-bounds(b.hidden?document.getElementById("sticker-rankings"):stories[stories.length-1]).bottom,
        chapterHeight:bounds(a).height,
        fits:[...b.querySelectorAll("li,h3,.memory-art,.memory-date,.memory-trend-row")].every(x=>bounds(x).right<=bounds(a).right&&x.scrollWidth<=x.clientWidth+1),
        text:b.innerText};
      const heading=b.querySelector("h3");
      if(heading){
        const original=[...heading.childNodes];heading.textContent=heading.textContent.repeat(4);
        result.longTitleFits=heading.scrollWidth<=heading.clientWidth+1&&bounds(heading).right<=bounds(a).right&&bounds(heading).height>=parseFloat(getComputedStyle(heading).lineHeight)*2-1;
        heading.replaceChildren(...original);
      }
      const pre=document.createElement("pre");pre.id="memories-probe";pre.hidden=true;
      pre.textContent=JSON.stringify(result);window.parent.document.body.appendChild(pre);
    },300);});</script>'''
    page = source.replace("</body>", probe+"</body>")
    output.write_text(f'<body style="margin:0"><iframe style="display:block;border:0;width:{width}px;height:'
                      f'1200px" srcdoc="{html.escape(page, quote=True)}"></iframe></body>', encoding="utf-8")
    command = [chromium, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking", "--hide-scrollbars",
        "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={tmp_path / 'b'}",
        "--virtual-time-budget=2000"]
    browser = _run_browser(command + ["--window-size=1280,1200", "--dump-dom", output.as_uri()])
    assert browser.returncode == 0, browser.stderr
    match = re.search(r'<pre id="memories-probe" hidden="">(.*?)</pre>', browser.stdout.decode("utf-8"), re.S)
    assert match is not None
    result = json.loads(html.unescape(match.group(1)))
    (tmp_path/"layout.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    assert result["inside"] and result["visible"] and result["pages"] == 0
    assert result["toc"] == ["#stickers"] and result["title"] == "表情包"
    assert result["memoriesHidden"] == (not leaders)
    assert len(result["stories"]) == len(leaders) and result["sharedAbsent"]
    assert not result["overflow"] and result["fits"] and result["viewport"] == width
    assert 30 <= result["tail"] <= 115
    assert [s["compact"] for s in result["stories"]] == [m["compact"] for m in memories]
    has_relay = any(f["kind"]=="relay" for m in memories if not m["compact"] for f in m["findings"])
    assert len(result["staffs"]) == (2 if has_relay else 1)
    assert all(s["favorites"] or s["relay"] for s in result["staffs"])
    assert sum(s["favorites"] for s in result["staffs"]) == 1
    assert len(result["stats"]) == 3 and len(set(result["stats"])) == 1
    for pair in result["habitPairs"]:
        assert abs(pair["children"][0]["left"] - pair["bounds"]["left"]) <= 1
        assert all(child["width"] >= (250 if width > 720 else 120) for child in pair["children"])
    assert result["tops"][0]["bounds"]["bottom"] <= result["tops"][1]["bounds"]["top"]
    assert all(all(x["right"]<=y["left"] for x,y in zip(m["entries"],m["entries"][1:])) for m in result["tops"])
    common_keys = {item["asset_key"] for member in payload["stickers"]["members"]
                   for item in member["top_materials"] if len(item["side_counts"])==2 and all(item["side_counts"])}
    assert set(result["common"]) == common_keys
    if scene == "zero":
        assert result["chapterHeight"] < 800
    if leaders:
        assert result["longTitleFits"]
    for rendered,memory in zip(result["stories"],memories):
        if memory["compact"]:
            assert len(rendered["art"]) <= 1 and not rendered["turns"]
            assert memory["findings"][0]["title"] in rendered["findings"][0]["text"]
            continue
        ordinary_keys={i["asset_key"] for f in memory["findings"] if f["kind"]!="relay" for i in f["materials"]}
        assert {a["key"] for a in rendered["art"]} == ordinary_keys
        assert len(rendered["art"]) == len(ordinary_keys)
        assert all((65 if width > 720 else 60)<=a["width"]<=164 for a in rendered["art"])
        for finding in memory["findings"]:
            actual=next(x for x in rendered["findings"] if x["kind"]==finding["kind"])
            for key in ("period","note"):
                if finding[key]:
                    assert finding[key] in actual["text"]
            for point in finding["points"]:
                for key in ("start_date","end_date"):
                    if point[key]:
                        assert point[key] in actual["text"]
                if finding["kind"]=="trend":
                    assert f'{point["value"]} / {point["total"]} 次' in actual["text"]
                    assert f'{round(point["value"]/point["total"]*100)}%' in actual["text"]
                if finding["kind"] in ("signature","shared"):
                    assert f'{point["value"]} 次' in actual["text"]
                    assert f'{point["date_count"]} 天' in actual["text"]
            if finding["kind"]=="trend":
                windows=actual["windows"]
                assert len({round(x["top"]) for x in windows})==1
                assert all(x["right"]<=y["left"] for x,y in zip(windows,windows[1:]))
            if finding["kind"]=="relay":
                turns=rendered["turns"]
                assert len(turns)==len(finding["points"])==8
                assert all(x["right"]<=y["left"] for x,y in zip(turns,turns[1:]))
                assert len({round(t["top"]) for t in turns[::2]})>1
                assert min(t["top"] for t in turns[1::2])>max(t["top"] for t in turns[::2])
                for turn,point in zip(turns,finding["points"]):
                    assert point["label"] in turn["text"]
                    assert turn["key"]==(point["materials"][0]["asset_key"] if point["materials"] else "")
                    assert turn["side"]["bottom"]<=turn["image"]["top"]
                    assert turn["image"]["width"]<=65
    if scene == "three":
        first=result["stories"][0]["findings"]
        assert len(first)==1 and len(first[0]["windows"])==3
    if scene == "combined":
        assert sum(len(m["entries"]) for m in result["tops"])==6
        assert result["imageCount"]==9
        assert result["sameResource"] and result["loaded"] and result["nativeSave"] and result["offline"]
        assert all(word in result["text"] for word in ("70 天","49 天","8 轮","回音","约 9.7 种","约 1.0 种","10 次"))
        assert all(word not in result["text"] for word in ("不代表谁带动了谁", "按已有记录估算", "各随机取", "部分发送时间不明"))
    elif leaders:
        assert result["missing"]>0
    assert all(secret not in result["text"] for secret in ("虚构日常","虚构回复","private-body-sentinel"))


@pytest.mark.slow_integration
@pytest.mark.parametrize("width", [1280, 390])
@pytest.mark.parametrize("member_count", [0, 5, 30])
def test_group_opening_ring_is_proportional_bounded_and_has_all_members(tmp_path, width, member_count):
    from qq_chat_analyzer.presentation.models import EchoSessionInitiator

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    people = tuple(EchoSessionInitiator(
        display_name=("</script><script>window.injected=true</script>" if i == 0 else
                      "虚构成员" + str(i) + ("很长的名字" * 12 if i == 1 else "")),
        count=1 if i == member_count - 1 else (member_count - i) * 100,
        is_viewer=i == 1,
    ) for i in range(member_count))
    total = sum(p.count for p in people) + 1
    view = EchoReportView(title="Fictional", has_data=True, conversation_kind="group",
        conversation_sessions=EchoConversationSessions(
            threshold_seconds=1800, session_count=total, average_duration_seconds=60,
            median_duration_seconds=60, longest_duration_seconds=60, average_message_count=2,
            group_initiators=people, group_unknown_count=1,
        ))
    page = export_echo_report_html(view, tmp_path / "report.html")
    probe = r"""<script>window.addEventListener('load',()=>{
      const root=document.getElementById('session-group-opening');
      const details=document.getElementById('session-openers-details');
      const rows=[...document.querySelectorAll('#session-openers-list li')];
      const ring=root.querySelector('.session-opening-ring').getBoundingClientRect();
      const list=document.getElementById('session-openers-list');
      const result={hidden:root.hidden, injected:!!window.injected, viewport:innerWidth,
        listBelowRing:ring.bottom<=list.getBoundingClientRect().top,
        circles:[...root.querySelectorAll('circle[data-count]')].map(x=>({
          count:Number(x.dataset.count), arc:Number(x.getAttribute('stroke-dasharray').split(' ')[0])})),
        labels:[...root.querySelectorAll('.session-opener-label')].map(x=>x.textContent),
        count:rows.length, collapsible:details.tagName==='DETAILS',
        listVisible:rows.every(x=>x.getBoundingClientRect().height>0),
        overflow:document.documentElement.scrollWidth>innerWidth,
        fits:[...root.querySelectorAll('li')].every(x=>x.scrollWidth<=x.clientWidth+1),
        height:root.getBoundingClientRect().height};
      result.listHeight=list.clientHeight;
      const search=document.getElementById('session-openers-search');
      search.value='虚构成员2'; search.dispatchEvent(new Event('input'));
      result.matches=rows.filter(x=>!x.hidden).map(x=>x.textContent);
      search.value='不存在的虚构人'; search.dispatchEvent(new Event('input'));
      result.empty=!document.getElementById('session-openers-empty').hidden;
      const pre=document.createElement('pre');pre.id='opening-result';
      pre.textContent=JSON.stringify(result);parent.document.body.append(pre);
    });</script>"""
    source = page.read_text(encoding="utf-8").replace("</body>", probe + "</body>")
    page.write_text(f'<body style="margin:0"><iframe style="border:0;width:{width}px;height:3000px" '
                    f'srcdoc="{html.escape(source, quote=True)}"></iframe></body>', encoding="utf-8")
    command = [chromium, "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={max(width, 800)},1600",
               "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
               "--virtual-time-budget=2000", "--allow-file-access-from-files", "--dump-dom", page.as_uri()]
    completed = _run_browser(command)
    assert completed.returncode == 0, completed.stderr
    stdout = completed.stdout.decode("utf-8")
    match = re.search(r'<pre id="opening-result">(.*?)</pre>', stdout, re.S)
    assert match, stdout[-2000:]
    result = json.loads(html.unescape(match.group(1)))
    assert result["viewport"] == width
    assert not result["hidden"] and not result["injected"]
    assert result["count"] == member_count
    assert not result["collapsible"] and result["listVisible"]
    if member_count:
        assert result["empty"]
        assert result["matches"] and all("虚构成员2" in text for text in result["matches"])
        assert result["listBelowRing"]
    assert not result["overflow"] and result["fits"]
    assert result["height"] < 620
    assert result["listHeight"] <= 300
    assert sum(circle["count"] for circle in result["circles"]) == total
    assert all(0 < circle["arc"] <= circle["count"] / total * 100 for circle in result["circles"])
    assert "未确认" in result["labels"]
    assert any("其他" in label for label in result["labels"]) is (member_count > 6)


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


@pytest.mark.slow_integration
@pytest.mark.parametrize("scene,width", [("relay", 1280), ("all", 1280), ("all", 390)])
def test_group_memories_use_the_same_offline_story_template_without_overflow(tmp_path, scene, width):
    from test_group_sticker_features import relay_rows, all_group_story_rows, discover
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.analysis.stickers import StickerData, collect_sticker_sends, aggregate_stickers
    from qq_chat_analyzer.presentation import build_echo_report_view
    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    rows = relay_rows() if scene == "relay" else all_group_story_rows()
    data = StickerData(collect_sticker_sends(rows))
    view = build_echo_report_view(AnalysisReports(stickers=aggregate_stickers(data, rows),
        group_stickers=discover(rows)), conversation_kind="group")
    # Long friendly labels must remain readable without exposing internal IDs.
    from dataclasses import replace
    chapter = view.stickers
    memories = tuple(replace(memory, findings=tuple(replace(finding,
        points=tuple(replace(p, label=p.label+"虚构的较长群昵称"*3) for p in finding.points))
        for finding in memory.findings)) for memory in chapter.memories)
    view = replace(view, stickers=replace(chapter, memories=memories))
    output = export_echo_report_html(view, tmp_path/"group.html")
    probe = '''<script>addEventListener("load",()=>{setTimeout(()=>{
      const root=document.getElementById("sticker-memories");
      const result={visible:!root.hidden,stories:root.querySelectorAll(".sticker-memory-story").length,
        turns:root.querySelectorAll(".memory-relay li").length,
        kinds:[...root.querySelectorAll("[data-finding]")].map(x=>x.dataset.finding),
        text:root.innerText,
        labels:[...root.querySelectorAll(".memory-turn-side")].map(x=>x.textContent),
        compactInline:[...root.querySelectorAll(".sticker-memory-story.is-compact:has(> .memory-art)")].every(x=>
          x.querySelector(".memory-art").getBoundingClientRect().right<=
          x.querySelector(".sticker-memory").getBoundingClientRect().left),
        relayFullWidth:[...root.querySelectorAll(".is-relay")].every(x=>
          x.getBoundingClientRect().width>=x.closest(".sticker-memory-story").getBoundingClientRect().width-1),
        viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
        fits:[...root.querySelectorAll("li,h3,.memory-art")].every(x=>x.scrollWidth<=x.clientWidth+1),
        clipped:[...root.querySelectorAll("*")].filter(x=>x.scrollWidth>x.clientWidth+1).map(x=>({
          cls:x.className,width:x.clientWidth,content:x.scrollWidth,whiteSpace:getComputedStyle(x).whiteSpace})),
        external:[...root.querySelectorAll("img")].some(x=>/^https?:/.test(x.src))};
      const pre=document.createElement("pre");pre.id="group-probe";pre.hidden=true;
      pre.textContent=JSON.stringify(result);window.parent.document.body.appendChild(pre);
    },300);});</script>'''
    page = output.read_text(encoding="utf-8").replace("</body>",probe+"</body>")
    output.write_text(f'<body style="margin:0"><iframe style="border:0;width:{width}px;height:1200px" '
                      f'srcdoc="{html.escape(page, quote=True)}"></iframe></body>', encoding="utf-8")
    browser = _run_browser([chromium,"--headless","--disable-gpu","--no-sandbox","--disable-extensions",
        f"--user-data-dir={tmp_path/'browser'}","--virtual-time-budget=2000",
        "--dump-dom",f"--window-size={width},1200",output.as_uri()])
    assert browser.returncode == 0, browser.stderr
    match = re.search(r'<pre id="group-probe" hidden="">(.*?)</pre>',browser.stdout.decode("utf-8"),re.S)
    assert match is not None
    result = json.loads(html.unescape(match.group(1)))
    assert result["viewport"] == width
    assert result["visible"] and result["stories"] == len(memories) and result["turns"] == 6
    assert len(set(result["labels"])) == 3
    assert result["fits"] and not result["overflow"] and not result["external"], result
    assert result["compactInline"] and result["relayFullWidth"], result
    assert not re.search(r"仅比较|跨两天|抽取|不包含未知|其他成员合计|不推断|依据 QQ|每轮展示|同期发表情", result["text"])
    if scene == "all":
        # Compact stories have one panel; associated findings remain visible as summaries.
        assert all(finding.title in result["text"] for memory in memories for finding in memory.findings)
        for finding in (f for m in memories for f in m.findings if f.kind == "style"):
            assert all(f"约 {point.value:.1f} 种" in result["text"] for point in finding.points)


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind,width,reliable,dated", [
    ("private", 1280, True, True),
    ("private", 1280, False, True),
    ("group", 390, False, True),
    ("unknown", 1280, False, False),
])
def test_merged_rhythm_wheel_scope_and_unknown_time(tmp_path, kind, width, reliable, dated):
    from qq_chat_analyzer.presentation import ChartPoint, EchoMemberCard

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    hours = (ChartPoint("00:00-00:59", 2), ChartPoint("05:00-05:59", 6), ChartPoint("23:00-23:59", 2)) if dated else ()
    members = tuple(EchoMemberCard(
        speaker_key=key, display_name=name, is_viewer=reliable and key == "alpha",
        message_count=count, message_share_percent=0, average_length=0, max_length=0, active_period="",
        hourly_activity=(ChartPoint("05:00-05:59", count),),
        weekday_activity=(ChartPoint("周一", count),),
        weekday_average_activity=(ChartPoint("周一", count / 2),),
    ) for key, name, count in (("alpha", "Fictional Alpha", 2), ("beta", "Fictional Beta", 6)))
    view = EchoReportView(
        title="Fictional rhythm", has_data=True, conversation_kind=kind,
        total_message_count=12, participant_count=2, active_days=1,
        average_messages_per_active_day=12, hourly_activity=hours,
        weekday_activity=(ChartPoint("周一", 6), ChartPoint("周二", 4)) if dated else (),
        members=members if dated else (),
        calendar_day_count=8 if dated else 0,
        weekday_average_activity=(ChartPoint("周一", 3), ChartPoint("周二", 4)) if dated else (),
    )
    output = export_echo_report_html(view, tmp_path / "rhythm.html")
    probe = r'''<script>addEventListener("load",()=>{
      const result={};
      try {
        const get=id=>document.getElementById(id);
        const dial=get("hour-dial"), bars=get("hour-bars-preview");
        const range=()=>get("hour-range").textContent;
        const wheel=(target,delta)=>{const event=new WheelEvent("wheel",{deltaY:delta,bubbles:true,cancelable:true});target.dispatchEvent(event);return event.defaultPrevented;};
        result.total=get("overview-message-count").textContent;
        result.initialCount=get("hour-count").textContent;
        result.initialShare=get("hour-share").textContent;
        result.noOverflow=document.documentElement.scrollWidth<=innerWidth;
        result.singleChapter=get("overview").contains(dial)&&!document.querySelector("section#rhythm");
        result.weekdayAverage=get("rhythm-week-rows").children[0].querySelector("strong").textContent;
        result.initialAveragePeak=get("rhythm-week-conclusion").textContent.includes("周二");
        const dated=Boolean(dial.querySelector('[data-hour="5"]:not([aria-disabled="true"])'));
        if(dated){
          const before=range();document.activeElement.blur();
          result.passiveWheel=!wheel(dial,120)&&range()===before;
          dial.querySelector('[data-hour="5"]').dispatchEvent(new MouseEvent("click",{bubbles:true}));
          result.noNativeFocusBox=getComputedStyle(document.activeElement).outlineStyle==="none";
          result.dialWheel=wheel(dial,120)&&range()==="06:00—07:00";
          result.noOrdinaryTitle=get("hour-context").textContent==="";
          result.noArrowShortcut=(()=>{dial.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true,cancelable:true}));return range()==="06:00—07:00";})();
          dial.querySelector('[data-hour="23"]').dispatchEvent(new MouseEvent("click",{bubbles:true}));
          result.wrap=wheel(dial,120)&&range()==="00:00—01:00";
          result.trackpad=!(()=>{wheel(dial,5);return range()!=="00:00—01:00";})();
          const dialHeight=get("overview").getBoundingClientRect().height;
          document.querySelector('[data-hour-view="bars"]').click();
          result.stableViewHeight=Math.abs(get("overview").getBoundingClientRect().height-dialHeight)<1;
          bars.querySelector('[data-hour="5"]').click();
          result.barWheel=wheel(bars,120)&&range()==="06:00—07:00"&&!get("bar-wrap").hidden;
          const controls=get("rhythm-member");
          const memberButton=document.querySelector('[data-rhythm-member="alpha"]');
          if(memberButton){memberButton.click();}
          else{controls.value="alpha";controls.dispatchEvent(new Event("change"));}
          result.memberCount=get("hour-count").textContent;
          result.memberLabel=memberButton?memberButton.textContent:controls.selectedOptions[0].textContent;
          result.summaryUnchanged=get("overview-message-count").textContent==="12";
          result.noPopups=!document.querySelector("#overview details,#count-note-toggle");
          result.averagePeak=get("rhythm-week-conclusion").textContent.includes("周一");
          result.period=get("rhythm-week-note").textContent.includes("约 1 周");
        }else{
          result.emptyClock=!get("hour-context").textContent&&get("hour-count").textContent==="—";
          result.emptyWheel=!wheel(dial,120);
          result.noPeak=range().includes("暂无");
        }
      }catch(error){result.error=String(error);}
      const out=document.createElement("pre");out.id="rhythm-probe";out.textContent=JSON.stringify(result);document.body.append(out);
    });</script>'''
    output.write_text(output.read_text(encoding="utf-8").replace("</body>", probe + "</body>"), encoding="utf-8")
    completed = _run_browser([
        chromium, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND", "--hide-scrollbars",
        f"--user-data-dir={tmp_path / 'rhythm-profile'}", "--virtual-time-budget=1500",
        f"--window-size={width},2400", "--dump-dom", output.as_uri(),
    ])
    assert completed.returncode == 0, completed.stderr
    match = re.search(r'<pre id="rhythm-probe">(.*?)</pre>', completed.stdout.decode("utf-8"), re.S)
    assert match, "Production report did not execute the rhythm probe"
    actual = json.loads(html.unescape(match.group(1)))
    expected = dict(total="12", initialCount="6" if dated else "—",
                    initialShare="占当前有效时间消息 60.0%" if dated else "",
                    noOverflow=True, singleChapter=True)
    expected["weekdayAverage"] = "3.0" if dated else "—"
    expected["initialAveragePeak"] = dated
    if dated:
        expected.update(passiveWheel=True, dialWheel=True, noOrdinaryTitle=True,
                        noArrowShortcut=True, wrap=True, trackpad=True, barWheel=True, stableViewHeight=True,
                        noNativeFocusBox=True,
                        averagePeak=True, period=True,
                        memberCount="2", memberLabel="你" if reliable else "Fictional Alpha",
                        summaryUnchanged=True, noPopups=True)
    else:
        expected.update(emptyClock=True, emptyWheel=True, noPeak=True)
    assert actual == expected


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
