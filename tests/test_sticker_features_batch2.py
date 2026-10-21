"""Independent fictional evidence for the three second-batch discoveries."""
from dataclasses import replace
import hashlib
from itertools import combinations
import json

import pytest

from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
from qq_chat_analyzer.analysis.sticker_index import build_sticker_fact_index
from qq_chat_analyzer.analysis.stickers import (
    StickerData, StickerMedia, collect_sticker_sends, count_sticker_messages,
)
from qq_chat_analyzer.rich_message import SenderIdentity, TextContent
from sticker_feature_samples import Messages


def facts(rows, *, positions=True, media=()):
    data = StickerData(collect_sticker_sends(rows), media=media,
                       message_counts=count_sticker_messages(rows))
    return build_sticker_fact_index(data, rows, source_positions=(
        range(len(rows)) if positions is True else None if positions is False else positions
    ))


def short_relay():
    # New scene: two days, 14 messages. Three opening/closing text messages
    # belong to sticker turns, while the following day's text stays outside.
    b = Messages("batch2-short", "2025-08-01")
    b.add(0, "A", text="虚构：用图回答今天的心情", seconds=0)
    b.add(0, "A", text="我先来", seconds=5)
    for i in range(8):
        b.add(0, "A" if i % 2 == 0 else "B", f"心情{i % 3}", seconds=10+i*20)
    b.add(0, "B", text="好了，该吃饭了", seconds=160)
    b.add(1, "A", text="午饭吃什么", seconds=0)
    b.add(1, "B", text="虚构面条", seconds=30)
    b.add(1, "A", text="好", seconds=60)
    return b.ordered()


def style_rows(a_counts, b_counts):
    b = Messages("batch2-style")
    for side, counts in (("A", a_counts), ("B", b_counts)):
        for k, count in enumerate(counts):
            for i in range(count):
                b.add((k+i) % 2, side, f"素材{k}", seconds=k*200+i*2+(side == "B"))
    return b.ordered()


def combined_scene():
    """Seven findings coexist, deliberately sharing one material/event."""
    b = Messages("batch2-seven", "2025-01-01")
    for day in (0, 7, 14, 21):
        b.add(day, "A", "打卡海豹")
    for day in (25, 30, 35, 40, 50):
        b.add(day, "A", text=f"虚构日常：今天是第{day}天")
        if day in (30, 35, 40):
            for i in range(30):
                b.add(day, "A", f"配角{day}-{i}", seconds=100+i*2)
        b.add(day, "B", text=f"虚构回复：第{day}天记下了", seconds=200)
    b.add(69, "B", text="虚构：明天再来接图")
    for i in range(8):
        b.add(70, "A" if i % 2 == 0 else "B", "打卡海豹", seconds=i*20)
    for day in (71, 72):
        b.add(day, "A", "打卡海豹")
        b.add(day, "B", "打卡海豹", seconds=20)
    b.add(73, "B", *("打卡海豹",)*4)
    return b.ordered()


def test_eight_turns_keep_the_actual_fourteen_message_scene_and_text():
    rows = short_relay()
    result = analyze_private_stickers(facts(rows))
    assert len(rows) == 14
    assert hasattr(result, "relays"), "second batch must expose relay evidence"
    relay, = result.relays
    assert relay.turn_count == 8
    assert (relay.self_send_count, relay.peer_send_count) == (4, 4)
    assert (relay.start_ordinal, relay.end_ordinal) == (0, 11)  # Half-open.
    assert relay.end_epoch_seconds-relay.start_epoch_seconds == 160
    refs = [m for turn in relay.turns for m in turn.messages]
    assert [m.ordinal for m in refs] == list(range(11))
    assert all(m.message is rows[m.ordinal] for m in refs)
    assert refs[0].message.contents == (TextContent("虚构：用图回答今天的心情"),)
    assert {s.occurrence_id for m in refs for s in m.sends} == {f"{i}:0" for i in range(2, 10)}
    assert {x.identity_key for x in relay.materials} == {f"fiction:心情{i}" for i in range(3)}
    common = next(x for x in relay.materials if x.identity_key == "fiction:心情0")
    assert (common.self_send_count, common.peer_send_count) == (2, 1)
    assert result.rule_version == "private-stickers.v1.1-batch2"


