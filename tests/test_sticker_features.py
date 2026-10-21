"""Private sticker discoveries: actual facts, independent fictional expectations."""
from dataclasses import replace
import importlib
import json

import pytest

from qq_chat_analyzer.analysis.stickers import (
    StickerData, StickerMedia, aggregate_stickers, collect_sticker_sends, count_sticker_messages,
)
from qq_chat_analyzer.rich_message import SenderIdentity
from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
from qq_chat_analyzer.analysis.sticker_index import build_sticker_fact_index
from sticker_feature_samples import Messages, reviewed_scenarios


def indexed(messages, *, positions=None, data=None):
    data = data or StickerData(collect_sticker_sends(messages), message_counts=count_sticker_messages(messages))
    reports = aggregate_stickers(data, messages)
    return build_sticker_fact_index(data, messages, reports=reports, source_positions=positions)


def discover(messages, **kwargs):
    index = indexed(messages, **kwargs)
    return analyze_private_stickers(index)


def adoption_messages():
    b = Messages()
    b.add(0, "A", "new")
    b.add(3, "B", "new")
    b.add(4, "B", "new", "new")
    return b.ordered()


def reunion_messages(activity=True):
    b = Messages()
    for day in (0, 2, 4, 60):
        b.add(day, "A", "old")
    b.add(0, "B", text="虚构好友")
    if activity:
        for day in (10, 20, 30):
            for i in range(7):
                b.add(day, "A", text="仍在聊天", seconds=i*10)
    return b.ordered()


def test_shared_index_preserves_occurrences_order_and_distinct_units():
    b = Messages()
    b.add(0, "A", "cat", "cat", None, None)
    b.add(1, "A", text="只有文字")
    b.add(2, "B", "cat")
    b.add(3, None, "cat")
    messages = b.ordered()
    index = indexed(messages, positions=(0, 1, 3, 4))
    assert index.available
    assert (index.message_count, index.sticker_message_count, index.send_count) == (4, 3, 6)
    assert (index.unknown_identity_count, index.unknown_sender_count) == (2, 1)
    assert [m.source_position for m in index.messages] == [0, 1, 3, 4]
    assert index.messages[2].barrier_before
    assert [s.occurrence_id for s in index.messages[0].sends] == ["0:0", "0:1", "0:2", "0:3"]
    assert set(index.materials) == {("fiction-A", "fiction:cat"), ("fiction-B", "fiction:cat")}
    series = index.members["fiction-A"]
    assert series.messages.total == 2
    assert series.sticker_messages.total == 1
    assert series.sends.total == 4
    assert series.known_sends.total == 2


def test_adoption_records_observed_order_and_later_cross_day_reuse():
    result = discover(adoption_messages())
    finding, = result.adoptions
    assert finding.claim == "observed_order_only"
    assert (finding.first_sender_id, finding.later_sender_id) == ("fiction-A", "fiction-B")
    assert (finding.lag_days, finding.later_send_count, finding.later_date_count) == (3, 3, 2)
    assert (finding.first_occurrence_id, finding.later_first_occurrence_id) == ("0:0", "1:0")
    assert "filtered_observations_only" in result.qualifiers


def test_cross_participant_time_inversion_does_not_get_sorted_into_an_adoption():
    rows = adoption_messages()
    # Each member's own timeline is sorted, but their first observations conflict
    # with input order. Repairing this by a timestamp sort would invent direction.
    assert not discover((*rows[1:], rows[0])).adoptions


def test_all_qualified_adoptions_survive_and_media_status_cannot_change_them():
    b = Messages()
    keys = tuple(f"new{i}" for i in range(5))
    b.add(0, "A", *keys)
    b.add(2, "B", *keys)
    b.add(3, "B", *keys, *keys)
    rows = b.ordered()
    first = discover(rows)
    assert len(first.adoptions) == 5
    data = StickerData(collect_sticker_sends(rows), media=(StickerMedia(
        media_key="fiction:new0", status="failed", reason="fictional_failure",
    ),))
    assert discover(rows, data=data) == first


