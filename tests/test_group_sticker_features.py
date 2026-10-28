"""Invented multi-member evidence through the shared index and report boundary."""
from dataclasses import replace
import json
import logging

import pytest

from qq_chat_analyzer.analysis.sticker_index import build_sticker_fact_index
from qq_chat_analyzer.analysis.stickers import StickerData, collect_sticker_sends
from qq_chat_analyzer.rich_message import ReplyRelation
from sticker_feature_samples import Messages


def group_rows(builder, source="fiction"):
    return tuple(replace(m, conversation_type="group", is_self=None, source=source,
                         message_id=f"msg-{i}") for i, m in enumerate(builder.ordered()))


def discover(rows, positions=None):
    from qq_chat_analyzer.analysis.group_stickers import analyze_group_stickers
    data = StickerData(collect_sticker_sends(rows))
    index = build_sticker_fact_index(data, rows, conversation_kind="group",
                                    source_positions=positions if positions is not None else range(len(rows)))
    return analyze_group_stickers(index)


def relay_rows():
    b = Messages()
    for i, member in enumerate("ABCABC"):
        b.add(0, member, "relay", seconds=i*20)
    return group_rows(b)


def all_group_story_rows():
    b = Messages("all-group-stories")
    for d in range(120):
        for i, member in enumerate("ABC"):
            b.add(d, member, "background-"+member, seconds=100*i)
            if d >= 92:
                b.add(d, member, *("rising" for _ in range(5)), seconds=100*i+10)
    for d in (0, 2, 4):
        for i, member in enumerate("AB"):
            b.add(d, member, "old", seconds=500+i*10)
    b.add(100, "A", "old", seconds=500)
    for d in (0, 10, 20, 30, 40, 50, 60):
        b.add(d, "A", *("distinctive" for _ in range(15)), seconds=600)
    for i, member in enumerate("ABC"):
        for d in range(10+i*10, 81+i*10, 14):
            b.add(d, member, *("common" for _ in range(12)), seconds=700+i*10)
    for d in (40, 41):
        b.add(d, "A", *(f"variety-{i}" for i in range(40)), seconds=900)
    for i, member in enumerate("ABCABC"):
        b.add(118, member, "relay", seconds=2000+i*20)
    rows = list(group_rows(b, source="qq"))
    reply = next(i for i, m in enumerate(rows) if m.contents[0].sticker.identity_key == "fiction:relay")+5
    rows[reply] = replace(rows[reply], relations=(ReplyRelation(rows[reply-1].message_id),))
    return tuple(rows)


def test_three_members_with_no_self_markers_form_a_same_material_relay():
    f, = discover(relay_rows()).relays
    assert f.member_count == 3
    assert len(f.turns) == 6
    assert f.identity_key == "fiction:relay"


def test_overlong_single_author_turn_does_not_crash_or_swallow_the_next_relay():
    b = Messages()
    for i in range(12):
        b.add(0, "A", "relay", seconds=i*60)
    for i, member in enumerate("BCAB"):
        b.add(0, member, "relay", seconds=720+i*20)
    f, = discover(group_rows(b)).relays
    assert len(f.turns) == 4
    assert f.member_count == 3


@pytest.mark.parametrize("obstruction", ["gap", "tie", "unknown", "text", "two_members"])
def test_group_relay_requires_contiguous_known_multi_member_order(obstruction):
    rows = list(relay_rows())
    positions = None
    if obstruction == "gap":
        positions = (0, 1, 2, 4, 5, 6)
    elif obstruction == "tie":
        rows[3] = replace(rows[3], timestamp=rows[2].timestamp)
    elif obstruction == "unknown":
        rows[3] = replace(rows[3], sender=replace(rows[3].sender, identity_id=None))
    elif obstruction == "text":
        rows[3] = replace(rows[3], contents=())
    else:
        rows = [replace(m, sender=rows[i % 2].sender) for i, m in enumerate(rows)]
    assert not discover(tuple(rows), positions).relays


def test_trend_requires_wider_use_and_compares_both_windows_denominators():
    b = Messages()
    for d in range(56):
        for i, member in enumerate("ABC"):
            b.add(d, member, "background", seconds=i*100)
            if d >= 28:
                b.add(d, member, "rising", seconds=i*100+10)
    f = next(f for f in discover(group_rows(b)).trends if f.identity_key == "fiction:rising")
    assert f.previous.send_count == 0
    assert f.current.send_count == 84
    assert f.current.known_send_count == 168
    assert (f.previous_members, f.current_members) == (0, 3)
    # A lone prolific author cannot turn a group trend into a finding.
    rows = [m for m in group_rows(b) if not (m.contents[0].sticker.identity_key == "fiction:rising"
            and m.sender.identity_id != "fiction-A")]
    assert not any(f.identity_key == "fiction:rising" for f in discover(rows).trends)


