"""Confirmed sends and byte-verified originals, using only fictional inputs."""
from io import BytesIO
import hashlib
import json
import os
import re
import sys

import pytest
from PIL import Image

from qq_chat_analyzer import wechat_db_adapter
from qq_chat_analyzer.application import AnalysisRequestDTO
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from test_qq_db_rich_contents import _parse, _sticker, _scalar, _bytes, _text, _payload, _body


def image_bytes(fmt="GIF", *, animated=False):
    stream = BytesIO()
    first = Image.new("RGB", (3, 2), "red")
    options = {}
    if animated:
        options = dict(save_all=True, append_images=[Image.new("RGB", (3, 2), "blue")],
                       duration=100, loop=0)
    first.save(stream, format=fmt, **options)
    return stream.getvalue()


def wx(md5=None):
    return wechat_db_adapter.parse_rich_message(dict(
        local_type=47, user_name="fiction-sender", username="fiction-room",
        create_time=1760000000, server_id="duplicate",
        message_content=f'<msg><emoji md5="{md5 or ""}"/></msg>',
    ))


def collect(messages):
    from qq_chat_analyzer.analysis.stickers import collect_sticker_sends
    return collect_sticker_sends(messages)


def test_report_aggregation_preserves_scope_identity_and_real_send_counts():
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    from qq_chat_analyzer.rich_message import (
        ExpressionContent, RichMessage, SenderIdentity, StickerIdentity,
    )

    def message(sender, own, *keys, room="fiction-room", source="qq", kind="private"):
        return RichMessage(
            message_id="duplicate", source=source, conversation_id=room,
            conversation_type=kind, sender=SenderIdentity(sender, "同名"),
            is_self=own, timestamp=1760000000, message_type="text",
            contents=tuple(ExpressionContent("sticker", "unused", sticker=StickerIdentity(
                "fictional", "fictional", key)) for key in keys),
        )

    messages = [
        message("a", True, "shared", "shared", "mine"), message("a", True),
        message("b", False, "shared", "theirs", None),
        message(None, None, "mine", None), message("c", None, "third"),
        message("a", True, "shared", room="another-room"),
        message("a", True, "shared", source="wechat"),
        message("a", True, "shared", room=None),
        message("a", True, "shared", kind="group"),
    ]
    reports = aggregate_stickers(StickerData(sends=collect(messages)), messages)
    report = next(r for r in reports if r.source == "qq" and r.conversation_id == "fiction-room")
    assert (report.total_send_count, report.message_count, report.unknown_identity_count) == (9, 5, 2)
    assert report.unknown_sender_count == 2
    assert len(report.members) == 3  # No two-person assumption; unknown sender is not a member.
    members = {m.sender_id: m for m in report.members}
    assert (members["a"].send_count, members["a"].message_count, members["a"].per_hundred_messages) == (3, 2, 150.0)
    assert members["b"].per_hundred_messages == 300.0
    assert members["c"].is_self is None
    materials = {m.identity_key: m for m in report.materials}
    assert set(materials) == {"shared", "mine", "theirs", "third"}
    assert materials["shared"].member_counts == (("a", 2), ("b", 1))
    assert (materials["mine"].count, materials["mine"].unknown_sender_count) == (2, 1)
    assert len(reports) == 5
    assert all(r.total_send_count == 1 for r in reports if r is not report)
    assert next(r for r in reports if r.conversation_id is None).materials == ()
    # Missing denominator is unknown, not a fabricated zero rate.
    without_messages, = aggregate_stickers(StickerData(sends=collect(messages[:1])), ())
    assert without_messages.members[0].per_hundred_messages is None
    # A conflicting self marker cannot assign a participant to either side.
    conflicting = [messages[0], replace(messages[0], is_self=False)]
    conflict, = aggregate_stickers(StickerData(sends=collect(conflicting)), conflicting)
    assert conflict.members[0].is_self is None


def test_sticker_full_rankings_distinguish_group_totals_shared_and_members():
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    base = qq_pic("a" * 32)
    sends = []
    for member, key, count in (("a", "shared", 3), ("b", "shared", 8),
                               (None, "shared", 20), ("c", "solo", 50),
                               ("a", "tie-z", 3), ("a", "tie-a", 3),
                               ("a", None, 2)):
        sends.extend(replace(base, sender_id=member, identity_key=key,
                             conversation_type="group") for _ in range(count))
    report, = aggregate_stickers(StickerData(sends=tuple(sends)), ())
    assert [(m.identity_key, n) for m, n in report.ranking()] == [
        ("solo", 50), ("shared", 31), ("tie-a", 3), ("tie-z", 3)]
    assert [(m.identity_key, n) for m, n in report.shared_ranking()] == [("shared", 11)]
    assert report.shared_ranking(("a", "a")) == ()
    assert [m.identity_key for m, n in report.ranking("a")] == ["shared", "tie-a", "tie-z"]
    assert report.materials[0].reliable_member_count == 2
    assert report.exclusive_material_count() == 3
    assert report.exclusive_material_count("a") == 2
    member = next(m for m in report.members if m.sender_id == "a")
    assert member.send_count == 11 and member.per_hundred_messages is None


def test_shared_ranking_prefers_participants_over_raw_volume():
    """One prolific sender must not outrank a material several members share."""
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    base = qq_pic("b" * 32)
    sends = []
    for key, distribution in (
        ("solo", {"m1": 100}),
        ("loud", {"m1": 100, "m2": 1}),
        ("balanced", {"m1": 12, "m2": 10}),
        ("trio", {"m1": 5, "m2": 4, "m3": 3}),
    ):
        for member, count in distribution.items():
            sends.extend(replace(base, sender_id=member, identity_key=key,
                                 conversation_type="group") for _ in range(count))
    report, = aggregate_stickers(StickerData(sends=tuple(sends)), ())

    # Participants first, then the capped contribution, then the real total.
    assert [(m.identity_key, n) for m, n in report.shared_ranking()] == [
        ("trio", 12), ("balanced", 22), ("loud", 101)]
    # The single-sender material keeps its real total and personal count, but
    # never enters the shared board.
    assert ("solo", 100) in [(m.identity_key, n) for m, n in report.ranking()]
    assert all(key != "solo" for key, _ in report.shared_ranking())
    assert report.ranking("m1")[0][1] == 100
    assert report.exclusive_material_count() == 1
    # Private-style explicit sides: only materials both sides actually used.
    assert [(m.identity_key, n) for m, n in report.shared_ranking(("m1", "m2"))] == [
        ("balanced", 22), ("trio", 9), ("loud", 101)]
    assert report.shared_ranking(("m1",)) == ()


def test_private_shared_ranking_uses_smaller_side_not_capped_volume():
    """Two private sides can both pass the cap, so the cap alone saturates."""
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    base = qq_pic("c" * 32)
    sends = []
    for key, distribution in (
        ("flood", {"me": 9, "them": 1}),
        ("even", {"me": 2, "them": 2}),
        ("deep", {"me": 6, "them": 5}),
    ):
        for member, count in distribution.items():
            sends.extend(replace(base, sender_id=member, identity_key=key,
                                 conversation_type="private") for _ in range(count))
    report, = aggregate_stickers(StickerData(sends=tuple(sends)), ())

    # The smaller side decides, and the displayed number stays the real total.
    assert [(m.identity_key, n) for m, n in report.shared_ranking(("me", "them"))] == [
        ("deep", 11), ("even", 4), ("flood", 10)]


def test_group_shared_ranking_second_member_before_capped_and_total():
    """A flood with a thin second member ranks below an evenly shared trio."""
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    base = qq_pic("d" * 32)
    sends = []
    for key, distribution in (
        ("flood", {"m1": 10, "m2": 2, "m3": 1}),
        ("trio", {"m1": 3, "m2": 3, "m3": 3}),
        ("pair", {"m1": 20, "m2": 19}),
    ):
        for member, count in distribution.items():
            sends.extend(replace(base, sender_id=member, identity_key=key,
                                 conversation_type="group") for _ in range(count))
    report, = aggregate_stickers(StickerData(sends=tuple(sends)), ())

    # Participants first, so a prolific pair cannot outrank three-person
    # materials; within equal participants the second-highest member decides.
    assert [(m.identity_key, n) for m, n in report.shared_ranking()] == [
        ("trio", 9), ("flood", 13), ("pair", 39)]