def test_shared_habit_is_repeated_cross_day_use_with_an_adoption_link():
    b = Messages("batch2-common")
    for side, days in (("A", (0, 2, 4)), ("B", (1, 3, 5))):
        for day in days:
            b.add(day, side, "早安水獭", "早安水獭")
    # Merely shared once: stays on the ordinary shared board, not a habit.
    b.add(6, "A", "擦肩图")
    b.add(6, "B", "擦肩图", seconds=20)
    result = analyze_private_stickers(facts(b.ordered()))
    assert hasattr(result, "shared_habits"), "second batch must expose shared habits"
    shared, = result.shared_habits
    assert shared.identity_key == "fiction:早安水獭"
    assert [(u.send_count, u.date_count, u.known_send_count) for u in shared.members] == [(6, 3, 7)]*2
    assert all(u.share == pytest.approx(6/7) for u in shared.members)
    assert [(u.first_date, u.last_date) for u in shared.members] == [
        ("2025-01-01", "2025-01-05"), ("2025-01-02", "2025-01-06")]
    assert shared.adoption is result.adoptions[0]


def test_style_at_equal_volume_has_a_clear_contrast():
    result = analyze_private_stickers(facts(style_rows([2]*20, [40])))
    assert hasattr(result, "styles"), "second batch must expose equal-volume style comparisons"
    style, = result.styles
    assert style.sample_size == 40
    assert style.richer.sender_id == "fiction-A"
    assert (style.richer.expected_unique_count, style.concentrated.expected_unique_count) == (20, 1)
    assert (style.richer.d2, style.concentrated.d2) == (20, 1)
    assert style.claim == "known_materials_only"


def test_rarefaction_matches_exhaustive_sampling_of_a_small_multiset():
    # This oracle enumerates combinations, independently of the production product.
    from qq_chat_analyzer.analysis import sticker_features
    expected = sum(len(set(x)) for x in combinations("aaabbc", 3))/20
    assert hasattr(sticker_features, "expected_sticker_richness")
    assert sticker_features.expected_sticker_richness((3, 2, 1), 3) == pytest.approx(expected)


def test_single_author_burst_is_one_turn_and_unknown_materials_are_not_merged():
    b = Messages()
    for i in range(10):
        b.add(0, "A", None, seconds=i)
    b.add(0, "B", "reply", seconds=20)
    rows = b.ordered()
    assert not analyze_private_stickers(facts(rows)).relays
    b.add(0, "A", None, seconds=30)
    b.add(0, "B", "different", seconds=40)
    relay, = analyze_private_stickers(facts(b.ordered())).relays
    assert relay.turn_count == 4
    assert (relay.self_send_count, relay.peer_send_count, relay.unknown_identity_count) == (11, 2, 11)
    assert len(relay.turns[0].messages) == 10
    assert len(relay.media_keys) == 13  # Unknowns retain distinct occurrence media refs.
    assert len(relay.materials) == 2


@pytest.mark.parametrize("damage", ["text_turn", "unknown_sender", "unknown_time", "tie", "reversal", "gap", "long_pause"])
def test_relay_cannot_join_across_untrusted_or_non_sticker_turns(damage):
    b = Messages()
    for i in range(4):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=i*40)
    rows = list(b.ordered())
    positions = True
    if damage == "text_turn":
        rows.insert(1, replace(rows[1], contents=(TextContent("纯文字打断"),), timestamp=rows[0].timestamp+10))
        rows.insert(2, replace(rows[0], contents=(TextContent("文字回应"),), timestamp=rows[0].timestamp+20))
    elif damage == "unknown_sender":
        rows[1] = replace(rows[1], sender=SenderIdentity(None, "同名"), is_self=None)
    elif damage == "unknown_time":
        rows[1] = replace(rows[1], timestamp="unknown")
    elif damage == "tie":
        rows[1] = replace(rows[1], timestamp=rows[0].timestamp)
    elif damage == "reversal":
        rows[1] = replace(rows[1], timestamp=rows[0].timestamp-1)
    elif damage == "gap":
        positions = (0, 1, 3, 4)
    else:
        rows[2:] = [replace(m, timestamp=m.timestamp+121) for m in rows[2:]]
    assert not analyze_private_stickers(facts(tuple(rows), positions=positions)).relays