def test_reunion_needs_old_shared_use_and_active_observable_absence():
    b = Messages()
    for d in (0, 2, 4):
        for i, member in enumerate("AB"):
            b.add(d, member, "old", seconds=i*10)
    for d in range(5, 60):
        b.add(d, "C", "background")
    b.add(60, "C", "old")
    rows = group_rows(b)
    f, = discover(rows).reunions
    assert f.gap_days == 56
    assert f.return_member_count == 1
    assert f.previous_member_count == 2
    rows = (*rows[:10], replace(rows[10], contents=(replace(rows[10].contents[0],
        sticker=replace(rows[10].contents[0].sticker, identity_key=None)),)), *rows[11:])
    assert not discover(rows).reunions


def habit_rows():
    b = Messages()
    for d in (0, 10, 20, 30, 40):
        b.add(d, "A", "distinctive", "common")
        b.add(d, "B", "other", "common", seconds=10)
        b.add(d, "C", "other", "common", seconds=20)
    return group_rows(b)


def test_distinctive_preference_requires_persistence_and_real_other_member_sample():
    fs = discover(habit_rows()).signatures
    assert [(f.habit.sender_id, f.habit.identity_key) for f in fs] == [("fiction-A", "fiction:distinctive")]
    assert fs[0].other_known_send_count == 20
    assert fs[0].other_send_count == 0
    assert not discover(tuple(m for m in habit_rows() if m.sender.identity_id == "fiction-A")).signatures


def test_persistent_relative_preference_is_not_hidden_below_fifteen_percent():
    b = Messages("fictional-relative-preference")
    for d in (0, 8, 16, 24, 32):
        b.add(d, "A", "personal")
    b.add(1, "A", *("background" for _ in range(35)))
    b.add(1, "B", *("other" for _ in range(20)), seconds=10)
    b.add(1, "C", *("other" for _ in range(20)), seconds=20)
    f, = discover(group_rows(b)).signatures
    assert f.habit.identity_key == "fiction:personal"
    assert f.habit.share == .125
    assert f.other_send_count == 0
    assert f.other_known_send_count == 40
    assert f.relative_share == 6


def test_shared_habit_and_widening_circle_preserve_observed_members_and_dates():
    b = Messages()
    for i, member in enumerate("ABC"):
        for d in (i*10, i*10+7, i*10+14, i*10+35):
            b.add(d, member, "common", seconds=i*10)
    fs = discover(group_rows(b))
    habit, = fs.shared_habits
    adoption, = fs.adoptions
    assert len(habit.members) == 3
    assert habit.active_member_count == 3
    assert [u.first_date for u in adoption.members] == ["2025-01-01", "2025-01-11", "2025-01-21"]
    assert adoption.claim == "observed_order_only"


def test_style_uses_equal_samples_and_ignores_insufficient_new_member():
    b = Messages()
    for d in range(3):
        b.add(d, "A", *(f"variety-{i}" for i in range(10)))
        b.add(d, "B", *("same" for _ in range(10)), seconds=10)
    b.add(2, "C", "one", seconds=20)
    style, = discover(group_rows(b)).styles
    assert style.sample_size == 30
    assert style.richer.expected_unique_count == 10
    assert style.concentrated.expected_unique_count == 1


def test_group_style_excludes_low_coverage_members_before_choosing_sample_and_extremes():
    b = Messages()
    for d in range(3):
        b.add(d, "A", *(f"variety-{i}" for i in range(10)))
        b.add(d, "B", *("same" for _ in range(10)), seconds=10)
        b.add(d, "C", "sparse", *(None for _ in range(4)), seconds=20)
    # C passes the count/day floor, but only 20% of its sends are identifiable.
    b.add(3, "C", *("sparse" for _ in range(7)), *(None for _ in range(28)))
    style, = discover(group_rows(b)).styles
    assert style.sample_size == 30
    assert {style.richer.sender_id, style.concentrated.sender_id} == {"fiction-A", "fiction-B"}


@pytest.mark.parametrize("sender", ["B", None])
def test_group_style_does_not_use_missing_materials_or_authors_to_claim_contrast(sender):
    b = Messages()
    for d in range(3):
        b.add(d, "A", *(f"variety-{i}" for i in range(10)))
        b.add(d, "B", *("same" for _ in range(10)), seconds=10)
    b.add(3, sender, *(None for _ in range(16 if sender is None else 8)))
    assert not discover(group_rows(b)).styles


