"""Fictional WeChat pats stay separate from authored messages and identity output."""

from dataclasses import replace
from datetime import date, datetime
from xml.sax.saxutils import escape
import importlib
import html
import json
import re

import pytest
import zstandard as zstd

from qq_chat_analyzer import wechat_db_adapter as adapter
from qq_chat_analyzer.application.scope_filter import AnalysisScope
from qq_chat_analyzer.filter_decisions import FilterDecision
from qq_chat_analyzer.filter_pipeline import FilterPipeline
from qq_chat_analyzer.presentation.echo_serializer import echo_report_to_dict
from test_rich_filtering_association import analyze


PAT_TYPE = (62 << 32) | 49
OWNER = "fiction-owner"
PEER = "fiction-peer"
STAMP = int(datetime.fromisoformat("2026-01-02T12:00:00+08:00").timestamp())


def pat_row(message_id=101, *, incoming=False, suffix="肩膀", timestamp=STAMP):
    actor, target = (PEER, OWNER) if incoming else (OWNER, PEER)
    # Incoming chatusername is the owner's identity, as seen by the sender.
    xml = (
        '<msg><appmsg><type>62</type><patinfo>'
        f'<fromusername>{actor}</fromusername><chatusername>{target}</chatusername>'
        f'<pattedusername>{target}</pattedusername>'
        f'<patsuffix>{escape(suffix)}</patsuffix><template>untrusted template</template>'
        '</patinfo></appmsg></msg>'
    )
    return dict(server_id=message_id, local_id=1, local_type=PAT_TYPE,
                create_time=timestamp, message_content=xml, user_name=actor,
                username=PEER, self_username=OWNER, conversation_type="private")


def payload(rows):
    return {"source": "wechat-db", "conversation": {
        "username": PEER, "self_username": OWNER, "session_type": "private",
    }, "messages": rows}


