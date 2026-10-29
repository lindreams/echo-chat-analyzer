"""Direct DB QQ facade regression coverage using only fictional data."""

from __future__ import annotations

from io import BytesIO
import hashlib
import re
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
    SessionInfo,
)
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
)

from qq_direct_db_testing import FakeSnapshotRuntime
from qq_db_test_data import (
    encode_varint as _varint,
    length_delimited_field as _field,
    synthetic_text_message_blob as _message_blob,
)


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


@pytest.mark.parametrize("kind,local", [("private", False), ("group", False), ("group", True)])
def test_generate_qq_report_recovers_media_before_its_only_export(tmp_path, monkeypatch, kind, local):
    import json
    from qq_chat_analyzer.presentation import echo_serializer

    raw = _fictional_png()
    digest = hashlib.md5(raw).digest()
    facade, provider, runtime = _fetch_facade(tmp_path, digest=digest, content=raw,
                                             group_sender="10087" if kind == "group" else None)
    roots = tmp_path / "approved-originals"
    roots.mkdir()
    if local:
        (roots / f"{digest.hex()}.png").write_bytes(raw)
    exports = []
    original = echo_serializer.export_echo_report_html

    def export(view, path, **kwargs):
        exports.append(view)
        assert any(a.data_uri for a in view.stickers.assets)
        return original(view, path, **kwargs)

    monkeypatch.setattr("qq_chat_analyzer.application.analysis_service.export_echo_report_html", export)
    progress = []
    outcome = facade.analyze_session(ChatSource.QQ, f"{kind}:{kind}-partition",
                                    AnalysisConfig(output_directory=tmp_path / "output",
                                                   sticker_media_roots=(roots,)), progress=progress.append)
    assert len(exports) == 1
    assert len(runtime.acquired) == 1  # Same acquired payload for stats and media identity.
    assert len(provider.calls) == (0 if local else 2)
    chapter = json.loads((outcome.report_directory / "echo-report.json").read_text(encoding="utf-8"))["stickers"]
    asset, = chapter["assets"].values()
    assert asset["status"] == "available"
    assert asset["data_uri"].startswith("media/")
    assert (outcome.report_directory / asset["data_uri"]).read_bytes() == raw
    assert asset["data_uri"] in outcome.report_path.read_text(encoding="utf-8")
    assert "正在获取表情包素材..." in progress


@pytest.mark.parametrize("kind", ["private", "group"])
def test_report_uses_another_verified_send_when_the_first_copy_has_no_resource(tmp_path, monkeypatch, caplog, kind):
    import json
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQMediaStageError

    raw = _fictional_png()
    facade, provider, runtime = _fetch_facade(tmp_path, digest=hashlib.md5(raw).digest(), content=raw,
        group_sender="10087" if kind == "group" else None)
    table = "c2c_msg_table" if kind == "private" else "group_msg_table"
    with sqlite3.connect(tmp_path / "plaintext-qq.db") as db:
        db.execute(f'''INSERT INTO {table}
            ("40001", "40020", "40021", "40027", "40030", "40033", "40050", "40800")
            SELECT 202, "40020", "40021", "40027", "40030", "40033", "40050" + 1, "40800"
            FROM {table} WHERE "40001" = 201''')
    downloads = []
    download = provider.download_pic_media
    def fetch(**locator):
        downloads.append(locator["msg_id"])
        if locator["msg_id"] == "201":
            raise NapCatQQMediaStageError("media_download_no_path")
        return download(**locator)
    monkeypatch.setattr(provider, "download_pic_media", fetch)
    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.facade"):
        outcome = facade.analyze_session(ChatSource.QQ, f"{kind}:{kind}-partition",
            AnalysisConfig(output_directory=tmp_path / "report"))
    assert downloads == ["201", "202"]
    assert [(call[1]["msg_id"], call[1]["expected_time"]) for call in provider.calls if call[0] == "resolve"] == [
        ("201", 1760000001), ("202", 1760000002)]
    chapter = json.loads((outcome.report_directory / "echo-report.json").read_text("utf-8"))["stickers"]
    asset, = chapter["assets"].values()
    assert chapter["total_send_count"] == 2 and asset["status"] == "available"
    assert runtime.acquired == runtime.cleaned and len(runtime.acquired) == 1
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[sticker-media-candidate]")]
    assert len(lines) == 1 and "code=qq_media_download_no_path" in lines[0]
    assert str(tmp_path) not in lines[0] and hashlib.md5(raw).hexdigest() not in lines[0]


