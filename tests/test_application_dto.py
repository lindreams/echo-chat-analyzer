"""Contract tests for privacy-safe application data transfer objects."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


REQUIRED_RESULT_FIELDS = {
    "status",
    "processed_message_count",
    "valid_text_count",
    "top_words",
    "artifacts",
}
FORBIDDEN_PUBLIC_FIELDS = {
    "candidate",
    "content",
    "filter_decision",
    "font_path",
    "input_path",
    "messages",
    "nickname",
    "output_directory",
    "raw_json",
    "sender",
    "stopwords_path",
    "target",
    "text",
    "user_id",
}


def _application_module():
    return importlib.import_module("qq_chat_analyzer.application")


def test_analysis_request_is_immutable_and_hides_local_paths() -> None:
    application = _application_module()
    private_input = Path("C:/fictional-private/chat.json")
    private_output = Path("C:/fictional-private/output")
    private_stopwords = Path("C:/fictional-private/stopwords.txt")
    private_font = "C:/fictional-private/font.ttf"

    request = application.AnalysisRequestDTO(
        input_path=private_input,
        output_directory=private_output,
        stopwords_path=private_stopwords,
        font_path=private_font,
        top=25,
    )

    request_repr = repr(request)
    assert str(private_input) not in request_repr
    assert str(private_output) not in request_repr
    assert str(private_stopwords) not in request_repr
    assert private_font not in request_repr
    assert not hasattr(request, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.top = 50


def test_analysis_result_has_required_fields_without_private_data() -> None:
    application = _application_module()
    result_fields = {
        field.name
        for field in dataclasses.fields(application.AnalysisResultDTO)
    }
    public_field_names = {
        field.name
        for dto_type in (
            application.AnalysisResultDTO,
            application.WordFrequencyDTO,
            application.ArtifactDTO,
        )
        for field in dataclasses.fields(dto_type)
    }

    assert REQUIRED_RESULT_FIELDS <= result_fields
    assert FORBIDDEN_PUBLIC_FIELDS.isdisjoint(public_field_names)
