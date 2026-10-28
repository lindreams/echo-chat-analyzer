"""Original-message lookup uses retained lexical facts, never substring search."""
from dataclasses import asdict, replace
import json

import pytest

from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.presentation.models import (
    EchoLanguageMember, EchoLanguageProfile, EchoMemberCard, EchoReportView, EchoSharedWord,
)


def _view():
    members = tuple(EchoMemberCard(
        speaker_key=key, display_name="同名成员", is_viewer=index == 0,
        message_count=4, message_share_percent=50, average_length=8, max_length=20,
        active_period="晚上",
    ) for index, key in enumerate(("fictional-self", "fictional-peer")))
    return EchoReportView(title="Fictional", conversation_kind="private", members=members,
        language_profile=EchoLanguageProfile(mode="private_common", available=True,
            members=(EchoLanguageMember("fictional-self", "同名成员", "你常说", ("苹果", "apple"), ("散步",)),
                     EchoLanguageMember("fictional-peer", "同名成员", "TA 常说", ("苹果",))),
            shared_words=(EchoSharedWord("苹果", 2, 1, "equal"),),
            side_preference_words=(EchoSharedWord("apple", 1, 0, "self"),)))


def _message(text, *, index=0, sender="fictional-self", **changes):
    return replace(ChatMessage(timestamp=1760000000 + index * 10, sender="同名成员",
        sender_id=sender, message_type="text", text=text, message_id="duplicate",
        platform="wechat", conversation_id="fictional-chat", conversation_type="private"), **changes)


def _build(messages, tokens, positions=None, view=None):
    from qq_chat_analyzer.presentation.language_sources import build_language_sources
    return build_language_sources(view or _view(), messages, tokens,
        source_positions=list(range(len(messages))) if positions is None else positions)


def test_sources_keep_occurrences_distinct_from_messages_and_do_not_substring_match():
    messages = [_message("苹果 苹果，今天去散步。"), _message("先吃苹果。", index=1, sender="fictional-peer"),
                _message("pineapple is different", index=2), _message("水果也有 apple。", index=3)]
    sources = _build(messages, [["苹果", "苹果", "今天", "散步"], ["苹果"], ["pineapple"], ["水果", "apple"]])
    terms = {(term.member_index, term.word): term for term in sources.terms}
    assert terms[0, "苹果"].occurrence_count == 2
    assert terms[0, "苹果"].message_refs == (0,)
    assert terms[None, "苹果"].occurrence_count == 3
    assert terms[None, "苹果"].message_refs == (0, 1)
    assert terms[0, "apple"].message_refs == (3,)
    assert terms[0, "散步"].message_refs == (0,)
    assert [m.ref for m in sources.messages] == [0, 1, 2, 3]
    assert sources.messages[0].text == "苹果 苹果，今天去散步。"
    assert sources.messages[0].speaker_label != sources.messages[1].speaker_label
    assert "fictional-self" not in json.dumps(asdict(sources))
    assert "message_id" not in json.dumps(asdict(sources))


def test_duplicate_and_missing_source_ids_never_collapse_distinct_occurrences():
    messages = [_message("苹果", index=i, message_id=None if i > 1 else "same") for i in range(4)]
    sources = _build(messages, [["苹果"]] * 4)
    term = next(t for t in sources.terms if t.member_index == 0 and t.word == "苹果")
    assert term.occurrence_count == 4
    assert term.message_refs == (0, 1, 2, 3)
    assert len(sources.messages) == 4


@pytest.mark.parametrize("boundary,expected_before,expected_after", [
    ("none", (1, 2), (4, 5)),
    ("filtered_before", (), (4, 5)),
    ("filtered_after", (1, 2), ()),
    ("unknown_time", (), (4, 5)),
    ("time_reversal", (), (4, 5)),
    ("too_far", (), (4, 5)),
    ("other_conversation", (), (4, 5)),
    ("other_platform", (), (4, 5)),
])
def test_context_is_bounded_and_stops_at_uncertain_or_filtered_boundaries(boundary, expected_before, expected_after):
    messages = [_message("苹果" if i == 3 else f"别的话 {i}", index=i) for i in range(7)]
    positions = list(range(7))
    if boundary == "filtered_before":
        positions = [0, 1, 2, 4, 5, 6, 7]
    elif boundary == "filtered_after":
        positions = [0, 1, 2, 3, 5, 6, 7]
    elif boundary == "unknown_time":
        messages[2] = replace(messages[2], timestamp="unknown")
    elif boundary == "time_reversal":
        messages[2] = replace(messages[2], timestamp=1760000050)
    elif boundary == "too_far":
        messages[2] = replace(messages[2], timestamp=1760000000 - 600)
    elif boundary == "other_conversation":
        messages[2] = replace(messages[2], conversation_id="other-fictional-chat")
    elif boundary == "other_platform":
        messages[2] = replace(messages[2], platform="qq")
    sources = _build(messages, [["苹果"] if i == 3 else ["别的"] for i in range(7)], positions)
    hit = next(m for m in sources.messages if m.ref == 3)
    assert hit.before_refs == expected_before
    assert hit.after_refs == expected_after
    assert {m.ref for m in sources.messages} == {3, *expected_before, *expected_after}