def test_left_truncated_scope_is_not_a_gap_across_the_entire_observed_history():
    rows = adoption_messages()
    result = discover(rows, positions=(20, 21, 22))
    assert len(result.adoptions) == 1
    assert "history_may_be_truncated" in result.qualifiers


@pytest.mark.parametrize("damage", ["same_day", "missing_time", "unknown_sender", "reversed", "gap", "one_reuse"])
def test_adoption_does_not_invent_direction(damage):
    messages = list(adoption_messages())
    positions = None
    if damage == "same_day":
        messages[0] = replace(messages[0], timestamp=messages[1].timestamp-60)
    elif damage == "missing_time":
        messages[0] = replace(messages[0], timestamp="unknown")
    elif damage == "unknown_sender":
        messages[0] = replace(messages[0], sender=SenderIdentity(None, "同名"), is_self=None)
    elif damage == "reversed":
        messages.reverse()
    elif damage == "gap":
        positions = (0, 2, 3)
    else:
        messages = messages[:2]
    assert not discover(tuple(messages), positions=positions).adoptions


def test_reunion_requires_old_habit_and_observed_activity_not_just_elapsed_time():
    result = discover(reunion_messages())
    finding, = result.reunions
    assert (finding.gap_days, finding.previous_send_count, finding.previous_date_count) == (56, 3, 3)
    assert (finding.active_message_count, finding.active_date_count) == (21, 3)
    assert finding.other_sticker_send_count == 0  # Text activity is enough.
    assert finding.previous_gap_median == 2
    assert not discover(reunion_messages(False)).reunions


def test_low_message_volume_can_qualify_reunion_with_other_sticker_activity():
    b = Messages()
    b.add(0, "A", "old", "old")
    b.add(4, "A", "old")
    b.add(34, "A", "old")
    b.add(0, "B", text="朋友")
    b.add(10, "A", "other", "other")
    b.add(20, "A", "other")
    finding, = discover(b.ordered()).reunions
    assert (finding.gap_days, finding.previous_send_count, finding.previous_date_count) == (30, 3, 2)
    assert (finding.active_message_count, finding.active_date_count) == (2, 2)
    assert (finding.other_sticker_send_count, finding.other_sticker_date_count) == (3, 2)


@pytest.mark.parametrize("damage", ["unknown_material", "unknown_sender_same_key", "undated_same_key", "gap"])
def test_reunion_rejects_uncertainty_that_could_hide_use(damage):
    messages = list(reunion_messages())
    positions = None
    if damage == "gap":
        positions = tuple(i if i < 5 else i+1 for i in range(len(messages)))
    else:
        b = Messages()
        b.add(25, None if damage == "unknown_sender_same_key" else "A",
              None if damage == "unknown_material" else "old")
        extra = b.rows[0]
        if damage == "undated_same_key":
            extra = replace(extra, timestamp="unknown")
            messages.append(extra)
        else:
            messages.append(extra)
            messages.sort(key=lambda m: m.timestamp)
    assert not discover(tuple(messages), positions=positions).reunions


def test_regular_rare_rotation_is_not_reunion_and_other_material_unknown_is_local():
    b = Messages()
    for day in (0, 40, 80, 120):
        b.add(day, "A", "routine")
    for day in range(1, 120):
        b.add(day, "A", text="持续聊天")
    assert not discover(b.ordered()).reunions
    messages = reunion_messages()
    # Unknown time on a DIFFERENT identified material must not silence old.
    extra = replace(messages[0], timestamp="unknown")
    part = replace(extra.contents[0], sticker=replace(extra.contents[0].sticker, identity_key="fiction:other"))
    assert discover((*messages, replace(extra, contents=(part,)))).reunions


def changing_messages(*, volume_only=False, fade=False):
    b = Messages()
    for day in range(14):
        b.add(day, "B", text="普通回复")
        count = 1 if day < 7 else 5
        for j in range(count):
            b.add(day, "A", "base", seconds=j*20)
            if volume_only or (day < 7 if fade else day >= 7):
                b.add(day, "A", "new", seconds=j*20+1)
    return b.ordered()