def test_sticker_signature_requires_repetition_and_keeps_low_frequency_and_iso_years():
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    base = qq_pic("a" * 32)
    sends = []
    cases = {
        ("a", "burst"): ["2025-01-01"] * 30,
        ("a", "signature"): ["2024-12-29", "2025-01-05", "2025-01-12", "2025-02-02"],
        ("b", "quiet"): ["2024-01-03", "2024-07-03", "2025-01-01", "2025-07-02"],
        ("b", "endpoints"): ["2024-01-01", "2025-12-31"],
        ("c", "missing"): [None, "invalid", "2025-01-01", None],
    }
    for (member, key), dates in cases.items():
        sends.extend(replace(base, sender_id=member, identity_key=key, chat_date=day)
                     for day in dates)
    report, = aggregate_stickers(StickerData(sends=tuple(sends)), ())
    habits = {(h.sender_id, h.identity_key): h for h in report.habits}
    signature = habits["a", "signature"]
    assert (signature.send_count, signature.date_count, signature.span_days, signature.week_count) == (4, 4, 35, 4)
    assert signature.share == pytest.approx(4 / 34) and signature.qualified
    assert habits["b", "quiet"].week_count == 4 and habits["b", "quiet"].qualified
    assert not habits["a", "burst"].qualified
    assert not habits["b", "endpoints"].qualified
    assert not habits["c", "missing"].qualified
    assert habits["c", "missing"].dated_send_count == 1


def resolve(sends, roots=(), **limits):
    from qq_chat_analyzer.application.sticker_media import resolve_sticker_media
    return resolve_sticker_media(sends, roots=roots, **limits)


def qq_pic(digest):
    """One confirmed QQ PIC send carrying only a fictional trusted digest."""
    return collect([_parse(_scalar(45002, 2) + _scalar(45003, 1)
                           + _bytes(45406, bytes.fromhex(digest)) + _scalar(45418, 1))])[0]


def test_both_qq_sides_recover_using_only_authorized_content_evidence(tmp_path):
    from qq_chat_analyzer.analysis.stickers import StickerData
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages

    account = tmp_path / "12345001"
    mine = account / "nt_qq/nt_data/Pic/2026-01/Ori"
    received = account / "nt_qq/nt_data/Emoji/emoji-recv/2026-02/Ori"
    mine.mkdir(parents=True)
    received.mkdir(parents=True)
    raws = (image_bytes("JPEG"), image_bytes("GIF", animated=True))
    digests = tuple(hashlib.md5(raw).hexdigest() for raw in raws)
    paths = (mine / f"{digests[0]}.jpg", received / "fictional-resource-id.dat")
    blobs = []
    for index, (digest, path, raw) in enumerate(zip(digests, paths, raws)):
        path.write_bytes(raw)
        blobs.append(_body(_scalar(45002, 2) + _scalar(45003, 1)
            + _bytes(45406, bytes.fromhex(digest))
            + _bytes(45424, digest.upper().encode())
            + _bytes(45402, b"fictional-file-unique-not-content-md5.jpg")
            + _bytes(45812, str(path).encode()) + _scalar(45418, 1 - index)))
    payload = _payload(*blobs, session_type="private")
    payload["self"] = {"namespace": "qq_uin", "value": "10001"}
    for record, sender in zip(payload["records"], ("10001", "20002")):
        record["fields"]["40033"] = sender
    messages, warnings = parse_qq_db_rich_messages(payload)
    assert not warnings
    sends = collect(messages)
    assert [send.is_self for send in sends] == [True, False]
    assert [send.content_md5 for send in sends] == list(digests)
    data = ChatAnalyzerFacade.associate_sticker_media(StickerData(sends=sends),
        media_keys=tuple(send.media_key for send in sends), roots=(mine, received), source="qq")
    assert [media.status for media in data.media] == ["available", "available"]
    assert [media.original_bytes for media in data.media] == list(raws)


@pytest.mark.parametrize("kind", ["different_bytes", "corrupt", "outside", "thumb", "relative"])
def test_qq_path_candidates_never_replace_content_or_read_authority(tmp_path, monkeypatch, kind):
    from contextlib import contextmanager
    from dataclasses import replace
    from qq_chat_analyzer.application import sticker_media
    ori = tmp_path / "nt_qq/nt_data/Emoji/emoji-recv/2026-02/Ori"
    ori.mkdir(parents=True)
    raw = image_bytes("GIF", animated=True)
    digest = hashlib.md5(raw).hexdigest()
    path = ori / "opaque-resource"
    content = image_bytes("PNG")  # A valid but different image is not an original.
    if kind == "corrupt":
        content = b"GIF89a" + b"broken" * 4
        digest = hashlib.md5(content).hexdigest()
    elif kind in {"outside", "thumb"}:
        path = (tmp_path / "unapproved" if kind == "outside" else ori.parent / "Thumb") / "opaque-resource"
        path.parent.mkdir()
        content = raw
    path.write_bytes(content)
    hint = "../opaque-resource" if kind == "relative" else str(path)
    send = replace(qq_pic(digest), local_paths=(hint,), is_self=False)
    opened = []
    real_open = sticker_media._open_original
    @contextmanager
    def record(candidate, root):
        assert candidate.is_relative_to(ori)
        opened.append(candidate)
        with real_open(candidate, root) as stream:
            yield stream
    monkeypatch.setattr(sticker_media, "_open_original", record)
    item, = resolve((send,), (ori,), targeted=True, digest_names_only=True)
    assert item.original_bytes is None
    if kind == "corrupt":
        assert (item.status, item.reason) == ("invalid", "invalid_image")
        assert opened == [path]
    elif kind == "different_bytes":
        assert (item.status, item.reason) == ("missing", "digest_mismatch")
        assert opened == [path]
    else:
        assert (item.status, item.reason) == ("missing", "no_digest_name_match")
        assert opened == []


def test_qq_repeated_material_keeps_earlier_authorized_path_candidate(tmp_path):
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerData
    from qq_chat_analyzer.application.sticker_media import associate_sticker_media
    raw = image_bytes("PNG")
    path = tmp_path / "opaque-original"
    path.write_bytes(raw)
    first = replace(qq_pic(hashlib.md5(raw).hexdigest()), local_paths=(str(path),))
    later = replace(first, local_paths=(), is_self=False)
    result = associate_sticker_media(StickerData(sends=(first, later)),
        media_keys=(first.media_key,), roots=(tmp_path,), source="qq")
    assert result.media[0].original_bytes == raw


@pytest.mark.parametrize("failure", ["bytes", "entries", "cancel"])
def test_qq_opaque_path_candidate_uses_existing_global_budgets(tmp_path, failure):
    from dataclasses import replace
    raw = image_bytes("PNG")
    path = tmp_path / "opaque-resource"
    path.write_bytes(raw)
    send = replace(qq_pic(hashlib.md5(raw).hexdigest()), local_paths=(str(path),), is_self=False)
    options = {"bytes": dict(max_total_bytes=1), "entries": dict(max_scan_entries=0),
               "cancel": dict(cancelled=lambda: True)}[failure]
    item, = resolve((send,), (tmp_path,), targeted=True, digest_names_only=True, **options)
    assert item.status == ("cancelled" if failure == "cancel" else "limited")
    assert item.original_bytes is None


def test_reliable_identity_and_unresolved_sends_never_merge_by_message_id():
    digest = "abcdef0123456789abcdef0123456789"
    sends = collect([wx(digest.upper()), wx(digest), wx("invalid"), wx(), wx()])
    assert len(sends) == 5
    assert len({s.occurrence_id for s in sends}) == 5
    assert sends[0].identity_key == sends[1].identity_key == "wechat:md5:" + digest
    assert [s.identity_key for s in sends[2:]] == [None, None, None]
    assert len({s.media_key for s in sends[2:]}) == 3
    assert sends[0].classification_basis == "wechat_type_47"
    assert sends[0].identity_basis == "wechat_xml_md5"
    assert sends[0].sender_id == "fiction-sender"
    assert sends[0].conversation_id == "fiction-room"
    assert sends[0].epoch_seconds == 1760000000
    assert sends[0].chat_date == "2025-10-09"
    assert resolve(sends)[0].status == "not_requested"