def test_explicit_qq_reply_resolves_only_unique_kept_targets_without_adjacency_claims():
    rows = list(relay_rows())
    rows = [replace(m, source="qq") for m in rows]
    rows[3] = replace(rows[3], relations=(ReplyRelation(rows[1].message_id),))
    f, = discover(rows).replies
    assert f.sender_id == rows[3].sender.identity_id
    assert f.target_sender_id == rows[1].sender.identity_id
    assert not discover([replace(m, source="wechat") for m in rows]).replies
    assert not discover([replace(m, message_id=rows[1].message_id) if i == 2 else m
                         for i, m in enumerate(rows)]).replies
    assert not discover([m for i, m in enumerate(rows) if i != 1]).replies


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_group_discovery_reaches_formal_source_pipeline_and_share_export(tmp_path, source, monkeypatch):
    from sticker_feature_samples import formal_payload
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application import analysis_service as service
    from qq_chat_analyzer.presentation.stickers import sticker_report_targets
    rows = relay_rows()
    payload = formal_payload(rows, source, group=True)
    identities = {"fiction-A": "10001", "fiction-B": "20002", "fiction-C": "30003"}
    for record, row in zip(payload["records"] if source == "qq" else payload["messages"], rows):
        if source == "qq":
            record["fields"]["40033"] = identities[row.sender.identity_id]
        else:
            record["user_name"] = "fiction-member-"+identities[row.sender.identity_id]
    path = tmp_path/"fictional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    original = service.resolve_sticker_media
    observed = []
    analyze = getattr(service, "analyze_group_stickers", None)
    assert analyze is not None, "Group discovery must be connected to the application service"
    def record_analysis(index):
        result = analyze(index)
        observed.append(result)
        return result
    def resolve(sends, **kwargs):
        assert observed, "Group discovery must finish before media recovery"
        return original(sends, **kwargs)
    monkeypatch.setattr(service, "analyze_group_stickers", record_analysis)
    monkeypatch.setattr(service, "resolve_sticker_media", resolve)
    result = service.AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=tmp_path/"out", stopwords_path=stopwords))
    assert result.reports.private_stickers is None
    relay, = result.reports.group_stickers.relays
    assert relay.member_count == 3
    exported = json.loads((tmp_path/"out"/"echo-report.json").read_text(encoding="utf-8"))
    memory, = exported["sticker_memories"]
    assert memory["findings"][0]["kind"] == "relay"
    assert len(memory["findings"][0]["points"]) == 6
    assert len(sticker_report_targets(result.echo_report_view.stickers)) == 1
    assert all("fiction" not in point["label"] for point in memory["findings"][0]["points"])
    serialized = json.dumps(memory, ensure_ascii=False)
    for forbidden in ("identity_key", "sender_id", "message_id", "fiction-", "observed_order_only", relay.media_key):
        assert forbidden not in serialized


def test_private_analyzer_cannot_consume_an_explicit_group_index():
    from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
    rows = relay_rows()
    data = StickerData(collect_sticker_sends(rows))
    index = build_sticker_fact_index(data, rows, conversation_kind="group")
    assert not analyze_private_stickers(index).available


def test_unknown_material_from_another_member_obstructs_a_group_absence_claim():
    b = Messages()
    for d in (0, 2, 4):
        for i, member in enumerate("AB"):
            b.add(d, member, "old", seconds=i*10)
    for d in range(5, 60):
        b.add(d, "C", "background")
    b.add(20, "D", None, seconds=10)
    b.add(60, "A", "old")
    assert not discover(group_rows(b)).reunions


def test_striking_reunion_precedes_an_ordinary_relay_regardless_of_category_order():
    b = Messages()
    for d in (0, 2, 4):
        for i, member in enumerate("AB"):
            b.add(d, member, "old", seconds=i*10)
    for d in (20, 40, 60):
        b.add(d, "C", *("background" for _ in range(4)))
    b.add(200, "C", "old")
    for i, member in enumerate("ABCABC"):
        b.add(201, member, "relay", seconds=i*20)
    features = discover(group_rows(b))
    assert features.relays and features.reunions
    assert features.stories[0].findings[0][0] == "reunions"


def test_discovery_selection_keeps_category_diversity_when_many_materials_qualify():
    b = Messages()
    for key in range(12):
        for i, member in enumerate("ABCABC"):
            b.add(key, member, f"relay-{key}", seconds=i*20)
    for d in range(20, 23):
        b.add(d, "A", *(f"rich-{i}" for i in range(20)))
        b.add(d, "B", *("single" for _ in range(20)), seconds=10)
    features = discover(group_rows(b))
    assert features.styles
    assert any(name == "styles" for story in features.stories for name, _ in story.findings)
    assert len(features.stories) <= 9
    assert sum(not s.compact for s in features.stories) <= 3


