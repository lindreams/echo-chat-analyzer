"""Independent fictional evidence for the three second-batch discoveries."""
from dataclasses import replace
import hashlib
from itertools import combinations
import json

import pytest

from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
from qq_chat_analyzer.analysis.stickers import (
    StickerData, StickerMedia, collect_sticker_sends,
)
from qq_chat_analyzer.rich_message import SenderIdentity, TextContent
from sticker_feature_samples import Messages, formal_payload, indexed


def facts(rows, *, positions=True, media=()):
    return indexed(rows, media=media, positions=(
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
    moment, = result.stories.moments
    assert (moment.core_start, moment.core_end) == (2, 10)
    assert (moment.context_start, moment.context_end) == (0, 11)
    assert moment.dense_exchange
    assert all(m.message is rows[m.ordinal] for m in moment.messages)
    assert "context_time_gap" in moment.qualifiers


def test_shared_habit_is_repeated_cross_day_use_with_an_adoption_link():
    b = Messages("batch2-common")
    for side, days in (("A", (0, 2, 4)), ("B", (1, 3, 5))):
        for day in days:
            b.add(day, side, "早安水獭", "早安水獭")
    # Merely shared once: stays on the ordinary shared board, not a habit.
    b.add(6, "A", "擦肩图")
    b.add(6, "B", "擦肩图", seconds=20)
    result = analyze_private_stickers(facts(b.ordered()))
    shared, = result.shared_habits
    assert shared.identity_key == "fiction:早安水獭"
    assert [(u.send_count, u.date_count, u.known_send_count) for u in shared.members] == [(6, 3, 7)]*2
    assert all(u.share == pytest.approx(6/7) for u in shared.members)
    assert [(u.first_date, u.last_date) for u in shared.members] == [
        ("2025-01-01", "2025-01-05"), ("2025-01-02", "2025-01-06")]
    assert shared.adoption is result.adoptions[0]


def test_style_at_equal_volume_has_a_clear_contrast():
    result = analyze_private_stickers(facts(style_rows([2]*20, [40])))
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
    assert sticker_features.expected_sticker_richness((3, 2, 1), 3) == pytest.approx(expected)


def test_single_author_burst_is_one_turn_and_unknown_materials_are_not_merged():
    b = Messages()
    for i in range(10):
        b.add(0, "A", None, seconds=i)
    b.add(0, "B", "reply", seconds=20)
    rows = b.ordered()
    result = analyze_private_stickers(facts(rows))
    assert not result.relays and not result.stories.moments
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
    # The same gap across the actual 30-minute session boundary starts a fresh
    # author round; old text must not swallow a genuine later four-turn relay.
    rows = list(b.ordered())
    rows[0] = replace(rows[0], timestamp=rows[1].timestamp-3600)
    relay, = analyze_private_stickers(facts(rows)).relays
    assert (relay.start_ordinal, relay.end_ordinal, relay.turn_count) == (1, 5, 4)
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


def test_all_seven_algorithms_keep_linkable_overlapping_stories_in_one_chat():
    rows = combined_scene()
    result = analyze_private_stickers(facts(rows))
    assert analyze_private_stickers(facts(rows, media=(StickerMedia("fiction:打卡海豹", "failed"),))) == result
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
    selection = result.stories
    assert len(selection.candidates) == 2
    material = next(s for s in selection.candidates if s.kind == "material")
    assert {name for name, _ in material.findings} == {
        "signatures", "adoptions", "reunions", "trends", "shared_habits", "relays"}
    moment, = selection.moments
    assert moment.event_id in material.event_ids
    assert {name for _, _, name, _ in material.timeline} == {"adoptions", "reunions", "trends", "relays"}
    assert material.timeline == tuple(sorted(material.timeline))
    assert moment.shared_identity_keys == (shared.identity_key,)
    assert material.story_id in selection.featured_ids


@pytest.mark.parametrize("counts,m,expected", [((100,), 10, 1), ((1,)*10, 10, 10), ((3, 1), 2, 1.5), ((3, 1), 0, 0)])
def test_rarefaction_handles_single_material_full_and_empty_samples(counts, m, expected):
    from qq_chat_analyzer.analysis.sticker_features import expected_sticker_richness
    assert expected_sticker_richness(counts, m) == expected


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("group", [False, True])
def test_private_features_reach_real_adapters_without_exporting_evidence(tmp_path, source, group):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    payload = formal_payload(combined_scene(), source, group=group)
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
        assert f.stories.featured_ids and f.stories.moments
        assert [(u.send_count, u.known_send_count) for u in f.shared_habits[0].members] == [(10, 100), (10, 10)]
    assert all(m.status not in {"available", "preview"} for m in result.stickers.media)
    exported = (tmp_path/"out"/"echo-report.json").read_text(encoding="utf-8")
    for private_field in ("start_ordinal", "occurrence_id", "shared_habits", "known_materials_only", "barrier_reasons",
                          "featured_ids", "core_start", "虚构日常"):
        assert private_field not in exported
    normalized = json.dumps(json.loads(exported), ensure_ascii=False)
    html = (tmp_path/"out"/"echo-report.html").read_text(encoding="utf-8")
    for private_value in ("featured_ids", "core_start", "虚构日常：今天是第25天"):
        assert private_value not in normalized and private_value not in html


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_formal_quality_filter_leaves_a_relay_barrier(tmp_path, source):
    from qq_chat_analyzer.application import AnalysisRequestDTO
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService

    b = Messages("formal-filter")
    b.add(0, "A", "same")
    b.add(1, "B", text="Filtered " + "x"*110)
    b.add(3, "B", "same")
    b.add(4, "B", "same", "same")
    for i in range(4):
        b.add(5, "A" if i % 2 == 0 else "B", "same", seconds=i*20)
    b.add(5, "A", text="Filtered " + "x"*110, seconds=30)
    payload = formal_payload(b.ordered(), source)
    path = tmp_path/"fictional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path/"stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=tmp_path/"out", stopwords_path=stopwords, export_echo_report=False))
    assert result.diagnostic_counts.analyzed_message_count == (7 if source == "qq" else 8)
    assert "known_filter_gaps" in result.reports.private_stickers.qualifiers
    assert not result.reports.private_stickers.relays
    assert not result.reports.private_stickers.adoptions