def test_short_record_can_have_rise_but_overall_volume_growth_is_not_a_fad():
    result = discover(changing_messages())
    rise = next(t for t in result.trends if t.identity_key == "fiction:new" and t.direction == "rise")
    assert (rise.previous.send_count, rise.current.send_count) == (0, 35)
    assert (rise.previous.known_send_count, rise.current.known_send_count) == (7, 70)
    assert rise.window_days == 7 and rise.current.share == .5
    assert not discover(changing_messages(volume_only=True)).trends


def test_fade_needs_prior_cross_day_habit_and_continued_sticker_activity():
    result = discover(changing_messages(fade=True))
    fade = next(t for t in result.trends if t.identity_key == "fiction:new" and t.direction == "fade")
    assert (fade.previous.send_count, fade.current.send_count) == (7, 0)
    assert fade.current.known_send_count == 35
    b = Messages()
    for i in range(20): b.add(0, "A", "burst", seconds=i)
    for day in range(14): b.add(day, "A", "base", seconds=200)
    assert not discover(b.ordered()).trends


def test_uncertain_current_material_or_filter_gap_cannot_support_fade():
    rows = changing_messages(fade=True)
    positions = tuple(i if i < 18 else i+1 for i in range(len(rows)))
    assert not any(t.direction == "fade" for t in discover(rows, positions=positions).trends)
    b = Messages()
    b.add(10, "A", None)
    damaged = tuple(sorted((*rows, *b.rows), key=lambda m: m.timestamp))
    assert not any(t.direction == "fade" for t in discover(damaged).trends)


def test_trend_uses_text_tail_days_and_keeps_candidates_instead_of_top_one():
    b = Messages()
    for day in range(60):
        b.add(day, "A", text="覆盖到最后一天")
        b.add(day, "B", text="同一会话")
        if day < 30:
            b.add(day, "A", "base", seconds=60)
        elif day < 40:
            b.add(day, "A", "x", "y", seconds=60)
    result = discover(b.ordered())
    rises = [t for t in result.trends if t.direction == "rise"]
    assert {t.identity_key for t in rises} == {"fiction:x", "fiction:y"}
    assert all(t.current.end_date == "2025-03-02" for t in rises)  # Exclusive end.
    assert all(t.window_days == 30 for t in rises)


def test_signature_reuses_existing_qualification_and_exposes_rank_top3_and_long_span():
    b = Messages()
    for day in (0, 7, 14, 200): b.add(day, "A", "old")
    for i in range(12): b.add(0, "A", "burst", seconds=100+i)
    b.add(0, "B", text="朋友")
    result = discover(b.ordered())
    sig, = result.signatures
    assert sig.habit.identity_key == "fiction:old"
    assert sig.is_selected_signature and sig.frequency_rank == 2
    assert sig.overlaps_top3 and sig.long_term and sig.story_eligible
    assert sig.habit.span_days == 200 and sig.habit.qualified


def test_signature_outside_frequency_top3_keeps_its_unchanged_habit_qualification():
    b = Messages()
    for day in (0, 7, 14, 30):
        b.add(day, "A", "old")
    for i in range(5):
        b.add(0, "A", "burst1", "burst2", "burst3", seconds=100+i)
    sig, = discover(b.ordered()).signatures
    assert sig.frequency_rank == 4 and not sig.overlaps_top3
    assert not sig.long_term and sig.story_eligible and sig.is_selected_signature
    assert sig.habit.qualified and sig.habit.span_days == 30