def test_qq_marketface_keeps_opaque_identity_and_pic_is_not_confirmed_sticker():
    message = _parse(_sticker(), _sticker(), _scalar(45002, 2)
                     + _bytes(45406, b"x" * 16) + _bytes(45403, b"../outside.gif")
                     + _scalar(45418, 1))
    sends = collect([message])
    assert len(sends) == 2
    assert sends[0].identity_key == sends[1].identity_key
    assert sends[0].identity_basis == "qq_45600_sha256_opaque"
    assert sends[0].classification_basis == "qq_content_type_11"
    media = resolve(sends)
    assert len(media) == 1 and media[0].status == "unsupported"
    assert media[0].reason == "original_digest_unproven"
    pic = message.contents[-1]
    assert pic.kind == "image"
    assert pic.media.content_md5 == "78" * 16
    assert pic.media.is_original is True
    assert pic.media.local_paths == ("../outside.gif",)
    assert wechat_db_adapter.parse_rich_message(dict(
        local_type=3, user_name="fiction-sender", create_time=1760000000,
        message_content='<msg><emoji md5="' + "a" * 32 + '"/></msg>',
    )) is None


def test_actual_format_original_bytes_and_duplicate_media(tmp_path):
    raw = image_bytes("PNG")
    digest = hashlib.md5(raw).hexdigest()
    # Names and extensions are deliberately misleading; only bytes authorize a match.
    (tmp_path / "not-the-name.jpg").write_bytes(raw)
    (tmp_path / "duplicate.dat").write_bytes(raw)
    sends = collect([wx(digest), wx(digest)])
    media = resolve(sends, (tmp_path,))
    assert len(media) == 1
    item = media[0]
    assert item.status == "available" and item.reason is None
    assert item.format == "PNG"
    assert item.frame_count == 1
    assert item.animation_preserved is False
    assert item.original_bytes == raw
    assert item.sha256 == hashlib.sha256(raw).hexdigest()
    assert item.byte_count == len(raw)
    assert item.verified_reference is not None
    assert item.original_bytes not in repr(item).encode()


def test_matching_png_with_corrupt_chunk_checksum_is_not_verified(tmp_path):
    raw = bytearray(image_bytes("PNG"))
    tag = raw.index(b"IDAT")
    chunk_size = int.from_bytes(raw[tag - 4:tag], "big")
    raw[tag + 4 + chunk_size] ^= 1  # Damage CRC without damaging pixel data.
    raw = bytes(raw)
    (tmp_path / "original").write_bytes(raw)
    result = resolve(collect([wx(hashlib.md5(raw).hexdigest())]), (tmp_path,))[0]
    assert result.status == "invalid" and result.original_bytes is None


def test_read_and_decode_budgets_fail_closed(tmp_path):
    raw = image_bytes()
    (tmp_path / "original").write_bytes(raw)
    sends = collect([wx(hashlib.md5(raw).hexdigest())])
    for limits in (dict(max_file_bytes=10), dict(max_total_bytes=10),
                   dict(max_entries=0), dict(max_pixels=1), dict(max_frames=1)):
        result = resolve(sends, (tmp_path,), **limits)[0]
        if limits == dict(max_frames=1):  # static GIF fits the frame budget
            assert result.status == "available"
        else:
            assert result.status == "limited" and result.original_bytes is None
    animated = image_bytes(animated=True)
    (tmp_path / "original").write_bytes(animated)
    assert resolve(collect([wx(hashlib.md5(animated).hexdigest())]),
                   (tmp_path,), max_frames=1)[0].status == "limited"


@pytest.mark.parametrize("frames,limits,accepted", [
    (129, {}, True),
    (129, {"max_frames": 128}, False),
    (3, {"max_pixels": 3 * 8 * 6}, True),
    (3, {"max_pixels": 3 * 8 * 6 - 1}, False),
])
def test_local_and_fetched_gif_share_frame_and_canvas_pixel_limits(tmp_path, frames, limits, accepted):
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media

    # Only one pixel changes: optimized GIF patches still need a full canvas.
    images = []
    for index in range(frames):
        image = Image.new("RGB", (8, 6), "black")
        image.putpixel((0, 0), (index + 1, 0, 0))
        images.append(image)
    stream = BytesIO()
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:],
                   optimize=True, duration=100, loop=0)
    raw = stream.getvalue()
    digest = hashlib.md5(raw).hexdigest()
    (tmp_path / "fictional.gif").write_bytes(raw)
    send = qq_pic(digest)
    local, = resolve((send,), (tmp_path,), **limits)
    fetched = verify_fetched_media(raw, media_key=send.media_key, expected_md5=digest, **limits)
    for media in (local, fetched):
        if accepted:
            assert (media.status, media.reason) == ("available", None)
            assert media.frame_count == frames and media.animation_preserved
            assert media.original_bytes == raw and media.byte_count == len(raw)
        else:
            assert (media.status, media.reason) == ("limited", "decode_budget")
            assert media.original_bytes is None


@pytest.mark.parametrize("fmt", ["GIF", "PNG", "WEBP"])
def test_long_animation_validates_without_changing_original_or_preview_identity(fmt):
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media

    images = [Image.new("RGB", (16, 12), "red" if index % 2 else "blue")
              for index in range(200)]
    stream = BytesIO()
    images[0].save(stream, format=fmt, save_all=True, append_images=images[1:], duration=40, loop=0)
    raw = stream.getvalue()
    for digest, status in ((hashlib.md5(raw).hexdigest(), "available"), ("a" * 32, "preview")):
        media = verify_fetched_media(raw, media_key="fictional", expected_md5=digest)
        assert media.status == status
        assert media.original_bytes == raw and media.frame_count == 200
        assert media.animation_preserved


@pytest.mark.parametrize("size, noisy", [((320, 240), True), ((512, 512), False)])
def test_qq_large_long_gif_keeps_all_frames_without_relaxing_local_limits(size, noisy):
    import random
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media

    # Exercise the old byte limit and cumulative frame-work limits separately.
    randomizer = random.Random(73)
    images = ([Image.frombytes("P", size, randomizer.randbytes(size[0] * size[1])) for _ in range(300)]
              if noisy else [Image.new("RGB", size, "red" if i % 2 else "blue") for i in range(300)])
    stream = BytesIO()
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:],
                   optimize=False, duration=40, loop=0)
    raw = stream.getvalue()
    assert len(raw) <= 32 * 1024 * 1024
    if noisy:
        assert len(raw) > 2 * 1024 * 1024
    media = verify_fetched_media(raw, media_key="fictional", expected_md5=hashlib.md5(raw).hexdigest())
    assert media.status == "available"
    assert media.original_bytes == raw and media.frame_count == 300
    assert media.animation_preserved


@pytest.mark.parametrize("limit", ["work", "canvas", "late_canvas", "time", "qq_window", "late_corruption"])
def test_animation_resource_limits_and_late_corruption_fail_closed(tmp_path, monkeypatch, limit):
    from qq_chat_analyzer.application import sticker_media

    raw = image_bytes(animated=True)
    if limit == "work":
        monkeypatch.setattr(sticker_media, "MAX_DECODE_WORK", 64 * 1024)
        monkeypatch.setattr(sticker_media, "QQ_MAX_DECODE_WORK", 64 * 1024)
    elif limit == "canvas":
        # Enormous declared canvas, with tiny compressed data; never allocate it.
        raw = raw[:6] + (4096).to_bytes(2, "little") * 2 + raw[10:]
    elif limit == "late_canvas":
        descriptor = raw.rfind(b",")
        assert raw[descriptor + 5:descriptor + 9] == b"\x03\x00\x02\x00"
        raw = raw[:descriptor + 1] + b"\xff\x7f" + raw[descriptor + 3:]
    elif limit == "time":
        ticks = iter(range(1000))
        monkeypatch.setattr(sticker_media.time, "monotonic", lambda: next(ticks) * 20)
    elif limit == "qq_window":
        clock = [0.0]
        open_image = Image.open
        def delayed_open(*args, **kwargs):
            clock[0] += 3.0
            return open_image(*args, **kwargs)
        monkeypatch.setattr(sticker_media.time, "monotonic", lambda: clock[0])
        monkeypatch.setattr(Image, "open", delayed_open)
    else:
        raw = raw[:-10]  # Damage the last frame, preserving a valid first frame.
    if limit in {"canvas", "late_canvas"}:
        monkeypatch.setattr(Image, "open", lambda *a, **kw: pytest.fail("invalid canvas reached decoder"))
    digest = hashlib.md5(raw).hexdigest()
    (tmp_path / "fictional.gif").write_bytes(raw)
    send = qq_pic(digest)
    fetched = sticker_media.verify_fetched_media(raw, media_key=send.media_key, expected_md5=digest)
    if limit == "qq_window":
        assert fetched.status == "available" and fetched.frame_count == 2
        local, = resolve((send,), (tmp_path,))
        assert (local.status, local.reason) == ("limited", "decode_budget")
        return
    assert fetched.status == ("invalid" if limit in {"late_corruption", "late_canvas"} else "limited")
    assert fetched.original_bytes is None
    local, = resolve((send,), (tmp_path,))
    assert local.status in {"invalid", "limited"} and local.original_bytes is None