def test_relay_keeps_all_maximal_windows_and_inclusive_time_limits():
    b = Messages()
    for i in range(8):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=i*100)
    relays = analyze_private_stickers(facts(b.ordered())).relays
    assert [(x.start_ordinal, x.end_ordinal, x.turn_count) for x in relays] == [(0, 7, 7), (1, 8, 7)]
    assert all(x.end_epoch_seconds-x.start_epoch_seconds == 600 for x in relays)
    b = Messages()
    for day in range(5):
        for i in range(4):
            b.add(day, "A" if i % 2 == 0 else "B", f"day{day}", seconds=i*120)
    assert len(analyze_private_stickers(facts(b.ordered())).relays) == 5


def test_relay_cannot_trim_a_long_author_turn_to_invent_a_short_chain():
    b = Messages()
    b.add(0, "A", text="很久以前的开场")
    for i in range(4):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=1000+i*20)
    assert not analyze_private_stickers(facts(b.ordered())).relays
    assert not analyze_private_stickers(facts(short_relay(), positions=False)).relays


def test_relay_resumes_after_a_barrier_without_discarding_later_valid_events():
    b = Messages()
    b.add(0, None, "same")
    for i in range(4):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=10+i*20)
    rows = b.ordered()
    relay, = analyze_private_stickers(facts(rows, positions=(0, 2, 3, 4, 5))).relays
    assert (relay.start_ordinal, relay.end_ordinal) == (1, 5)
    assert relay.start_barrier_reasons == ("filtered_or_unpaired_gap",)


@pytest.mark.parametrize("case", ["once", "single_day", "low_share"])
def test_shared_board_membership_does_not_imply_a_shared_habit(case):
    b = Messages()
    for side in ("A", "B"):
        for i in range(1 if case == "once" else 3):
            b.add(0 if case == "single_day" else i, side, "common", seconds=i*10+(side == "B"))
        if case == "low_share":
            b.add(4, side, *[f"tail{i}" for i in range(28)])
    index = facts(b.ordered())
    assert index.report.shared_ranking(index.side_members)
    assert not analyze_private_stickers(index).shared_habits


def test_shared_habits_keep_more_than_three_candidates_in_the_designed_order():
    b = Messages()
    keys = tuple(f"shared{i}" for i in range(5))
    for side in ("A", "B"):
        for day in range(3):
            b.add(day, side, *keys, seconds=(side == "B"))
    result = analyze_private_stickers(facts(b.ordered()))
    assert [x.identity_key for x in result.shared_habits] == [f"fiction:{k}" for k in keys]


def test_undated_known_sends_remain_in_the_shared_denominator():
    b = Messages()
    for side in ("A", "B"):
        for day in range(3):
            b.add(day, side, "common", seconds=(side == "B"))
    rows = b.ordered()
    extra = replace(rows[0], timestamp="unknown", contents=(
        replace(rows[0].contents[0], sticker=replace(rows[0].contents[0].sticker, identity_key="fiction:tail")),)*28)
    assert not analyze_private_stickers(facts((*rows, extra))).shared_habits
    # Known same-material sends with unknown dates count, without inventing dates.
    extra = replace(rows[0], timestamp="unknown")
    shared, = analyze_private_stickers(facts((*rows, extra))).shared_habits
    assert (shared.members[0].send_count, shared.members[0].date_count) == (4, 3)
    assert shared.members[0].has_unknown_time


@pytest.mark.parametrize("a,b", [([180]*30, [18, 2]), ([12]*30, [18, 2]), ([1]*30, [15, 15]), ([20]*30, [150])])
def test_style_corrects_large_volume_imbalance_and_one_or_two_material_concentration(a, b):
    style, = analyze_private_stickers(facts(style_rows(a, b))).styles
    assert style.sample_size == min(100, sum(a), sum(b))
    assert style.richer.raw_unique_count == 30
    assert style.concentrated.raw_unique_count <= 2
    assert style.richer.expected_unique_count >= 1.8*style.concentrated.expected_unique_count
    assert style.richer.expected_unique_count-style.concentrated.expected_unique_count >= 3
    assert style.richer.d2 >= 1.5*style.concentrated.d2