@pytest.mark.parametrize("damage", ["group", "mixed_room", "mixed_source", "ambiguous_side", "conflicting_side"])
def test_scope_and_private_members_cannot_be_guessed(damage):
    messages = list(adoption_messages())
    if damage == "group":
        messages = [replace(m, conversation_type="group") for m in messages]
    elif damage == "mixed_room":
        messages[-1] = replace(messages[-1], conversation_id="other")
    elif damage == "mixed_source":
        messages[-1] = replace(messages[-1], source="other")
    elif damage == "ambiguous_side":
        messages[-1] = replace(messages[-1], sender=SenderIdentity("third", "同名"))
    else:
        messages[-1] = replace(messages[-1], is_self=True)
    result = discover(tuple(messages))
    assert not result.available
    assert not (result.adoptions or result.reunions or result.trends or result.signatures)


def test_index_rejects_data_from_a_different_message_set():
    messages = adoption_messages()
    bad = StickerData(collect_sticker_sends(messages[:1]))
    with pytest.raises(ValueError, match="scope|occurrence|message"):
        indexed(messages, data=bad)


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), 10**30, -1, 0, True, "not-a-time"])
def test_invalid_times_remain_unknown_instead_of_crashing_or_fabricating_first_use(timestamp):
    messages = list(adoption_messages())
    messages[0] = replace(messages[0], timestamp=timestamp)
    index = indexed(tuple(messages))
    assert index.messages[0].epoch_seconds is None and index.messages[0].day is None
    assert not discover(tuple(messages)).adoptions


def test_self_context_unknown_is_not_a_missing_sender_identity():
    rows = tuple(replace(m, is_self=None) for m in adoption_messages())
    index = indexed(rows)
    assert index.unknown_sender_count == 0
    assert index.unattributed_send_count == 4
    assert not discover(rows).adoptions


def test_untrusted_normalized_time_cannot_override_the_source_message_fact():
    rows = adoption_messages()
    sends = list(collect_sticker_sends(rows))
    sends[0] = replace(sends[0], chat_date="2020-01-01")
    with pytest.raises(ValueError, match="occurrence|message"):
        indexed(rows, data=StickerData(tuple(sends)))