def test_targeted_lookup_opens_only_digest_named_candidates_in_a_qq_tree(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from qq_chat_analyzer.application import sticker_media

    raw = image_bytes("GIF", animated=True)
    digest = hashlib.md5(raw).hexdigest()
    ori = tmp_path / "nt_qq" / "nt_data" / "Pic" / "2026-10" / "Ori"
    thumb = ori.parent / "Thumb"
    ori.mkdir(parents=True)
    thumb.mkdir(parents=True)
    # Names and suffixes are hints only: the bytes still decide the format.
    (ori / f"{digest}.jpg").write_bytes(raw)
    (thumb / "unrelated-thumb").write_bytes(b"fictional unrelated cache file")
    (ori / "not-a-sticker").write_bytes(b"fictional unrelated cache file")

    opened = []
    original_open = sticker_media._open_original

    @contextmanager
    def record(path, root):
        opened.append(path.name)
        with original_open(path, root) as stream:
            yield stream

    monkeypatch.setattr(sticker_media, "_open_original", record)
    # Fewer record slots than files forces name-only candidate selection.
    item = resolve((qq_pic(digest),), (tmp_path,),
                   targeted=True, max_entries=1)[0]
    assert (item.status, item.format, item.frame_count) == ("available", "GIF", 2)
    assert item.animation_preserved is True and item.original_bytes == raw
    assert opened == [f"{digest}.jpg"]


def test_targeted_lookup_still_reads_a_small_explicit_copies_folder(tmp_path):
    raw = image_bytes("GIF", animated=True)
    digest = hashlib.md5(raw).hexdigest()
    (tmp_path / "renamed-copy.bin").write_bytes(raw)
    item = resolve((qq_pic(digest),), (tmp_path,), targeted=True)[0]
    assert item.status == "available" and item.original_bytes == raw
    assert resolve((qq_pic(digest),), (), targeted=True)[0].status == "not_requested"


def test_qq_discovered_scope_never_opens_unrelated_small_cache_files(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media

    raw = image_bytes("PNG")
    digest = hashlib.md5(raw).hexdigest()
    (tmp_path / "renamed.png").write_bytes(raw)
    real_open = sticker_media._open_original

    def named_only(path, root):
        assert digest in path.name
        return real_open(path, root)

    monkeypatch.setattr(sticker_media, "_open_original", named_only)
    stats = {}
    options = dict(targeted=True, digest_names_only=True, diagnostics=stats)
    item = resolve((qq_pic(digest),), (tmp_path,), **options)[0]
    assert (item.status, item.reason) == ("missing", "no_digest_name_match")
    assert str(tmp_path) not in repr(stats) and digest not in repr(stats)
    (tmp_path / f"{digest}.bin").write_bytes(raw)
    assert resolve((qq_pic(digest),), (tmp_path,), **options)[0].original_bytes == raw
    item = resolve((qq_pic(digest),), (tmp_path,), cancelled=lambda: True, **options)[0]
    assert item.status == "cancelled" and item.original_bytes is None


@pytest.mark.parametrize("budget", ["entries", "bytes", "time", "cancel"])
def test_coalesced_qq_scopes_share_budgets_across_all_months(tmp_path, monkeypatch, budget):
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.application.qq.qq_media_directories import qq_media_search_roots

    raw = image_bytes("PNG")
    digest = hashlib.md5(raw).hexdigest()
    scopes = []
    for index in range(59):
        ori = tmp_path / "12345001/nt_qq/nt_data/Pic" / f"{2020 + index // 12}-{1 + index % 12:02}" / "Ori"
        ori.mkdir(parents=True)
        (ori / f"{digest}.png").write_bytes(raw)
        scopes.append(ori)
    options = dict(targeted=True, digest_names_only=True, authorized_scopes=tuple(scopes))
    visited = []
    real_scan = sticker_media.os.scandir

    def scan(path):
        visited.append(path)
        return real_scan(path)

    monkeypatch.setattr(sticker_media.os, "scandir", scan)
    if budget == "entries":
        options["max_scan_entries"] = 150
    elif budget == "bytes":
        options["max_total_bytes"] = len(raw) * 20
    elif budget == "time":
        monkeypatch.setattr(sticker_media.time, "monotonic", lambda: 11 if len(visited) > 20 else 0)
    else:
        options["cancelled"] = lambda: len(visited) > 20
    item = resolve((qq_pic(digest),), qq_media_search_roots(tuple(scopes)), **options)[0]
    assert item.original_bytes is None
    if budget == "cancel":
        assert (item.status, item.reason) == ("cancelled", "user_cancelled")
    else:
        assert item.status == "limited"
        assert item.reason == ("total_byte_budget" if budget == "bytes" else "scan_budget")


@pytest.mark.parametrize("scope_kind", ["empty", "outside", "traversal"])
def test_coalesced_media_scope_cannot_expand_root_authority(tmp_path, scope_kind):
    root = tmp_path / "approved"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    scopes = {
        "empty": (), "outside": (other,),
        "traversal": (root / ".." / "other",),
    }[scope_kind]
    item = resolve((qq_pic("a" * 32),), (root,), targeted=True,
                   digest_names_only=True, authorized_scopes=scopes)[0]
    assert (item.status, item.reason) == ("unsafe", "invalid_scope")
    assert item.original_bytes is None


def test_no_root_or_no_reliable_digest_never_opens_local_resources(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media

    def forbidden(*args, **kwargs):
        pytest.fail("Resource discovery must remain opt-in and digest-bound")

    monkeypatch.setattr(sticker_media.os, "scandir", forbidden)
    assert resolve(collect([wx("a" * 32)]))[0].status == "not_requested"
    assert resolve(collect([wx()]), (tmp_path,))[0].status == "unsupported"
    qq = _parse(_sticker() + _bytes(45812, b"../outside.gif"))
    assert resolve(collect([qq]), (tmp_path,))[0].status == "unsupported"
    # Targeted evidence never upgrades an opaque MFACE identity into a digest.
    assert resolve(collect([qq]), (tmp_path,), targeted=True)[0].status == "unsupported"


def test_missing_decoder_does_not_claim_available_original(tmp_path, monkeypatch):
    raw = image_bytes()
    (tmp_path / "original").write_bytes(raw)
    sends = collect([wx(hashlib.md5(raw).hexdigest())])
    monkeypatch.setitem(sys.modules, "PIL", None)
    item = resolve(sends, (tmp_path,))[0]
    assert item.status == "unsupported" and item.reason == "decoder_unavailable"
    assert item.original_bytes is None and len(sends) == 1


def test_conflicting_md5_contents_are_ambiguous_not_first_match(tmp_path, monkeypatch):
    # Force a digest collision at the hash boundary; the contents and all file
    # verification remain real. A resolver choosing its first hit would fail.
    from qq_chat_analyzer.application import sticker_media
    digest = "a" * 32
    (tmp_path / "first").write_bytes(image_bytes("PNG"))
    (tmp_path / "second").write_bytes(image_bytes("GIF"))

    class Collision:
        def hexdigest(self):
            return digest

    monkeypatch.setattr(sticker_media.hashlib, "md5", lambda raw: Collision())
    result = resolve(collect([wx(digest)]), (tmp_path,))[0]
    assert result.status == "ambiguous" and result.original_bytes is None


def test_unreadable_and_changed_files_are_explicit_failures(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media
    raw = image_bytes()
    (tmp_path / "original").write_bytes(raw)
    sends = collect([wx(hashlib.md5(raw).hexdigest())])
    original_open = sticker_media._open_original
    from contextlib import contextmanager

    @contextmanager
    def replaced(path, root):
        path.write_bytes(raw + b"changed")
        with original_open(path, root) as stream:
            yield stream

    monkeypatch.setattr(sticker_media, "_open_original", replaced)
    item = resolve(sends, (tmp_path,))[0]
    assert item.status == "unsafe" and item.reason == "file_changed"

    @contextmanager
    def denied(*args):
        raise PermissionError("fictional private path must not escape in reasons")
        yield

    monkeypatch.setattr(sticker_media, "_open_original", denied)
    item = resolve(sends, (tmp_path,))[0]
    assert item.status == "unreadable" and item.reason == "local_read_failed"


def test_deep_or_unfinished_scan_does_not_publish_partial_success(tmp_path):
    raw = image_bytes()
    (tmp_path / "original").write_bytes(raw)
    (tmp_path / "nested").mkdir()
    sends = collect([wx(hashlib.md5(raw).hexdigest())])
    assert resolve(sends, (tmp_path,), max_depth=0)[0].status == "limited"


@pytest.mark.parametrize("xml", [
    '<msg><emoji md5="' + "a" * 32 + '"/><emoji md5="' + "b" * 32 + '"/></msg>',
    '<!DOCTYPE msg [<!ENTITY x "' + "a" * 32 + '">]><msg><emoji md5="&x;"/></msg>',
    '<msg><emoji md5="' + "a" * 32 + '"/>' + "x" * 20000 + '</msg>',
])
def test_ambiguous_or_unsafe_xml_cannot_authorize_material_identity(xml):
    message = wechat_db_adapter.parse_rich_message(dict(
        local_type=47, user_name="fiction-sender", create_time=1760000000,
        message_content=xml,
    ))
    sends = collect([message])
    assert len(sends) == 1 and sends[0].identity_key is None
    assert resolve(sends)[0].status == "unsupported"


def test_qq_stickers_follow_message_scope_with_duplicate_ids(tmp_path, monkeypatch):
    from datetime import date, datetime
    from qq_chat_analyzer.application.scope_filter import AnalysisScope
    from test_rich_filtering_association import analyze
    timestamp = int(datetime(2026, 1, 2, 12).timestamp())

    def row(text, identity, moment):
        record = _payload(_body(_text(text), _sticker(identity)))["records"][0]
        record["record_id"] = "duplicate"
        record["fields"].update({"40033": "fiction-human", "40050": moment})
        return record

    rows = [row("Human authored", b"kept", timestamp), row("Outside", b"filtered", 1700000000)]
    scope = AnalysisScope.custom(date(2026, 1, 2), date(2026, 1, 2))
    payload = _payload()
    payload["records"] = rows
    result, _ = analyze(tmp_path, monkeypatch, [payload], scope)
    assert len(result.stickers.sends) == 1
    assert result.stickers.sends[0].identity_key == (
        "qq-marketface:sha256:" + hashlib.sha256(b"kept").hexdigest())
    assert len(result.stickers.media) == 1
    assert result.reports.stickers[0].total_send_count == 1
    assert len(result.reports.stickers[0].materials) == 1


def test_media_roots_reject_traversal_links_and_relative_paths(tmp_path):
    raw = image_bytes()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(raw)
    root = tmp_path / "allowed"
    root.mkdir()
    sends = collect([wx(hashlib.md5(raw).hexdigest())])
    assert resolve(sends, (root / ".." / "outside",))[0].status == "unsafe"
    assert resolve(sends, (root.relative_to(tmp_path),))[0].status == "unsafe"
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       check=True, capture_output=True)
    assert resolve(sends, (root,))[0].status == "unsafe"
    assert resolve(sends, (link,))[0].status == "unsafe"


@pytest.mark.skipif(os.name != "nt", reason="Windows handle sharing contract")
def test_open_original_holds_write_and_delete_exclusion(tmp_path):
    from qq_chat_analyzer.application.sticker_media import _open_original
    original = tmp_path / "original"
    raw = image_bytes()
    original.write_bytes(raw)
    with _open_original(original, tmp_path) as stream:
        with pytest.raises(OSError):
            original.write_bytes(b"replacement")
        with pytest.raises(OSError):
            original.unlink()
        assert stream.read() == raw
    assert original.read_bytes() == raw


def test_filtered_official_analysis_chain_returns_only_kept_sticker_sends(tmp_path):
    from datetime import date
    from qq_chat_analyzer.application.scope_filter import AnalysisScope
    raw = image_bytes(animated=True)
    digest = hashlib.md5(raw).hexdigest()
    roots = tmp_path / "media"
    roots.mkdir()
    (roots / "original").write_bytes(raw)
    rows = []
    for timestamp, xml in [(1760000000, f'<msg><emoji md5="{digest}"/></msg>'),
                           (1700000000, '<msg><emoji md5="' + "b" * 32 + '"/></msg>')]:
        rows.append(dict(local_type=47, server_id="duplicate", create_time=timestamp,
                         user_name="fiction-sender", message_content=xml))
    payload = dict(source="wechat-db", conversation=dict(username="fiction-room"), messages=rows)
    source = tmp_path / "source.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path / "stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=source, output_directory=tmp_path / "output", stopwords_path=stopwords,
        scope=AnalysisScope.custom(date(2025, 10, 9), date(2025, 10, 9)),
        sticker_media_roots=(roots,),
    ))
    assert len(result.stickers.sends) == 1
    assert len(result.stickers.media) == 1
    assert result.stickers.media[0].original_bytes == raw
    assert result.reports.expression.expression_occurrence_count == 1
    report_text = (tmp_path / "output" / "echo-report.json").read_text(encoding="utf-8")
    assert digest not in report_text and str(roots) not in report_text


@pytest.mark.parametrize("kind,fmt", [("private", "GIF"), ("group", "WEBP")])
def test_wechat_type47_reaches_formal_report_through_provider_and_facade(tmp_path, monkeypatch, kind, fmt):
    from qq_chat_analyzer.application.facade import AnalysisConfig, ChatAnalyzerFacade, ChatSource
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfig, WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter,
    )
    from qq_chat_analyzer.application.wechat.wechat_provider_factory import WeChatProviderFactory
    from qq_chat_analyzer.application.wechat.wechat_export_import_service import WeChatExportImportService
    import base64
    import zstandard
    from qq_chat_analyzer.providers.wechat_database_provider import WeChatDatabaseProvider, WeChatSession

    raw = image_bytes(fmt, animated=True)
    digest = hashlib.md5(raw).hexdigest()
    media_root = tmp_path / "explicit-originals"
    media_root.mkdir()
    (media_root / "unrelated-name.bin").write_bytes(raw)
    path = tmp_path / "wechat.json"
    config = WeChatEnvironmentConfig(sticker_media_roots=(media_root,))
    WeChatEnvironmentConfigWriter(path).save(config)
    loader = WeChatEnvironmentConfigLoader(path)
    assert loader.load().sticker_media_roots == (media_root,)
    factory = WeChatProviderFactory(config_loader=loader)
    provider = factory.create()
    assert isinstance(provider, WeChatDatabaseProvider)
    assert provider.with_data_root(tmp_path / "other-account").sticker_media_roots() == ()
    assert provider.sticker_media_roots() == (media_root,)
    session_id = "wxid_fiction_room@chatroom" if kind == "group" else "wxid_fiction_peer"
    # Keep real provider export, adapter, filters, aggregation and packaging.
    # Only database reads/identity lookup return fictional source facts.
    monkeypatch.setattr(provider, "list_sessions", lambda: [WeChatSession(
        session_id=session_id, display_name="Fictional chat", session_type=kind)])
    monkeypatch.setattr(provider, "_contact_display_names", lambda: {
        "wxid_fiction_self": "Fictional Me", "wxid_fiction_peer": "Fictional Peer"})
    monkeypatch.setattr(provider, "_resolve_self_username", lambda: "wxid_fiction_self")
    xml = f'<msg><emoji md5="{digest.upper()}" cdnurl="https://fictional.invalid/never-fetch"/></msg>'
    compressed = zstandard.ZstdCompressor().compress(xml.encode()).hex()
    rows = [dict(local_type=1, server_id="text", user_name="wxid_fiction_self",
                 create_time=1760000000, message_content="Fictional ordinary conversation."),
            dict(local_type=47, server_id="mine", user_name="wxid_fiction_self",
                 create_time=1760000001, message_content=xml),
            dict(local_type=0x10000002F, server_id="theirs", user_name="wxid_fiction_peer",
                 create_time=1760000002, WCDB_CT_message_content=4, message_content=compressed),
            dict(local_type=47, server_id="unknown", user_name="wxid_fiction_peer",
                 create_time=1760000003, message_content='<msg><emoji md5="invalid"/></msg>'),
            dict(local_type=3, server_id="image", user_name="wxid_fiction_peer",
                 create_time=1760000004, message_content=xml)]
    monkeypatch.setattr(provider, "read_session_rows", lambda *args, **kwargs: rows)
    facade = ChatAnalyzerFacade(
        wechat_service=WeChatExportImportService(provider_factory=factory),
        analysis_service=AnalysisApplicationService(),
    )
    outcome = facade.analyze_session(ChatSource.WECHAT, session_id, AnalysisConfig(
        output_directory=tmp_path / "result",
    ))
    assert outcome.result.stickers.media[0].original_bytes == raw
    assert outcome.result.stickers.media[0].frame_count == 2
    sends = outcome.result.stickers.sends
    assert len(sends) == 3
    assert [item.is_self for item in sends] == [True, False, False]
    assert all(item.conversation_type == kind and item.conversation_id == session_id for item in sends)
    assert sends[0].media_key == sends[1].media_key == "wechat:md5:" + digest
    assert sends[2].identity_key is None
    chapter = outcome.echo_report_view.stickers
    assert chapter.available and chapter.conversation_kind == kind
    assert (chapter.total_send_count, chapter.unique_material_count, chapter.unknown_identity_count) == (3, 1, 1)
    assert chapter.covered_message_count == 4  # Type 3 is not a confirmed sticker or denominator.
    assert sorted(member.send_count for member in chapter.members) == [1, 2]
    asset, = chapter.assets
    assert asset.status == "available"
    assert base64.b64decode(asset.data_uri.split(",", 1)[1]) == raw
    report_json = (outcome.report_directory / "echo-report.json").read_text(encoding="utf-8")
    report_html = outcome.report_path.read_text(encoding="utf-8")
    assert json.loads(report_json)["stickers"]["total_send_count"] == 3
    assert asset.data_uri in report_html
    assert session_id not in json.dumps(json.loads(report_json)["stickers"])
    for secret in (digest, str(media_root), "fictional.invalid", "cdnurl"):
        assert secret not in report_json and secret not in report_html
    opted_out = facade.analyze_session(ChatSource.WECHAT, session_id, AnalysisConfig(
        output_directory=tmp_path / "no-media", sticker_media_roots=(),
    ))
    # Without an authorized local root the report falls back to the verified
    # CDN hint only. This fictional host is outside the allowlist, so it is
    # rejected before any request and no bytes are produced.
    assert (opted_out.result.stickers.media[0].status,
            opted_out.result.stickers.media[0].reason) == (
        "unsupported", "wechat_cdn_url_host_rejected")
    assert len(opted_out.result.stickers.sends) == 3
    no_media = opted_out.echo_report_view.stickers
    assert no_media.total_send_count == chapter.total_send_count
    assert no_media.unique_material_count == chapter.unique_material_count
    assert all(not asset.data_uri for asset in no_media.assets)
    assert opted_out.report_path.is_file()


