"""Stable, privacy-safe errors for application use cases."""

from __future__ import annotations


class ApplicationServiceError(Exception):
    """Base error exposed by the application layer."""

    code = "application_error"
    public_message = "The application operation failed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class InvalidAnalysisRequest(ApplicationServiceError):
    """Raised when an analysis request violates the use-case contract."""

    code = "invalid_request"
    public_message = "The analysis request is invalid."


class AnalysisCancelled(ApplicationServiceError):
    """Raised at a cooperative checkpoint before publishing more results."""

    code = "analysis_cancelled"
    public_message = "分析已取消。"


class InvalidAnalysisScope(ApplicationServiceError):
    """Raised when an analysis scope cannot be resolved safely."""

    code = "invalid_analysis_scope"
    public_message = "分析时间范围无效，请重新选择。"


class MissingAnalysisScopeDate(InvalidAnalysisScope):
    """Raised when a custom scope omits either boundary date."""

    public_message = "请选择开始日期和结束日期。"


class InvalidAnalysisScopeRange(InvalidAnalysisScope):
    """Raised when a custom scope starts after it ends."""

    public_message = "开始日期不能晚于结束日期，请重新选择。"


class NoMessagesInScope(ApplicationServiceError):
    """Raised when a selected time range contains no messages."""

    code = "no_messages_in_scope"
    public_message = "当前时间范围内没有可分析的聊天记录。"


class InputPathNotFound(ApplicationServiceError):
    """Raised when the requested local input cannot be found."""

    code = "input_not_found"
    public_message = "The input path was not found."


class NoSupportedInput(ApplicationServiceError):
    """Raised when an input contains no supported local chat files."""

    code = "no_supported_input"
    public_message = "No supported input was found."


class ArtifactGenerationFailed(ApplicationServiceError):
    """Raised when local result artifacts cannot be generated."""

    code = "artifact_generation_failed"
    public_message = "Artifact generation failed."