def test_stories_keep_separate_returns_years_apart_without_history_bridging():
    b = Messages("batch3-years")
    for day in (0, 2, 4, 100, 102, 104, 800):
        b.add(day, "A", "old")
    b.add(0, "B", text="虚构朋友", seconds=1)
    for day in (20, 40, 200, 300):
        b.add(day, "A", "other", "other", "other")
    f = analyze_private_stickers(facts(b.ordered()))
    assert sum(r.identity_key == "fiction:old" for r in f.reunions) == 2
    returns = [s for s in f.stories.candidates if "fiction:old" in s.identity_keys
               and any(n == "reunions" for n, _ in s.findings)]
    assert len(returns) == 2
    assert returns[0].end_date < returns[1].start_date
    assert sum(n == "signatures" for s in returns for n, _ in s.findings) <= 1
    assert all(s.story_id in f.stories.featured_ids for s in returns)


def test_independent_high_interest_returns_remain_available_after_featured_cap():
    from qq_chat_analyzer.analysis.sticker_stories import select_additional_sticker_stories

    b = Messages("independent-long-returns")
    for k, returned in enumerate((200, 400, 600, 800)):
        for day in (0, 2, 4, returned):
            b.add(day, "A", f"old{k}", seconds=k*10)
    for day in (20, 40, 60):
        b.add(day, "A", "background")
    b.add(0, "B", text="fictional friend", seconds=900)
    f = analyze_private_stickers(facts(b.ordered()))
    assert len(f.reunions) == len(f.stories.candidates) == 4
    featured = [s for sid in f.stories.featured_ids for s in f.stories.candidates if s.story_id == sid]
    assert [f.reunions[i].gap_days for s in featured for name, i in s.findings if name == "reunions"] == [796, 596, 396]
    extra, = select_additional_sticker_stories(f)
    assert extra.interest_level == 3 and extra.lead_finding == "reunions"
    assert [f.reunions[i].gap_days for name, i in extra.findings if name == "reunions"] == [196]
    assert extra.story_id not in f.stories.featured_ids
    assert dict(f.stories.diagnostic_counts)["stories.reject_cap"] == 1  # Main shortlist only.
    assert select_additional_sticker_stories(replace(f, stories=type(f.stories)())) == ()
    # A high-interest near-repeat must not be revived as another extra.
    for day in (0, 2, 4, 201):
        b.add(day, "A", "nearby-return", seconds=200)
    extended = analyze_private_stickers(facts(b.ordered()))
    extra, = select_additional_sticker_stories(extended)
    assert [extended.reunions[i].gap_days for name, i in extra.findings if name == "reunions"] == [197]