def test_wechat_media_failure_keeps_local_report_but_cancel_does_not(
    tmp_path, monkeypatch,
):
    """A recovery bug keeps the local analysis; cancellation aborts export."""
    from qq_chat_analyzer.application.facade import (
        AnalysisConfig, ChatAnalyzerFacade, ChatSource, FacadeError,
    )
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfig, WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter,
    )
    from qq_chat_analyzer.application.wechat.wechat_export_import_service import (
        WeChatExportImportService,
    )
    from qq_chat_analyzer.application.wechat.wechat_provider_factory import WeChatProviderFactory
    from qq_chat_analyzer.providers.wechat_database_provider import WeChatSession
    import qq_chat_analyzer.application.wechat.wechat_sticker_cdn as sticker_cdn

    path = tmp_path / "wechat.json"
    WeChatEnvironmentConfigWriter(path).save(WeChatEnvironmentConfig())
    factory = WeChatProviderFactory(config_loader=WeChatEnvironmentConfigLoader(path))
    provider = factory.create()
    session_id = "wxid_fiction_room@chatroom"
    xml = ('<msg><emoji md5="0123456789abcdef0123456789abcdef" '
           'cdnurl="https://fictional-vweixinf.tc.qq.com/fictional"/></msg>')
    monkeypatch.setattr(provider, "list_sessions", lambda: [WeChatSession(
        session_id=session_id, display_name="Fictional chat", session_type="group")])
    monkeypatch.setattr(provider, "_contact_display_names", lambda: {})
    monkeypatch.setattr(provider, "_resolve_self_username", lambda: "wxid_fiction_self")
    monkeypatch.setattr(provider, "read_session_rows", lambda *args, **kwargs: [dict(
        local_type=47, server_id="fictional-sticker", create_time=1760000001,
        message_content=xml, user_name="wxid_fiction_peer")])
    facade = ChatAnalyzerFacade(
        wechat_service=WeChatExportImportService(provider_factory=factory),
        analysis_service=AnalysisApplicationService(),
    )

    def failing_recovery(*args, **kwargs):
        raise RuntimeError("fictional recovery defect")

    monkeypatch.setattr(sticker_cdn, "recover_wechat_sticker_media", failing_recovery)
    outcome = facade.analyze_session(ChatSource.WECHAT, session_id, AnalysisConfig(
        output_directory=tmp_path / "fallback"))
    assert outcome.report_path.is_file()
    assert len(outcome.result.stickers.sends) == 1
    assert outcome.result.stickers.media[0].status == "not_requested"
    assert all(not asset.data_uri for asset in outcome.echo_report_view.stickers.assets)

    cancelled = {"value": False}

    def cancelled_recovery(*args, **kwargs):
        cancelled["value"] = True
        raise RuntimeError("fictional recovery defect")

    monkeypatch.setattr(sticker_cdn, "recover_wechat_sticker_media", cancelled_recovery)
    with pytest.raises(FacadeError) as error:
        facade.analyze_session(
            ChatSource.WECHAT, session_id,
            AnalysisConfig(output_directory=tmp_path / "cancelled"),
            cancelled=lambda: cancelled["value"],
        )
    assert error.value.code == "analysis_cancelled"
    assert not (tmp_path / "cancelled" / "echo-report.html").is_file()