def test_unknown_time_hit_remains_readable_without_invented_context_or_highlights():
    text = "<script>window.fictionalAttack=true</script> 苹果\n原话保留"
    sources = _build([_message("前文"), _message(text, index=1, timestamp="unknown"), _message("后文", index=2)],
                     [["前文"], ["苹果"], ["后文"]])
    assert len(sources.messages) == 1
    assert sources.messages[0].text == text
    assert sources.messages[0].timestamp == ""
    assert sources.messages[0].before_refs == sources.messages[0].after_refs == ()


def test_unavailable_profiles_export_no_originals_and_alignment_fails_closed():
    view = replace(_view(), language_profile=EchoLanguageProfile("unknown", False))
    assert _build([_message("苹果")], [["苹果"]], view=view) is None
    with pytest.raises(ValueError, match="alignment"):
        _build([_message("苹果")], [])


def test_original_text_cannot_be_reinterpreted_as_report_template_placeholders(tmp_path):
    import re
    from qq_chat_analyzer.presentation import export_echo_report_html

    text = '苹果 __ECHO_APP_JS__ __ECHO_ASSETS__ __ECHO_DATA__ </script> 原话'
    view = replace(_view(), language_sources=_build([_message(text)], [["苹果"]]))
    report = export_echo_report_html(view, tmp_path / "template-markers.html").read_text(encoding="utf-8")
    match = re.search(r'window.ECHO_DATA = (.*?);\s*window.ECHO_ASSETS', report, re.S)
    payload = json.loads(match.group(1))
    assert payload["language_sources"]["messages"][0]["text"] == text
    assert report.count("</script>") == 2


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind,width", [("private", 390), ("group", 1280)])
def test_offline_word_lookup_paginates_keeps_text_inert_and_restores_reading_position(tmp_path, kind, width):
    import html
    import re
    from test_echo_conversation_sessions_frontend import _find_chromium, _run_browser
    from qq_chat_analyzer.presentation import export_echo_report_html

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    view = _view()
    if kind == "group":
        view = replace(view, conversation_kind="group", language_profile=replace(
            view.language_profile, mode="group_distinctive", shared_words=(), side_preference_words=()))
    dangerous = '</script><img id="fictional-attack" src="x" onerror="window.fictionalAttack=true"> 苹果\n保留换行'
    messages = [_message(dangerous if i == 0 else f"苹果 原话 {i}", index=i) for i in range(55)]
    view = replace(view, language_sources=_build(messages, [["苹果"]] * 55, view=view))
    output = export_echo_report_html(view, tmp_path / "originals.html")
    probe = r"""<script>
window.addEventListener('load',()=>{
 const r={};
 try {
  const word=document.querySelector('.voice-entry .language-word-button');
  r.wordAvailable=!!word;
  const hint=document.getElementById('language-original-hint');
  r.lookupHint=!!hint&&!hint.hidden&&hint.textContent.includes('点击词语');
  if(!word)throw Error('no word lookup button');
  word.scrollIntoView({block:'center'});word.focus({preventScroll:true});
  const y=scrollY,dialog=document.getElementById('language-originals');
  r.initiallyClosed=!dialog.open;
  word.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));r.hoverQuiet=!dialog.open;
  word.click();r.open=dialog.open;
  r.initialHits=dialog.querySelectorAll('.language-original-hit').length;
  r.rawText=dialog.querySelector('.language-original-text').textContent.includes('保留换行');
  r.inert=!window.fictionalAttack&&!document.getElementById('fictional-attack');
  dialog.querySelector('.language-context-toggle').click();
  r.contextRows=dialog.querySelector('.language-original-hit').querySelectorAll('.language-original-row').length;
  dialog.querySelector('.language-all').click();r.firstPage=dialog.querySelectorAll('.language-original-hit').length;
  dialog.querySelector('.language-more').click();r.secondPage=dialog.querySelectorAll('.language-original-hit').length;
  while(!dialog.querySelector('.language-more').hidden)dialog.querySelector('.language-more').click();
  r.allHits=dialog.querySelectorAll('.language-original-hit').length;
  r.summary=dialog.querySelector('.language-original-summary').textContent;
  r.noInputs=!dialog.querySelector('input,textarea,[contenteditable=true]');
  r.overflow=document.documentElement.scrollWidth>innerWidth||dialog.scrollWidth>dialog.clientWidth+1;
  dialog.querySelector('.language-original-close').click();r.closed=!dialog.open;
  r.focusRestored=document.activeElement===word;r.scrollStable=Math.abs(scrollY-y)<2;
 } catch(error) { r.error=String(error); }
 const pre=document.createElement('pre');pre.id='language-probe';pre.hidden=true;pre.textContent=JSON.stringify(r);document.body.append(pre);
});
</script>"""
    output.write_text(output.read_text(encoding="utf-8").replace("</body>", probe + "</body>"), encoding="utf-8")
    completed = _run_browser([chromium, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={width},1000",
        "--virtual-time-budget=2000", "--dump-dom", output.as_uri()])
    assert completed.returncode == 0
    match = re.search(r'<pre id="language-probe" hidden="">(.*?)</pre>', completed.stdout.decode("utf-8"), re.S)
    assert match is not None
    result = json.loads(html.unescape(match.group(1)))
    assert result == {"wordAvailable": True, "lookupHint": True, "initiallyClosed": True, "hoverQuiet": True, "open": True,
        "initialHits": 3, "rawText": True, "inert": True, "contextRows": 3,
        "firstPage": 10, "secondPage": 20, "allHits": 55,
        "summary": "出现 55 次，分布于 55 条消息", "noInputs": True, "overflow": False,
        "closed": True, "focusRestored": True, "scrollStable": True}