@pytest.mark.parametrize("damage", ["gap", "unknown_sender", "unknown_time"])
def test_moment_context_stops_at_untrusted_neighbor_and_reports_it(damage):
    rows = list(short_relay())
    # Damage the opening context, leaving eight trusted sticker turns intact.
    positions = list(range(len(rows)))
    if damage == "gap":
        positions = [p if p < 2 else p+1 for p in positions]
    elif damage == "unknown_sender":
        rows[1] = replace(rows[1], sender=SenderIdentity(None, "未知"), is_self=None)
    else:
        rows[1] = replace(rows[1], timestamp="unknown")
    moment, = analyze_private_stickers(facts(rows, positions=positions)).stories.moments
    assert moment.context_start == 2
    assert moment.context_end == 11
    assert any(q.startswith("context_barrier:") for q in moment.qualifiers)
    assert moment.messages[0].message is rows[2]


def test_selection_keeps_all_candidates_and_promotes_a_later_stronger_event():
    b = Messages("batch3-interest")
    for day in range(6):
        for i in range(12 if day == 5 else 4):
            b.add(day, "A" if i % 2 == 0 else "B", f"图{day}-{i}", seconds=i*15)
    f = analyze_private_stickers(facts(b.ordered()))
    assert len(f.relays) == 6
    assert len(f.stories.candidates) == 6
    assert len(f.stories.featured_ids) == 3
    best = next(s for s in f.stories.candidates if s.story_id == f.stories.featured_ids[0])
    assert best.event_ids == (f.stories.moments[0].event_id,)
    assert len(f.stories.moments[0].messages) == 12
    assert "alternating_turns:12" in best.interest_reasons
    from qq_chat_analyzer.analysis.sticker_stories import select_additional_sticker_stories
    assert not select_additional_sticker_stories(f)  # Remaining four-turn relays are ordinary.
    # A vivid 60-turn exchange should not lose simply because a reunion uses
    # days (200) as its unit. Both have the same editorial interest level.
    for i in range(60):
        b.add(6, "A" if i % 2 == 0 else "B", f"快接{i}", seconds=i)
    for day in (0, 2, 4, 204):
        b.add(day, "A", "old", seconds=1000)
    for day in (20, 40):
        b.add(day, "A", "other", "other", seconds=1000)
    f = analyze_private_stickers(facts(b.ordered()))
    assert any(r.gap_days == 200 for r in f.reunions)
    best = next(s for s in f.stories.candidates if s.story_id == f.stories.featured_ids[0])
    assert "alternating_turns:60" in best.interest_reasons


def test_repeated_adoptions_leave_room_for_a_qualified_sparse_shared_habit():
    b = Messages("selection-adoptions")
    for key in ("adopted-a", "adopted-b"):
        b.add(0, "A", key)
        for day in (15, 16, 17):
            b.add(day, "B", key)
    for day in (0, 7, 14, 365):
        b.add(day, "A", "signature", seconds=300)
    for day, keys in ((0, ("shared", "shared")), (2, ("shared",))):
        b.add(day, "A", *keys, seconds=600)
        b.add(day, "B", *keys, seconds=900)
    rows = b.ordered()
    index = facts(rows)
    f = analyze_private_stickers(index)
    assert len(f.adoptions) == 2 and len(f.shared_habits) == 1
    selected = [s for sid in f.stories.featured_ids for s in f.stories.candidates if s.story_id == sid]
    assert len(selected) == 3
    assert sum(any(n == "adoptions" for n, _ in s.findings) for s in selected) == 1
    assert any(n == "shared_habits" for s in selected for n, _ in s.findings)
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.presentation import build_echo_report_view
    view = build_echo_report_view(AnalysisReports(stickers=(index.report,), private_stickers=f),
                                  conversation_kind="private")
    assert {m.findings[0].kind for m in view.stickers.memories} == {"signature", "adoption", "shared"}