@pytest.mark.parametrize("incoming", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_pat_adapter_preserves_direction_without_authored_text(incoming, compressed):
    row = pat_row(incoming=incoming)
    if compressed:
        row["message_content"] = zstd.ZstdCompressor().compress(row["message_content"].encode()).hex()
        row["WCDB_CT_message_content"] = 4
    rich = adapter.parse_rich_message(row)
    assert rich is not None
    assert rich.message_type == "nudge" and rich.is_system
    assert rich.is_self is (not incoming)
    assert rich.contents == ()
    assert rich.relations[0].target_identity_id == (OWNER if incoming else PEER)
    assert rich.relations[0].suffix == "肩膀"
    assert adapter.parse_message(row).text == ""


@pytest.mark.parametrize("mutation", [
    {"local_type": 49}, {"local_type": (63 << 32) | 49},
    {"server_id": 0}, {"server_id": None}, {"server_id": True},
    {"self_username": None}, {"username": None},
    {"conversation_type": "group"}, {"user_name": "fiction-stranger"},
    {"create_time": "not a time"},
])
def test_pat_adapter_rejects_unreliable_provenance(mutation):
    assert adapter.parse_rich_message(pat_row() | mutation) is None


@pytest.mark.parametrize("transform", [
    lambda xml: xml.replace('<type>62</type>', '<type>57</type>'),
    lambda xml: xml.replace('</patinfo>', '<fromusername>fiction-owner</fromusername></patinfo>'),
    lambda xml: xml.replace('<pattedusername>fiction-peer', '<pattedusername>fiction-stranger'),
    lambda xml: xml.replace('<pattedusername>fiction-peer', '<pattedusername>fiction-owner'),
    lambda xml: '<!DOCTYPE msg [<!ENTITY x "unsafe">]>' + xml,
    lambda xml: xml.replace('</msg>', '</msg><msg/>'),
    lambda xml: xml.replace('</patinfo>', '<patsuffix>ambiguous</patsuffix></patinfo>'),
])
def test_pat_adapter_rejects_ambiguous_or_unsafe_xml(transform):
    row = pat_row()
    row["message_content"] = transform(row["message_content"])
    assert adapter.parse_rich_message(row) is None


def test_nudge_aggregation_deduplicates_and_keeps_three_latest():
    from qq_chat_analyzer.analysis.private_nudges import analyze_private_nudges

    rows = [pat_row(i, incoming=i % 2 == 0, timestamp=STAMP + i) for i in range(1, 6)]
    facts = [adapter.parse_rich_message(row) for row in rows]
    result = analyze_private_nudges([*facts, facts[0]])
    assert (result.self_count, result.peer_count) == (3, 2)
    assert [item.timestamp for item in result.recent] == [STAMP + 5, STAMP + 4, STAMP + 3]
    # A server identity with conflicting evidence must not pick the first row.
    conflict = replace(facts[0], timestamp=STAMP + 100)
    result = analyze_private_nudges([*facts, conflict])
    assert (result.self_count, result.peer_count) == (2, 2)
    assert analyze_private_nudges([facts[0], replace(facts[1], conversation_id="fiction-other")]) is None


def test_custom_pat_labels_use_latest_retained_direction_even_outside_recent_three():
    from qq_chat_analyzer.analysis.private_nudges import analyze_private_nudges

    rows = [pat_row(i, incoming=i == 2, timestamp=STAMP + i,
                    suffix='并说“虚构的晚安”' if i == 2 else "的纸飞机") for i in range(1, 7)]
    # The latest raw row has conflicting evidence and must not supply a label.
    facts = [adapter.parse_rich_message(row) for row in rows]
    facts.append(replace(facts[-1], relations=(replace(facts[-1].relations[0], suffix="不可信后缀"),)))
    result = analyze_private_nudges(facts)
    assert (result.self_count, result.peer_count) == (4, 1)
    assert all(moment.is_self for moment in result.recent)
    assert (result.self_suffix, result.peer_suffix) == ("的纸飞机", '并说“虚构的晚安”')
    assert "纸飞机" not in repr(result) and "晚安" not in repr(result)

    # An explicitly empty newer suffix must not resurrect an older setting.
    facts.append(adapter.parse_rich_message(pat_row(7, incoming=True, timestamp=STAMP + 7, suffix="")))
    assert analyze_private_nudges(facts).peer_suffix == ""
    # Different texts at the same latest time do not establish one reliable label.
    facts.append(adapter.parse_rich_message(pat_row(8, timestamp=STAMP + 8, suffix="的云朵")))
    facts.append(adapter.parse_rich_message(pat_row(9, timestamp=STAMP + 8, suffix="的风筝")))
    assert analyze_private_nudges(facts).self_suffix == ""
    assert analyze_private_nudges(reversed(facts)).self_suffix == ""


def test_application_counts_pats_separately_and_serializes_no_account_ids(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    rows = [pat_row(1), pat_row(2, incoming=True, timestamp=STAMP + 1800, suffix='并说“虚构的晚安”'),
            pat_row(3, timestamp=STAMP + 3600)]
    rows.extend([
        dict(server_id=4, local_type=1, create_time=STAMP, user_name=OWNER,
             message_content="虚构的午后一起散步"),
        dict(server_id=5, local_type=1, create_time=STAMP + 3600, user_name=PEER,
             message_content="虚构的傍晚一起吃饭"),
    ])
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, [payload(rows)])
    assert len(kept) == result.reports.activity.total_message_count == 2
    # A pat halfway through the silence must not bridge two ordinary sessions.
    assert result.reports.conversation_sessions.session_count == 2
    assert "肩膀" not in analyzed.tokens
    nudges = result.reports.private_nudges
    assert (nudges.self_count, nudges.peer_count) == (2, 1)
    data = echo_report_to_dict(result.echo_report_view)["private_nudges"]
    assert (data["self_count"], data["peer_count"]) == (2, 1)
    assert (data["self_suffix"], data["peer_suffix"]) == ("肩膀", '并说“虚构的晚安”')
    assert OWNER not in json.dumps(data) and PEER not in json.dumps(data)
    assert "untrusted template" not in json.dumps(data)
    pat_logs = "\n".join(record.getMessage() for record in caplog.records
                         if "wechat.pats" in record.getMessage() or "private_nudges" in record.getMessage())
    assert "candidates=3 accepted=3 rejected=0" in pat_logs
    assert "self=2 peer=1" in pat_logs
    assert OWNER not in pat_logs and PEER not in pat_logs and "肩膀" not in pat_logs and "晚安" not in pat_logs


def test_pat_only_and_scope_use_the_same_retained_time_range(tmp_path, monkeypatch):
    outside = int(datetime.fromisoformat("2026-01-01T12:00:00+08:00").timestamp())
    result, (kept, _) = analyze(tmp_path, monkeypatch, [payload([
        pat_row(1, timestamp=outside), pat_row(2, incoming=True),
    ])], AnalysisScope.custom(date(2026, 1, 2), date(2026, 1, 2)))
    assert kept == []
    assert result.echo_report_view.conversation_kind == "private"
    assert result.reports.activity.total_message_count == 0
    assert (result.reports.private_nudges.self_count, result.reports.private_nudges.peer_count) == (0, 1)
    assert (result.echo_report_view.private_nudges.self_suffix,
            result.echo_report_view.private_nudges.peer_suffix) == ("", "肩膀")
    assert result.echo_report_view.private_nudges is not None


def test_unrelated_ordinary_conversation_cannot_receive_private_pats(tmp_path, monkeypatch):
    other = payload([dict(server_id=4, local_type=1, create_time=STAMP, user_name=OWNER,
                          message_content="另一段虚构的聊天记录")])
    other["conversation"] = other["conversation"] | {"username": "fiction-other-peer"}
    result, _ = analyze(tmp_path, monkeypatch, [payload([pat_row()]), other])
    assert result.reports.private_nudges is None
    assert echo_report_to_dict(result.echo_report_view)["private_nudges"] is None


def test_group_serialization_omits_private_actions_even_if_view_contains_them():
    from qq_chat_analyzer.presentation.models import EchoNudgeMoment, EchoPrivateNudges, EchoReportView

    view = EchoReportView(title="Fictional Echo", conversation_kind="group",
                          private_nudges=EchoPrivateNudges(1, 0, (EchoNudgeMoment(STAMP, True),)))
    assert echo_report_to_dict(view)["private_nudges"] is None


@pytest.mark.parametrize("ignored", [OWNER, PEER])
def test_sender_exclusion_covers_actor_and_target(tmp_path, monkeypatch, ignored):
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    decision = FilterDecision(ignored, "sender", "ignore", 1, "fiction", "manual")

    def filter_sender(messages):
        assert all(message.message_type != "nudge" for message in messages)
        return FilterPipeline().apply_filter_decisions(messages, [decision])

    monkeypatch.setattr(service, "run_smart_profile", filter_sender)
    text = dict(server_id=4, local_type=1, create_time=STAMP, user_name=ignored,
                message_content="虚构的普通消息")
    result, _ = analyze(tmp_path, monkeypatch, [payload([
        pat_row(1), pat_row(2, incoming=True), text,
    ])])
    assert result.reports is None or result.reports.private_nudges is None


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind,width,has_actions,has_sessions,source", [
    ("private", 390, True, True, "wechat"), ("private", 1280, True, False, "wechat"),
    ("private", 1280, True, True, "wechat"),
    ("private", 1280, False, True, "wechat"), ("group", 390, True, True, "wechat"),
    ("private", 390, True, True, "qq"),
    ("private", 1280, True, True, "qq"),
])
def test_pat_report_is_readonly_offline_and_hides_unavailable_actions(
    tmp_path, kind, width, has_actions, has_sessions, source,
):
    from qq_chat_analyzer.presentation import export_echo_report_html
    from qq_chat_analyzer.presentation.models import (
        EchoConversationSession, EchoConversationSessions, EchoNudgeMoment, EchoPrivateNudges, EchoReportView,
    )
    from test_echo_conversation_sessions_frontend import _find_chromium, _run_browser

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    suffix = '</script><img id="fictional-attack" onerror="window.fictionalAttack=true">' + '虚构' * 80
    peer_suffix = '并说“虚构的周末见”'
    highlights = [EchoConversationSession(
        start_timestamp=STAMP + index * 7200, end_timestamp=STAMP + index * 7200 + 120,
        duration_seconds=120, message_count=20 + index, participant_count=2, initiator="self",
        self_message_count=10, peer_message_count=10 + index,
    ) for index in range(4)]
    view = EchoReportView(
        title="Fictional Echo", has_data=True, conversation_kind=kind,
        conversation_sessions=EchoConversationSessions(
            1800, 1, 120, 120, 120, 2, private_self_count=1, private_peer_count=0,
            private_unknown_count=0, private_reply_median_self_to_peer_seconds=12,
            private_reply_median_peer_to_self_seconds=36,
            loudest_most_messages=highlights[0], loudest_longest_duration=highlights[1],
            loudest_densest=highlights[2], loudest_most_back_and_forth=highlights[3],
        ) if has_sessions else None,
        private_nudges=EchoPrivateNudges(2, 1, (
            EchoNudgeMoment(STAMP + 2, True, suffix),
            EchoNudgeMoment(STAMP + 1, False, "肩膀"), EchoNudgeMoment(STAMP, True),
        ), source=source, self_suffix=suffix if has_sessions else "",
            peer_suffix=peer_suffix, self_action="摸了摸" if source == "qq" else "",
            peer_action="拍了拍" if source == "qq" else "") if has_actions else None,
    )
    output = export_echo_report_html(view, tmp_path / "pats.html")
    probe = r"""<script>
window.addEventListener('load',()=>{
 const block=document.getElementById('private-nudges');
 document.documentElement.style.scrollBehavior='auto';
 if(!block.hidden)block.scrollIntoView({block:'center',behavior:'instant'});
 const r={
  visible:!block.hidden,
  chapter:!document.getElementById('conversation-sessions').hidden,
  toc:!document.getElementById('session-toc').hidden,
  counts:[document.getElementById('nudge-self-count').textContent,document.getElementById('nudge-peer-count').textContent],
  titles:[document.getElementById('nudge-self-label').title,document.getElementById('nudge-peer-label').title],
  labels:[document.getElementById('nudge-self-label').textContent,document.getElementById('nudge-peer-label').textContent],
  recentLabel:!!block.querySelector('.nudge-recent-label'),
  rows:block.querySelectorAll('li').length,
  rawSuffix:block.textContent.includes('<img id="fictional-attack"'),
  inert:!window.fictionalAttack&&!document.getElementById('fictional-attack'),
  readonly:!block.querySelector('input,textarea,[contenteditable=true]'),
  overflow:document.documentElement.scrollWidth>innerWidth,
  time:block.querySelector('time')?.textContent||''
 };
 const box=id=>{const r=document.getElementById(id).getBoundingClientRect();
   return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
 const highnotes=document.getElementById('session-highnotes');
 r.layout={beat:box('session-beat'),reply:box('session-reply'),nudges:box('private-nudges'),
   highlights:box('session-highnotes'),
   highlightsNested:document.getElementById('session-duet').contains(highnotes),
   cards:[...highnotes.querySelectorAll('.highnote-card:not([hidden])')].map(x=>box(x.id)),
   labels:[...highnotes.querySelectorAll('.highnote-card:not([hidden]) .highnote-badge')].map(x=>x.textContent.replace(/[♪𝅝♫♬]/gu,'')),
   highlightsFit:[...highnotes.querySelectorAll('.highnote-card')].every(x=>x.scrollWidth<=x.clientWidth+1),
   nested:document.getElementById('session-duet').contains(block),
   duetVisible:!document.getElementById('session-duet').hidden,
   countTops:[...block.querySelectorAll('dd')].map(x=>x.getBoundingClientRect().top),
   labelLines:[...block.querySelectorAll('dt')].map(x=>x.clientHeight/parseFloat(getComputedStyle(x).lineHeight)),
   fits:[...block.querySelectorAll('dt,dd')].every(x=>x.scrollWidth<=x.clientWidth+1)};
 const pre=document.createElement('pre');pre.id='nudge-probe';pre.hidden=true;
 pre.textContent=JSON.stringify(r);document.body.appendChild(pre);
});</script>"""
    output.write_text(output.read_text(encoding="utf-8").replace("</body>", probe + "</body>"), encoding="utf-8")
    completed = _run_browser([
        chromium, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--run-all-compositor-stages-before-draw",
        "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={width},1000",
        f"--screenshot={tmp_path / 'pats.png'}", "--virtual-time-budget=2500", "--dump-dom", output.as_uri() + "#private-nudges",
    ])
    assert completed.returncode == 0
    match = re.search(r'<pre id="nudge-probe" hidden="">(.*?)</pre>', completed.stdout.decode("utf-8"), re.S)
    assert match is not None
    rendered = json.loads(html.unescape(match.group(1)))
    visible = has_actions and kind == "private"
    layout = rendered.pop("layout")
    assert layout["nested"]
    if kind == "private" and has_sessions:
        assert layout["highlightsNested"] and layout["highlightsFit"]
        assert len(layout["cards"]) == 2
        assert layout["labels"] == ["话最多", "聊最久"]
        assert layout["reply"]["bottom"] <= layout["highlights"]["top"]
        if width > 720:
            if has_actions:
                assert layout["highlights"]["left"] == pytest.approx(layout["reply"]["left"])
                assert layout["highlights"]["top"] == pytest.approx(layout["nudges"]["top"])
                assert all(a["bottom"] <= b["top"] for a, b in zip(layout["cards"], layout["cards"][1:]))
            else:
                assert layout["highlights"]["left"] == pytest.approx(layout["beat"]["left"])
                assert layout["highlights"]["right"] == pytest.approx(layout["reply"]["right"])
        elif has_actions:
            assert layout["nudges"]["bottom"] <= layout["highlights"]["top"]
    if visible:
        assert layout["duetVisible"] and layout["fits"]
        assert layout["countTops"][0] == pytest.approx(layout["countTops"][1])
        assert layout["labelLines"] == pytest.approx([2, 2], abs=0.03)
        if has_sessions:
            assert layout["reply"]["bottom"] <= layout["nudges"]["top"]
            if width > 720:
                assert layout["beat"]["right"] <= layout["reply"]["left"]
                assert layout["beat"]["left"] == pytest.approx(layout["nudges"]["left"])
            else:
                assert layout["beat"]["bottom"] <= layout["reply"]["top"]
    labels = ["你摸了摸 TA", "TA 拍了拍你"] if source == "qq" else ["你拍了拍 TA", "TA 拍了拍你"]
    labels[0] += suffix if has_sessions else ""
    labels[1] += peer_suffix
    assert rendered == dict(
        visible=visible, chapter=has_sessions or visible, toc=has_sessions or visible,
        counts=["2 次", "1 次"] if visible else ["", ""], rows=0,
        titles=labels if visible else ["", ""],
        labels=labels if visible else ["", ""], recentLabel=False,
        rawSuffix=visible and has_sessions,
        inert=True, readonly=True, overflow=False, time="",
    )
