"""Fictional-only checks for the material catalog and normal Qt lifecycle.

No real chat data, account, path or image is used: every send and every GIF
below is constructed inside the test.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qq_chat_analyzer.analysis.stickers import (  # noqa: E402
    StickerData, StickerMedia, StickerSend,
)
from qq_chat_analyzer.application.sticker_catalog import build_sticker_catalog  # noqa: E402


PIC_KEY = "qq-pic:md5:" + "a" * 32


@pytest.fixture(autouse=True)
def fictional_public_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC", str(tmp_path / "public"))


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_qq_discovery_custom_parent_preserves_account_choice(tmp_path, encoding, monkeypatch):
    from qq_chat_analyzer.application.qq.qq_media_directories import discover_qq_media
    from qq_chat_analyzer.application import sticker_media

    parent = tmp_path / "虚构数据"
    expected = []
    for account in ("12345001", "12345002"):
        root = parent / account / "nt_qq" / "nt_data"
        roots = tuple(root / suffix for suffix in (
            "Pic/2026-01/Ori", "Emoji/emoji-recv/2026-02/Ori",
            "Emoji/personal_emoji/Ori", "Emoji/personal-emoji/Ori"))
        for directory in roots:
            directory.mkdir(parents=True)
            (directory / "unrelated.bin").write_bytes(b"fictional")
        expected.append((parent / account, set(roots)))
    # No recursive discovery, and no account inferred from an install/runtime tree.
    (parent / "runtime" / "nt_qq" / "nt_data" / "Pic/2026-01/Ori").mkdir(parents=True)
    (parent / "nested" / "12345003" / "nt_qq/nt_data/Pic/2026-01/Ori").mkdir(parents=True)
    ini = tmp_path / "UserDataInfo.ini"
    ini.write_text(f'[UserDataSet]\nUserDataSavePath={parent}\n', encoding=encoding)
    real_open = sticker_media._open_original

    def config_only(path, root):
        assert path == ini, "discovery must not read media bytes"
        return real_open(path, root)

    monkeypatch.setattr(sticker_media, "_open_original", config_only)
    candidates = discover_qq_media(config_path=ini)
    assert {(c.account_directory, frozenset(c.roots)) for c in candidates} == {
        (account, frozenset(roots)) for account, roots in expected}
    assert "12345001" not in repr(candidates)
    assert discover_qq_media(data_path=parent / "12345002")[0].account_directory == parent / "12345002"


@pytest.mark.parametrize("content", [None, b"\xff\x00garbage", b"[UserDataSet]\nUserDataSavePath=Z:/fictional-missing\n"])
def test_qq_discovery_bad_config_allows_structural_manual_fallback(tmp_path, content):
    from qq_chat_analyzer.application.qq.qq_media_directories import discover_qq_media

    ini = tmp_path / "missing.ini"
    if content is not None:
        ini.write_bytes(content)
    assert discover_qq_media(config_path=ini) == ()
    account = tmp_path / "12345001"
    ori = account / "nt_qq/nt_data/Emoji/personal_emoji/Ori"
    ori.mkdir(parents=True)
    assert discover_qq_media(data_path=account)[0].roots == (ori,)
    assert discover_qq_media(data_path=account / "nt_qq/nt_data") == ()


def test_qq_59_discovered_scopes_are_all_searched_without_expanding_consent(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.application.qq.qq_media_directories import discover_qq_media

    account = tmp_path / "12345001"
    data = account / "nt_qq/nt_data"
    originals = []
    raw = png_bytes()
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
    candidate, = discover_qq_media(data_path=account)
    assert len(candidate.roots) == 59
    # A new month created after discovery is not part of the user's consent.
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
    data = StickerData(sends=(send(key=f"qq-pic:md5:{digest}", content_md5=digest),))
    result = ChatAnalyzerFacade.associate_sticker_media(
        data, media_keys=(data.sends[0].media_key,), roots=candidate.roots, source="qq")
    media, = result.media
    assert media.status == "available", (media.status, media.reason)
    assert media.original_bytes == raw
    assert set(opened) == set(originals) and len(opened) == 59


def send(
    *,
    is_self=True,
    key=PIC_KEY,
    occurrence="0:0",
    source="qq",
    conversation_type="private",
    content_md5=None,
):
    wechat = source == "wechat"
    return StickerSend(
        occurrence_id=occurrence,
        source=source,
        conversation_id="fictional-conversation",
        conversation_type=conversation_type,
        sender_id="fictional-sender",
        is_self=is_self,
        message_id="fictional-message",
        content_index=0,
        timestamp=0,
        epoch_seconds=0,
        chat_date="2026-01-01",
        classification_basis="wechat_type_47" if wechat else "qq_pic_45003_custom",
        identity_basis=(
            "wechat_xml_md5" if wechat else "qq_pic_45406_md5"
        ) if key else "unresolved",
        identity_key=key,
        media_key=key or f"unresolved:{occurrence}",
        content_md5=content_md5,
    )


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6", reason="PySide6 is required for the GUI layer")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def available_media(key, data):
    return StickerMedia(
        key, "available", format="PNG", frame_count=1,
        animation_preserved=False, byte_count=len(data), original_bytes=data,
    )


def png_bytes():
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 6), (120, 80, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def dialog_for(stickers, executor=None, source="qq"):
    from qq_chat_analyzer.gui.sticker_media_dialog import StickerMediaDialog
    from qq_chat_analyzer.gui.workers import run_inline

    return StickerMediaDialog(
        stickers, source=source, conversation_label="虚构会话",
        executor=executor or run_inline)


def qq_scope(tmp_path, monkeypatch):
    from qq_chat_analyzer.gui import sticker_media_dialog as module

    parent = tmp_path / "fictional-data"
    ori = parent / "12345001/nt_qq/nt_data/Pic/2026-01/Ori"
    ori.mkdir(parents=True)
    public = Path(os.environ["PUBLIC"])
    ini = public / "Documents/Tencent/QQ/UserDataInfo.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text(f"[UserDataSet]\nUserDataSavePath={parent}\n", encoding="utf-8")
    monkeypatch.setattr(module.StickerMediaDialog, "_confirm_qq_scope", lambda self, candidates: candidates[0].roots)
    return ori


def test_qq_scope_confirmation_has_no_implicit_account(qt_app, tmp_path):
    from qq_chat_analyzer.application.qq.qq_media_directories import QQMediaDirectories
    from qq_chat_analyzer.gui.sticker_media_dialog import _QQMediaScopeDialog

    first = tmp_path / "12345001"
    second = tmp_path / "12345002"
    roots = (second / "nt_qq/nt_data/Pic/2026-01/Ori",)
    dialog = _QQMediaScopeDialog((QQMediaDirectories(first, ()), QQMediaDirectories(second, roots)))
    assert dialog.accounts.currentIndex() == -1
    assert not dialog.confirm.isEnabled()
    dialog.accounts.setCurrentIndex(1)
    assert dialog.confirm.isEnabled()
    assert str(roots[0]) in dialog.scope.toPlainText()
    assert str(first) not in dialog.scope.toPlainText()
    assert dialog.roots == roots
    dialog.reject()


def test_qq_discovery_requires_authorization_before_media_read(qt_app, tmp_path, monkeypatch):
    from qq_chat_analyzer.gui import sticker_media_dialog as module
    from qq_chat_analyzer.application import sticker_media

    ori = qq_scope(tmp_path, monkeypatch)
    raw = png_bytes()
    digest = hashlib.md5(raw).hexdigest()
    key = f"qq-pic:md5:{digest}"
    (ori / f"{digest}.png").write_bytes(raw)
    monkeypatch.setattr(module.StickerMediaDialog, "_confirm_qq_scope", lambda *args: ())
    real_open = sticker_media._open_original

    def no_media(path, root):
        assert path.suffix == ".ini", "authorization was declined"
        return real_open(path, root)

    monkeypatch.setattr(sticker_media, "_open_original", no_media)
    dialog = dialog_for(StickerData(sends=(send(key=key, content_md5=digest),)))
    dialog._choose_media_folder()
    assert dialog.card.image.pixmap().isNull()
    assert "未授权" in dialog.status.text()
    dialog.close()


@pytest.mark.parametrize("close", [False, True])
def test_qq_cancel_or_close_stops_pending_media_read(qt_app, tmp_path, monkeypatch, close):
    from qq_chat_analyzer.gui import sticker_media_dialog as module
    from qq_chat_analyzer.gui.workers import run_inline

    ori = qq_scope(tmp_path, monkeypatch)
    raw = png_bytes()
    digest = hashlib.md5(raw).hexdigest()
    key = f"qq-pic:md5:{digest}"
    (ori / f"{digest}.png").write_bytes(raw)
    pending = {}
    calls = 0

    def discovery_inline_then_defer(operation, **callbacks):
        nonlocal calls
        calls += 1
        if calls == 1:
            run_inline(operation, **callbacks)
        else:
            pending.update(operation=operation, **callbacks)

    dialog = dialog_for(StickerData(sends=(send(key=key, content_md5=digest),)), executor=discovery_inline_then_defer)
    dialog._choose_media_folder()
    assert calls == 2 and dialog.cancel_button.isEnabled()
    if close:
        dialog.close()
    else:
        dialog.cancel_button.click()
    media = pending["operation"]()
    assert not media.media  # cancellation returns unchanged sending facts
    pending["on_success"](media)
    pending["on_finished"]()
    assert dialog.card.image.pixmap().isNull()
    if not close:
        assert "已取消" in dialog.status.text()
        assert dialog.media_button.isEnabled()
    dialog.close()



def test_catalog_preserves_sides_unknowns_occurrences_and_namespaces():
    market = "qq-marketface:sha256:" + "a" * 64
    entries = build_sticker_catalog((
        send(), send(), send(is_self=False), send(is_self=None),
        send(key=None, occurrence="1:0"), send(key=None, occurrence="1:1"),
        send(key=market), send(source="wechat"), send(conversation_type="group"),
    ), source="qq")
    assert sum(e.count for e in entries) == 7
    assert len(entries) == 4 and sum(e.identity_known for e in entries) == 2
    pic = next(e for e in entries if e.media_key == PIC_KEY)
    assert (pic.self_count, pic.other_count, pic.unknown_count) == (2, 1, 1)
    assert build_sticker_catalog((send(source="wechat"),), source="qq") == ()


def test_paging_selects_only_current_batch(qt_app, tmp_path, monkeypatch):
    source = "qq"
    from qq_chat_analyzer.gui import sticker_media_dialog as module
    sends = tuple(send(key=f"qq-pic:md5:{i:032x}",
                       content_md5=f"{i:032x}", source=source) for i in range(35))
    pending, captured = {}, {}
    def defer(operation, **callbacks):
        pending.update(operation=operation, **callbacks)
    dialog = dialog_for(StickerData(sends=sends), executor=defer, source=source)
    assert dialog.table.rowCount() == 32 and "35 项" in dialog.page_label.text()
    dialog.next_button.click()
    assert dialog.table.rowCount() == 3
    def associate(data, **kwargs):
        captured.update(kwargs)
        return data
    monkeypatch.setattr(module.ChatAnalyzerFacade, "associate_sticker_media", associate)
    dialog._resolve_roots((tmp_path,))
    assert not dialog.previous_button.isEnabled()
    pending["on_success"](pending["operation"]())
    pending["on_finished"]()
    assert len(captured["media_keys"]) == 3
    assert set(captured["media_keys"]) == {entry.media_key for entry in dialog._page_entries()}
    assert captured["roots"] == (tmp_path,)
    dialog.close()


def test_native_movie_error_is_handled_without_preimporting_qimagereader(tmp_path):
    import subprocess
    import textwrap

    pytest.importorskip("PySide6")
    # QImageReader imported by another Qt test registers its enum globally and
    # hides this production failure. Exercise the native signal in a fresh Qt
    # process, inheriting the test's isolated user directories.
    script = textwrap.dedent("""
        import sys
        from io import BytesIO
        from PIL import Image
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from qq_chat_analyzer.gui.sticker_media_dialog import _StickerCard

        errors = []
        def uncaught(kind, value, tb):
            if kind is AssertionError:
                sys.__excepthook__(kind, value, tb)
            else:
                errors.append((kind.__name__, str(value)))
        sys.excepthook = uncaught
        app = QApplication([])
        raw = BytesIO()
        Image.new('RGB', (3, 2), 'red').save(
            raw, format='GIF', save_all=True,
            append_images=[Image.new('RGB', (3, 2), 'blue')], duration=40, loop=0)
        card = _StickerCard('fictional', 'empty')
        assert card._start_movie(raw.getvalue(), b'gif')
        movie, buffer = card._movie, card._buffer
        movie.stop()
        buffer.setData(b'fictional-invalid-gif')
        movie.setDevice(buffer)
        movie.start()  # Qt emits its real QImageReader::ImageReaderError.
        app.processEvents()
        assert not errors, errors
        assert card._movie is None and card._buffer is None
        assert not card._playback_timer.isActive()
        assert card.detail.text() == '动画播放失败，已停止。'
        card.release_media()
        card.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert not errors, errors
    """)
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "src"), QT_QPA_PLATFORM="offscreen",
               PYTHONIOENCODING="utf-8")
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_verified_long_gif_actually_plays_past_frame_128_without_caching(qt_app):
    import time
    from PIL import Image
    from PySide6.QtGui import QMovie
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media

    stream = BytesIO()
    images = [Image.new("RGB", (16, 12), "red" if index % 2 else "blue")
              for index in range(140)]
    images[0].save(stream, format="GIF", save_all=True, append_images=images[1:], duration=20, loop=0)
    raw = stream.getvalue()
    media = verify_fetched_media(raw, media_key=PIC_KEY, expected_md5=hashlib.md5(raw).hexdigest())
    assert media.status == "available"
    data = StickerData(sends=(send(),), media=(media,))
    dialog = dialog_for(data)
    try:
        movie = dialog.card._movie
        assert movie is not None and movie.cacheMode() == QMovie.CacheMode.CacheNone
        seen = []
        movie.frameChanged.connect(lambda number: seen.append((
            number, movie.currentImage().pixelColor(0, 0).name(), time.monotonic())))
        movie.setSpeed(1000)  # Exercise the refresh guard, not just the normal file delay.
        deadline = time.monotonic() + 12
        while not any(number >= 129 for number, _, _ in seen) and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.002)
        assert any(number >= 129 for number, _, _ in seen)
        assert len({color for _, color, _ in seen}) == 2
        assert all(b[2] - a[2] >= 0.035 for a, b in zip(seen, seen[1:]))
        assert dialog.stickers.sends is data.sends and dialog.stickers.media == (media,)
    finally:
        dialog.close()
    assert dialog.card._movie is None and dialog.card._buffer is None
    assert not dialog.stickers.media and not dialog.stickers.sends
    assert not dialog.card._playback_timer.isActive()


def test_closed_dialog_discards_late_results(qt_app, tmp_path):
    from dataclasses import replace
    pending = {}
    def deferred(operation, **callbacks):
        pending.update(operation=operation, **callbacks)
    data = StickerData(sends=(send(),))
    dialog = dialog_for(data, executor=deferred)
    dialog._resolve_roots((tmp_path,))
    dialog.reject()
    pending["on_success"](replace(data, media=(available_media(PIC_KEY, png_bytes()),)))
    pending["on_finished"]()
    assert not dialog.stickers.media and not dialog.stickers.sends
    assert not dialog.media_button.isEnabled()
    assert dialog.card._movie is None and dialog.card._buffer is None


def test_main_window_material_action_in_frozen_sources(qt_app, monkeypatch):
    from test_gui import StubFacade, _main_window
    from qq_chat_analyzer.application.facade import ChatSource, SessionInfo
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    window = _main_window(qt_app, StubFacade())
    def outcome(source, session_type):
        return SimpleNamespace(source=source,
            session=SessionInfo(source, "fictional-session", "虚构会话", session_type),
            result=SimpleNamespace(stickers=StickerData(sends=(
                send(source=source.value, conversation_type=session_type),))),
            report_path=None, report_directory=None)
    for source in (ChatSource.QQ, ChatSource.WECHAT):
        window.show_outcome(outcome(source, "group"))
        assert window._sticker_button.isEnabled() == (source == ChatSource.QQ)
        if source == ChatSource.QQ:
            window._sticker_button.click()
            assert "当前群聊" in window._sticker_media_dialog.scope.text()
            assert window._sticker_media_dialog.card.count.text() == "发送 1 次"
        window.show_outcome(outcome(source, "private"))
        assert window._sticker_button.isEnabled() and window._sticker_media_dialog is None
        window._sticker_button.click()
        dialog = window._sticker_media_dialog
        assert dialog is not None and dialog.isVisibleTo(window) and len(dialog._entries) == 1
        window._sticker_button.click()
        assert window._sticker_media_dialog is dialog
        window.show_outcome(outcome(source, "private"))
        assert dialog._closed and window._sticker_media_dialog is None
    window._sticker_button.click()
    dialog = window._sticker_media_dialog
    window.close()
    assert dialog._closed


def test_group_material_dialog_selects_member_send_and_requires_consent(qt_app, monkeypatch):
    from dataclasses import replace
    from qq_chat_analyzer.gui.sticker_media_dialog import StickerMediaDialog
    from qq_chat_analyzer.gui.workers import run_inline

    base = send(conversation_type="group")
    data = StickerData(sends=tuple(replace(base, sender_id=sender, is_self=index == 0,
                                         occurrence_id=f"{index}:0", content_md5="a" * 32)
                                  for index, sender in enumerate(("20002", "20002", "30003"))))
    calls = []
    class _Facade:
        def fetch_qq_sticker_media(self, stickers, **kwargs):
            calls.append(kwargs)
            return replace(stickers, media=(available_media(PIC_KEY, png_bytes()),))
    dialog = StickerMediaDialog(data, source="qq", conversation_type="group", session_id="group:12345001",
                                executor=run_inline, facade=_Facade())
    try:
        assert dialog.table.rowCount() == 1 and dialog.card.count.text() == "发送 3 次"
        assert "20002：2 次" in dialog.members.toPlainText()
        assert "30003：1 次" in dialog.members.toPlainText()
        assert dialog.members.isReadOnly()
        assert "TA" not in dialog.table.horizontalHeaderItem(2).text()
        assert dialog.fetch_button.isEnabled()
        assert dialog.send_selector.currentData() == "1:0"  # Prefer another member, even for shared materials.
        monkeypatch.setattr(dialog, "_confirm_network_fetch", lambda *_: False)
        dialog._fetch_selected_media()
        assert not calls
        monkeypatch.setattr(dialog, "_confirm_network_fetch", lambda *_: True)
        dialog._fetch_selected_media()
        assert calls[0]["occurrence_id"] == "1:0" and calls[0]["network_consent"] is True
        assert not dialog.card.image.pixmap().isNull()
        dialog.send_selector.setCurrentIndex(0)
        dialog._fetch_selected_media()
        assert calls[1]["occurrence_id"] == "0:0"  # The same material can also verify the self send.
    finally:
        dialog.close()
    assert not dialog.members.toPlainText()


def test_normal_executor_validates_off_gui_thread(qt_app, tmp_path, monkeypatch):
    import threading
    import time
    from qq_chat_analyzer.application import sticker_media
    from qq_chat_analyzer.gui.sticker_media_dialog import StickerMediaDialog
    from qq_chat_analyzer.gui import workers

    raw = png_bytes()
    digest = hashlib.md5(raw).hexdigest()
    key = f"wechat:md5:{digest}"
    (tmp_path / "original").write_bytes(raw)
    decoder_threads = []
    inspect = sticker_media._inspect

    def inspect_in_background(*args, **kwargs):
        decoder_threads.append(threading.get_ident())
        return inspect(*args, **kwargs)

    monkeypatch.setattr(sticker_media, "_inspect", inspect_in_background)
    dialog = StickerMediaDialog(StickerData(sends=(
        send(source="wechat", key=key, content_md5=digest),)), source="wechat")
    try:
        dialog._resolve_roots((tmp_path,))
        deadline = time.monotonic() + 5
        while (dialog._resolving or not workers.is_idle()) and time.monotonic() < deadline:
            qt_app.processEvents()
            threading.Event().wait(0.005)
        qt_app.processEvents()
        assert decoder_threads and threading.get_ident() not in decoder_threads
        assert workers.is_idle() and not dialog._resolving
        assert not dialog.card.image.pixmap().isNull()
    finally:
        dialog.close()


def test_qq_fetch_needs_explicit_consent_and_reports_a_trusted_preview(qt_app, monkeypatch):
    from dataclasses import replace
    from qq_chat_analyzer.gui.sticker_media_dialog import StickerMediaDialog
    from qq_chat_analyzer.gui.workers import run_inline

    png = png_bytes()
    data = StickerData(sends=(send(key=PIC_KEY, content_md5="a" * 32),))
    calls = []

    class _Facade:
        def fetch_qq_sticker_media(self, stickers, **kwargs):
            calls.append(kwargs)
            return replace(stickers, media=(StickerMedia(
                PIC_KEY, "preview", "content_digest_mismatch", format="PNG",
                frame_count=1, byte_count=len(png), original_bytes=png),))

    def build():
        return StickerMediaDialog(
            data, source="qq", session_id="private:fictional",
            facade=_Facade(), executor=run_inline)

    dialog = build()
    try:
        assert dialog.fetch_button.isEnabled()
        monkeypatch.setattr(dialog, "_confirm_network_fetch", lambda entry: False)
        dialog._fetch_selected_media()
        assert calls == []
        assert "未确认" in dialog.status.text()

        monkeypatch.setattr(dialog, "_confirm_network_fetch", lambda entry: True)
        dialog._fetch_selected_media()
        assert len(calls) == 1
        assert calls[0]["media_key"] == PIC_KEY
        assert calls[0]["session_id"] == "private:fictional"
        assert calls[0]["network_consent"] is True
        assert "可信预览" in dialog.status.text()
        assert "可信预览" in dialog.table.item(0, 5).text()
        assert not dialog.card.image.pixmap().isNull()
    finally:
        dialog.close()

    # No selected QQ session or a non-QQ source can never fetch.
    for kwargs in ({"source": "qq", "session_id": None}, {"source": "wechat", "session_id": "private:x"}):
        data = StickerData(sends=(send(key=PIC_KEY, content_md5="a" * 32,
                                       source=kwargs["source"]),))
        dialog = StickerMediaDialog(data, facade=_Facade(), executor=run_inline, **kwargs)
        try:
            assert not dialog.fetch_button.isEnabled()
            before = len(calls)
            dialog._fetch_selected_media()
            assert len(calls) == before
        finally:
            dialog.close()
