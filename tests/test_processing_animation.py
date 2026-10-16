"""Keep drawing and lifecycle contracts while trimming unused observations."""

from qq_chat_analyzer.application.facade import AnalysisPhase
from qq_chat_analyzer.gui.processing_animation import render_processing_frame
from qq_chat_analyzer.gui.processing_animation_model import PaperSide, ProcessingAnimationModel


def _advance(model, milliseconds):
    for _ in range(milliseconds // 50):
        model.advance(50)


def test_reading_frames_clamp_time_freeze_and_reset():
    model = ProcessingAnimationModel()
    first = render_processing_frame(model)
    assert not first.isNull()
    model.advance(5000)
    clamped = ProcessingAnimationModel()
    clamped.advance(50)
    assert render_processing_frame(model) == render_processing_frame(clamped)
    assert render_processing_frame(model) != first
    for setter in (model.set_paused, model.set_hidden):
        before = render_processing_frame(model)
        setter(True)
        _advance(model, 500)
        assert render_processing_frame(model) == before
        setter(False)
        model.advance(50)
        assert render_processing_frame(model) != before
    _advance(model, 60000)
    assert all(len(model.leaves(side)) <= 7 for side in PaperSide)
    assert all(model.leaf_depth(side) <= 5.5 for side in PaperSide)
    model.reset()
    assert render_processing_frame(model) == first


def test_writing_turns_keep_drawn_paper_and_stop_immediately():
    model = ProcessingAnimationModel()
    model.set_phase(AnalysisPhase.ANALYZING_REPORT)
    _advance(model, 2000)
    assert model.pen_alpha == 1
    assert model.ink_progress > 0
    writing = render_processing_frame(model)
    model.set_phase(AnalysisPhase.ANALYZING_REPORT)
    assert render_processing_frame(model) == writing
    _advance(model, 6000)
    assert model.turn is not None
    turning = render_processing_frame(model)
    assert turning != writing
    model.set_phase(AnalysisPhase.READING)
    _advance(model, 2000)
    assert model.turn is None
    assert model.pen_alpha == 0
    assert model.incoming is not None
    model.stop()
    assert not model.active
    assert model.incoming is None and model.turn is None and model.pen_alpha == 0
    stopped = render_processing_frame(model)
    _advance(model, 2000)
    assert render_processing_frame(model) == stopped


def test_reduced_motion_keeps_static_drawings_for_both_phases():
    model = ProcessingAnimationModel()
    model.set_reduced_motion(True)
    reading = render_processing_frame(model)
    _advance(model, 5000)
    assert render_processing_frame(model) == reading
    model.set_phase(AnalysisPhase.ANALYZING_REPORT)
    writing = render_processing_frame(model)
    assert writing != reading and model.pen_alpha == 1
    _advance(model, 5000)
    assert render_processing_frame(model) == writing