def test_independent_adoption_intervals_survive_cross_material_deduplication():
    b = Messages("adoption-horizons")
    for key, first, later in (("short", 0, 10), ("long", 0, 210), ("later", 100, 110), ("repeat", 0, 11)):
        b.add(first, "A", key)
        for day in (later, later+1, later+2):
            b.add(day, "B", key)
    f = analyze_private_stickers(facts(b.ordered()))
    assert len(f.adoptions) == len(f.stories.candidates) == 4
    selected = [s for s in f.stories.candidates if s.story_id in f.stories.featured_ids]
    assert len(selected) == 3
    assert sorted(f.adoptions[i].lag_days for s in selected for name, i in s.findings if name == "adoptions") == [10, 11, 210]
    # The 10/11-day events near the start compete for one slot; another ten-day
    # event months later and the seven-month interval remain independent.
    assert sum("fiction:later" in s.identity_keys for s in selected) == 1
    counts = dict(f.diagnostic_counts)
    assert counts["stories.reject_repeat"] == 1 and counts["stories.reject_cap"] == 0
    from qq_chat_analyzer.analysis.sticker_stories import select_additional_sticker_stories
    assert not select_additional_sticker_stories(f)
    for name in ("adoptions", "reunions", "trends", "signatures", "relays", "shared_habits", "styles"):
        assert counts[name+".raw"] == counts[name+".qualified"] + sum(
            value for key, value in counts.items() if key.startswith(name+".reject_"))


def test_large_trends_do_not_displace_distinct_interaction_and_shared_stories():
    b = Messages("selection-trends")
    for day in range(21):
        b.add(day, "A", *((f"phase{day//7}",)*3))
    for i in range(8):
        b.add(21, "A" if i % 2 == 0 else "B", f"reply{i}", seconds=i*20)
    for day in (23, 25):
        b.add(day, "A", *(("shared",)*4))
        b.add(day, "B", *(("shared",)*4), seconds=300)
    index = facts(b.ordered())
    f = analyze_private_stickers(index)
    assert len(f.trends) >= 3 and f.relays and f.shared_habits
    selected = [s for sid in f.stories.featured_ids for s in f.stories.candidates if s.story_id == sid]
    assert {n for s in selected for n, _ in s.findings} >= {"trends", "relays", "shared_habits"}
    # Full candidates and separate events remain available for local inspection.
    assert {i for s in f.stories.candidates for n, i in s.findings if n == "trends"} == set(range(len(f.trends)))
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.presentation import build_echo_report_view
    view = build_echo_report_view(AnalysisReports(stickers=(index.report,), private_stickers=f),
                                  conversation_kind="private")
    assert [m.findings[0].kind for m in view.stickers.memories if not m.compact] == ["trend", "relay", "shared"]


def test_overlapping_relays_share_one_event_without_building_an_unbounded_core():
    b = Messages("batch3-overlap")
    for i in range(45):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=i*30)
    f = analyze_private_stickers(facts(b.ordered()))
    assert len(f.relays) > 1
    moment, = f.stories.moments
    assert len(moment.relay_indices) == len(f.relays)
    assert moment.core_end-moment.core_start <= 21
    assert "bounded_representative_of_overlapping_relays" in moment.qualifiers
    assert sum(n == "relays" for s in f.stories.candidates for n, _ in s.findings) == len(f.relays)