@pytest.mark.parametrize("problem", ["gap", "unknown_time", "reversal", "one_day_spam"])
def test_first_observed_circle_does_not_invent_history(problem):
    b = Messages()
    for i, member in enumerate("ABC"):
        for d in (i*10, i*10+2, i*10+4):
            b.add(d if problem != "one_day_spam" else i*10, member, "common", seconds=d)
    rows = list(group_rows(b))
    positions = None
    if problem == "gap":
        positions = tuple(i if i < 2 else i+1 for i in range(len(rows)))
    elif problem == "unknown_time":
        rows[3] = replace(rows[3], timestamp="unknown")
    elif problem == "reversal":
        rows = [*rows[3:6], *rows[:3], *rows[6:]]
    assert not discover(rows, positions).adoptions


def test_all_eight_categories_share_bounded_stories_and_ignore_media_failures():
    from qq_chat_analyzer.analysis.group_stickers import analyze_group_stickers
    from qq_chat_analyzer.analysis.stickers import StickerMedia
    from qq_chat_analyzer.presentation.stickers import build_echo_stickers
    rows = all_group_story_rows()
    f = discover(rows)
    categories = {"relays", "reunions", "trends", "signatures", "shared_habits", "adoptions", "styles", "replies"}
    assert all(getattr(f, name) for name in categories)
    assert {name for s in f.stories for name, _ in s.findings} == categories
    data = StickerData(collect_sticker_sends(rows), media=(StickerMedia("fiction:relay", "failed"),))
    index = build_sticker_fact_index(data, rows, conversation_kind="group", source_positions=range(len(rows)))
    assert analyze_group_stickers(index) == f
    chapter = build_echo_stickers((index.report,), data.media, conversation_kind="group", group_features=f)
    assert {v.kind for s in chapter.memories for v in s.findings} == {
        "relay", "reunion", "trend", "signature", "shared", "adoption", "style", "reply"}
    for finding in (v for s in chapter.memories for v in s.findings):
        if finding.kind in {"signature", "style"}:
            assert not finding.note
            assert finding.points and all(point.value is not None for point in finding.points)
    other = replace(f, conversation_id="other-scope")
    assert not build_echo_stickers((index.report,), (), conversation_kind="group", group_features=other).memories


def test_group_discovery_explains_empty_results_with_numeric_counts_only(caplog):
    caplog.set_level(logging.INFO, logger="qq_chat_analyzer.desktop.analysis_diagnostics")
    b = Messages("private-scope-sentinel")
    b.add(0, "A", "private-material-sentinel", text="private-body-sentinel")
    b.add(1, "B", "different")
    f = discover(group_rows(b, source="wechat"))
    audit = dict(f.diagnostic_counts)
    assert audit["input.members"] == 2
    assert audit["input.sends"] == 2
    assert audit["input.span_days"] == 2
    assert audit["trends.reject_short_scope"] == 1
    assert audit["shared_habits.reject_members"] == 2
    assert audit["adoptions.reject_repetition_or_members"] == 2
    assert audit["styles.reject_sample_or_dates"] == 2
    assert audit["replies.unavailable_source"] == 1
    assert audit["stories.selected"] == 0
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[group-sticker-counts] ")]
    assert len(lines) == 1
    assert json.loads(lines[0].split("] ", 1)[1]) == audit
    assert all(type(value) is int for value in audit.values())
    assert all(secret not in lines[0] for secret in ("fiction-", "private-scope", "private-material", "private-body"))


def test_group_discovery_and_projection_counts_distinguish_a_scope_mismatch(caplog):
    from qq_chat_analyzer.analysis.stickers import aggregate_stickers
    from qq_chat_analyzer.presentation.stickers import build_echo_stickers
    caplog.set_level(logging.INFO, logger="qq_chat_analyzer.desktop.analysis_diagnostics")
    rows = relay_rows()
    data = StickerData(collect_sticker_sends(rows))
    f = discover(rows)
    assert dict(f.diagnostic_counts)["relays.qualified"] == 1
    assert dict(f.diagnostic_counts)["stories.selected"] == 1
    for features in (f, replace(f, conversation_id="wrong-private-scope-sentinel")):
        build_echo_stickers(aggregate_stickers(data, rows), (), conversation_kind="group", group_features=features)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[group-sticker-projection-counts] ")]
    assert lines == [
        "[group-sticker-projection-counts] available=1 matched_scope=1 stories=1 memories=1 findings=1",
        "[group-sticker-projection-counts] available=1 matched_scope=0 stories=1 memories=0 findings=0",
    ]