@pytest.mark.parametrize("limit", ["none", "many", "bridge", "time", "transport", "cancel"])
def test_report_batch_selects_top10_once_and_survives_failure_or_stops(
    tmp_path, monkeypatch, caplog, limit,
):
    import json
    from threading import Event
    from PIL import Image
    from qq_chat_analyzer.application import facade as module
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQError, NapCatQQMediaStageError

    raw = _fictional_png()
    initial = hashlib.md5(raw).digest()
    facade, provider, runtime = _fetch_facade(tmp_path, digest=initial, content=raw, group_sender="10087")
    by_digest = {}
    with sqlite3.connect(tmp_path / "plaintext-qq.db") as db:
        seed, = db.execute('SELECT "40800" FROM group_msg_table').fetchone()
        db.execute('DELETE FROM group_msg_table')
        for index in range(40 if limit == "many" else 12):
            stream = BytesIO()
            Image.new("RGB", (3, 2), (index * 5, 50, 80)).save(stream, format="PNG")
            content = stream.getvalue()
            digest = hashlib.md5(content).digest()
            by_digest[digest.hex()] = content
            for member in ((str(10086 + index // 8),) if limit == "many" else ("10086", "10087")):
                db.execute('''INSERT INTO group_msg_table
                    ("40001", "40020", "40021", "40027", "40030", "40033", "40050", "40800")
                    VALUES (?, 'u_fictionalmember000000', '12345001', 'group-partition', '12345001', ?, ?, ?)''',
                    (201 + index * 2 + (member == "10087"), member, 1760000001 + index,
                     seed.replace(initial, digest)))
    cancelled = Event()
    clock = [0.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    downloads = []
    if limit == "bridge":
        resolve = provider.resolve_pic_message
        throttled = [False, False]
        def limited_resolve(**locator):
            if len(downloads) == 3 and not throttled[1]:
                throttled[0] = True
                raise NapCatQQError("media_budget_exhausted")
            return resolve(**locator)
        def ready(**kwargs):
            if throttled[0]:
                throttled[1] = True
        monkeypatch.setattr(provider, "resolve_pic_message", limited_resolve)
        monkeypatch.setattr(provider, "wait_media_ready", ready, raising=False)

    def download(**locator):
        digest = locator["expected_md5"]
        downloads.append(digest)
        if limit == "transport":
            raise NapCatQQMediaStageError("media_transport_timeout")
        if limit == "cancel":
            cancelled.set()
        elif limit == "time":
            clock[0] = 26.0 if len(downloads) == 1 else 60.0
        if len(downloads) == 2:
            raise NapCatQQMediaStageError("media_download_timeout")
        return by_digest[digest]

    monkeypatch.setattr(provider, "download_pic_media", download)
    output = tmp_path / "output"
    historical = tmp_path / "historical.html"
    historical.write_bytes(b"fictional old report")
    caplog.set_level("INFO", logger="qq_chat_analyzer.desktop.facade")
    if limit == "cancel":
        with pytest.raises(FacadeError) as caught:
            facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                   AnalysisConfig(output_directory=output), cancelled=cancelled.is_set)
        assert caught.value.code == "analysis_cancelled" and len(downloads) == 1
        assert not (output / "echo-report.html").exists()
    else:
        progress = []
        outcome = facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                         AnalysisConfig(output_directory=output), progress=progress.append)
        chapter = json.loads((outcome.report_directory / "echo-report.json").read_text(encoding="utf-8"))["stickers"]
        assert chapter["total_send_count"] == (40 if limit == "many" else 24)
        assert chapter["unique_material_count"] == (40 if limit == "many" else 12)
        from qq_chat_analyzer.presentation.stickers import sticker_report_targets
        targets = sticker_report_targets(outcome.echo_report_view.stickers)
        assert len(targets) >= 10  # Includes the Top 10 expansion, beyond the initial three.
        expected = len(targets)
        if limit == "many":
            assert expected == 40
        assert len(downloads) == len(set(downloads)) == expected
        if limit != "transport":
            assert {"available", "failed"} <= {a["status"] for a in chapter["assets"].values()}
        limited = sum(a["status"] == "limited" for a in chapter["assets"].values())
        assert limited == 0
        assert len(downloads) <= len(by_digest)  # No duplicate or unselected recovery.
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[sticker-report-media")]
        assert len(lines) == 2 and all(str(tmp_path) not in line and "u_fiction" not in line for line in lines)
        details = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[sticker-media-")]
        results = [line for line in details if line.startswith("[sticker-media-result]")]
        assert [int(re.search(r"target=(\d+)", line)[1]) for line in results] == list(range(1, len(targets) + 1))
        assert all(str(tmp_path) not in line and "u_fiction" not in line and
                   not any(digest in line for digest in by_digest) for line in details)
        if expected >= 2 and limit != "transport":
            assert any("code=qq_media_download_timeout" in line for line in results)
        if limit == "time":
            assert not any("code=report_media_time_budget" in line for line in results)
        if limit == "transport":
            assert all("code=qq_media_transport_timeout" in line for line in results)
            assert not any("code=external_file" in line for line in details)
        else:
            assert any("code=external_file" in line for line in details)
    assert runtime.acquired == runtime.cleaned and len(runtime.acquired) == 1
    assert historical.read_bytes() == b"fictional old report"


@pytest.mark.parametrize("cancel", [False, True])
def test_cancel_or_export_failure_closes_prepared_media_even_if_error_is_retained(tmp_path, monkeypatch, cancel):
    raw = _fictional_png()
    facade, _, _ = _fetch_facade(tmp_path, digest=hashlib.md5(raw).digest(), content=raw)
    stopped, retained = [False], []

    def failed_export(result, stickers, output, **kwargs):
        retained.extend(item.stored for item in stickers.media if item.stored is not None)
        stopped[0] = cancel
        raise OSError("fictional export failure")

    monkeypatch.setattr(facade._require_analysis_service(), "export_sticker_report", failed_export)
    with pytest.raises(FacadeError) as error:
        facade.analyze_session(ChatSource.QQ, "private:private-partition",
            AnalysisConfig(output_directory=tmp_path / "generated"), cancelled=lambda: stopped[0])
    if cancel:
        assert error.value.code == "analysis_cancelled"
    assert len(retained) == 1
    with pytest.raises(ValueError, match="closed"):
        retained[0].read()


@pytest.mark.slow_integration
@pytest.mark.parametrize("kind", ["private", "group"])
@pytest.mark.parametrize("scenario", ["slow", "timeout", "failed", "cancel"])
def test_formal_generate_keeps_gui_live_during_media(tmp_path, monkeypatch, kind, scenario):
    """A blocked media RPC must not stop GUI timers, progress or cancellation."""
    import os
    import threading
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication
    from qq_chat_analyzer.gui.main_window import MainWindow
    from qq_chat_analyzer.gui import workers
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQMediaStageError

    app = QApplication.instance() or QApplication([])
    raw = _fictional_png()
    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=hashlib.md5(raw).digest(), content=raw,
        group_sender="10087" if kind == "group" else None)
    entered, release = threading.Event(), threading.Event()
    stages = []
    download = provider.download_pic_media

    def slow_download(**locator):
        stages.append(("download", threading.current_thread() is threading.main_thread()))
        entered.set()
        assert release.wait(3), "GUI did not release the fictional request"
        if scenario in {"timeout", "failed"}:
            raise NapCatQQMediaStageError("media_download_timeout" if scenario == "timeout" else "media_download_failed")
        return download(**locator)

    verify = sticker_media.verify_fetched_media
    def checked_verify(*args, **kwargs):
        stages.append(("decode", threading.current_thread() is threading.main_thread()))
        return verify(*args, **kwargs)
    export = facade._require_analysis_service().export_sticker_report
    def checked_export(*args, **kwargs):
        stages.append(("assembly", threading.current_thread() is threading.main_thread()))
        return export(*args, **kwargs)
    monkeypatch.setattr(provider, "download_pic_media", slow_download)
    monkeypatch.setattr(sticker_media, "verify_fetched_media", checked_verify)
    monkeypatch.setattr(facade._require_analysis_service(), "export_sticker_report", checked_export)
    window = MainWindow(facade)
    window.show()
    monkeypatch.setattr(window, "open_echo_report", lambda: None)
    panel = window.qq_workspace.session_panel
    panel.populate_sessions([SessionInfo(source=ChatSource.QQ, session_id=f"{kind}:{kind}-partition",
                                        display_name="Fictional chat", message_count=1)])
    panel._session_list.setCurrentRow(0)
    outcomes, errors, progress = [], [], []
    panel.analysis_succeeded.connect(outcomes.append)
    panel.analysis_failed.connect(lambda *args: errors.append(args))
    panel.status_changed.connect(progress.append)
    beats, live_copy, cancelled = [], [], []
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    deadline = time.monotonic() + 8
    def tick():
        if entered.is_set() and not release.is_set():
            beats.append(time.monotonic())
            live_copy.append(window.processing_page.status_label.text())
            if len(beats) >= 5:
                if scenario == "cancel":
                    window.processing_page.cancel_button.click()
                    cancelled.append(not panel._analysis_running)
                release.set()
        if (entered.is_set() and workers.is_idle()) or time.monotonic() > deadline:
            loop.quit()
    timer.timeout.connect(tick)
    timer.start()
    try:
        panel._analyze_button.click()
        loop.exec()
    finally:
        release.set()
        timer.stop()
        panel.cancel_analysis()
        workers.QThreadPool.globalInstance().waitForDone(3000)
        window.processing_page.stop()
        window.deleteLater()
    assert len(beats) >= 5 and not any(main for _, main in stages)
    assert any("1/1" in text for text in live_copy)
    assert not errors
    assert runtime.acquired == runtime.cleaned
    if scenario == "cancel":
        assert cancelled == [True] and not outcomes
        assert not any(name == "assembly" for name, _ in stages)
    else:
        assert len(outcomes) == 1
        assert any(name == "assembly" for name, _ in stages)
        asset, = outcomes[0].echo_report_view.stickers.assets
        assert asset.status == ("available" if scenario == "slow" else "failed")


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
    from qq_chat_analyzer.qq_db_adapter import QQPicMediaElement, QQPicMediaFact
    provider.stored_facts = (QQPicMediaFact(
        message_id="201", timestamp=1760000001,
        peer_uid=None if group_sender else "u_fictionalpeer000000000000",
        conversation_type="group" if group_sender else "private",
        conversation_id="12345001" if group_sender else "private-partition",
        group_id="12345001" if group_sender else None,
        sender_uin=group_sender, sender_uid="u_fictionalmember000000" if group_sender else None,
        is_self=group_sender == "10086" if group_sender else False,
        elements=(QQPicMediaElement("7000000000000000001", "fictional-file-uuid", digest.hex(), True),),
    ),)
    facade = ChatAnalyzerFacade(
        qq_service=service, qq_connection_service=_ProviderConnection(provider),
        analysis_service=AnalysisApplicationService(), stopwords_directory=Path(__file__).resolve().parents[1])
    return facade, provider, runtime


@pytest.mark.parametrize("mine,original", [(False, False), (True, True)])
def test_group_analyzed_send_reaches_native_fetch_after_identity_check(tmp_path, mine, original, caplog):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest() if original else _PIC_KEY_BYTES.hex()
    sender = "10086" if mine else "10087"
    facade, provider, runtime = _fetch_facade(tmp_path, digest=bytes.fromhex(digest), content=png, group_sender=sender)
    result = facade.analyze_session(ChatSource.QQ, "group:group-partition",
                                   AnalysisConfig(output_directory=tmp_path / "report")).result
    send, = result.stickers.sends
    assert send.sender_id == sender and send.is_self is mine
    provider.calls.clear()  # Inspect the shared report fetch checks with explicit stored facts.
    caplog.set_level("INFO", logger="qq_chat_analyzer.desktop.analysis_diagnostics")
    caplog.clear()
    data = facade._fetch_qq_pic(result.stickers, media_key=send.media_key,
                                       session_id="group:group-partition", stored_facts=provider.stored_facts, provider=provider, occurrence_id=send.occurrence_id)
    assert data.sends is result.stickers.sends
    media, = data.media
    assert media.original_bytes == png and media.status == ("available" if original else "preview")
    assert media.reason == (None if original else "content_digest_mismatch")
    assert media.format == "PNG"
    query, download = provider.calls
    assert query[0] == "resolve" and download[0] == "download"
    assert query[1]["chat_type"] == download[1]["chat_type"] == 2
    assert query[1]["peer_uid"] == download[1]["peer_uid"] == "12345001"
    assert query[1]["expected_sender_uin"] == sender
    assert query[1]["expected_sender_uid"] == "u_fictionalmember000000"
    assert runtime.acquired == runtime.cleaned
    timing_lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[analysis-timing]")]
    assert len(timing_lines) == 2
    assert all(re.fullmatch(r"\[analysis-timing\] stage=sticker_media_(download|verify) elapsed_ms=\d+", line)
               for line in timing_lines)


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
    provider.calls.clear()
    resolve = provider.resolve_pic_message
    monkeypatch.setattr(provider, "resolve_pic_message", lambda **kwargs: replace(resolve(**kwargs), **{field: value}))
    with pytest.raises(FacadeError) as caught:
        facade._fetch_qq_pic(data, media_key=data.sends[0].media_key,
                                     session_id="group:group-partition", stored_facts=provider.stored_facts, provider=provider)
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
    provider.calls.clear()
    retained_media = data.media
    changes = {"sender_id": "10088", "conversation_id": "12345002", "timestamp": 1760000002, "is_self": True}
    session = "private:private-partition" if changed == "session" else "group:group-partition"
    if changed != "session":
        data = replace(data, sends=(replace(data.sends[0], **{changed: changes[changed]}),))
    with pytest.raises(FacadeError) as caught:
        facade._fetch_qq_pic(data, media_key=data.sends[0].media_key, session_id=session, stored_facts=provider.stored_facts, provider=provider)
    assert caught.value.code.startswith("qq_media_group_")
    assert not provider.calls and data.media == retained_media
    assert runtime.acquired == runtime.cleaned


def test_report_pic_fetch_checks_identity_and_returns_verified_original(tmp_path):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest()
    data = StickerData(sends=(_pic_send(digest),))
    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=bytes.fromhex(digest), content=png)
    key = data.sends[0].media_key

    result = facade._fetch_qq_pic(
        data, media_key=key, session_id="private:private-partition", stored_facts=provider.stored_facts, provider=provider)

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
    assert [name for name, _ in provider.calls] == ["resolve", "download"]
    assert provider.calls[0][1] == {**expected, "expected_segment_id": element_id}
    download = dict(provider.calls[1][1])
    assert callable(download.pop("cancelled")) and download.pop("timeout") >= 120
    assert download == {**expected, "element_id": element_id}
    assert not runtime.acquired and not runtime.cleaned


def test_group_media_is_refused_before_acquisition_or_rpc(tmp_path, monkeypatch):
    from dataclasses import replace

    facade, provider, runtime = _fetch_facade(
        tmp_path, digest=_PIC_KEY_BYTES, content=_fictional_png())
    data = StickerData(sends=(replace(_pic_send(_PIC_KEY_BYTES.hex()), conversation_type="group"),))
    monkeypatch.setattr(runtime, "acquire",
                        lambda: pytest.fail("invalid selection must not acquire a snapshot"))
    with pytest.raises(FacadeError) as caught:
        facade._fetch_qq_pic(
            data, media_key=data.sends[0].media_key, session_id="group:fictional", stored_facts=provider.stored_facts, provider=provider)
    assert caught.value.code == "qq_media_invalid_selection"
    assert not provider.calls and not runtime.cleaned and not data.media


def test_group_fetched_gif_decode_limit_has_a_specific_public_error(tmp_path, monkeypatch):
    from PIL import Image
    from qq_chat_analyzer.application import sticker_media

    monkeypatch.setattr(sticker_media, "QQ_MAX_DECODE_WORK", 64 * 1024)

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
    provider.calls.clear()
    with pytest.raises(FacadeError) as caught:
        facade._fetch_qq_pic(
            data, media_key=data.sends[0].media_key,
            session_id="group:group-partition", stored_facts=provider.stored_facts, provider=provider)
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
        facade._fetch_qq_pic(
            data, media_key=data.sends[0].media_key,
            session_id="private:private-partition", stored_facts=provider.stored_facts, provider=provider)

    assert caught.value.code == expected
    assert not data.media
    if failure == "mapping":
        assert [name for name, _ in provider.calls] == ["resolve"]


def test_unknown_fetch_failure_stays_generic_and_never_leaks_details(tmp_path):
    png = _fictional_png()
    digest = hashlib.md5(png).hexdigest()
    data = StickerData(sends=(_pic_send(digest),))
    facade, provider, _runtime = _fetch_facade(
        tmp_path, digest=bytes.fromhex(digest), content=png,
        download_error=RuntimeError("PRIVATE C:/fictional/secret 201"))

    with pytest.raises(FacadeError) as caught:
        facade._fetch_qq_pic(
            data, media_key=data.sends[0].media_key,
            session_id="private:private-partition", stored_facts=provider.stored_facts, provider=provider)

    assert caught.value.code == "qq_media_fetch_failed"
    message = caught.value.public_message
    assert "未返回可用的图片内容" in message
    assert "PRIVATE" not in message and "secret" not in message and "201" not in message
