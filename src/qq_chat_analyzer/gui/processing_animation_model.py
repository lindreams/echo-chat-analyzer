"""Deterministic state and timing model for the Echo processing animation.

This is the testable half of the accepted Astra book prototype
(``output/processing-book-prototype/dist/index.html``): the phase timeline, the
paper bookkeeping and the transition relations the prototype's ``T`` table and
``tick`` functions define, with the drawing removed.  A later QPainter caller
reads state from here and renders it.

Deliberate boundaries:

* Time is external.  :meth:`ProcessingAnimationModel.advance` is the only input
  that moves state, so a GUI timer and a test drive the same timeline, and no
  test needs a real clock.
* The milliseconds in :class:`AnimationTiming` are visual gesture lengths taken
  from the prototype.  They are never task durations and never describe the
  progress of the real analysis work.
* Geometry stays outside this model.  The twelve control points, the Coons
  surface interpolation for paper text, the pen silhouette and the ink
  arc-length walk are Stage 2B work and are deliberately not ported here.
* Phase events come from the application layer's
  :class:`~qq_chat_analyzer.application.analysis_phase.AnalysisPhase`, so the
  model never invents a second vocabulary for the same two stages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

from ..application.facade import AnalysisPhase


def clamp01(value: float) -> float:
    """Clamp ``value`` into the prototype's ``0..1`` range."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def ease(value: float) -> float:
    """Prototype ``ease``: smoothstep, used for every approach and landing."""
    t = clamp01(value)
    return t * t * (3.0 - 2.0 * t)


def mix(start: float, end: float, amount: float) -> float:
    """Prototype ``mix``: linear interpolation between two values."""
    return start + (end - start) * amount


class PaperSide(str, Enum):
    """Which half of the open book a sheet belongs to."""

    LEFT = "left"
    RIGHT = "right"

    def other(self) -> "PaperSide":
        """Return the opposite side, as the prototype's alternating flights do."""
        return PaperSide.RIGHT if self is PaperSide.LEFT else PaperSide.LEFT


class LeafKind(str, Enum):
    BASE = "base"
    READING = "reading"
    TURNED = "turned"


@dataclass(frozen=True, slots=True)
class PenMotion:
    """Geometry-free pen anchor, also frozen when a transition starts."""

    writing_progress: float = 0.0
    turn_progress: float | None = None
    depth: float = 0.0


@dataclass(frozen=True, slots=True)
class AnimationTiming:
    """Visual gesture lengths and book bounds, straight from the prototype.

    ``max_frame_step_ms`` is the prototype's own per-frame clamp: a single
    frame delta is never larger than this, so a stalled caller cannot skip a
    settle, pen or page-turn window.
    """

    reading_cycle_ms: float = 3700.0
    landing_ratio: float = 0.88
    settle_ms: float = 620.0
    pen_enter_ms: float = 480.0
    pen_drop_ms: float = 320.0
    writing_ms: float = 6100.0
    rest_ms: float = 720.0
    turn_ms: float = 1650.0
    exit_ms: float = 480.0
    leaf_rise: float = 1.1
    max_leaves_per_side: int = 7
    max_visible_page_edges: int = 5
    max_frame_step_ms: float = 50.0

    @property
    def landing_ms(self) -> float:
        """Reading time until the incoming sheet is bound to the spine."""
        return self.reading_cycle_ms * self.landing_ratio


@dataclass(frozen=True, slots=True)
class PaperLeaf:
    """One paper sheet: still flying in, or already part of the book."""

    leaf_id: int
    side: PaperSide
    depth: float
    landed: bool
    progress: float
    kind: LeafKind = LeafKind.BASE
    ink_progress: float = 0.0


@dataclass(frozen=True, slots=True)
class _Transition:
    """A pending phase change that retargets from the current visual state."""

    target: AnalysisPhase
    elapsed_ms: float
    flight_start: float
    turn_start: float | None
    pen_alpha: float
    resume_clock_ms: float
    pen_motion: PenMotion
    pen_lift: float


@dataclass(frozen=True, slots=True)
class PaperTurn:
    """A written sheet being turned over onto the left half of the book."""

    leaf_id: int | None
    progress: float
    target_depth: float
    leaf: PaperLeaf


