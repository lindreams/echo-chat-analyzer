"""Stable application-layer contracts for local chat analysis."""

from ..analysis.models import (
    ActivityReport,
    AnalysisReports,
    ConversationReport,
    UserProfileReport,
)
from ..analysis.conversation_sessions import ConversationSessionReport
from .analysis_service import AnalysisApplicationService
from .connection_models import ConnectionSnapshot, ConnectionState
from .qq.qq_auth_bridge import QQAuthBridge
from .qq.qq_connection_manager import QQConnectionManager

from .dto import (
    AnalysisDiagnosticCounts,
    AnalysisRequestDTO,
    AnalysisResultDTO,
    AnalysisStatus,
    ArtifactDTO,
    WordFrequencyDTO,
)
from .errors import (
    ApplicationServiceError,
    ArtifactGenerationFailed,
    InputPathNotFound,
    InvalidAnalysisRequest,
    InvalidAnalysisScope,
    NoMessagesInScope,
    NoSupportedInput,
)
from .facade import (
    AnalysisConfig,
    AnalysisOutcome,
    ChatAnalyzerFacade,
    ChatSource,
    FacadeError,
    SessionInfo,
    SourceInfo,
    SourceUnavailable,
    UnknownChatSource,
)
from .import_outcome import ImportOutcome
from .import_request import ImportRequest
from .import_result import ImportResult
from .import_service import ImportService
from .report_package_catalog import (
    REPORT_PACKAGE_DELETION_REASONS,
    ReportPackageCatalog,
    ReportPackageDeletionFailure,
    ReportPackageDeletionResult,
    ReportPackageSummary,
    ReportPackageIssue,
    ReportPackageListing,
    ReportStorageUsage,
)
from .qq.qq_connection_service import (
    QQConnectionService,
    QQConnectionStatus,
)
from .qq.qq_runtime_manager import (
    QQRuntimeManager,
    QQRuntimeState,
    QQRuntimeStatus,
)
from .wechat.wechat_export_import_service import (
    WeChatExportFileMissing,
    WeChatExportImportRequest,
    WeChatExportImportService,
    WeChatExportProvider,
    WeChatExportUnavailable,
)
from .wechat.wechat_connection_service import (
    WeChatConnectionService,
    WeChatConnectionStatus,
)
from .wechat.wechat_environment_config import (
    WeChatConfigCorrupted,
    WeChatConfigNotFound,
    WeChatConfigWriteFailed,
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigError,
    WeChatEnvironmentConfigLoader,
    WeChatEnvironmentConfigWriter,
)
from .wechat.wechat_provider_factory import (
    WeChatProviderFactory,
    WeChatProviderUnavailable,
)
from .wechat.wechat_setup_service import (
    WeChatSetupService,
    WeChatSetupState,
    WeChatSetupStatus,
)
from .scope_filter import AnalysisScope, AnalysisScopeMode

__all__ = [
    "REPORT_PACKAGE_DELETION_REASONS",
    "ReportPackageCatalog",
    "ReportPackageDeletionFailure",
    "ReportPackageDeletionResult",
    "ReportPackageSummary",
    "ReportPackageIssue",
    "ReportPackageListing",
    "ReportStorageUsage",
    "ActivityReport",
    "AnalysisApplicationService",
    "AnalysisConfig",
    "AnalysisDiagnosticCounts",
    "AnalysisOutcome",
    "AnalysisReports",
    "AnalysisRequestDTO",
    "AnalysisResultDTO",
    "AnalysisScope",
    "AnalysisScopeMode",
    "AnalysisStatus",
    "ApplicationServiceError",
    "ArtifactDTO",
    "ArtifactGenerationFailed",
    "ChatAnalyzerFacade",
    "ChatSource",
    "ConnectionSnapshot",
    "ConnectionState",
    "ConversationReport",
    "ConversationSessionReport",
    "FacadeError",
    "ImportOutcome",
    "ImportRequest",
    "ImportResult",
    "ImportService",
    "InputPathNotFound",
    "InvalidAnalysisRequest",
    "InvalidAnalysisScope",
    "NoSupportedInput",
    "NoMessagesInScope",
    "QQRuntimeManager",
    "QQRuntimeState",
    "QQRuntimeStatus",
    "QQConnectionManager",
    "QQAuthBridge",
    "QQConnectionService",
    "QQConnectionStatus",
    "SessionInfo",
    "SourceInfo",
    "SourceUnavailable",
    "UnknownChatSource",
    "UserProfileReport",
    "WeChatExportFileMissing",
    "WeChatExportImportRequest",
    "WeChatExportImportService",
    "WeChatExportProvider",
    "WeChatExportUnavailable",
    "WeChatConnectionService",
    "WeChatConnectionStatus",
    "WeChatConfigCorrupted",
    "WeChatConfigNotFound",
    "WeChatConfigWriteFailed",
    "WeChatEnvironmentConfig",
    "WeChatEnvironmentConfigError",
    "WeChatEnvironmentConfigLoader",
    "WeChatEnvironmentConfigWriter",
    "WeChatProviderFactory",
    "WeChatProviderUnavailable",
    "WeChatSetupService",
    "WeChatSetupState",
    "WeChatSetupStatus",
    "WordFrequencyDTO",
]