@pytest.mark.parametrize("value", ["", "relative", ["relative"], ["../outside"], [3], ["\\\\server\\share"]])
def test_wechat_media_config_rejects_invalid_authority(tmp_path, value):
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfigLoader, WeChatConfigCorrupted,
    )
    path = tmp_path / "wechat.json"
    path.write_text(json.dumps(dict(sticker_media_roots=value)), encoding="utf-8")
    with pytest.raises(WeChatConfigCorrupted):
        WeChatEnvironmentConfigLoader(path).load()


def test_facade_config_exposes_explicit_roots_without_source_discovery(tmp_path):
    from qq_chat_analyzer.application.facade import AnalysisConfig
    config = AnalysisConfig(sticker_media_roots=(tmp_path,))
    assert config.with_output_directory(tmp_path / "result").sticker_media_roots == (tmp_path,)
    assert str(tmp_path) not in repr(config)


@pytest.mark.parametrize("subtype,repeat", [(0, False), (2, False), (2, True)])
def test_qq_ordinary_unknown_or_unreliable_pic_subtype_never_becomes_sticker(subtype, repeat):
    segment = _scalar(45002, 2) + _scalar(45003, subtype) + _bytes(45406, b"\xab" * 16)
    if repeat:
        segment += _scalar(45003, subtype)
    message = _parse(segment)
    assert message.contents[0].kind == "image"
    assert message.contents[0].sticker is None
    assert collect([message]) == ()


def test_qq_pic_subtype_conflicting_values_are_not_classified():
    message = _parse(_scalar(45002, 2) + _scalar(45003, 0) + _scalar(45003, 1)
                     + _bytes(45406, b"\xab" * 16))
    assert message.contents[0].sticker is None
    assert collect([message]) == ()


@pytest.mark.parametrize("fields,want", [
    (_bytes(45406, b"\xab" * 16), "ab" * 16),
    (_bytes(45406, b"\xab" * 16) + _bytes(45424, b"AB" * 16), "ab" * 16),
    (_bytes(45406, b"\xab" * 16) + _bytes(45424, b"\xab" * 16), "ab" * 16),
    (_bytes(45424, b"ab" * 16), None),
    (_bytes(45406, b"\xab" * 16) + _bytes(45424, b"invalid"), None),
    (_bytes(45406, b"x" * 16) + _bytes(45406, b"\xab" * 16), None),
    (_bytes(45406, b"\xab" * 16) + _bytes(45424, b"cd" * 16)
     + _bytes(45424, b"ab" * 16), None),
])
def test_qq_pic_digest_evidence_is_consistent_and_does_not_authorize_sticker_classification(fields, want):
    message = _parse(_scalar(45002, 2) + fields)
    media = message.contents[0].media
    assert (media.content_md5 if media is not None else None) == want
    assert collect([message]) == ()