@pytest.mark.parametrize("a,b", [([15, 5], [180, 60]), ([2]*30, [2]*30), ([20, 10, 5], [35]), ([9], [10]), ([10], [10]), ([80]+[1]*20, [20]*5)])
def test_styles_omit_scaled_proportions_similar_repertoires_boring_and_low_samples(a, b):
    assert not analyze_private_stickers(facts(style_rows(a, b))).styles


def test_style_does_not_attribute_missing_materials_or_unknown_senders():
    rows = style_rows([2]*20, [40])
    unknown = replace(rows[0], contents=(replace(rows[0].contents[0], sticker=replace(
        rows[0].contents[0].sticker, identity_key=None)),)*100)
    unassigned = replace(rows[0], sender=SenderIdentity(None, "未知"), is_self=None)
    style, = analyze_private_stickers(facts((*rows, unknown, unassigned))).styles
    assert style.richer.known_send_count == 40
    assert style.richer.unknown_identity_send_count == 100
    assert style.unattributed_send_count == 1
    assert style.claim == "known_materials_only"
    # 100 unidentifiable stickers cannot satisfy a 10-known-send sample floor.
    assert not analyze_private_stickers(facts((*style_rows([2, 2], [40]), unknown))).styles


def test_style_needs_two_actual_usage_days_and_counts_undated_known_sends():
    rows = style_rows([2]*20, [40])
    single_day = tuple(replace(m, timestamp=rows[0].timestamp+i) for i, m in enumerate(rows))
    assert not analyze_private_stickers(facts(single_day)).styles
    extra = replace(rows[0], timestamp="unknown")
    style, = analyze_private_stickers(facts((*rows, extra))).styles
    assert style.richer.known_send_count == 41
    assert style.richer.date_count == 2


def test_text_only_days_do_not_satisfy_the_style_sticker_day_floor():
    rows = style_rows([2]*20, [40])
    one_sticker_day = tuple(replace(m, timestamp=rows[0].timestamp+i) for i, m in enumerate(rows))
    b = Messages("batch2-style")
    b.add(1, "A", text="第二天只有文字")
    b.add(1, "B", text="没有贴图的回复", seconds=20)
    assert not analyze_private_stickers(facts((*one_sticker_day, *b.ordered()))).styles


def test_text_only_days_do_not_satisfy_the_reunion_other_sticker_day_floor():
    # The same index defect must not invent cross-day other-sticker activity
    # during a reunion interval either. Two text messages cannot meet M>=20.
    b = Messages()
    for day in (0, 2, 4, 60):
        b.add(day, "A", "old")
    b.add(0, "B", text="朋友")
    b.add(10, "A", "other", "other", "other")
    b.add(20, "A", text="这天没有发图")
    assert not analyze_private_stickers(facts(b.ordered())).reunions


def test_second_batch_uses_private_identity_and_is_independent_of_media_success():
    rows = short_relay()
    initial = analyze_private_stickers(facts(rows))
    assert analyze_private_stickers(facts(rows, media=(StickerMedia("fiction:心情0", "failed"),))) == initial
    for changed in (tuple(replace(m, conversation_type="group") for m in rows),
                    tuple(replace(m, is_self=None) for m in rows)):
        f = analyze_private_stickers(facts(changed))
        assert not (f.relays or f.shared_habits or f.styles)


def test_all_seven_algorithms_keep_linkable_overlapping_stories_in_one_chat():
    result = analyze_private_stickers(facts(combined_scene()))
    assert all((result.signatures, result.adoptions, result.reunions, result.trends,
                result.relays, result.shared_habits, result.styles))
    shared, = result.shared_habits
    assert shared.adoption in result.adoptions
    assert shared.identity_key == "fiction:打卡海豹"
    assert result.relays[0].materials[0].identity_key == shared.identity_key
    assert any(s.habit.identity_key == shared.identity_key for s in result.signatures)
    assert any(r.identity_key == shared.identity_key for r in result.reunions)
    assert any(t.identity_key == shared.identity_key for t in result.trends)
    assert [(u.send_count, u.known_send_count) for u in shared.members] == [(10, 100), (10, 10)]
    assert result.relays[0].turn_count == 8
    assert result.reunions[0].gap_days == 49


