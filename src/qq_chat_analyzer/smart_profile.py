"""Orchestrate Smart Profile candidate detection and filtering."""

from __future__ import annotations

from collections.abc import Iterable

from .analysis_diagnostics import timed_stage
from .decision_engine import create_filter_decisions
from .detectors import (
    detect_robot_candidates,
    detect_template_candidates,
)
from .filter_pipeline import FilterPipeline, FilteringResult
from .message import ChatMessage


def run_smart_profile(
    messages: Iterable[ChatMessage],
) -> FilteringResult:
    """Detect candidates, create decisions, and apply explicit filters."""
    message_list = list(messages)
    with timed_stage("robot_detector"):
        robot_candidates = detect_robot_candidates(message_list)
    with timed_stage("template_detector"):
        template_candidates = detect_template_candidates(message_list)
    candidates = [*robot_candidates, *template_candidates]
    with timed_stage("decision_engine"):
        decisions = create_filter_decisions(candidates)
    with timed_stage("filter_pipeline"):
        return FilterPipeline().apply_filter_decisions(
            message_list,
            decisions,
        )