class ProcessingAnimationModel:
    """Deterministic processing animation state, driven by external time.

    Lifecycle:

    * :meth:`reset` starts a new task; nothing from the previous task survives.
    * :meth:`set_phase` requests ``READING`` or ``ANALYZING_REPORT``.  A
      repeated request is a no-op, so duplicate phase events never restart a
      gesture.
    * :meth:`stop` ends the run immediately - a task that finished, failed or
      was cancelled never waits for the animation to play out.
    * :meth:`advance` moves the timeline; while paused or hidden it moves
      nothing, so hidden time is never replayed on resume.
    """

    def __init__(
        self,
        *,
        timing: AnimationTiming | None = None,
        phase: AnalysisPhase = AnalysisPhase.READING,
    ) -> None:
        self._timing = timing if timing is not None else AnimationTiming()
        self._paused = False
        self._hidden = False
        self._reduced_motion = False
        self._start(AnalysisPhase(phase))

    # ------------------------------------------------------------ lifecycle

    def _start(self, phase: AnalysisPhase) -> None:
        """Lay out a fresh run: an open book, and one sheet flying in."""
        self._active = True
        self._phase = phase
        self._requested = phase
        self._clock_ms = 0.0
        self._next_side = PaperSide.LEFT
        self._next_leaf_id = 0
        self._leaves: dict[PaperSide, list[PaperLeaf]] = {
            PaperSide.LEFT: [],
            PaperSide.RIGHT: [],
        }
        self._counts: dict[PaperSide, int] = {
            PaperSide.LEFT: 0,
            PaperSide.RIGHT: 0,
        }
        self._transition: _Transition | None = None
        self._turn: PaperTurn | None = None
        self._pen_alpha = 0.0
        self._pen_lift = 0.0
        self._pen_motion = PenMotion()
        self._ink_progress = 0.0
        # The prototype opens on one base sheet per side, then flies the first
        # sheet in from the left.
        self._leaves[PaperSide.LEFT].append(
            self._new_leaf(PaperSide.LEFT, 0.0, landed=True)
        )
        self._leaves[PaperSide.RIGHT].append(
            self._new_leaf(PaperSide.RIGHT, 0.0, landed=True)
        )
        self._incoming: PaperLeaf | None = self._make_incoming(self._next_side)
        if self._reduced_motion:
            self._static_pose(phase)

    def reset(self) -> None:
        """Begin a new task; no state of the previous task is carried over."""
        self._start(AnalysisPhase.READING)

    def stop(self) -> None:
        """End the run at once, whatever gesture is on screen.

        The pen is taken away and any sheet still in flight or mid-turn is
        dropped, so a stopped run reports no residual activity and ``advance``
        can no longer change anything.
        """
        self._active = False
        self._transition = None
        self._turn = None
        self._incoming = None
        self._pen_alpha = 0.0
        self._pen_lift = 0.0

    def set_phase(self, phase: AnalysisPhase) -> None:
        """Request a phase, retargeting from the current visual state.

        The request is compared against the *requested* phase, exactly like the
        prototype's stage buttons, so repeating an event that is already
        pending or already reached never restarts the animation.
        """
        target = AnalysisPhase(phase)
        if not self._active or target is self._requested:
            return
        if self._reduced_motion:
            self._static_pose(target)
            return
        self._requested = target
        incoming = self._incoming
        self._transition = _Transition(
            target=target,
            elapsed_ms=0.0,
            flight_start=(
                incoming.progress
                if incoming is not None and not incoming.landed
                else 1.0
            ),
            turn_start=self._turn.progress if self._turn is not None else None,
            pen_alpha=self._pen_alpha,
            resume_clock_ms=(
                min(self._clock_ms, self._timing.writing_ms)
                if self._phase is AnalysisPhase.ANALYZING_REPORT
                and self._turn is None
                else 0.0
            ),
            pen_motion=self._pen_motion,
            pen_lift=self._pen_lift,
        )

    def set_paused(self, paused: bool) -> None:
        """Hold or release the timeline; nothing catches up while held."""
        self._paused = bool(paused)

    def set_hidden(self, hidden: bool) -> None:
        """Tell the model whether its window is hidden.

        A hidden window advances nothing: the caller's elapsed time is simply
        not consumed, so resuming never replays the hidden interval.
        """
        self._hidden = bool(hidden)

    def set_reduced_motion(self, reduced: bool) -> None:
        """Use the prototype's .67 reading pose, or a settled writing pose."""
        self._reduced_motion = bool(reduced)
        if self._reduced_motion and self._active:
            self._static_pose(self._requested)

    def _static_pose(self, phase: AnalysisPhase) -> None:
        if self._turn is not None:
            self._finish_turn()
        self._transition = None
        self._phase = self._requested = phase
        if phase is AnalysisPhase.READING:
            if self._incoming is None or self._incoming.landed:
                self._incoming = self._make_incoming(self._next_side)
            self._pose_incoming(.67)
            self._clock_ms = .67*self._timing.landing_ms
            self._place_pen(alpha=0, lift=0)
        else:
            self._bind_incoming()
            self._incoming = None
            self._clock_ms = 0
            self._ink_progress = 0
            self._place_pen(alpha=1, lift=0, motion=PenMotion(depth=self._leaves[PaperSide.RIGHT][-1].depth))

    def advance(self, elapsed_ms: float) -> None:
        """Advance the timeline by externally measured milliseconds.

        Like the prototype RAF, consume at most one capped frame and discard
        the excess. Deterministic long samples must call this in small steps;
        a stalled or resumed caller must never replay its elapsed downtime.
        """
        if not self._active or self._paused or self._hidden or self._reduced_motion:
            return
        step = float(elapsed_ms)
        if step <= 0.0:
            return
        step_cap = self._timing.max_frame_step_ms
        self._tick(min(step, step_cap))

    # ---------------------------------------------------------- public state

    @property
    def active(self) -> bool:
        return self._active

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def hidden(self) -> bool:
        return self._hidden

    @property
    def reduced_motion(self) -> bool:
        return self._reduced_motion

    @property
    def pen_alpha(self) -> float:
        return self._pen_alpha

    @property
    def pen_lift(self) -> float:
        return self._pen_lift

    @property
    def pen_motion(self) -> PenMotion:
        return self._pen_motion

    @property
    def ink_progress(self) -> float:
        """Live ink on the newest right sheet; saved ink belongs to each leaf."""
        return self._ink_progress

    @property
    def turn(self) -> PaperTurn | None:
        return self._turn

    @property
    def incoming(self) -> PaperLeaf | None:
        """The sheet still on its way into the book, if any."""
        incoming = self._incoming
        if incoming is None or incoming.landed:
            return None
        return incoming

    def leaves(self, side: PaperSide | None = None) -> tuple[PaperLeaf, ...]:
        """Landed sheets in painting order, oldest first.

        One side's stack is returned when ``side`` is given; otherwise the left
        stack followed by the right stack.  A sheet that is still flying in is
        not part of the book yet - a caller paints :attr:`incoming` last so it
        stays on top of both stacks.
        """
        if side is not None:
            return tuple(self._leaves[PaperSide(side)])
        return tuple(self._leaves[PaperSide.LEFT]) + tuple(
            self._leaves[PaperSide.RIGHT]
        )

    def leaf_depth(self, side: PaperSide) -> float:
        """Depth offset of the newest sheet on one side, bounded by the cap."""
        return (
            min(
                self._counts[PaperSide(side)],
                self._timing.max_visible_page_edges,
            )
            * self._timing.leaf_rise
        )

    # ------------------------------------------------------------ time steps

    def _tick(self, dt: float) -> None:
        if self._transition is not None:
            self._tick_transition(dt)
            return
        self._clock_ms += dt
        if self._phase is AnalysisPhase.READING:
            self._tick_reading()
        else:
            self._tick_analysis()

    def _tick_reading(self) -> None:
        timing = self._timing
        if self._incoming is not None:
            self._pose_incoming(clamp01(self._clock_ms / timing.landing_ms))
            if self._clock_ms >= timing.landing_ms:
                self._bind_incoming()
        if self._clock_ms >= timing.reading_cycle_ms:
            self._clock_ms %= timing.reading_cycle_ms
            self._next_side = self._next_side.other()
            self._incoming = self._make_incoming(self._next_side)

    def _tick_analysis(self) -> None:
        timing = self._timing
        clock = self._clock_ms
        depth = self._leaves[PaperSide.RIGHT][-1].depth
        if clock < 0.0:
            settle = ease((clock + timing.pen_drop_ms) / timing.pen_drop_ms)
            self._place_pen(alpha=1.0, lift=17.0 * (1.0 - settle), motion=PenMotion(depth=depth))
        elif clock < timing.writing_ms:
            self._ink_progress = clamp01(clock / timing.writing_ms)
            self._place_pen(alpha=1.0, lift=0.0, motion=PenMotion(self._ink_progress, depth=depth))
        elif clock < timing.writing_ms + timing.rest_ms:
            self._ink_progress = 1.0
            rest = ease((clock - timing.writing_ms) / timing.rest_ms)
            self._place_pen(alpha=1.0, lift=8.0 * rest, motion=PenMotion(1.0, depth=depth))
        elif clock < timing.writing_ms + timing.rest_ms + timing.turn_ms:
            if self._turn is None:
                self._start_turn()
            progress = (
                clock - timing.writing_ms - timing.rest_ms
            ) / timing.turn_ms
            self._pose_turn(progress)
            self._place_pen(
                alpha=1.0,
                lift=17.0 + 7.0 * math.sin(progress * math.pi),
                motion=PenMotion(1.0, progress, self._turn.leaf.depth),
            )
        else:
            self._finish_turn()
            self._clock_ms = -timing.pen_drop_ms
            self._place_pen(alpha=1.0, lift=17.0, motion=PenMotion(depth=depth))

    def _tick_transition(self, dt: float) -> None:
        transition = self._transition
        if transition is None:  # pragma: no cover - guarded by the caller
            return
        self._transition = replace(
            transition, elapsed_ms=transition.elapsed_ms + dt
        )
        transition = self._transition
        elapsed = transition.elapsed_ms
        timing = self._timing
        if transition.target is AnalysisPhase.ANALYZING_REPORT:
            self._enter_analysis(transition, elapsed)
            return
        self._enter_reading(transition, elapsed)

    def _enter_analysis(self, transition: _Transition, elapsed: float) -> None:
        """Settle the incoming sheet, then bring the pen in to write."""
        timing = self._timing
        incoming = self._incoming
        if incoming is not None and not incoming.landed:
            self._pose_incoming(
                mix(
                    transition.flight_start,
                    1.0,
                    ease(elapsed / timing.settle_ms),
                )
            )
            if elapsed >= timing.settle_ms:
                self._bind_incoming()
        if self._turn is not None:
            settle = ease(elapsed / timing.settle_ms)
            self._pose_turn(mix(transition.turn_start or 0.0, 1.0, settle))
            self._place_pen(
                alpha=transition.pen_alpha * (1.0 - settle),
                lift=transition.pen_lift + 17.0 * settle,
                motion=transition.pen_motion,
            )
            if settle >= 1.0:
                self._finish_turn()
        # The pen waits out the settle window so a sheet in flight lands first.
        enter_at = (
            timing.settle_ms
            if transition.flight_start < 1.0
            or transition.turn_start is not None
            else 0.0
        )
        enter = ease((elapsed - enter_at) / timing.pen_enter_ms)
        if elapsed >= enter_at:
            self._place_pen(
                alpha=mix(
                    0.0
                    if transition.turn_start is not None
                    else transition.pen_alpha,
                    1.0,
                    enter,
                ),
                lift=18.0 * (1.0 - enter),
                motion=PenMotion(clamp01(transition.resume_clock_ms / timing.writing_ms),
                                 depth=self._leaves[PaperSide.RIGHT][-1].depth),
            )
        if elapsed >= enter_at + timing.pen_enter_ms:
            self._phase = AnalysisPhase.ANALYZING_REPORT
            self._clock_ms = transition.resume_clock_ms
            self._incoming = None
            self._transition = None

    def _enter_reading(self, transition: _Transition, elapsed: float) -> None:
        """Lift the pen away, resolving a page turn if one was in flight."""
        timing = self._timing
        done = ease(
            elapsed
            / (timing.settle_ms if self._turn is not None else timing.exit_ms)
        )
        self._place_pen(
            alpha=transition.pen_alpha * (1.0 - done),
            lift=transition.pen_lift + done * 17.0,
            motion=transition.pen_motion,
        )
        if self._turn is not None:
            self._pose_turn(mix(transition.turn_start or 0.0, 1.0, done))
            if done >= 1.0:
                self._finish_turn()
        if done < 1.0:
            return
        right = self._leaves[PaperSide.RIGHT]
        right[-1] = replace(right[-1], ink_progress=max(right[-1].ink_progress, self._ink_progress))
        self._ink_progress = 0.0
        self._phase = AnalysisPhase.READING
        self._clock_ms = 0.0
        self._transition = None
        incoming = self._incoming
        if incoming is None or incoming.landed:
            self._next_side = self._next_side.other()
            self._incoming = self._make_incoming(self._next_side)
        else:
            # A sheet was still flying in when the reversal started: keep it,
            # and resume the reading clock where that sheet already is.
            self._clock_ms = incoming.progress * timing.landing_ms

    # -------------------------------------------------------- paper handling

    def _new_leaf(
        self,
        side: PaperSide,
        depth: float,
        *,
        landed: bool,
    ) -> PaperLeaf:
        self._next_leaf_id += 1
        return PaperLeaf(
            leaf_id=self._next_leaf_id,
            side=side,
            depth=depth,
            landed=landed,
            progress=1.0 if landed else 0.0,
        )

    def _make_incoming(self, side: PaperSide) -> PaperLeaf:
        depth = (
            min(
                self._counts[side] + 1,
                self._timing.max_visible_page_edges,
            )
            * self._timing.leaf_rise
        )
        return replace(self._new_leaf(side, depth, landed=False), kind=LeafKind.READING)

    def _pose_incoming(self, progress: float) -> None:
        incoming = self._incoming
        if incoming is None:
            return
        self._incoming = replace(incoming, progress=clamp01(progress))

    def _bind_incoming(self) -> None:
        """Move the flown-in sheet into the book without fading or discarding it."""
        incoming = self._incoming
        if incoming is None or incoming.landed:
            return
        landed = replace(incoming, landed=True, progress=1.0)
        self._incoming = landed
        self._counts[incoming.side] += 1
        self._leaves[incoming.side].append(landed)
        self._cap(incoming.side)

    def _cap(self, side: PaperSide) -> None:
        """Recycle the oldest sheet of one stack once the bound is exceeded."""
        leaves = self._leaves[side]
        while len(leaves) > self._timing.max_leaves_per_side:
            leaves.pop(0)

    def _start_turn(self) -> None:
        """Turn the written sheet over and reveal a blank one beneath it."""
        right = self._leaves[PaperSide.RIGHT]
        written = right[-1] if right else None
        self._ink_progress = 0.0
        revealed_depth = (
            min(
                self._counts[PaperSide.RIGHT],
                self._timing.max_visible_page_edges,
            )
            * self._timing.leaf_rise
        )
        right.append(
            self._new_leaf(PaperSide.RIGHT, revealed_depth, landed=True)
        )
        self._cap(PaperSide.RIGHT)
        self._turn = PaperTurn(
            leaf_id=written.leaf_id if written is not None else None,
            progress=0.0,
            target_depth=(
                min(
                    self._counts[PaperSide.LEFT] + 1,
                    self._timing.max_visible_page_edges,
                )
                * self._timing.leaf_rise
            ),
            leaf=written,
        )

    def _pose_turn(self, progress: float) -> None:
        turn = self._turn
        if turn is None:
            return
        self._turn = replace(turn, progress=clamp01(progress))

    def _finish_turn(self) -> None:
        """Land the turned written sheet on the left, keeping its identity."""
        turn = self._turn
        if turn is None:
            return
        self._pose_turn(1.0)
        if turn.leaf_id is not None:
            written = self._take_leaf(PaperSide.RIGHT, turn.leaf_id)
            if written is not None:
                self._leaves[PaperSide.LEFT].append(
                    replace(
                        written,
                        side=PaperSide.LEFT,
                        depth=turn.target_depth,
                        landed=True,
                        progress=1.0,
                        kind=LeafKind.TURNED,
                        ink_progress=0.0,
                    )
                )
                self._cap(PaperSide.LEFT)
        self._counts[PaperSide.LEFT] += 1
        self._turn = None

    def _take_leaf(
        self,
        side: PaperSide,
        leaf_id: int,
    ) -> PaperLeaf | None:
        leaves = self._leaves[side]
        for index, leaf in enumerate(leaves):
            if leaf.leaf_id == leaf_id:
                return leaves.pop(index)
        return None

    def _place_pen(self, *, alpha: float, lift: float, motion: PenMotion | None = None) -> None:
        self._pen_alpha = clamp01(alpha)
        self._pen_lift = max(0.0, lift)
        if motion is not None:
            self._pen_motion = motion


__all__ = [
    "AnimationTiming",
    "PaperLeaf",
    "PaperSide",
    "LeafKind",
    "PaperTurn",
    "PenMotion",
    "ProcessingAnimationModel",
    "clamp01",
    "ease",
    "mix",
]