@pytest.mark.slow_integration
@pytest.mark.parametrize("width", [1280, 390])
def test_expanding_originals_reveals_front_context_and_backdrop_dismisses_without_losing_place(tmp_path, width):
    import html
    import re
    from test_echo_conversation_sessions_frontend import _find_chromium, _run_browser
    from qq_chat_analyzer.presentation import export_echo_report_html

    chromium = _find_chromium()
    if chromium is None:
        pytest.skip("no local Chromium available")
    messages = [_message("苹果，周末再一起去走走。" if i % 5 == 2 else
        f"第 {i} 条虚构上下文。散步时经过湖边，看到了树叶和小花，慢慢走了一会儿。" * 3,
        index=i) for i in range(60)]
    view = _view()
    view = replace(view, language_sources=_build(messages,
        [["苹果"] if i % 5 == 2 else [] for i in range(60)], view=view))
    output = export_echo_report_html(view, tmp_path / "context.html")
    probe = r"""<script>window.addEventListener('load',()=>{
      const r={};
      try {
        const word=document.querySelector('.language-word-button');
        word.scrollIntoView({block:'center',behavior:'instant'});word.focus({preventScroll:true});
        const y=scrollY,pageWidth=document.body.clientWidth;
        word.click();const dialog=document.getElementById('language-originals');
        const list=dialog.querySelector('.language-original-results');
        const toggle=dialog.querySelector('.language-context-toggle');toggle.click();
        const first=dialog.querySelector('.language-original-row');
        r.frontText=first.querySelector('.language-original-text').textContent.startsWith('第 0 条');
        r.frontVisible=first.getBoundingClientRect().top>=list.getBoundingClientRect().top-1&&
          first.getBoundingClientRect().top<list.getBoundingClientRect().bottom;
        toggle.click();toggle.focus({preventScroll:true});
        const focus=getComputedStyle(toggle);
        r.keyboardFocusThin=toggle.matches(':focus-visible')&&focus.outlineStyle==='solid'&&parseFloat(focus.outlineWidth)<=1;
        dialog.focus({preventScroll:true});r.panelHasNoFocusFrame=getComputedStyle(dialog).outlineStyle==='none';
        const box=dialog.getBoundingClientRect(),outside={clientX:2,clientY:innerHeight/2};
        function pointer(target,point){target.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,...point}))}
        function click(target,point){target.dispatchEvent(new MouseEvent('click',{bubbles:true,...point}))}
        pointer(dialog,{clientX:box.x+10,clientY:box.y+10});click(dialog,{clientX:box.x+10,clientY:box.y+10});
        r.insideKeepsOpen=dialog.open;
        pointer(dialog.querySelector('.language-original-text'),{clientX:box.x+30,clientY:box.y+150});
        click(dialog,outside);r.selectionKeepsOpen=dialog.open;
        r.openKeepsPageWidth=document.body.clientWidth===pageWidth;
        pointer(dialog,outside);click(dialog,outside);r.backdropCloses=!dialog.open;
        r.pageStable=Math.abs(scrollY-y)<2&&document.body.clientWidth===pageWidth;
        setTimeout(()=>{
          r.focusRestored=document.activeElement===word;
          const pre=document.createElement('pre');pre.id='context-probe';pre.hidden=true;
          pre.textContent=JSON.stringify(r);document.body.append(pre);
        },0);
      } catch(error) {const pre=document.createElement('pre');pre.id='context-probe';pre.hidden=true;
        pre.textContent=JSON.stringify({error:String(error)});document.body.append(pre)}
    });</script>"""
    output.write_text(output.read_text(encoding="utf-8").replace("</body>", probe + "</body>"), encoding="utf-8")
    completed = _run_browser([chromium, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--disable-background-networking", "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--user-data-dir={tmp_path / 'browser'}", f"--window-size={width},900",
        "--virtual-time-budget=2000", "--dump-dom", output.as_uri()])
    assert completed.returncode == 0
    match = re.search(r'<pre id="context-probe" hidden="">(.*?)</pre>', completed.stdout.decode("utf-8"), re.S)
    assert match is not None
    result = json.loads(html.unescape(match.group(1)))
    assert result == {"frontText": True, "frontVisible": True, "keyboardFocusThin": True,
        "panelHasNoFocusFrame": True, "insideKeepsOpen": True, "selectionKeepsOpen": True,
        "openKeepsPageWidth": True, "backdropCloses": True, "pageStable": True, "focusRestored": True}
