"""Contract tests for privacy-safe application errors."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


EXPECTED_ERROR_CODES = {
    "ApplicationServiceError": "application_error",
    "ArtifactGenerationFailed": "artifact_generation_failed",
    "InputPathNotFound": "input_not_found",
    "InvalidAnalysisRequest": "invalid_request",
    "InvalidAnalysisScope": "invalid_analysis_scope",
    "NoMessagesInScope": "no_messages_in_scope",
    "NoSupportedInput": "no_supported_input",
}
FORBIDDEN_ERROR_ATTRIBUTES = {
    "input_path",
    "messages",
    "nickname",
    "sender",
    "target",
}


def _application_module():
    return importlib.import_module("qq_chat_analyzer.application")


def test_application_package_exports_stable_error_codes() -> None:
    application = _application_module()

    for error_name, expected_code in EXPECTED_ERROR_CODES.items():
        error_type = getattr(application, error_name)
        assert error_type.code == expected_code


def test_application_errors_expose_only_safe_public_context() -> None:
    application = _application_module()
    error_types = (
        application.ApplicationServiceError,
        application.ArtifactGenerationFailed,
        application.InputPathNotFound,
        application.InvalidAnalysisRequest,
        application.InvalidAnalysisScope,
        application.NoMessagesInScope,
        application.NoSupportedInput,
    )

    for error_type in error_types:
        error = error_type()
        assert str(error)
        assert FORBIDDEN_ERROR_ATTRIBUTES.isdisjoint(vars(error))
