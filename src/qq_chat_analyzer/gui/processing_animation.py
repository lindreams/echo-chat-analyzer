"""Stateless QPainter rendering of Astra's book animation.

No widget, timer, task integration or clock. Reads Stage 2A's paper state.
Animated ink and pen share the same cubic arc-length split. SVG blur filters are simplified to a
soft ground gradient and an unblurred, faint flying-paper shadow. All other
paths, gradient stops, paragraph marks and grain retain the prototype values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QGradient, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)

from . import processing_geometry as g
from .processing_animation_model import LeafKind, PaperSide, ProcessingAnimationModel, clamp01, ease, mix

_PAPER_STOPS = {
    PaperSide.LEFT: ((0, "#fbf8ef"), (.65, "#fffdf7"), (.94, "#efe7d9"), (1, "#e4d7c5")),
    PaperSide.RIGHT: ((0, "#e4d7c5"), (.09, "#f5efe4"), (.43, "#fffdf7"), (1, "#f8f3e9")),
}


def _gradient(stops, loose=False):
    gradient = QLinearGradient(.12, 0, .9, 1) if loose else QLinearGradient(0, 0, 1, 0)
    gradient.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
    for at, color in stops:
        gradient.setColorAt(at, QColor(color))
    return QBrush(gradient)


def _draw(painter, path, fill=None, stroke=None, width=1, opacity=1):
    painter.save()
    try:
        painter.setOpacity(painter.opacity()*opacity)
        painter.setBrush(Qt.BrushStyle.NoBrush if fill is None else QBrush(fill))
        if stroke is None:
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            pen = QPen(QColor(stroke), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
        painter.drawPath(path)
    finally:
        painter.restore()


def _ellipse(x, y, rx, ry):
    path = QPainterPath()
    path.addEllipse(QRectF(x-rx, y-ry, rx*2, ry*2))
    return path


def _grain(painter, path):
    """SVG's 37 x 31 pattern, clipped in logical user-space coordinates."""
    painter.save()
    try:
        painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
        rect = path.boundingRect()
        for y in range(math.floor(rect.top()/31)*31, math.ceil(rect.bottom()/31)*31, 31):
            for x in range(math.floor(rect.left()/37)*37, math.ceil(rect.right()/37)*37, 37):
                _draw(painter, _ellipse(x+3, y+7, .5, .5), "#a78865", opacity=.15)
                _draw(painter, _ellipse(x+19, y+23, .45, .45), "#8f795f", opacity=.12)
                marks = QPainterPath()
                marks.moveTo(x+28, y+11)
                marks.lineTo(x+29.5, y+11)
                marks.moveTo(x+9, y+27)
                marks.lineTo(x+10, y+27)
                _draw(painter, marks, stroke="#a78865", width=.45, opacity=.13)
    finally:
        painter.restore()


def _paper(painter, points, side, *, incoming_progress=None, recorded=False):
    path = g.paper_path(points)
    loose = incoming_progress is not None or recorded
    fill = _gradient(((0, "#fffef9"), (.65, "#fbf7ed"), (1, "#e9ddca")), True) if loose else _gradient(_PAPER_STOPS[side])
    _draw(painter, path, fill, "#cabb9f" if loose else "#caba9f", .8 if loose else .75)
    if loose:
        shade = 1 if recorded else ease((incoming_progress-.52)/.48)
        _draw(painter, path, _gradient(_PAPER_STOPS[side]), opacity=shade)
    _grain(painter, path)
    if loose:
        _draw(painter, g.paper_ink_path(points, side), stroke="#b1a189", width=1.05, opacity=.24)


def _pen(painter, point, angle, alpha, lift):
    painter.save()
    try:
        painter.setOpacity(painter.opacity()*alpha)
        painter.translate(*point)
        _draw(painter, _ellipse(5, 4, 11, 3), "#775943", opacity=.09*(1-clamp01(lift/35)))
        painter.rotate(angle)
        _draw(painter, g.pen_body_path(), _gradient(((0, "#794631"), (.43, "#b47755"), (.68, "#a75e41"), (1, "#84472f"))), "#844a33", .65)
        highlight = QPainterPath()
        highlight.moveTo(-3, -31)
        highlight.lineTo(-3, -97)
        highlight.quadTo(-3, -111, -1, -119)
        _draw(painter, highlight, stroke="#e3b18a", width=1, opacity=.48)
        bands = QPainterPath()
        for y in (-28, -25):
            bands.moveTo(-6, y)
            bands.lineTo(6, y)
        _draw(painter, bands, stroke="#cdaa7e", width=1)
        _draw(painter, g.pen_nib_path(), _gradient(((0, "#a97952"), (.45, "#ead4af"), (.6, "#f5e7c9"), (1, "#b58a5e"))), "#9a724c", .65)
        slit = QPainterPath()
        slit.moveTo(0, -2)
        slit.lineTo(0, -17)
        slit.moveTo(-4, -18)
        slit.quadTo(0, -15, 4, -18)
        _draw(painter, slit, stroke="#8e6946", width=.7)
        _draw(painter, _ellipse(0, -18, 1.15, 1.15), "#947453")
    finally:
        painter.restore()