def test_missing_rich_pair_is_a_gap_not_a_new_sticker_message_denominator(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.import_outcome import ImportOutcome
    from qq_chat_analyzer.application.import_result import ImportResult
    from qq_chat_analyzer.legacy_projection import project_legacy_message
    from qq_chat_analyzer.rich_message import TextContent

    rows = adoption_messages()
    unpaired = replace(rows[0], timestamp=rows[0].timestamp+86400,
                       contents=(TextContent("Imported ordinary note"),))
    rich = (rows[0], unpaired, *rows[1:])
    projected = tuple(project_legacy_message(m) for m in rich)
    outcome = ImportOutcome(ImportResult("fiction", 4, 1), 4, projected,
                            rich_messages=rows,
                            rich_message_pairs=((projected[0], rows[0]),
                                                (projected[2], rows[1]), (projected[3], rows[2])))
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    monkeypatch.setattr(service.ImportService, "execute", lambda self, request: outcome)
    source = tmp_path/"input"
    source.write_text("fictional import seam", encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = service.AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=source, output_directory=tmp_path/"out", stopwords_path=stopwords,
        export_echo_report=False,
    ))
    assert result.diagnostic_counts.analyzed_message_count == 4
    assert result.stickers.message_counts.total_messages == 3
    assert result.reports.stickers[0].total_send_count == 4
    assert "known_filter_gaps" in result.reports.private_stickers.qualifiers
    assert not result.reports.private_stickers.adoptions


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("filtered,group", [(False, False), (True, False), (False, True)])
def test_formal_analysis_chain_exposes_private_evidence_before_media_without_exporting_it(tmp_path, monkeypatch, source, filtered, group):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from test_qq_db_rich_contents import _body, _sticker, _text
    from test_sticker_data import _private_payload

    b = Messages()
    for day, side, second in ((0, "A", 0), (3, "B", 0), (4, "B", 0), (4, "B", 60)):
        b.add(day, side, "shared", seconds=second)
    rows = b.ordered()
    digest = "ab"*16
    if source == "qq":
        payload = _private_payload(*[_body(_sticker(b"fiction-shared")) for _ in rows],
                                   senders=("10001", "20002", "20002", "20002"))
        payload["self"] = {"namespace": "qq_uin", "value": "10001"}
        for record, row in zip(payload["records"], rows):
            record["fields"]["40050"] = row.timestamp
        if filtered:
            extra = _private_payload(_body(_text("Filtered " + "z"*110)), senders=("20002",))["records"][0]
            extra["fields"]["40050"] = rows[0].timestamp+86400
            payload["records"].insert(1, extra)
        if group:
            payload["query"]["session_type"] = "group"
    else:
        records = [dict(local_type=47, server_id="duplicate", create_time=m.timestamp,
                        user_name="fiction-self" if m.is_self else "fiction-peer",
                        message_content=f'<msg><emoji md5="{digest}"/></msg>') for m in rows]
        if filtered:
            records.insert(1, dict(local_type=1, create_time=rows[0].timestamp+86400,
                                   user_name="fiction-peer", message_content="Filtered " + "z"*110))
        payload = dict(source="wechat-db", conversation=dict(username="fiction-room",
                       session_type="group" if group else "private", self_username="fiction-self"), messages=records)
    input_path = tmp_path/"fiction.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    observed = []
    original_analyze = service.analyze_private_stickers
    def observe(index):
        result = original_analyze(index)
        observed.append(result)
        return result
    monkeypatch.setattr(service, "analyze_private_stickers", observe)
    original_resolve = service.resolve_sticker_media
    def resolve(sends, **kwargs):
        if not group:
            assert observed, "Discovery must finish before even local media resolution"
        return original_resolve(sends, **kwargs)
    monkeypatch.setattr(service, "resolve_sticker_media", resolve)
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=input_path, output_directory=tmp_path/"out", stopwords_path=stopwords,
    ))
    if group:
        assert result.reports.private_stickers is None
        assert result.reports.stickers[0].total_send_count == 4
        return
    features = result.reports.private_stickers
    assert features is not None and features.available
    assert result.stickers.message_counts.total_messages == 4
    assert result.reports.stickers[0].total_send_count == 4
    assert len(features.adoptions) == (0 if filtered else 1)
    if filtered:
        assert "known_filter_gaps" in features.qualifiers
    else:
        assert features.adoptions[0].lag_days == 3
    assert all(m.status not in {"available", "preview"} for m in result.stickers.media)
    exported = (tmp_path/"out"/"echo-report.json").read_text(encoding="utf-8")
    assert "observed_order_only" not in exported and digest not in exported


@pytest.mark.parametrize("name,messages,sends,signature_count,qualified_count", [
    ("daily", 292, 57, 2, 2), ("fighters", 154, 124, 0, 0),
    ("unequal", 2220, 760, 1, 2), ("short", 14, 8, 0, 0),
    ("old_friends", 628, 210, 2, 2), ("rich_steady", 720, 720, 0, 0),
    ("new_fad", 402, 162, 1, 2),
])
def test_reviewed_seven_scenarios_use_production_algorithms_deterministically(name, messages, sends, signature_count, qualified_count):
    rows = reviewed_scenarios()[name]
    index = indexed(rows)
    assert (index.message_count, index.send_count) == (messages, sends)
    result = discover(rows)
    assert sum(s.is_selected_signature for s in result.signatures) == signature_count
    assert len(result.signatures) == qualified_count  # Keep alternatives, not just the chosen one.
    assert result == discover(rows)
    if name == "daily":
        assert any(a.lag_days == 14 and a.identity_key == "fiction:penguin" for a in result.adoptions)
    elif name == "old_friends":
        assert any(r.gap_days == 217 and r.active_message_count == 139 for r in result.reunions)
    elif name == "new_fad":
        assert any(t.current.send_count == 100 and t.earlier_send_count == 2 for t in result.trends)
    elif name in {"fighters", "short", "rich_steady"}:
        assert not (result.adoptions or result.reunions or result.trends)
