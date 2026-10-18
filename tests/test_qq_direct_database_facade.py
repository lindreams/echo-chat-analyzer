"""Direct DB QQ facade regression coverage using only fictional data."""

from __future__ import annotations

from io import BytesIO
import hashlib
import sqlite3
from pathlib import Path
import pytest

from qq_chat_analyzer.analysis.stickers import StickerData, StickerSend
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.facade import (
    AnalysisConfig,
    ChatAnalyzerFacade,
    ChatSource,
    FacadeError,
)
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
)

from qq_direct_db_testing import FakeSnapshotRuntime


@pytest.mark.parametrize("fails", [False, True])
def test_qq_facade_conversion_diagnostics_preserve_results_and_errors(tmp_path, monkeypatch, caplog, fails):
    from qq_chat_analyzer.application import facade as module
    snapshot = tmp_path / "fictional.db"
    _create_plaintext_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    facade = ChatAnalyzerFacade(qq_service=QQDirectDatabaseImportService(runtime_client=runtime))
    error = ValueError("PRIVATE_CONVERSION path account token")
    if fails:
        def convert(*args):
            raise error
        monkeypatch.setattr(module, "_to_session_info", convert)
    with caplog.at_level("INFO"):
        if fails:
            with pytest.raises(ValueError) as caught:
                facade.list_sessions(ChatSource.QQ)
            assert caught.value is error
        else:
            assert len(facade.list_sessions(ChatSource.QQ)) == 2
    log = "\n".join(r.getMessage() for r in caplog.records if "[qq sessions]" in r.getMessage())
    assert "stage=facade_convert outcome=started" in log
    assert f"stage=facade_convert outcome={'failed' if fails else 'success'}" in log
    assert "PRIVATE" not in log and str(tmp_path) not in log
    assert runtime.cleaned == ["gen-0001"]


def _varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def _message_blob(text: str) -> bytes:
    segment = (
        _varint((45002 << 3) | 0)
        + _varint(1)
        + _field(45101, text.encode("utf-8"))
    )
    return _field(40800, segment)


def _create_plaintext_snapshot(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for table_name in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'''CREATE TABLE {table_name} (
                    "40001" INTEGER PRIMARY KEY,
                    "40027" TEXT NOT NULL,
                    "40030" TEXT NOT NULL,
                    "40033" TEXT NOT NULL,
                    "40050" INTEGER NOT NULL,
                    "40800" BLOB NOT NULL
                )'''
            )
        connection.execute(
            '''INSERT INTO group_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            (101, "group-partition", "fictional-group", "fictional-group-sender", 1760000001, _message_blob("fictional group message")),
        )
        connection.execute(
            '''INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            (201, "private-partition", "fictional-peer", "fictional-private-sender", 1760000002, _message_blob("fictional private message")),
        )


def test_direct_db_group_and_private_sessions_reach_existing_echo_pipeline(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "plaintext-qq.db"
    _create_plaintext_snapshot(snapshot_path)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot_path)
    direct_service = QQDirectDatabaseImportService(runtime_client=runtime)
    facade = ChatAnalyzerFacade(
        qq_service=direct_service,
        analysis_service=AnalysisApplicationService(),
        stopwords_directory=Path(__file__).resolve().parents[1],
    )

    sessions = {item.session_type: item for item in facade.list_sessions(ChatSource.QQ)}
    assert set(sessions) == {"group", "private"}

    for session_type in ("group", "private"):
        outcome = facade.analyze_session(
            ChatSource.QQ,
            sessions[session_type].session_id,
            AnalysisConfig(output_directory=tmp_path / f"{session_type}-report"),
        )

        assert outcome.session is not None
        assert outcome.session.session_type == session_type
        assert outcome.result.processed_message_count > 0
        assert outcome.report_path is not None and outcome.report_path.is_file()