def test_context_adds_one_whole_author_round_on_each_side_only():
    b = Messages("batch3-context")
    for seconds, side in ((0, "A"), (1, "B"), (2, "B")):
        b.add(0, side, text="虚构开场", seconds=seconds)
    for i in range(8):
        b.add(0, "A" if i % 2 == 0 else "B", "same", seconds=10+i*20)
    for seconds, side in ((160, "A"), (161, "A"), (170, "B")):
        b.add(0, side, text="虚构收尾", seconds=seconds)
    rows = b.ordered()
    moment, = analyze_private_stickers(facts(rows)).stories.moments
    assert (moment.core_start, moment.core_end) == (3, 11)
    assert (moment.context_start, moment.context_end) == (1, 13)
    assert [m.message for m in moment.messages] == list(rows[1:13])


def test_same_image_moment_requires_alternating_uses_of_that_image():
    b = Messages("batch3-same-image")
    for i in range(8):
        b.add(0, "A" if i % 2 == 0 else "B", "same" if i in (0, 2, 5, 7) else f"other{i}", seconds=i*20)
    moment, = analyze_private_stickers(facts(b.ordered())).stories.moments
    assert moment.dense_exchange
    assert not moment.shared_identity_keys  # A,A then B,B is not four alternating replies.


@pytest.mark.slow_integration
def test_local_preview_rejects_equal_sends_from_another_analysis(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from qq_chat_analyzer.presentation.sticker_moment_preview import create_local_moment_preview

    app = QApplication.instance() or QApplication([])
    rows = short_relay()
    features = analyze_private_stickers(facts(rows))
    moment, = features.stories.moments
    foreign = StickerData(collect_sticker_sends(rows))  # Equal values, different run objects.
    with pytest.raises(ValueError, match="same analysis"):
        dialog = create_local_moment_preview(moment, foreign, features=features)
        dialog.close()
        app.processEvents()
    own = StickerData(tuple(s for row in moment.messages for s in row.sends))
    replaced_row = replace(moment.messages[0], message=replace(rows[0], contents=(TextContent("替换的虚构正文"),)))
    replaced_moment = replace(moment, messages=(replaced_row, *moment.messages[1:]))
    with pytest.raises(ValueError, match="same analysis"):
        create_local_moment_preview(replaced_moment, own, features=features)
    b = Messages("preview-content-budget")
    for i in range(4):
        b.add(0, "A" if i % 2 == 0 else "B", *(("same",)*257 if i == 0 else ("same",)), seconds=i*20)
    index = facts(b.ordered())
    features = analyze_private_stickers(index)
    moment, = features.stories.moments
    data = StickerData(tuple(s for row in index.messages for s in row.sends))
    with pytest.raises(ValueError, match="content budget"):
        create_local_moment_preview(moment, data, features=features)


@pytest.mark.slow_integration
def test_local_preview_keeps_content_order_plays_verified_animation_and_marks_gaps(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication, QLabel
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media
    from qq_chat_analyzer.presentation import sticker_moment_preview as preview_module
    from qq_chat_analyzer.presentation.sticker_moment_preview import create_local_moment_preview
    from qq_chat_analyzer.rich_message import NonTextContent, RecallState, ReplyRelation
    from test_sticker_data import image_bytes
    from shiboken6 import isValid

    app = QApplication.instance() or QApplication([])
    class PlainFirstLabel(QLabel):
        def __init__(self, *args, **kwargs):
            assert not any(isinstance(arg, str) for arg in args), "text entered QLabel before PlainText"
            super().__init__(*args, **kwargs)

        def setText(self, text):
            assert self.textFormat() == Qt.TextFormat.PlainText
            super().setText(text)
    monkeypatch.setattr(preview_module, "QLabel", PlainFirstLabel)
    # The Windows offscreen plugin has no system font database. Load a system
    # font explicitly for readable synthetic screenshots, without user settings.
    if not QFontDatabase.families():
        import os
        from pathlib import Path
        font = Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"
        font_id = QFontDatabase.addApplicationFont(str(font))
        assert font_id >= 0
        app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    rows = list(short_relay())
    rows[2] = replace(rows[2], contents=(TextContent("<b>虚构原文</b>"), rows[2].contents[0],
                                       NonTextContent("unknown"), TextContent("虚构尾段")),
                      recall_state=RecallState(True), relations=(ReplyRelation("duplicate"),))
    index = facts(rows)
    features = analyze_private_stickers(index)
    moment, = features.stories.moments
    raw = image_bytes(animated=True)
    key = index.messages[2].sends[0].media_key
    verified = verify_fetched_media(raw, media_key=key, expected_md5=hashlib.md5(raw).hexdigest())
    assert verified.status == "available" and verified.frame_count == 2
    data = StickerData(tuple(s for row in index.messages for s in row.sends), media=(verified,))
    dialog = create_local_moment_preview(moment, data, features=features)
    try:
        dialog.show()
        app.processEvents()
        labels = dialog.findChildren(QLabel)
        texts = [label.text() for label in labels]
        assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
        assert texts.index("<b>虚构原文</b>") < texts.index("[未支持内容：unknown]") < texts.index("虚构尾段")
        assert any("缺图" in text for text in texts)
        assert any("撤回" in text for text in texts)
        assert any("回复关系" in text for text in texts)
        movies = [label.movie() for label in labels if label.movie() is not None]
        assert movies
        movie = movies[0]
        changed = QSignalSpy(movie.frameChanged)
        QTest.qWait(250)
        assert changed.count() >= 1  # Playback timer, beyond manual decoding.
        assert movie.jumpToFrame(0)
        first = movie.currentImage()
        assert movie.jumpToFrame(1) and movie.currentImage() != first
        # Explicitly requested synthetic artifact; never a default preview export.
        assert dialog.grab().save(str(tmp_path/"fictional-preview.png"))
    finally:
        dialog.close()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # Resolved-byte lifetime is owned by the analysis result, not this dialog.
    assert verified.original_bytes == raw
    assert not isValid(movie)  # Closing releases players, not caller-owned media.
    # Repeated occurrences share one playback device and byte buffer.
    assert len({id(movie) for movie in movies}) == 1
    from qq_chat_analyzer.media_content import StoredMedia
    snapshot = StoredMedia(raw)
    snapshot.close()
    for item, expected in (
        (replace(verified, status="preview"), "可信预览；并非原图"),
        (replace(verified, original_bytes=None, stored=snapshot), "快照不可读"),
        (replace(verified, frame_count=99), "动画暂无法复现"),
    ):
        preview = create_local_moment_preview(moment, replace(data, media=(item,)), features=features)
        try:
            assert any(expected in label.text() for label in preview.findChildren(QLabel))
        finally:
            preview.close()
            app.processEvents()
    # Many different animations get bounded playback, with honest placeholders.
    b = Messages("preview-budget")
    for i in range(20):
        b.add(0, "A" if i % 2 == 0 else "B", f"animated{i}", seconds=i*2)
    index = facts(b.ordered())
    features = analyze_private_stickers(index)
    moment, = features.stories.moments
    sends = tuple(s for row in index.messages for s in row.sends)
    data = StickerData(sends, media=tuple(replace(verified, media_key=s.media_key) for s in sends))
    preview = create_local_moment_preview(moment, data, features=features)
    try:
        labels = preview.findChildren(QLabel)
        assert len({id(label.movie()) for label in labels if label.movie() is not None}) == 4
        assert sum("播放器预算" in label.text() for label in labels) == 16
    finally:
        preview.close()
        app.processEvents()
    snapshot = StoredMedia(raw)
    try:
        def forbidden_read():
            pytest.fail("encoded budget must be checked before snapshot I/O")
        monkeypatch.setattr(snapshot, "read", forbidden_read)
        monkeypatch.setattr(preview_module, "MAX_PREVIEW_BYTES", 1)
        preview = create_local_moment_preview(moment, replace(data, media=(
            replace(data.media[0], original_bytes=None, stored=snapshot),)), features=features)
        try:
            assert any("字节预算" in label.text() for label in preview.findChildren(QLabel))
        finally:
            preview.close()
            app.processEvents()
    finally:
        snapshot.close()
    monkeypatch.setattr(preview_module, "MAX_PREVIEW_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(preview_module, "MAX_PREVIEW_DECODE_WORK", 1)
    preview = create_local_moment_preview(moment, data, features=features)
    try:
        assert any("解码预算" in label.text() for label in preview.findChildren(QLabel))
        assert not any(label.movie() is not None for label in preview.findChildren(QLabel))
    finally:
        preview.close()
        app.processEvents()
