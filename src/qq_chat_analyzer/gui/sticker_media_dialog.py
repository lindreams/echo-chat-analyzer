"""Opt-in material recovery and explicit export through the application facade."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..analysis.stickers import StickerData, StickerMedia
from ..application.facade import ChatAnalyzerFacade
from ..application.qq.qq_media_directories import QQMediaDirectories
from ..application.sticker_catalog import StickerCatalogEntry, build_sticker_catalog
from ..application.sticker_media import STICKER_MEDIA_BATCH_SIZE
from ..presentation.models import EchoStickerItem
from .theme import COLOR_MUTED, FONT_SIZE_SMALL
from .workers import submit

_IMAGE_BOX = QSize(180, 180)
_NO_MEDIA_TEXT = "原图暂不可用"
_MOVIE_FORMATS = {"GIF": b"gif", "APNG": b"apng", "WEBP": b"webp"}
_DISPLAYABLE = frozenset({"available", "preview"})
_MIN_FRAME_INTERVAL_MS = 40


def _is_available(media: StickerMedia | None) -> bool:
    return media is not None and media.status in _DISPLAYABLE and bool(media.original_bytes)


def _media_text(media: StickerMedia | None) -> str:
    if media is None or media.status == "not_requested":
        return "未授权关联"
    if media.reason == "no_digest_name_match":
        return "未发现摘要名称或授权路径候选；不代表原件不存在 · no_digest_name_match"
    labels = {
        "available": "原件已验证", "preview": "可信预览（摘要与消息不符，非原件）",
        "missing": "未找到匹配原件",
        "limited": "未完整搜索（预算受限）", "unsupported": "暂无可靠原件支持",
        "invalid": "图片验证失败", "unsafe": "不安全路径，未读取",
        "ambiguous": "内容存在歧义", "cancelled": "已取消",
        "failed": "获取失败",
    }
    return labels.get(media.status, "原件不可用") + (
        f" · {media.reason}" if media.reason else "")


class _StickerCard(QFrame):
    """A selected material's verified original or explicit unavailable state."""

    def __init__(self, title: str, empty_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("stickerMediaCard")
        self._empty_text = empty_text
        self._movie: QMovie | None = None
        self._buffer: QBuffer | None = None
        self._playback_timer = QTimer(self)
        self._playback_timer.setSingleShot(True)
        self._playback_timer.timeout.connect(self._resume_movie)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        heading = QLabel(title, self)
        heading.setStyleSheet(f"color: {COLOR_MUTED}; font-size: {FONT_SIZE_SMALL};")
        layout.addWidget(heading)
        self.image = QLabel(_NO_MEDIA_TEXT, self)
        self.image.setObjectName("stickerMediaImage")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setWordWrap(True)
        self.image.setFixedSize(_IMAGE_BOX)
        layout.addWidget(self.image, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.count = QLabel("\u6682\u65e0\u8bb0\u5f55", self)
        self.count.setObjectName("stickerMediaCount")
        layout.addWidget(self.count)
        self.detail = QLabel("", self)
        self.detail.setObjectName("stickerMediaDetail")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.detail)
        layout.addStretch(1)

    # -- states ---------------------------------------------------------
    def show_empty(self) -> None:
        self.release_media()
        self.image.setText(self._empty_text)
        self.count.setText("\u65e0")
        self.detail.setText("")

    def show_entry(self, entry: StickerCatalogEntry, media: StickerMedia | None) -> None:
        self.release_media()
        self.image.setText(_NO_MEDIA_TEXT)
        self.count.setText(f"\u53d1\u9001 {entry.count} \u6b21")
        if _is_available(media):
            if self._show_original(media):
                self.detail.setText(self._describe(media))
                return
            self.detail.setText(f"{_NO_MEDIA_TEXT}\uff08\u5df2\u9a8c\u8bc1\u4f46\u65e0\u6cd5\u663e\u793a\uff09")
            return
        self.detail.setText(self._failure_text(media))

    # -- original display -----------------------------------------------
    def _show_original(self, media: StickerMedia) -> bool:
        data = media.original_bytes
        if not data:
            return False
        movie_format = _MOVIE_FORMATS.get((media.format or "").upper())
        if (media.frame_count or 1) > 1:
            return movie_format is not None and self._start_movie(data, movie_format)
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return False
        self.image.setText("")
        self.image.setPixmap(pixmap.scaled(
            _IMAGE_BOX, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        return True

    def _start_movie(self, data: bytes, movie_format: bytes) -> bool:
        buffer = QBuffer(self)
        buffer.setData(data)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            buffer.deleteLater()
            return False
        movie = QMovie(buffer, QByteArray(movie_format), self)
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        if not movie.isValid():
            movie.deleteLater()
            buffer.close()
            buffer.deleteLater()
            return False
        frame = movie.frameRect()
        if frame.isEmpty():
            # Frame metadata may only be known once the first frame is decoded;
            # the scaled size must be set before start to affect that frame.
            movie.jumpToFrame(0)
            frame = movie.frameRect()
        if not frame.isEmpty():
            movie.setScaledSize(frame.size().scaled(
                _IMAGE_BOX, Qt.AspectRatioMode.KeepAspectRatio))
        self._buffer, self._movie = buffer, movie
        movie.frameChanged.connect(self._movie_frame_changed)
        movie.error.connect(self._movie_failed)
        self.image.setText("")
        self.image.setMovie(movie)
        movie.start()
        return self._movie is movie

    def _movie_frame_changed(self, _number: int) -> None:
        movie = self._movie
        if movie is not None and movie.nextFrameDelay() < _MIN_FRAME_INTERVAL_MS:
            # Zero/very short delays must not turn an infinite loop into a hot
            # GUI-thread decoder. Resume lazily, keeping QMovie's CacheNone.
            movie.setPaused(True)
            self._playback_timer.start(_MIN_FRAME_INTERVAL_MS)

    def _resume_movie(self) -> None:
        if self._movie is not None:
            self._movie.setPaused(False)

    @Slot()
    def _movie_failed(self) -> None:
        # Ignore the unused native enum in Qt, before PySide tries to convert it.
        # Its converter may not be registered unless QImageReader was imported.
        self.release_media()
        self.image.setText(_NO_MEDIA_TEXT)
        self.detail.setText("动画播放失败，已停止。")

    @staticmethod
    def _describe(media: StickerMedia) -> str:
        parts = ["\u5df2\u9a8c\u8bc1\u539f\u4ef6" if media.status == "available"
                 else "\u53ef\u4fe1\u9884\u89c8\uff08\u975e\u539f\u4ef6\uff09"]
        parts.append(media.format or "\u539f\u56fe")
        if media.frame_count is not None:
            parts.append(f"{media.frame_count} \u5e27")
        if media.byte_count:
            parts.append(
                f"{media.byte_count} B" if media.byte_count < 1024
                else f"{media.byte_count / 1024:.0f} KB")
        return " \u00b7 ".join(parts)

    @staticmethod
    def _failure_text(media: StickerMedia | None) -> str:
        return _media_text(media)

    # -- lifecycle -------------------------------------------------------
    def release_media(self) -> None:
        """Stop playback and drop every decoded/encoded reference we hold."""
        self._playback_timer.stop()
        self.image.clear()
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None


class _QQMediaScopeDialog(QDialog):
    """Account choice and exact local read scopes, with no implicit consent."""

    def __init__(self, candidates: tuple[QQMediaDirectories, ...], parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认 QQ 账号及素材范围")
        self.resize(650, 430)
        self.roots: tuple[Path, ...] = ()
        layout = QVBoxLayout(self)
        note = QLabel("请选择本次聊天对应的 QQ 账号。确认后，Echo 仅在下面列出的原图目录内只读查找本页素材；不会访问其他账号或修改缓存。", self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.accounts = QComboBox(self)
        self.accounts.setPlaceholderText("请选择 QQ 账号（不会自动判断当前账号）")
        for candidate in candidates:
            self.accounts.addItem(candidate.account_directory.name)
        self.accounts.setCurrentIndex(-1)
        layout.addWidget(self.accounts)
        self.scope = QPlainTextEdit(self)
        self.scope.setReadOnly(True)
        layout.addWidget(self.scope)
        actions = QHBoxLayout()
        self.confirm = QPushButton("授权只读并开始验证", self)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        actions.addWidget(self.confirm)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        layout.addLayout(actions)

        def choose(index):
            self.roots = candidates[index].roots if index >= 0 else ()
            self.scope.setPlainText("将访问的聊天图片／接收表情／收藏表情原件目录：\n" + "\n".join(map(str, self.roots)))
            self.confirm.setEnabled(bool(self.roots))

        self.accounts.currentIndexChanged.connect(choose)


class StickerMediaDialog(QDialog):
    """Paged catalog and one controlled in-memory batch at a time."""

    report_exported = Signal(object)

    def __init__(self, stickers: StickerData, *, source: str = "qq",
                 conversation_label: str = "", session_id: str | None = None,
                 conversation_type: str = "private",
                 report_targets: tuple[EchoStickerItem, ...] | None = None,
                 export_report: Callable[[StickerData], Any] | None = None,
                 executor: Callable[..., Any] | None = None,
                 facade=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("表情素材")
        self.resize(850, 620)
        self._stickers = stickers
        self._source = source
        self._conversation_type = conversation_type
        group = conversation_type == "group"
        self._session_id = session_id
        self._executor = executor or submit
        self._facade = facade or ChatAnalyzerFacade
        self._cancelled = Event()
        self._closed = self._resolving = False
        self._page = 0
        self._report_targets = ({item.media_key: item.label for item in report_targets}
                                if source == "qq" and report_targets is not None else None)
        self._export_report = export_report if self._report_targets is not None else None
        self._entries = build_sticker_catalog(
            stickers.sends, source=source, conversation_type=conversation_type)
        all_entries = self._entries
        if self._report_targets is not None:
            by_key = {entry.media_key: entry for entry in self._entries}
            self._entries = tuple(by_key[key] for key in self._report_targets if key in by_key)
        self._media = {item.media_key: item for item in stickers.media}
        layout = QVBoxLayout(self)
        self.scope = QLabel(
            f"当前{'群聊' if group else '私聊'}：{conversation_label or '未命名会话'}\n"
            "仅本次分析范围内已确认的表情发送；不代表账号全局使用量。", self)
        self.scope.setTextFormat(Qt.TextFormat.PlainText)
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        known = sum(entry.identity_known for entry in all_entries)
        unresolved = sum(entry.count for entry in all_entries if not entry.identity_known)
        unknown = sum(entry.unknown_sender_count if group else entry.unknown_count for entry in all_entries)
        self.coverage = QLabel(
            f"表情发送 {sum(e.count for e in all_entries)} 次 · 可信独特素材 {known} 种 · "
            f"素材身份不明 {unresolved} 次 · 发送者未知 {unknown} 次", self)
        self.coverage.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)
        if self._report_targets is not None:
            note = QLabel(f"本报告需要 {len(self._entries)} 种素材（含 Top 10 与招牌，已去重）。"
                          "恢复结果先保留在内存；点击“保存素材到新报告”才写入报告，旧报告保留。", self)
            note.setWordWrap(True)
            layout.addWidget(note)
        counts = stickers.message_counts
        denominator = QLabel(
            (f"本次群聊消息分母：共 {counts.total_messages} 条（包括非表情消息）" if group else
             f"本次私聊消息分母：我 {counts.self_messages} / TA {counts.other_messages} / 未知 {counts.unknown_messages}"),
            self)
        layout.addWidget(denominator)
        content = QHBoxLayout()
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["素材类别", "我", "其他成员合计", "本人归属未知", "发送次数", "原件状态"] if group else
            ["素材类别", "我", "TA", "未知", "发送次数", "原件状态"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda *_: self._show_selected())
        content.addWidget(self.table, 1)
        self.card = _StickerCard("真实原件预览", "请选择素材", self)
        content.addWidget(self.card)
        layout.addLayout(content, 1)
        self.members = QPlainTextEdit(self)
        self.members.setReadOnly(True)
        self.members.setPlaceholderText("选择素材查看逐成员发送次数（按发送者 ID 区分）")
        self.members.setMaximumHeight(120)
        self.members.setVisible(group)
        layout.addWidget(self.members)
        self.send_selector = QComboBox(self)
        self.send_selector.setToolTip("选择要通过 QQ 获取的具体发送记录；优先其他成员。")
        self.send_selector.setVisible(group and source == "qq")
        layout.addWidget(self.send_selector)
        paging = QHBoxLayout()
        self.previous_button = QPushButton("上一页", self)
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.next_button = QPushButton("下一页", self)
        self.next_button.clicked.connect(lambda: self._change_page(1))
        self.page_label = QLabel(self)
        paging.addWidget(self.previous_button)
        paging.addWidget(self.page_label)
        paging.addWidget(self.next_button)
        paging.addStretch()
        layout.addLayout(paging)
        self.status = QLabel(
            "未授权不会读取素材。每页最多32种，共用一次扫描；其他页需另行发起关联。"
            + ("群聊可选择对应成员的发送记录，单独确认后复核身份；仅在全部匹配时通过 QQ 获取。" if group else
               "QQ 自定义表情选中后可单独确认，通过 QQ 获取该条消息的图片。"), self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.media_button = QPushButton("关联本页原件（最多32种）", self)
        self.media_button.clicked.connect(self._choose_media_folder)
        actions.addWidget(self.media_button)
        self.fetch_button = QPushButton("通过 QQ 获取所选素材", self)
        self.fetch_button.setToolTip(
            "仅对所选的一条已确认 QQ 图片消息，经你单独确认、内核身份复核通过后请求该图片元素。")
        self.fetch_button.setVisible(self._source == "qq")
        self.fetch_button.clicked.connect(self._fetch_selected_media)
        actions.addWidget(self.fetch_button)
        self.export_button = QPushButton("保存素材到新报告", self)
        self.export_button.setVisible(self._export_report is not None)
        self.export_button.setToolTip("将报告所需的已授权图片保存为新报告；统计和旧报告保持原样。")
        self.export_button.clicked.connect(self._save_report)
        actions.addWidget(self.export_button)
        self.cancel_button = QPushButton("取消查找", self)
        self.cancel_button.clicked.connect(self._cancel_search)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        close = QPushButton("关闭", self)
        close.clicked.connect(self.close)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._render()

    @property
    def stickers(self) -> StickerData:
        """Current enriched facts; consumers never need to inspect source caches."""
        return self._stickers

    def _page_entries(self):
        start = self._page * STICKER_MEDIA_BATCH_SIZE
        return self._entries[start:start + STICKER_MEDIA_BATCH_SIZE]

    def _change_page(self, step):
        if self._closed or self._resolving:
            return
        page = self._page + step
        if 0 <= page < max(1, (len(self._entries) + STICKER_MEDIA_BATCH_SIZE - 1) // STICKER_MEDIA_BATCH_SIZE):
            self._page = page
            self._render()

    def _render(self):
        entries = self._page_entries()
        self.table.setRowCount(0)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            kind = {"qq_pic_45406_md5": "QQ PIC", "qq_marketface_45600": "QQ MFACE",
                    "wechat_xml_md5": "微信 Type 47"}.get(entry.identity_basis, "身份不明")
            if entry.media_key.startswith("qq-marketface:"):
                kind = "QQ MFACE"
            if self._report_targets is not None:
                kind = f"{self._report_targets[entry.media_key]} · {kind}"
            values = (kind, entry.self_count, entry.other_count, entry.unknown_count,
                      entry.count, _media_text(self._media.get(entry.media_key)))
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        if entries:
            self.table.setCurrentCell(0, 0)
        else:
            self.card.show_empty()
            self.members.clear()
            self.send_selector.clear()
        pages = max(1, (len(self._entries) + STICKER_MEDIA_BATCH_SIZE - 1) // STICKER_MEDIA_BATCH_SIZE)
        self.page_label.setText(f"第 {self._page + 1} / {pages} 页 · 共 {len(self._entries)} 项")
        self._update_buttons()

    def _selected_entry(self) -> StickerCatalogEntry | None:
        row = self.table.currentRow()
        entries = self._page_entries()
        return entries[row] if 0 <= row < len(entries) else None

    def _show_selected(self):
        entry = self._selected_entry()
        if entry is not None:
            self.card.show_entry(entry, self._media.get(entry.media_key))
            if self._conversation_type == "group":
                lines = [f"{sender}：{count} 次" for sender, count in entry.member_counts]
                if entry.unknown_sender_count:
                    lines.append(f"发送者未知：{entry.unknown_sender_count} 次")
                self.members.setPlainText(
                    f"已确认成员 {len(entry.member_counts)} 人 · 发送 {entry.count} 次\n" + "\n".join(lines))
                previous = self.send_selector.currentData()
                self.send_selector.clear()
                sends = [s for s in self._stickers.sends if s.media_key == entry.media_key
                         and s.source == "qq" and s.conversation_type == "group"]
                for index, send in enumerate(sends):
                    self.send_selector.addItem(
                        f"{'本人' if send.is_self is True else '成员'} {send.sender_id or '未知'}"
                        f" · {send.chat_date or '日期未知'} · 发送记录 {index + 1}", send.occurrence_id)
                preferred = next((s.occurrence_id for s in sends if s.is_self is False), None)
                index = self.send_selector.findData(previous)
                self.send_selector.setCurrentIndex(index if index >= 0 else max(0, self.send_selector.findData(preferred)))
        self._update_buttons()

    def _can_fetch(self, entry: StickerCatalogEntry | None) -> bool:
        """Only one selected custom PIC send from this private QQ chat."""
        return (
            entry is not None
            and self._source == "qq"
            and self._conversation_type in ("private", "group")
            and bool(self._session_id)
            and (self._conversation_type != "group" or self.send_selector.currentData() is not None)
            and entry.identity_basis == "qq_pic_45406_md5"
            and entry.media_key.startswith("qq-pic:md5:")
            and (self._conversation_type == "group" or not _is_available(self._media.get(entry.media_key)))
        )

    def _update_buttons(self):
        idle = not self._closed and not self._resolving
        self.previous_button.setEnabled(idle and self._page > 0)
        self.next_button.setEnabled(idle and (self._page + 1) * STICKER_MEDIA_BATCH_SIZE < len(self._entries))
        self.media_button.setEnabled(idle and any(
            entry.identity_basis in {"qq_pic_45406_md5", "wechat_xml_md5"}
            and not _is_available(self._media.get(entry.media_key))
            for entry in self._page_entries()))
        self.fetch_button.setEnabled(idle and self._can_fetch(self._selected_entry()))
        self.send_selector.setEnabled(idle)
        self.cancel_button.setEnabled(self._resolving and not self._cancelled.is_set())
        self.export_button.setEnabled(idle and self._export_report is not None and any(
            self._media.get(key) is not None and self._media[key].status not in {"not_requested", "unsupported"}
            for key in (self._report_targets or ())))

    def _choose_media_folder(self):
        if self._closed or self._resolving:
            return
        self._cancelled = Event()
        if self._source == "qq":
            self._discover_qq_directories()
        else:
            selected = QFileDialog.getExistingDirectory(
                self, "选择允许 Echo 只读验证本页原件的本地文件夹（含子目录）")
            if selected and not self._closed:
                self._resolve_roots((Path(selected),))
            else:
                self.status.setText("未选择文件夹，未读取媒体。")

    def _discover_qq_directories(self, data_path=None) -> None:
        self._resolving = True
        self._update_buttons()
        self.status.setText("正在识别 QQ 数据目录，尚未读取媒体文件…")
        facade, cancelled = self._facade, self._cancelled
        self._executor(
            lambda: facade.discover_qq_sticker_directories(data_path=data_path, cancelled=cancelled.is_set),
            on_success=lambda candidates: self._directories_found(candidates, manual=data_path is not None),
            on_error=self._discovery_failed,
            on_finished=lambda: None,
        )

    def _discovery_failed(self, code, public_message) -> None:
        self._media_failed(code, public_message)
        self._media_finished()

    def _directories_found(self, candidates, *, manual) -> None:
        self._media_finished()
        if self._closed or self._cancelled.is_set():
            return
        if not candidates and not manual:
            selected = QFileDialog.getExistingDirectory(self, "未发现有效 QQ 素材目录，请选择 QQ 数据保存文件夹或账号文件夹")
            if self._closed:
                return
            if selected:
                self._discover_qq_directories(Path(selected))
            else:
                self.status.setText("未选择文件夹，未读取任何媒体文件。")
            return
        if not candidates:
            self.status.setText("所选位置未识别到支持的 QQ 原图目录，未读取媒体文件。")
            return
        roots = self._confirm_qq_scope(candidates)
        if self._closed:
            return
        if not roots:
            self.status.setText("未授权读取素材，未读取任何媒体文件。")
            return
        self._resolve_roots(roots)

    def _confirm_qq_scope(self, candidates) -> tuple[Path, ...]:
        dialog = _QQMediaScopeDialog(candidates, self)
        try:
            return dialog.roots if dialog.exec() == QDialog.DialogCode.Accepted else ()
        finally:
            dialog.deleteLater()

    def _resolve_roots(self, roots: tuple[Path, ...]) -> None:
        if self._closed or self._cancelled.is_set():
            return
        keys = tuple(entry.media_key for entry in self._page_entries())
        if not keys:
            return
        self._resolving = True
        self._update_buttons()
        self.status.setText("正在授权范围内共用一次有界扫描，逐一验证完整 MD5 与图片…")
        facade, cancelled, data, source = self._facade, self._cancelled, self._stickers, self._source
        diagnostics = {} if source == "qq" else None
        self._executor(
            lambda: facade.associate_sticker_media(
                data, media_keys=keys, roots=roots, source=source, cancelled=cancelled.is_set,
                diagnostics=diagnostics),
            on_success=lambda result: self._media_resolved(result, diagnostics=diagnostics),
            on_error=self._media_failed,
            on_finished=self._media_finished)

    def _confirm_network_fetch(self, entry: StickerCatalogEntry) -> bool:
        """Separate, explicit consent: the only path that uses the network."""
        answer = QMessageBox.question(
            self, "确认通过 QQ 获取素材",
            "即将通过已登录的 QQ 客户端，从 QQ 网络下载本次所选的一条图片消息素材。\n"
            f"· 仅处理当前{'群聊' if self._conversation_type == 'group' else '私聊'}中所选的一条发送记录及其图片元素；\n"
            "· 先复核消息、会话、发送者与图片元素，未通过则不下载；\n"
            "· 不读取其他消息、其他会话或本机任意文件；\n"
            + ("· 内容先保留在本次窗口内存；仅在点击“保存素材到新报告”后写入报告；\n"
               if self._export_report is not None else
               "· 取回内容只保留在本次窗口内存中，不写入磁盘、不进入报告；\n")
            + "· 单次上限 2 MiB，超出或验证失败则不展示。\n\n"
            "继续并允许本次网络获取？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _fetch_selected_media(self) -> None:
        if self._closed or self._resolving:
            return
        entry = self._selected_entry()
        if not self._can_fetch(entry):
            return
        if not self._confirm_network_fetch(entry):
            self.status.setText("未确认网络获取，未读取 QQ 媒体。")
            return
        self._cancelled = Event()
        self._resolving = True
        self._update_buttons()
        self.status.setText("正在通过 QQ 获取所选素材：仅此一条已确认消息，不写入磁盘…")
        facade, data = self._facade, self._stickers
        session_id, key, cancelled = self._session_id, entry.media_key, self._cancelled
        selection = ({"occurrence_id": self.send_selector.currentData()}
                     if self._conversation_type == "group" else {})
        self._executor(
            lambda: facade.fetch_qq_sticker_media(
                data, media_key=key, session_id=session_id,
                network_consent=True, cancelled=cancelled.is_set, **selection),
            on_success=lambda result: self._network_resolved(result, key),
            on_error=lambda code, message: self._network_failed(key, code, message),
            on_finished=self._media_finished)

    def _network_failed(self, key: str, code: str, message: str) -> None:
        if self._closed or self._cancelled.is_set():
            return
        # Retain only fixed failure categories; never put exception text or
        # locators into report data. A failed retry cannot erase a valid image.
        if not _is_available(self._media.get(key)):
            from ..application.sticker_media import qq_media_failure
            self._media[key] = qq_media_failure(key, code)
            self._stickers = replace(self._stickers, media=tuple(self._media.values()))
            self._render()
        self._media_failed(code, message)

    def _save_report(self) -> None:
        if not self.export_button.isEnabled():
            return
        self._cancelled = Event()
        self._resolving = True
        self._update_buttons()
        self.cancel_button.setEnabled(False)
        self.status.setText("正在将已授权素材保存到新报告，旧报告保留…")
        export, data = self._export_report, self._stickers
        self._executor(lambda: export(data), on_success=self._report_saved,
                       on_error=self._media_failed, on_finished=self._media_finished)

    def _report_saved(self, outcome) -> None:
        if not self._closed:
            # Publishing an explicitly requested snapshot cannot be undone by
            # a late cancel. It remains in local history even if this closes.
            self.report_exported.emit(outcome)

    def _network_resolved(self, data: StickerData, key: str) -> None:
        if self._closed or self._cancelled.is_set():
            return
        self._stickers = data
        self._media = {item.media_key: item for item in data.media}
        self._render()
        # Keep the fetched material selected; a redraw would otherwise jump to row 0.
        row = next((index for index, entry in enumerate(self._page_entries())
                    if entry.media_key == key), -1)
        if row >= 0:
            self.table.setCurrentCell(row, 0)
        self._show_selected()
        media = self._media.get(key)
        if media is None:
            self.status.setText("QQ 媒体获取未返回结果，未展示任何图片。")
        elif media.status == "available":
            self.status.setText(
                "QQ 媒体获取成功：内容摘要与消息摘要一致，按已验证原件展示；未写入磁盘。")
        elif media.status == "preview":
            self.status.setText(
                "QQ 媒体获取成功：内容摘要与消息摘要不符，仅作为可信预览展示，"
                "不代表原件；未写入磁盘。")
        else:
            self.status.setText(f"QQ 媒体获取失败：{_media_text(media)}")

    def _media_resolved(self, data: StickerData, *, diagnostics=None) -> None:
        if self._closed or self._cancelled.is_set():
            return
        self._stickers = data
        self._media = {item.media_key: item for item in data.media}
        self._render()
        selected = [self._media.get(entry.media_key) for entry in self._page_entries()]
        available = sum(_is_available(item) for item in selected)
        limited = sum(item is not None and item.status == "limited" for item in selected)
        self.status.setText(
            f"本页已验证 {available} 个原件；{limited} 项未完整搜索。"
            "缺失、摘要不匹配及不支持原因见状态列；发送次数不受影响。")
        if diagnostics:
            traversal = "目录遍历完成" if diagnostics["traversal_complete"] else "目录遍历未完成"
            coverage = "全部文件内容已检查" if diagnostics["all_files_checked"] else "未检查非候选内容"
            budget = "预算受限" if diagnostics["budget_exhausted"] else "预算未耗尽"
            self.status.setText(self.status.text() + (
                f"\n{traversal} · 候选 {diagnostics['candidate_files']}"
                f"（名称 {diagnostics['name_candidates']}／路径 {diagnostics['path_candidates']}）"
                f" · 已读 {diagnostics['files_read']} · {coverage} · {budget}。"))

    def _media_failed(self, code: str, public_message: str) -> None:
        if not self._closed and not self._cancelled.is_set():
            self.status.setText(public_message)

    def _media_finished(self) -> None:
        self._resolving = False
        if self._closed:
            return
        if self._cancelled.is_set():
            self.status.setText("已取消，本次关联结果未使用。")
        self._update_buttons()

    def _cancel_search(self) -> None:
        self._cancelled.set()
        self.cancel_button.setEnabled(False)
        self.status.setText("正在取消并释放资源…")

    def done(self, result: int) -> None:
        self._release()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._release()
        super().closeEvent(event)

    def _release(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancelled.set()
        self.card.release_media()
        self.members.clear()
        self.send_selector.clear()
        self._media.clear()
        self._entries = ()
        self._stickers = StickerData()
        self._export_report = None
        self._report_targets = None
        self.table.setRowCount(0)
        self._update_buttons()