@dataclass(frozen=True)
class PenPose:
    point: g.Point
    angle: float


def pen_pose(model: ProcessingAnimationModel) -> PenPose:
    """Physical tip location, including the prototype's word-hop/phase lifts."""
    motion = model.pen_motion
    points = g.page_points(PaperSide.RIGHT, motion.depth)
    pose = g.writing_pose(points, motion.writing_progress)
    point, angle, hop_lift = pose.point, pose.angle, pose.lift
    if motion.turn_progress is not None:
        end = g.writing_pose(points, 1).point
        start = g.writing_pose(points, 0).point
        t = ease(motion.turn_progress)
        point = (mix(end[0], start[0], t), mix(end[1], start[1], t))
        angle, hop_lift = 31, 0
    return PenPose((point[0], point[1]-hop_lift-model.pen_lift), angle)


def _written_ink(painter, points, progress):
    if progress > 0:
        for path in g.writing_pose(points, progress).paths:
            _draw(painter, path, stroke="#a75e41", width=1.45, opacity=.75)


def _turned_paper(painter, points, progress):
    fill = _gradient(_PAPER_STOPS[PaperSide.LEFT]) if progress > .75 else _gradient(
        ((0, "#fffef9"), (.65, "#fbf7ed"), (1, "#e9ddca")), True)
    _draw(painter, g.paper_path(points), fill, "#caba9f", .75)
    _draw(painter, g.paper_ink_path(points, PaperSide.RIGHT, detailed=True),
          stroke="#a75e41", width=1.45, opacity=mix(.6, .28, ease(progress)))


def paint_processing_frame(painter: QPainter, viewport: QRectF, model: ProcessingAnimationModel) -> None:
    """Paint a model snapshot, without advancing or retaining state.

    Aspect ratio is preserved in any viewport. Painter state is restored.
    The caller owns the background.
    """
    if viewport.width() <= 0 or viewport.height() <= 0:
        return
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(viewport, Qt.ClipOperation.IntersectClip)
        scale = min(viewport.width()/g.LOGICAL_WIDTH, viewport.height()/g.LOGICAL_HEIGHT)
        painter.translate(viewport.x()+(viewport.width()-800*scale)/2,
                          viewport.y()+(viewport.height()-460*scale)/2)
        painter.scale(scale, scale)
        # SVG groundBlur approximation only; book geometry is unchanged.
        painter.save()
        painter.translate(401, 392)
        painter.scale(211, 23)
        shadow = QRadialGradient(0, 0, 1)
        color = QColor("#7f6448")
        color.setAlphaF(.12)
        shadow.setColorAt(0, color)
        shadow.setColorAt(.55, color)
        color = QColor(color)
        color.setAlphaF(0)
        shadow.setColorAt(1, color)
        _draw(painter, _ellipse(0, 0, 1, 1), QBrush(shadow))
        painter.restore()
        _draw(painter, g.book_cover_path(), "#d5b49c", "#b88c6c", 1.1)
        _draw(painter, g.cover_edge_path(), stroke="#a77553", width=1, opacity=.55)
        for side in (PaperSide.LEFT, PaperSide.RIGHT):
            for edge in g.page_edge_paths(side, model.leaf_depth(side)):
                _draw(painter, edge, stroke="#cdbda6", width=.8)
        for leaf in model.leaves():
            points = g.page_points(leaf.side, leaf.depth)
            if leaf.kind is LeafKind.TURNED:
                _turned_paper(painter, points, 1)
            else:
                _paper(painter, points, leaf.side, recorded=leaf.kind is LeafKind.READING)
            _written_ink(painter, points, leaf.ink_progress)
        _draw(painter, g.gutter_path(), stroke="#b29a7f", width=.8, opacity=.65)
        _draw(painter, g.binding_tail_path(), stroke="#a7805e", width=1.2)
        if model.turn is None:
            right = model.leaves(PaperSide.RIGHT)[-1]
            _written_ink(painter, g.page_points(PaperSide.RIGHT, right.depth), model.ink_progress)
        incoming = model.incoming
        if incoming is not None:
            painter.save()
            painter.setOpacity(painter.opacity()*ease(incoming.progress/.16))
            points = g.flight_points(incoming.side, incoming.progress, incoming.depth)
            shadow_points = tuple((x+2, y+4) for x, y in points)
            _draw(painter, g.paper_path(shadow_points), "#806348",
                  opacity=math.sin(clamp01((incoming.progress-.28)/.72)*math.pi)*.065)
            _paper(painter, points, incoming.side, incoming_progress=incoming.progress)
            painter.restore()
        turn = model.turn
        if turn is not None:
            points = g.turn_points(g.page_points(PaperSide.RIGHT, turn.leaf.depth),
                                   turn.target_depth, turn.progress)
            _turned_paper(painter, points, turn.progress)
        if model.pen_alpha > 0:
            pose = pen_pose(model)
            _pen(painter, pose.point, pose.angle, model.pen_alpha, model.pen_lift)
    finally:
        painter.restore()