@pytest.mark.parametrize("fields", [
    b"",
    _bytes(45424, b"ab" * 16),
    _bytes(45406, b"\xab" * 16) + _bytes(45424, b"cd" * 16),
    _bytes(45406, b"\xab" * 16) + _bytes(45406, b"\xcd" * 16),
    _bytes(45406, b"\xab" * 16) + _bytes(45424, b"invalid"),
])
def test_qq_custom_pic_without_reliable_digest_keeps_send_but_never_merges(fields):
    message = _parse(_scalar(45002, 2) + _scalar(45003, 1) + fields)
    sends = collect([message, message])
    assert len(sends) == 2
    assert {send.identity_key for send in sends} == {None}
    assert {send.content_md5 for send in sends} == {None}
    assert sends[0].media_key == "unresolved:" + sends[0].occurrence_id
    assert sends[0].media_key != sends[1].media_key
    assert sends[0].identity_basis == "unresolved"
    assert all(item.status == "unsupported" for item in resolve(sends))


def test_official_chain_adds_only_custom_pic_and_keeps_legacy_semantics(tmp_path, monkeypatch):
    from test_rich_filtering_association import analyze
    digest = "cd" * 16
    custom = _scalar(45002, 2) + _scalar(45003, 1) + _bytes(45406, bytes.fromhex(digest))
    ordinary = _scalar(45002, 2) + _scalar(45003, 0) + _bytes(45406, b"\xab" * 16)
    result, (messages, analyzed) = analyze(tmp_path, monkeypatch, [_payload(
        _body(_text("Fictional remark about the first day"), custom),
        _body(_text("Fictional note on the second attempt"), custom),
        _body(_text("Fictional comment on another image"), ordinary))])
    assert [message.message_type for message in messages] == ["mixed"] * 3
    assert len(result.stickers.sends) == 2
    assert {send.identity_key for send in result.stickers.sends} == {"qq-pic:md5:" + digest}
    assert len(result.stickers.media) == 1
    assert result.stickers.media[0].status == "not_requested"
    assert result.reports.expression.expression_occurrence_count == 0
    assert not any(token.startswith("expression:")
                   for _, tokens in analyzed.sender_tokens for token in tokens)


def _private_payload(*blobs, senders):
    payload = _payload(*blobs, session_type="private")
    for record, sender in zip(payload["records"], senders):
        record["fields"]["40033"] = sender
    return payload


def test_group_pic_facts_keep_members_shared_material_and_unknowns():
    from qq_chat_analyzer.analysis.stickers import count_sticker_messages
    from qq_chat_analyzer.analysis.stickers import StickerData, aggregate_stickers
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages

    custom = _scalar(45002, 2) + _scalar(45003, 1) + _bytes(45406, b"\xab" * 16)
    unresolved = _scalar(45002, 2) + _scalar(45003, 1)
    ordinary = _scalar(45002, 2) + _scalar(45003, 0) + _bytes(45406, b"\xab" * 16)
    payload = _payload(*map(_body, (
        custom, custom, custom, custom, custom, ordinary, unresolved, unresolved, custom)))
    payload["self"] = {"namespace": "qq_uin", "value": "10001"}
    for record, sender in zip(payload["records"], (
            "10001", "10001", "20002", "20002", "30003", "30003", "20002", "30003", 0)):
        record["fields"]["40033"] = sender
    messages, warnings = parse_qq_db_rich_messages(payload)
    assert not warnings
    sends = collect(messages)
    assert len(sends) == 8
    assert [(s.sender_id, s.is_self) for s in sends[:5]] == [
        ("10001", True), ("10001", True), ("20002", False), ("20002", False), ("30003", False)]
    assert sends[-1].sender_id is None and sends[-1].is_self is None
    assert all(s.conversation_type == "group" and s.conversation_id == "fictional-room" for s in sends)
    assert sends[0].message_id == "fictional-0" and sends[0].epoch_seconds == 1760000000
    assert sends[0].content_md5 == "ab" * 16 and sends[0].chat_date is not None
    report, = aggregate_stickers(StickerData(sends=sends), messages)
    shared, = report.materials
    assert shared.count == 6
    assert dict(shared.member_counts) == {"10001": 2, "20002": 2, "30003": 1}
    assert shared.unknown_sender_count == 1
    assert report.unknown_identity_count == 2
    assert count_sticker_messages(messages).total_messages == 9
    # Missing self identity must not erase independently known members.
    payload.pop("self")
    messages, _ = parse_qq_db_rich_messages(payload)
    report, = aggregate_stickers(StickerData(sends=collect(messages)), messages)
    shared, = report.materials
    assert dict(shared.member_counts) == {"10001": 2, "20002": 2, "30003": 1}
    assert shared.unknown_sender_count == 1


def test_qq_private_send_identity_follows_source_self_marker_only():
    from qq_chat_analyzer.analysis.stickers import count_sticker_messages
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
    payload = _private_payload(
        _body(_sticker(b"mine")), _body(_sticker(b"theirs")),
        _body(_sticker(b"opaque")), senders=("10001", "20002", 0))
    payload["self"] = {"namespace": "qq_uin", "value": "10001"}
    messages, warnings = parse_qq_db_rich_messages(payload)
    assert warnings == ()
    sends = collect(messages)
    assert [send.is_self for send in sends] == [True, False, None]
    assert [send.sender_id for send in sends] == ["10001", "20002", None]
    counts = count_sticker_messages(messages)
    assert (counts.self_messages, counts.other_messages,
            counts.unknown_messages) == (1, 1, 1)
    assert counts.total_messages == 3


def test_unknown_self_identity_is_never_inferred_from_participants():
    from qq_chat_analyzer.analysis.stickers import count_sticker_messages
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
    messages, _ = parse_qq_db_rich_messages(_private_payload(
        _body(_sticker(b"first")), _body(_sticker(b"second")),
        senders=("10001", "20002")))
    sends = collect(messages)
    assert [send.is_self for send in sends] == [None, None]
    counts = count_sticker_messages(messages)
    assert (counts.self_messages, counts.other_messages,
            counts.unknown_messages) == (0, 0, 2)


def test_wechat_send_identity_requires_known_self_username():
    from qq_chat_analyzer.analysis.stickers import count_sticker_messages
    base = dict(local_type=47, username="fiction-room", create_time=1760000000,
                message_content='<msg><emoji md5="' + "a" * 32 + '"/></msg>')
    mine = wechat_db_adapter.parse_rich_message(dict(
        base, user_name="fiction-me", self_username="fiction-me", server_id="m1"))
    theirs = wechat_db_adapter.parse_rich_message(dict(
        base, user_name="fiction-peer", self_username="fiction-me", server_id="m2"))
    opaque = wechat_db_adapter.parse_rich_message(dict(
        base, user_name="fiction-peer", server_id="m3"))
    sends = collect([mine, theirs, opaque])
    assert [send.is_self for send in sends] == [True, False, None]
    assert [send.classification_basis for send in sends] == ["wechat_type_47"] * 3
    counts = count_sticker_messages([mine, theirs, opaque])
    assert (counts.self_messages, counts.other_messages,
            counts.unknown_messages) == (1, 1, 1)


@pytest.mark.parametrize("segments", [
    (_sticker(b"one"), _sticker(b"two")),
    (_scalar(45002, 2) + _scalar(45003, 1) + _bytes(45406, b"\xab" * 16),
     _scalar(45002, 2) + _scalar(45003, 1) + _bytes(45406, b"\xcd" * 16)),
])
def test_message_counts_count_message_once_while_sends_stay_per_content(segments):
    from qq_chat_analyzer.analysis.stickers import count_sticker_messages
    message = _parse(*segments)
    sends = collect([message])
    counts = count_sticker_messages([message])
    assert len(sends) == len(segments) == 2
    assert (counts.total_messages, counts.unknown_messages) == (1, 1)


def test_private_chain_denominators_match_kept_messages_and_sends(tmp_path, monkeypatch):
    from test_rich_filtering_association import analyze
    payload = _private_payload(
        _body(_text("Fictional morning note from me"), _sticker(b"mine")),
        _body(_text("Fictional reply from the other side"), _sticker(b"theirs")),
        _body(_text("Filtered " + "z" * 110)),
        _body(_text("Unattributed message body")),
        senders=("10001", "20002", "20002", "0"))
    payload["self"] = {"namespace": "qq_uin", "value": "10001"}
    result, (messages, _) = analyze(tmp_path, monkeypatch, [payload])
    counts = result.stickers.message_counts
    assert counts.total_messages == len(messages)
    assert result.diagnostic_counts.analyzed_message_count == len(messages)
    assert [send.is_self for send in result.stickers.sends] == [True, False]
    assert (counts.self_messages, counts.other_messages,
            counts.unknown_messages) == (1, 1, 1)