def _create_private_pic_snapshot(path: Path, digest: bytes = b"\xab" * 16) -> None:
    segment = (
        _varint((45002 << 3) | 0) + _varint(2)
        + _varint((45001 << 3) | 0) + _varint(7000000000000000001)
        + _field(45503, b"fictional-file-uuid")
        + _field(45406, digest)
        + _varint((45003 << 3) | 0) + _varint(1)
    )
    with sqlite3.connect(path) as connection:
        for table_name in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'''CREATE TABLE {table_name} (
                    "40001" INTEGER PRIMARY KEY,
                    "40021" TEXT,
                    "40020" TEXT,
                    "40027" TEXT NOT NULL,
                    "40030" TEXT NOT NULL,
                    "40033" TEXT NOT NULL,
                    "40050" INTEGER NOT NULL,
                    "40800" BLOB NOT NULL
                )'''
            )
        connection.execute(
            '''INSERT INTO c2c_msg_table
                ("40001", "40021", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (
                201, "u_fictionalpeer000000000000", "private-partition",
                "fictional-peer", "10087", 1760000001, _field(40800, segment),
            ),
        )


# --------------------------------------------------- QQ PIC media fetch

_PIC_KEY_BYTES = b"\xab" * 16


def _fictional_png() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (7, 5), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _pic_send(digest_hex: str) -> StickerSend:
    return StickerSend(
        occurrence_id="0:0", source="qq", conversation_id="private-partition",
        conversation_type="private", sender_id="fictional-peer", is_self=False,
        message_id="201", content_index=0, timestamp=1760000001,
        epoch_seconds=1760000001, chat_date="2025-10-09",
        classification_basis="qq_pic_45003_custom", identity_basis="qq_pic_45406_md5",
        identity_key=f"qq-pic:md5:{digest_hex}", media_key=f"qq-pic:md5:{digest_hex}",
        content_md5=digest_hex,
    )


class _PicProvider:
    def __init__(self, content: bytes, *, mapping_passed: bool = True,
                 download_error: Exception | None = None) -> None:
        self.content = content
        self.mapping_passed = mapping_passed
        self.download_error = download_error
        self.calls = []

    def resolve_pic_message(self, **kwargs):
        from qq_chat_analyzer.providers.napcat_qq_provider import PicMessageMapping

        self.calls.append(("resolve", kwargs))
        return PicMessageMapping(
            passed=self.mapping_passed, found=True, unique=True, msg_id_matches=True,
            time_matches=True, peer_matches=True, sender_matches=True,
            pic_element_count=1, matched_pic_count=1, segment_id_matches=True,
            file_uuid_matches=True, md5_matches=self.mapping_passed,
            match_basis="segment_id+file_uuid+md5",
        )

    def download_pic_media(self, **kwargs):
        self.calls.append(("download", kwargs))
        if self.download_error is not None:
            raise self.download_error
        return self.content


class _ProviderConnection:
    def __init__(self, provider) -> None:
        self._provider = provider

    def provider(self):
        return self._provider


def _fetch_facade(tmp_path, *, digest: bytes, content: bytes, mapping_passed: bool = True,
                  download_error: Exception | None = None, group_sender: str | None = None):
    snapshot_path = tmp_path / "plaintext-qq.db"
    _create_private_pic_snapshot(snapshot_path, digest=digest)
    if group_sender is not None:
        with sqlite3.connect(snapshot_path) as db:
            db.execute('''INSERT INTO group_msg_table
                ("40001", "40020", "40021", "40027", "40030", "40033", "40050", "40800")
                SELECT "40001", ?, '12345001', 'group-partition', '12345001', ?, "40050", "40800"
                FROM c2c_msg_table''', ("u_fictionalmember000000", group_sender))
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot_path)
    service = QQDirectDatabaseImportService(runtime_client=runtime)
    service.start()
    provider = _PicProvider(
        content, mapping_passed=mapping_passed, download_error=download_error)
    facade = ChatAnalyzerFacade(
        qq_service=service, qq_connection_service=_ProviderConnection(provider),
        analysis_service=AnalysisApplicationService(), stopwords_directory=Path(__file__).resolve().parents[1])
    return facade, provider, runtime


@pytest.mark.parametrize("mine", [False, True])
@pytest.mark.parametrize("original", [False, True])
def test_group_analyzed_send_reaches_native_fetch_after_identity_check(tmp_path, mine, original):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest() if original else _PIC_KEY_BYTES.hex()
    sender = "10086" if mine else "10087"
    facade, provider, runtime = _fetch_facade(tmp_path, digest=bytes.fromhex(digest), content=png, group_sender=sender)
    result = facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                   AnalysisConfig(output_directory=tmp_path / "report")).result
    send, = result.stickers.sends
    assert send.sender_id == sender and send.is_self is mine
    data = facade.fetch_qq_sticker_media(result.stickers, media_key=send.media_key,
                                       session_id="group:group-partition", network_consent=True, occurrence_id=send.occurrence_id)
    assert data.sends is result.stickers.sends
    media, = data.media
    assert media.original_bytes == png and media.status == ("available" if original else "preview")
    query, download = provider.calls
    assert query[0] == "resolve" and download[0] == "download"
    assert query[1]["chat_type"] == download[1]["chat_type"] == 2
    assert query[1]["peer_uid"] == download[1]["peer_uid"] == "12345001"
    assert query[1]["expected_sender_uin"] == sender
    assert query[1]["expected_sender_uid"] == "u_fictionalmember000000"
    assert runtime.acquired == runtime.cleaned


@pytest.mark.parametrize("field,value,code", [
    ("sender_matches", None, "sender"), ("file_uuid_matches", None, "uuid"),
    ("segment_id_matches", False, "element"),
])
def test_group_facade_requires_each_identity_proof_even_with_passed_label(tmp_path, monkeypatch, field, value, code):
    from dataclasses import replace
    facade, provider, runtime = _fetch_facade(tmp_path, digest=_PIC_KEY_BYTES,
                                            content=_fictional_png(), group_sender="10087")
    data = facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                 AnalysisConfig(output_directory=tmp_path / "report")).result.stickers
    resolve = provider.resolve_pic_message
    monkeypatch.setattr(provider, "resolve_pic_message", lambda **kwargs: replace(resolve(**kwargs), **{field: value}))
    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(data, media_key=data.sends[0].media_key,
                                     session_id="group:group-partition", network_consent=True)
    assert caught.value.code == f"qq_media_group_{code}_unconfirmed"
    assert [name for name, _ in provider.calls] == ["resolve"]
    assert runtime.acquired == runtime.cleaned


@pytest.mark.parametrize("changed", ["sender_id", "conversation_id", "timestamp", "is_self", "session"])
def test_group_fetch_refuses_scope_or_analyzed_send_change_before_rpc(tmp_path, changed):
    from dataclasses import replace
    facade, provider, runtime = _fetch_facade(tmp_path, digest=_PIC_KEY_BYTES,
                                            content=_fictional_png(), group_sender="10087")
    data = facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                 AnalysisConfig(output_directory=tmp_path / "report")).result.stickers
    changes = {"sender_id": "10088", "conversation_id": "12345002", "timestamp": 1760000002, "is_self": True}
    session = "private:private-partition" if changed == "session" else "group:group-partition"
    if changed != "session":
        data = replace(data, sends=(replace(data.sends[0], **{changed: changes[changed]}),))
    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(data, media_key=data.sends[0].media_key, session_id=session, network_consent=True)
    assert caught.value.code.startswith("qq_media_group_")
    assert not provider.calls and all(m.original_bytes is None for m in data.media)
    assert runtime.acquired == runtime.cleaned


def test_fetched_pic_requires_separate_consent_then_reports_a_verified_original(tmp_path):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest()
    data = StickerData(sends=(_pic_send(digest),))
    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=bytes.fromhex(digest), content=png)
    key = data.sends[0].media_key

    with pytest.raises(FacadeError) as refused:
        facade.fetch_qq_sticker_media(
            data, media_key=key, session_id="private:private-partition")
    assert refused.value.code == "qq_media_consent_required"
    assert provider.calls == []

    result = facade.fetch_qq_sticker_media(
        data, media_key=key, session_id="private:private-partition", network_consent=True)

    media, = result.media
    assert (media.status, media.reason) == ("available", None)
    assert media.original_bytes == png and media.format == "PNG"
    assert result.sends is data.sends and result.message_counts == data.message_counts
    expected = {
        "msg_id": "201", "peer_uid": "u_fictionalpeer000000000000",
        "expected_time": 1760000001, "expected_md5": digest,
        "expected_file_uuid": "fictional-file-uuid", "expected_self": False,
    }
    element_id = "7000000000000000001"
    assert provider.calls == [
        ("resolve", {**expected, "expected_segment_id": element_id}),
        ("download", {**expected, "element_id": element_id}),
    ]
    assert len(runtime.cleaned) == 1


def test_digest_mismatch_stays_a_distinct_trusted_preview(tmp_path):
    png = _fictional_png()
    data = StickerData(sends=(_pic_send(_PIC_KEY_BYTES.hex()),))
    facade, _provider, _runtime = _fetch_facade(
        tmp_path, digest=_PIC_KEY_BYTES, content=png)

    result = facade.fetch_qq_sticker_media(
        data, media_key=data.sends[0].media_key,
        session_id="private:private-partition", network_consent=True)

    media, = result.media
    assert (media.status, media.reason) == ("preview", "content_digest_mismatch")
    assert media.original_bytes == png and media.format == "PNG"


def test_group_media_is_refused_before_acquisition_or_rpc(tmp_path, monkeypatch):
    from dataclasses import replace

    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=_PIC_KEY_BYTES, content=_fictional_png())
    data = StickerData(sends=(replace(_pic_send(_PIC_KEY_BYTES.hex()), conversation_type="group"),))
    monkeypatch.setattr(facade, "_qq_stored_pic_facts",
                        lambda *_: pytest.fail("group media must not acquire a snapshot"))
    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(
            data, media_key=data.sends[0].media_key, session_id="group:fictional", network_consent=True)
    assert caught.value.code == "qq_media_invalid_selection"
    assert not provider.calls and not runtime.cleaned and not data.media


def test_group_fetched_gif_decode_limit_has_a_specific_public_error(tmp_path, monkeypatch):
    from PIL import Image
    from qq_chat_analyzer.application import sticker_media

    monkeypatch.setattr(sticker_media, "MAX_DECODE_WORK", 64 * 1024)

    stream = BytesIO()
    images = [Image.new("RGB", (2, 2), "red" if index % 2 else "blue")
              for index in range(129)]
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:], duration=100)
    raw = stream.getvalue()
    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=hashlib.md5(raw).digest(), content=raw, group_sender="10086")
    data = facade.analyze_session(
        ChatSource.QQ, "group:group-partition",
        AnalysisConfig(output_directory=tmp_path / "report")).result.stickers
    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(
            data, media_key=data.sends[0].media_key,
            session_id="group:group-partition", network_consent=True)
    assert caught.value.code == "qq_media_decode_budget"
    assert "解码安全预算" in caught.value.public_message
    assert all(media.original_bytes is None for media in data.media)
    assert [name for name, _ in provider.calls] == ["resolve", "download"]
    assert runtime.acquired == runtime.cleaned


@pytest.mark.parametrize("failure", ["mapping", "content"])
def test_unconfirmed_mapping_or_undecodable_content_is_never_displayed(tmp_path, failure):
    png = _fictional_png()
    if failure == "mapping":
        digest = hashlib.md5(png).hexdigest()
        facade, provider, _runtime = _fetch_facade(
            tmp_path, digest=bytes.fromhex(digest), content=png, mapping_passed=False)
        data = StickerData(sends=(_pic_send(digest),))
        expected = "qq_media_mapping_rejected"
    else:
        garbage = b"fictional-not-an-image"
        digest = hashlib.md5(garbage).hexdigest()
        facade, provider, _runtime = _fetch_facade(
            tmp_path, digest=bytes.fromhex(digest), content=garbage)
        data = StickerData(sends=(_pic_send(digest),))
        expected = "qq_media_invalid_content"

    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(
            data, media_key=data.sends[0].media_key,
            session_id="private:private-partition", network_consent=True)

    assert caught.value.code == expected
    assert not data.media
    if failure == "mapping":
        assert [name for name, _ in provider.calls] == ["resolve"]


@pytest.mark.parametrize("stage,code,visible", [
    ("media_download_timeout", "qq_media_download_timeout", "限定时间"),
    ("media_download_failed", "qq_media_download_failed", "下载接口返回失败"),
    ("media_path_invalid", "qq_media_path_invalid", "不可安全读取"),
    ("media_file_missing", "qq_media_file_missing", "已不存在"),
    ("media_open_failed", "qq_media_open_failed", "无法打开"),
    ("media_file_type_rejected", "qq_media_file_type_rejected", "不是常规文件"),
    ("media_file_identity_changed", "qq_media_file_identity_changed", "不同文件"),
    ("media_file_empty", "qq_media_file_empty", "为空"),
    ("media_file_too_large", "qq_media_too_large", "2 MiB"),
    ("media_read_incomplete", "qq_media_read_incomplete", "读取不完整"),
    ("media_file_changed", "qq_media_file_changed", "读取过程中发生变化"),
    ("media_file_rejected", "qq_media_file_rejected", "其他安全校验"),
    ("media_api_unavailable", "qq_media_api_unavailable", "不支持图片下载接口"),
    ("media_busy", "qq_media_busy", "尚未结束"),
    ("media_budget_exhausted", "qq_media_budget_exhausted", "次数已用完"),
    ("media_message_query_failed", "qq_media_message_query_failed", "消息查询失败"),
])
def test_fetch_failure_names_the_stage_instead_of_one_generic_message(
        tmp_path, stage, code, visible):
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQMediaStageError

    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest()
    data = StickerData(sends=(_pic_send(digest),))
    facade, _provider, _runtime = _fetch_facade(
        tmp_path, digest=bytes.fromhex(digest), content=png,
        download_error=NapCatQQMediaStageError(stage))

    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(
            data, media_key=data.sends[0].media_key,
            session_id="private:private-partition", network_consent=True)

    assert caught.value.code == code
    assert visible in caught.value.public_message


def test_unknown_fetch_failure_stays_generic_and_never_leaks_details(tmp_path):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest()
    data = StickerData(sends=(_pic_send(digest),))
    facade, _provider, _runtime = _fetch_facade(
        tmp_path, digest=bytes.fromhex(digest), content=png,
        download_error=RuntimeError("PRIVATE C:/fictional/secret 201"))

    with pytest.raises(FacadeError) as caught:
        facade.fetch_qq_sticker_media(
            data, media_key=data.sends[0].media_key,
            session_id="private:private-partition", network_consent=True)

    assert caught.value.code == "qq_media_fetch_failed"
    message = caught.value.public_message
    assert "未返回可用的图片内容" in message
    assert "PRIVATE" not in message and "secret" not in message and "201" not in message