@pytest.mark.parametrize("counts,m,expected", [((100,), 10, 1), ((1,)*10, 10, 10), ((3, 1), 2, 1.5), ((3, 1), 0, 0)])
def test_rarefaction_handles_single_material_full_and_empty_samples(counts, m, expected):
    from qq_chat_analyzer.analysis.sticker_features import expected_sticker_richness
    assert expected_sticker_richness(counts, m) == expected


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("group", [False, True])
def test_second_batch_runs_through_real_adapters_and_service_without_exporting_private_evidence(tmp_path, source, group):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from test_qq_db_rich_contents import _body, _sticker, _text
    from test_sticker_data import _private_payload

    rows = combined_scene()
    if source == "qq":
        bodies = [_body(*(_text(p.text) if isinstance(p, TextContent) else
                           _sticker(p.sticker.identity_key.encode()) for p in m.contents)) for m in rows]
        payload = _private_payload(*bodies, senders=tuple("10001" if m.is_self else "20002" for m in rows))
        payload["self"] = {"namespace": "qq_uin", "value": "10001"}
        if group:
            payload["query"]["session_type"] = "group"
        for record, row in zip(payload["records"], rows):
            record["fields"]["40050"] = row.timestamp
    else:
        records = []
        for row in rows:
            if isinstance(row.contents[0], TextContent):
                kind, content = 1, row.contents[0].text
            else:
                # WeChat type 47 carries one sticker per message in this adapter.
                # Separate occurrences retain the original authors and unique seconds.
                for i, part in enumerate(row.contents):
                    digest = hashlib.md5(part.sticker.identity_key.encode()).hexdigest()
                    records.append(dict(local_type=47, server_id="duplicate", create_time=row.timestamp+i,
                                        user_name="fiction-self" if row.is_self else "fiction-peer",
                                        message_content=f'<msg><emoji md5="{digest}"/></msg>'))
                continue
            records.append(dict(local_type=kind, server_id="duplicate", create_time=row.timestamp,
                                user_name="fiction-self" if row.is_self else "fiction-peer", message_content=content))
        payload = dict(source="wechat-db", conversation=dict(username="fiction-room",
                       session_type="group" if group else "private", self_username="fiction-self"), messages=records)
    path = tmp_path/"fictional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=tmp_path/"out", stopwords_path=stopwords,
    ))
    f = result.reports.private_stickers
    assert result.stickers.sends
    assert result.reports.stickers[0].total_send_count == 110
    if group:
        assert f is None
    else:
        assert f.available and f.relays and f.shared_habits and f.styles
        assert f.relays[0].turn_count == 8
        assert f.styles[0].sample_size == 10
        assert [(u.send_count, u.known_send_count) for u in f.shared_habits[0].members] == [(10, 100), (10, 10)]
    exported = (tmp_path/"out"/"echo-report.json").read_text(encoding="utf-8")
    for private_field in ("start_ordinal", "occurrence_id", "shared_habits", "known_materials_only", "barrier_reasons"):
        assert private_field not in exported


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_formal_quality_filter_leaves_a_relay_barrier(tmp_path, source):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from test_qq_db_rich_contents import _body, _sticker, _text
    from test_sticker_data import _private_payload

    start = 1750000000
    if source == "qq":
        payload = _private_payload(_body(_sticker()), _body(_sticker()),
                                   _body(_text("Filtered " + "x"*110)), _body(_sticker()), _body(_sticker()),
                                   senders=("10001", "20002", "10001", "10001", "20002"))
        payload["self"] = {"namespace": "qq_uin", "value": "10001"}
        for i, record in enumerate(payload["records"]):
            record["fields"]["40050"] = start+i*20
    else:
        records = [dict(local_type=1 if i == 2 else 47, server_id="duplicate", create_time=start+i*20,
                        user_name="fiction-self" if i in (0, 2, 3) else "fiction-peer",
                        message_content="Filtered " + "x"*110 if i == 2 else '<msg><emoji md5="' + 'ab'*16 + '"/></msg>')
                   for i in range(5)]
        payload = dict(source="wechat-db", conversation=dict(username="fiction-room", session_type="private",
                       self_username="fiction-self"), messages=records)
    path = tmp_path/"fictional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=tmp_path/"out", stopwords_path=stopwords, export_echo_report=False))
    assert result.diagnostic_counts.analyzed_message_count == 4
    assert "known_filter_gaps" in result.reports.private_stickers.qualifiers
    assert not result.reports.private_stickers.relays
