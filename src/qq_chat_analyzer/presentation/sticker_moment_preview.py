"""Opt-in, in-memory Qt experiment. Never called by report/export pipelines.

Call on the Qt GUI thread with a live QApplication. The caller chooses whether
to show/exec the returned dialog. Only existing verified media snapshots are
read; the dialog neither recovers media nor takes ownership of those snapshots.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..analysis.sticker_stories import StickerMoment
from ..analysis.stickers import StickerData, StickerMedia
from ..analysis.timestamps import to_chat_datetime
from ..rich_message import ExpressionContent, NonTextContent, TextContent

if TYPE_CHECKING:
    from ..analysis.sticker_features import PrivateStickerFeatures

MAX_PREVIEW_CONTENTS = 256
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_MOVIES = 4
MAX_PREVIEW_PIXELS = 4_000_000
MAX_PREVIEW_DECODE_WORK = 64_000_000


def create_local_moment_preview(moment: StickerMoment, data: StickerData, *, features: PrivateStickerFeatures) -> QDialog:
    """Build a read-only local preview, with no files, logging or share actions."""
    sends = {id(send) for send in data.sends}
    # Equality cannot establish run ownership: another import can have identical
    # IDs, timestamps and media keys. Only a moment held by this result, and the
    # original send references preserved through media resolution, are accepted.
    if (not any(moment is item for item in features.stories.moments)
            or any(id(send) not in sends for row in moment.messages for send in row.sends)
            or len({item.media_key for item in data.media}) != len(data.media)):
        raise ValueError("moment and media must belong to the same analysis")
    if sum(max(1, len(row.message.contents)) for row in moment.messages) > MAX_PREVIEW_CONTENTS:
        raise ValueError("local preview content budget exceeded; evidence remains intact")
    dialog = QDialog()
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle("经典瞬间 · 本地实验预览")
    dialog.resize(640, 760)
    outer = QVBoxLayout(dialog)
    area = QScrollArea(dialog)
    area.setWidgetResizable(True)
    body = QWidget(area)
    layout = QVBoxLayout(body)
    area.setWidget(body)
    outer.addWidget(area)

    def label(text: str) -> QLabel:
        widget = QLabel(body)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setText(text)
        widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        widget.setWordWrap(True)
        layout.addWidget(widget)
        return widget

    label("仅本地预览 · 未接入分享报告\n只复现导入且通过过滤的片段；来源可能遗漏消息类型。")
    label("核心消息范围：" + str(moment.core_start) + "–" + str(moment.core_end)
          + "（末位不含）；上下文不等于完整聊天。")
    limits = {
        "imported_filtered_slice_only": "仅含正式过滤后的消息",
        "source_may_omit_message_types": "来源可能省略消息",
        "context_time_gap": "上下文在超过30分钟的间隔处停止",
        "context_message_budget": "上下文过长，已省略额外作者轮次",
        "import_boundary": "已到达本次导入边界",
        "bounded_representative_of_overlapping_relays": "此互动含重叠窗口，当前只复现一个有界片段",
        "context_barrier:unknown_side": "上下文遇到未知作者，未越过",
        "context_barrier:unknown_time": "上下文时间不确定，未越过",
        "context_barrier:tied_or_reversed_time": "上下文消息顺序不确定，未越过",
        "context_barrier:filtered_or_unpaired_gap": "上下文有过滤或缺失消息，未越过",
    }
    label("边界与限制：" + "；".join(limits.get(q, "存在未确认的上下文边界") for q in moment.qualifiers))
    media = {item.media_key: item for item in data.media}
    cache = {}
    budget = {"bytes": MAX_PREVIEW_BYTES, "movies": MAX_PREVIEW_MOVIES, "work": MAX_PREVIEW_DECODE_WORK}
    # One device per material, bounded across the dialog. Snapshots stay caller-owned.
    for row in moment.messages:
        msg = row.message
        side = "我" if msg.is_self is True else "TA" if msg.is_self is False else "未知作者"
        dt = to_chat_datetime(msg.timestamp)
        label(f"{side} · {dt.isoformat(sep=' ') if dt else '时间不确定'} · 消息 #{row.ordinal}")
        if msg.recall_state is not None and msg.recall_state.is_recalled:
            label("[已撤回；以下为来源仍保留的内容]")
        if msg.recall_event is not None:
            label("[来源记录了撤回事件]")
        for relation in msg.relations:
            label("[回复关系：目标仅为来源引用，不重建消息]" if hasattr(relation, "target_message_id")
                  else "[提及关系：保留来源记录]")
        by_content = {send.content_index: send for send in row.sends}
        if not msg.contents:
            label("[无可复现内容；来源类型未展开]")
        for i, part in enumerate(msg.contents):
            if isinstance(part, TextContent):
                label(part.text)
            elif i in by_content:
                item = media.get(by_content[i].media_key)
                image = label("")
                _set_image(image, item, dialog, cache, budget)
            elif isinstance(part, ExpressionContent):
                label(part.display_text or f"[表达：{part.expression_kind}；无可用媒体]")
            elif isinstance(part, NonTextContent):
                label(f"[未支持内容：{part.kind}]")
            else:
                label("[未支持内容]")
    layout.addStretch()
    return dialog


def _load_image(item: StickerMedia | None, dialog: QDialog, budget: dict):
    if item is None or item.status not in ("available", "preview"):
        return None, f"[缺图：{item.status if item else '未恢复'}；原消息仍在]"
    if item.frame_count and item.frame_count > 1 and not budget["movies"]:
        return None, "[预览播放器预算已用完；原消息与媒体引用保留]"
    size = len(item.original_bytes) if item.original_bytes is not None else item.stored.size if item.stored else 0
    if size > budget["bytes"]:
        return None, "[预览字节预算已用完；原消息与媒体引用保留]"
    try:
        raw = item.original_bytes if item.original_bytes is not None else item.stored.read() if item.stored else None
    except (OSError, ValueError):
        raw = None
    if not raw:
        return None, "[缺图：已验证快照不可读；不重新访问来源]"
    if len(raw) > budget["bytes"]:
        return None, "[预览字节预算已用完；原消息与媒体引用保留]"
    budget["bytes"] -= len(raw)
    buffer = QBuffer(dialog)
    buffer.setData(QByteArray(raw))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    pixels = size.width()*size.height()
    work = pixels*max(1, item.frame_count or 1)
    if not size.isValid() or pixels > MAX_PREVIEW_PIXELS or work > budget["work"]:
        buffer.deleteLater()
        return None, "[预览解码预算不足；原消息与媒体引用保留]"
    budget["work"] -= work
    prefix = "原图已验证" if item.status == "available" else "可信预览；并非原图"
    buffer.seek(0)
    if item.frame_count and item.frame_count > 1:
        movie = QMovie(buffer, QByteArray(), dialog)
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        if not movie.isValid() or movie.frameCount() != item.frame_count:
            movie.deleteLater()
            buffer.deleteLater()
            return None, "[动画暂无法复现；保留原消息与媒体验证事实]"
        movie.jumpToFrame(0)
        size = movie.currentImage().size()
        if size.width() > 280 or size.height() > 200:
            movie.setScaledSize(size.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio))
        budget["movies"] -= 1
        movie.start()
        return movie, prefix
    else:
        pixmap = QPixmap()
        buffer.deleteLater()
        if not pixmap.loadFromData(raw):
            return None, "[媒体暂无法显示；保留原消息]"
        return pixmap.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation), prefix


def _set_image(label: QLabel, item: StickerMedia | None, dialog: QDialog, cache: dict, budget: dict) -> None:
    key = item.media_key if item else None
    if key not in cache:
        cache[key] = _load_image(item, dialog, budget)
    image, prefix = cache[key]
    if image is None:
        label.setText(prefix)
        return
    label.setToolTip(prefix)
    if isinstance(image, QMovie):
        label.setMovie(image)
    else:
        label.setPixmap(image)
    # Visible provenance applies to animations as well as still images.
    caption = QLabel(label.parentWidget())
    caption.setTextFormat(Qt.TextFormat.PlainText)
    caption.setText(f"[{prefix}]")
    caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.parentWidget().layout().addWidget(caption)
