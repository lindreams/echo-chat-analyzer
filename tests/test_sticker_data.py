"""Confirmed sends and byte-verified originals, using only fictional inputs."""
from io import BytesIO
import hashlib
import json
import os
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


def wx(md5=None, *, message_id="duplicate", timestamp=1760000000):
    return wechat_db_adapter.parse_rich_message(dict(
        local_type=47, user_name="fiction-sender", username="fiction-room",
        create_time=timestamp, server_id=message_id,
        message_content=f'<msg><emoji md5="{md5 or ""}"/></msg>',
    ))


def collect(messages):
    from qq_chat_analyzer.analysis.stickers import collect_sticker_sends
    return collect_sticker_sends(messages)


def resolve(sends, roots=(), **limits):
    from qq_chat_analyzer.application.sticker_media import resolve_sticker_media
    return resolve_sticker_media(sends, roots=roots, **limits)


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


@pytest.mark.parametrize("fmt,animated,want", [
    ("PNG", False, "PNG"), ("JPEG", False, "JPEG"), ("GIF", True, "GIF"),
    ("PNG", True, "APNG"), ("WEBP", True, "WebP"),
])
def test_actual_format_original_bytes_and_duplicate_media(tmp_path, fmt, animated, want):
    raw = image_bytes(fmt, animated=animated)
    digest = hashlib.md5(raw).hexdigest()
    # Names and extensions are deliberately misleading; only bytes authorize a match.
    (tmp_path / "not-the-name.jpg").write_bytes(raw)
    (tmp_path / "duplicate.dat").write_bytes(raw)
    sends = collect([wx(digest), wx(digest)])
    media = resolve(sends, (tmp_path,))
    assert len(media) == 1
    item = media[0]
    assert item.status == "available" and item.reason is None
    assert item.format == want
    assert item.frame_count == (2 if animated else 1)
    assert item.animation_preserved is animated
    assert item.original_bytes == raw
    assert item.sha256 == hashlib.sha256(raw).hexdigest()
    assert item.byte_count == len(raw)
    assert item.verified_reference is not None
    assert item.original_bytes not in repr(item).encode()


def test_wrong_filename_digest_corrupt_media_and_missing_are_not_success(tmp_path):
    raw = image_bytes()
    expected = "a" * 32
    (tmp_path / (expected + ".gif")).write_bytes(raw)
    corrupt = b"GIF89a" + b"x" * 20
    (tmp_path / "broken").write_bytes(corrupt)
    sends = collect([wx(expected), wx(hashlib.md5(corrupt).hexdigest()), wx()])
    media = resolve(sends, (tmp_path,))
    assert [m.status for m in media] == ["missing", "invalid", "unsupported"]
    assert all(m.original_bytes is None for m in media)
    assert len(sends) == 3


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


def test_no_root_or_no_reliable_digest_never_opens_local_resources(tmp_path, monkeypatch):
    from qq_chat_analyzer.application import sticker_media

    def forbidden(*args, **kwargs):
        pytest.fail("Resource discovery must remain opt-in and digest-bound")

    monkeypatch.setattr(sticker_media.os, "scandir", forbidden)
    assert resolve(collect([wx("a" * 32)]))[0].status == "not_requested"
    assert resolve(collect([wx()]), (tmp_path,))[0].status == "unsupported"
    qq = _parse(_sticker() + _bytes(45812, b"../outside.gif"))
    assert resolve(collect([qq]), (tmp_path,))[0].status == "unsupported"


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


@pytest.mark.parametrize("stage", ["scope", "quality", "sender", "template"])
def test_qq_stickers_follow_every_message_filter_with_duplicate_ids(tmp_path, monkeypatch, stage):
    from datetime import date, datetime
    from qq_chat_analyzer.application.scope_filter import AnalysisScope
    from test_rich_filtering_association import analyze
    timestamp = int(datetime(2026, 1, 2, 12).timestamp())

    def row(text, identity=b"kept", sender="fiction-human", moment=timestamp):
        record = _payload(_body(_text(text), _sticker(identity)))["records"][0]
        record["record_id"] = "duplicate"
        record["fields"].update({"40033": sender, "40050": moment})
        return record

    rows = [row("Human authored")]
    scope = None
    if stage == "scope":
        rows.append(row("Outside", b"filtered", moment=1700000000))
        scope = AnalysisScope.custom(date(2026, 1, 2), date(2026, 1, 2))
    elif stage == "quality":
        rows.append(row("Filtered " + "z" * 110, b"filtered"))
    elif stage == "sender":
        rows.extend(row("固定签到播报", b"filtered", "fiction-robot", timestamp + i * 120)
                    for i in range(10))
    else:
        rows.extend(row(f"欢迎 虚构成员{member} 加入群聊", b"filtered", f"fiction-{member}")
                    for member in ("甲", "乙", "丙", "丁"))
    payload = _payload()
    payload["records"] = rows
    result, _ = analyze(tmp_path, monkeypatch, [payload], scope)
    assert len(result.stickers.sends) == 1
    assert result.stickers.sends[0].identity_key == (
        "qq-marketface:sha256:" + hashlib.sha256(b"kept").hexdigest())
    assert len(result.stickers.media) == 1


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


def test_wechat_configured_media_flows_through_provider_and_facade(tmp_path):
    from qq_chat_analyzer.application.facade import AnalysisConfig, ChatAnalyzerFacade, ChatSource
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfig, WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter,
    )
    from qq_chat_analyzer.application.wechat.wechat_provider_factory import WeChatProviderFactory
    from qq_chat_analyzer.application.wechat.wechat_export_import_service import WeChatExportImportService
    from qq_chat_analyzer.providers.wechat_database_provider import WeChatDatabaseProvider

    raw = image_bytes(animated=True)
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
    # Keep the real factory/provider wiring, replacing only database acquisition.
    provider.list_sessions = lambda: []
    def export(session_id, output_path, start_time=None, end_time=None):
        output_path.write_text(json.dumps(dict(
            source="wechat-db", conversation=dict(username=session_id), messages=[dict(
                local_type=47, server_id="fiction-id", create_time=1760000000,
                user_name="fiction-sender", message_content=f'<msg><emoji md5="{digest}"/></msg>',
            )],
        )), encoding="utf-8")
        return output_path
    provider.export_session_json = export
    facade = ChatAnalyzerFacade(
        wechat_service=WeChatExportImportService(provider_factory=factory),
        analysis_service=AnalysisApplicationService(),
    )
    outcome = facade.analyze_session(ChatSource.WECHAT, "fiction-room", AnalysisConfig(
        output_directory=tmp_path / "result",
    ))
    assert outcome.result.stickers.media[0].original_bytes == raw
    assert outcome.result.stickers.media[0].frame_count == 2
    opted_out = facade.analyze_session(ChatSource.WECHAT, "fiction-room", AnalysisConfig(
        output_directory=tmp_path / "no-media", sticker_media_roots=(),
    ))
    assert opted_out.result.stickers.media[0].status == "not_requested"
    assert len(opted_out.result.stickers.sends) == 1


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


def test_qq_pic_media_subtype_never_substitutes_for_napcat_pic_subtype():
    for subtype in (0, 1, 2):
        message = _parse(_scalar(45002, 2) + _scalar(45003, subtype)
                         + _bytes(45406, b"x" * 16) + _bytes(45424, b"79" * 16))
        assert collect([message]) == ()
        # Conflicting digest evidence cannot nominate an original.
        assert message.contents[0].media.content_md5 is None


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
