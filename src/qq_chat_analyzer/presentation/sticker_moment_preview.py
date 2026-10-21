"""Opt-in, in-memory Qt experiment. Never called by report/export pipelines.

Call on the Qt GUI thread with a live QApplication. The caller chooses whether
to show/exec the returned dialog. Only existing verified media snapshots are
read; the dialog neither recovers media nor takes ownership of those snapshots.
"""
from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..analysis.sticker_stories import StickerMoment
from ..analysis.stickers import StickerData, StickerMedia
from ..analysis.timestamps import to_chat_datetime
from ..rich_message import ExpressionContent, NonTextContent, TextContent


def create_local_moment_preview(moment: StickerMoment, data: StickerData) -> QDialog:
    """Build a read-only local preview, with no files, logging or share actions."""
    sends = set(data.sends)
    if any(send not in sends for row in moment.messages for send in row.sends):
        raise ValueError("moment and media must belong to the same analysis")
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
        widget = QLabel(text, body)
        widget.setTextFormat(Qt.TextFormat.PlainText)
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
    # Qt parent ownership keeps buffers and movies alive until dialog deletion.
    # Each occurrence gets its own playback device; snapshots remain caller-owned.
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
                _set_image(image, item, dialog)
            elif isinstance(part, ExpressionContent):
                label(part.display_text or f"[表达：{part.expression_kind}；无可用媒体]")
            elif isinstance(part, NonTextContent):
                label(f"[未支持内容：{part.kind}]")
            else:
                label("[未支持内容]")
    layout.addStretch()
    return dialog


def _set_image(label: QLabel, item: StickerMedia | None, dialog: QDialog) -> None:
    if item is None or item.status not in ("available", "preview"):
        label.setText(f"[缺图：{item.status if item else '未恢复'}；原消息仍在]")
        return
    try:
        raw = item.original_bytes if item.original_bytes is not None else item.stored.read() if item.stored else None
    except (OSError, ValueError):
        raw = None
    if not raw:
        label.setText("[缺图：已验证快照不可读；不重新访问来源]")
        return
    prefix = "原图已验证" if item.status == "available" else "可信预览；并非原图"
    label.setToolTip(prefix)
    if item.frame_count and item.frame_count > 1:
        buffer = QBuffer(dialog)
        buffer.setData(QByteArray(raw))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        movie = QMovie(buffer, QByteArray(), dialog)
        if not movie.isValid() or movie.frameCount() != item.frame_count:
            label.setText("[动画暂无法复现；保留原消息与媒体验证事实]")
            movie.deleteLater()
            buffer.deleteLater()
            return
        movie.jumpToFrame(0)
        size = movie.currentImage().size()
        if size.width() > 280 or size.height() > 200:
            movie.setScaledSize(size.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio))
        label.setMovie(movie)
        movie.start()
    else:
        pixmap = QPixmap()
        if not pixmap.loadFromData(raw):
            label.setText("[媒体暂无法显示；保留原消息]")
            return
        label.setPixmap(pixmap.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
    # Visible provenance applies to animations as well as still images.
    caption = QLabel(f"[{prefix}]", label.parentWidget())
    caption.setTextFormat(Qt.TextFormat.PlainText)
    caption.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.parentWidget().layout().addWidget(caption)