def test_decode_finishing_after_deadline_cannot_publish_success(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media
    raw = image_bytes()
    (tmp_path / "original").write_bytes(raw)
    elapsed = [0]
    inspect = sticker_media._inspect
    def delayed_inspect(*args, **kwargs):
        result = inspect(*args, **kwargs)
        elapsed[0] = 11
        return result
    monkeypatch.setattr(sticker_media.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(sticker_media, "_inspect", delayed_inspect)
    item = resolve(collect([wx(hashlib.md5(raw).hexdigest())]), (tmp_path,))[0]
    assert (item.status, item.reason) == ("limited", "scan_budget")
    assert item.original_bytes is None


def test_batch_association_reuses_one_scan_and_preserves_send_facts(tmp_path, monkeypatch, caplog):
    from qq_chat_analyzer.analysis.stickers import StickerData, StickerMessageCounts
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.application import sticker_media

    raws = (image_bytes("PNG"), image_bytes("GIF", animated=True))
    digests = [hashlib.md5(raw).hexdigest() for raw in raws]
    sends = tuple(qq_pic(digest) for digest in digests for _ in range(4))
    for digest, raw in zip(digests, raws):
        (tmp_path / f"{digest}.bin").write_bytes(raw)
    data = StickerData(sends=sends, message_counts=StickerMessageCounts(self_messages=8))
    scans, decodes = [], []
    real_scan, real_inspect = sticker_media.os.scandir, sticker_media._inspect

    def scan(path):
        scans.append(path)
        return real_scan(path)

    def inspect(raw, **kwargs):
        decodes.append(raw)
        return real_inspect(raw, **kwargs)

    monkeypatch.setattr(sticker_media.os, "scandir", scan)
    monkeypatch.setattr(sticker_media, "_inspect", inspect)
    caplog.set_level("INFO", logger="qq_chat_analyzer.desktop.analysis_diagnostics")
    result = ChatAnalyzerFacade.associate_sticker_media(
        data, media_keys=tuple(dict.fromkeys(s.media_key for s in sends)),
        roots=(tmp_path,), source="qq")
    assert result.sends is data.sends and result.message_counts is data.message_counts
    assert {m.original_bytes for m in result.media} == set(raws)
    assert scans == [tmp_path] and len(decodes) == 2
    timing_lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[analysis-timing]")]
    assert len(timing_lines) == 1
    assert re.fullmatch(r"\[analysis-timing\] stage=sticker_media_associate elapsed_ms=\d+", timing_lines[0])
    caplog.clear()
    with caplog.at_level("WARNING", logger="qq_chat_analyzer.desktop.analysis_diagnostics"):
        again = ChatAnalyzerFacade.associate_sticker_media(
            result, media_keys=tuple(m.media_key for m in result.media),
            roots=(tmp_path,), source="qq")
    assert again == result and scans == [tmp_path] and len(decodes) == 2
    assert not [r for r in caplog.records if r.getMessage().startswith("[analysis-timing]")]


def test_batch_rejects_oversized_selection_before_io(tmp_path, monkeypatch):
    from qq_chat_analyzer.analysis.stickers import StickerData
    from qq_chat_analyzer.application.sticker_media import associate_sticker_media
    from qq_chat_analyzer.application import sticker_media
    data = StickerData(sends=tuple(qq_pic(f"{i:032x}") for i in range(33)))
    monkeypatch.setattr(sticker_media.os, "scandir", lambda *a: pytest.fail("invalid batch"))
    with pytest.raises(ValueError, match="invalid_sticker_batch"):
        associate_sticker_media(data, media_keys=tuple(s.media_key for s in data.sends),
                                roots=(tmp_path,), source="qq")


def test_batch_memory_ceiling_applies_across_pages(tmp_path, monkeypatch):
    from qq_chat_analyzer.analysis.stickers import StickerData
    from qq_chat_analyzer.application import sticker_media
    raws = (image_bytes("PNG"), image_bytes("GIF", animated=True))
    sends = tuple(qq_pic(hashlib.md5(raw).hexdigest()) for raw in raws)
    for send, raw in zip(sends, raws):
        (tmp_path / f"{send.content_md5}.dat").write_bytes(raw)
    monkeypatch.setattr(sticker_media, "MAX_RETAINED_MEDIA_BYTES", len(raws[0]))
    first = sticker_media.associate_sticker_media(StickerData(sends=sends),
        media_keys=(sends[0].media_key,), roots=(tmp_path,), source="qq")
    second = sticker_media.associate_sticker_media(first,
        media_keys=(sends[1].media_key,), roots=(tmp_path,), source="qq")
    by_key = {item.media_key: item for item in second.media}
    assert by_key[sends[0].media_key].original_bytes == raws[0]
    assert (by_key[sends[1].media_key].status, by_key[sends[1].media_key].reason) == (
        "limited", "total_byte_budget")


def test_global_decode_and_file_budgets_are_shared_by_materials(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.application.sticker_media import resolve_sticker_media
    raws = (image_bytes("PNG"), image_bytes("GIF", animated=True))
    sends = tuple(qq_pic(hashlib.md5(raw).hexdigest()) for raw in raws)
    for send, raw in zip(sends, raws):
        (tmp_path / f"{send.content_md5}.dat").write_bytes(raw)
    items = resolve_sticker_media(sends, roots=(tmp_path,), targeted=True,
        digest_names_only=True, max_total_frames=1)
    assert [item.status for item in items] == ["available", "limited"]
    assert items[1].reason == "total_decode_budget" and items[1].original_bytes is None
    monkeypatch.setattr(sticker_media, "MAX_TOTAL_DECODE_WORK", sticker_media.DECODE_FRAME_COST + 6)
    items = resolve_sticker_media(sends, roots=(tmp_path,), targeted=True,
        digest_names_only=True)
    assert [item.status for item in items] == ["available", "limited"]
    assert items[1].reason == "total_decode_budget" and items[1].original_bytes is None
    items = resolve_sticker_media(sends, roots=(tmp_path,), targeted=True,
        digest_names_only=True, max_files=1)
    assert all((item.status, item.reason) == ("limited", "file_count_budget") for item in items)


def test_qq_59_authorized_scopes_are_all_searched_without_expanding_consent(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from qq_chat_analyzer.analysis.stickers import StickerData
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade

    account = tmp_path / "12345001"
    data = account / "nt_qq/nt_data"
    originals = []
    raw = image_bytes("PNG")
    digest = hashlib.md5(raw).hexdigest()
    for base in (data / "Pic", data / "Emoji/emoji-recv"):
        for index in range(29):
            month = base / f"{2024 + index // 12}-{1 + index % 12:02}"
            ori = month / "Ori"
            ori.mkdir(parents=True)
            original = ori / f"{digest}.png"
            original.write_bytes(raw)
            originals.append(original)
            thumb = month / "Thumb"
            thumb.mkdir()
            (thumb / f"{digest}.png").write_bytes(raw)
    personal = data / "Emoji/personal_emoji/Ori"
    personal.mkdir(parents=True)
    original = personal / f"{digest}.png"
    original.write_bytes(raw)
    originals.append(original)
    roots = tuple(path.parent for path in originals)
    assert len(roots) == 59
    # A new month outside the supplied roots is not part of the user's consent.
    unapproved = data / "Pic/2030-01/Ori"
    unapproved.mkdir(parents=True)
    (unapproved / f"{digest}.png").write_bytes(raw)
    opened = []
    real_open = sticker_media._open_original
    real_scan = sticker_media.os.scandir

    @contextmanager
    def approved_only(path, root):
        assert path in originals
        opened.append(path)
        with real_open(path, root) as stream:
            yield stream

    def scan_approved_only(path):
        assert "Thumb" not in path.parts
        assert not path.is_relative_to(unapproved.parent)
        return real_scan(path)

    monkeypatch.setattr(sticker_media, "_open_original", approved_only)
    monkeypatch.setattr(sticker_media.os, "scandir", scan_approved_only)
    data = StickerData(sends=(qq_pic(digest),))
    result = ChatAnalyzerFacade.associate_sticker_media(
        data, media_keys=(data.sends[0].media_key,), roots=roots, source="qq")
    media, = result.media
    assert media.status == "available", (media.status, media.reason)
    assert media.original_bytes == raw
    assert set(opened) == set(originals) and len(opened) == 59
