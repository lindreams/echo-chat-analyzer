"""Behavior tests for the ChatAnalyzerFacade application entry point."""

from __future__ import annotations

import dataclasses
import importlib
import json
from qq_db_test_data import qq_db_payload, qq_db_record
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _facade_module():
    return importlib.import_module("qq_chat_analyzer.application.facade")


def _report_catalog_module():
    return importlib.import_module("qq_chat_analyzer.application.report_package_catalog")


def _analysis_models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


def _dto():
    return importlib.import_module("qq_chat_analyzer.application.dto")


def _errors():
    return importlib.import_module("qq_chat_analyzer.application.errors")


def _analysis_phase_module():
    return importlib.import_module("qq_chat_analyzer.application.analysis_phase")


class _FakeQQGroup:
    """Mirror the fields of the real QQ ExportGroup without importing it."""

    def __init__(
        self,
        group_code: str,
        group_name: str,
        member_count: int | None = None,
        last_message_time: int | None = None,
        message_count: int | None = None,
    ) -> None:
        self.group_code = group_code
        self.group_name = group_name
        self.member_count = member_count
        self.message_count = message_count
        self.last_message_time = last_message_time


class _FakeQQFriend:
    def __init__(self, session_id: str, display_name: str, peer_uin: str) -> None:
        self.session_id = session_id
        self.display_name = display_name
        self.peer_uin = peer_uin
        self.session_type = "private"


class _StubQQService:
    def __init__(
        self,
        groups=(),
        export_path: Path | None = None,
        error=None,
        message_range=None,
    ):
        self._groups = list(groups)
        self._export_path = export_path
        self._error = error
        self._message_range = message_range
        self.export_requests: list[object] = []
        self.list_calls = 0
        self.range_requests: list[tuple[object, dict[str, object]]] = []

    def list_groups(self):
        self.list_calls += 1
        if self._error is not None:
            raise self._error
        return self._groups

    def list_sessions(self):
        return self.list_groups()

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None, end_time=None):
        request = SimpleNamespace(
            session_id=session_id, start_time=start_time, end_time=end_time
        )
        self.export_requests.append(request)
        if self._error is not None:
            raise self._error
        yield type(
            "Acquisition",
            (),
            {
                "payload_path": self._export_path,
                "session": next(
                    (
                        item for item in self._groups
                        if getattr(item, "session_id", getattr(item, "group_code", None))
                        == session_id
                    ),
                    None,
                ),
                "snapshot_id": None,
                "acquired_at": None,
                "reused_snapshot": False,
            },
        )()

    def get_session_message_range(self, group_code, **kwargs):
        self.range_requests.append((group_code, kwargs))
        if self._error is not None:
            raise self._error
        return self._message_range


class _ContextManagedQQService(_StubQQService):
    """Model Direct DB payload ownership across complete facade analysis."""

    def __init__(self, run_directory: Path, *, error=None) -> None:
        super().__init__(groups=[_FakeQQGroup("fictional-session", "Fictional")])
        self._run_directory = run_directory
        self._error = error
        self.entered = False
        self.exited = False

    def acquired_session(self, session_id, *, start_time=None, end_time=None):
        request = SimpleNamespace(
            session_id=session_id, start_time=start_time, end_time=end_time
        )
        service = self

        class _AcquisitionContext:
            def __enter__(self):
                service.entered = True
                service.export_requests.append(request)
                service._run_directory.mkdir(parents=True)
                payload_path = _export_file(
                    service._run_directory,
                    "direct-db-payload.json",
                )
                return type(
                    "Acquisition",
                    (),
                    {
                        "payload_path": payload_path,
                        "session": service._groups[0],
                        "snapshot_id": None,
                        "acquired_at": None,
                        "reused_snapshot": False,
                    },
                )()

            def __exit__(self, _exc_type, _exc, _traceback):
                for child in service._run_directory.iterdir():
                    child.unlink()
                service._run_directory.rmdir()
                service.exited = True
                return False

        return _AcquisitionContext()


class _FailingExportQQService(_StubQQService):
    """List sessions normally, but fail while Echo acquires the export.

    Session listing must succeed so the failure lands on the export step,
    the step that has to stay translated into a :class:`FacadeError`.
    """

    def __init__(self, error) -> None:
        super().__init__(groups=[_FakeQQGroup("fictional-session", "Fictional")])
        self._export_error = error

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None, end_time=None):
        request = SimpleNamespace(
            session_id=session_id, start_time=start_time, end_time=end_time
        )
        self.export_requests.append(request)
        if self._export_error is not None:
            raise self._export_error
        yield type(  # pragma: no cover - only the failure path is used
            "Acquisition",
            (),
            {
                "payload_path": self._export_path,
                "acquired_at": None,
            },
        )()


class _TrackingQQService(_StubQQService):
    """Record how long one Direct DB acquisition context stays open."""

    def __init__(self, payload_path: Path) -> None:
        super().__init__(
            groups=[_FakeQQGroup("fictional-session", "Fictional")],
            export_path=payload_path,
        )
        self.acquisition_entered = 0
        self.acquisition_exited = 0

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None, end_time=None):
        with super().acquired_session(
            session_id,
            start_time=start_time,
            end_time=end_time,
        ) as acquisition:
            self.acquisition_entered += 1
            try:
                yield acquisition
            finally:
                self.acquisition_exited += 1


class _StubWeChatService:
    def __init__(
        self,
        sessions=(),
        export_path: Path | None = None,
        error=None,
        provider=None,
    ):
        self._sessions = None if sessions is None else list(sessions)
        self._export_path = export_path
        self._error = error
        self._provider = provider
        self.export_requests: list[object] = []
        self.list_calls = 0

    def list_sessions(self):
        self.list_calls += 1
        if self._error is not None:
            raise self._error
        return self._sessions

    def export_only(self, request):
        self.export_requests.append(request)
        if self._error is not None:
            raise self._error
        return self._export_path

    def provider(self):
        return self._provider


class _ReturnTrackingWeChatService(_StubWeChatService):
    """Record that ``export_only`` already returned a payload."""

    def __init__(self, export_path: Path) -> None:
        super().__init__(export_path=export_path)
        self.export_returns = 0

    def export_only(self, request):
        path = super().export_only(request)
        self.export_returns += 1
        return path


class _FailingExportWeChatService(_StubWeChatService):
    """List sessions normally, but fail while Echo exports the conversation.

    Session listing must succeed so the failure lands on the export step, the
    step that must not publish the second analysis phase.
    """

    def __init__(self, error) -> None:
        super().__init__()
        self._export_error = error

    def list_sessions(self):
        self.list_calls += 1
        return []

    def export_only(self, request):
        self.export_requests.append(request)
        raise self._export_error


class _StubQQConnectionService:
    def __init__(self, status=None, error=None):
        self._status = status
        self._error = error
        self.check_calls = 0

    def check_status(self):
        self.check_calls += 1
        if self._error is not None:
            raise self._error
        return self._status


class _StubQQSetupService:
    def __init__(self, config=None, error=None, connect_status=None):
        self._config = config
        self._error = error
        self._connect_status = connect_status
        self.config_calls = 0
        self.connect_calls = 0
        self.save_calls = 0
        self.saved_configs: list[object] = []

    def get_environment_config(self):
        self.config_calls += 1
        if self._error is not None:
            raise self._error
        return self._config

    def save_environment(self, config):
        self.save_calls += 1
        self.saved_configs.append(config)
        if self._error is not None:
            raise self._error
        self._config = config
        return self._connect_status

    def connect(self):
        self.connect_calls += 1
        if self._error is not None:
            raise self._error
        return self._connect_status


class _StubQQAuthBridge:
    def __init__(self, snapshot=None, qr_ready=True):
        self._snapshot = snapshot
        self.qr_ready = qr_ready
        self.qr_ready_calls = 0
        self.calls: list[int] = []

    def start_auth_flow(self, progress=None):
        self.calls.append(1)
        if progress is not None:
            progress("backend stage")
        if self._snapshot is not None:
            return self._snapshot
        connection = importlib.import_module(
            "qq_chat_analyzer.application.connection_models"
        )
        return connection.ConnectionSnapshot(
            state=connection.ConnectionState.WAITING_AUTH,
            source="qq",
            message="\u7b49\u5f85\u6388\u6743",
        )

    def is_qrcode_ready(self):
        self.qr_ready_calls += 1
        return self.qr_ready

    def disconnect(self):
        self.calls.append(2)
        if self._snapshot is not None:
            return self._snapshot
        connection = importlib.import_module(
            "qq_chat_analyzer.application.connection_models"
        )
        return connection.ConnectionSnapshot(
            state=connection.ConnectionState.DISCONNECTED,
            source="qq",
            message="QQ 尚未连接。",
        )


class _RecordingProcessRegistry:
    def __init__(self):
        self.terminate_calls = 0

    def terminate_all(self) -> int:
        self.terminate_calls += 1
        return 1


class _StubWeChatConnectionService:
    def __init__(self, status=None, error=None):
        self._status = status
        self._error = error
        self.check_calls = 0

    def check_status(self):
        self.check_calls += 1
        if self._error is not None:
            raise self._error
        return self._status


class _LazySourceBundle:
    """One lazily built source with service/connection/setup slots."""

    def __init__(
        self,
        service: object | None = None,
        connection: object | None = None,
        setup: object | None = None,
    ) -> None:
        self.service = service
        self.connection = connection
        self.setup = setup


def _reports(message_count: int = 2):
    models = _analysis_models()
    return models.AnalysisReports(
        activity=models.ActivityReport(
            total_message_count=message_count,
            dated_message_count=message_count,
            hourly_counts=tuple(
                models.HourlyActivity(hour=hour, count=0) for hour in range(24)
            ),
            weekday_counts=tuple(
                models.WeekdayActivity(weekday=day, count=0) for day in range(7)
            ),
            busiest_hour=9,
            busiest_weekday=0,
        ),
        user_profiles=models.UserProfileReport(
            total_message_count=message_count,
            speaker_count=1,
            profiles=(
                models.UserProfile(
                    speaker="Fictional-Alice",
                    message_count=message_count,
                    message_share_percent=100.0,
                    average_length=5.0,
                    max_length=7,
                ),
            ),
        ),
        conversations=models.ConversationReport(conversation_count=1),
    )


def _result(message_count: int = 2):
    dto = _dto()
    return dto.AnalysisResultDTO(
        status=dto.AnalysisStatus.COMPLETED,
        processed_message_count=message_count,
        valid_text_count=message_count,
        diagnostic_counts=dto.AnalysisDiagnosticCounts(
            raw_message_count=message_count + 4,
            imported_message_count=message_count + 2,
            scope_message_count=message_count,
            filtered_message_count=message_count - 1,
            analyzed_message_count=message_count - 1,
        ),
        top_words=(dto.WordFrequencyDTO(word="deck", count=3),),
        reports=_reports(message_count),
    )


def _result_with_echo_artifact(message_count: int = 2):
    dto = _dto()
    result = _result(message_count)
    presentation = importlib.import_module("qq_chat_analyzer.presentation")
    return dataclasses.replace(
        result,
        echo_report_view=presentation.build_echo_report_view(result.reports),
        artifacts=(
            dto.ArtifactDTO(
                kind="echo_report_json",
                filename="echo-report.json",
            ),
            dto.ArtifactDTO(
                kind="echo_report_html",
                filename="echo-report.html",
            ),
        ),
    )


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_package_metadata_and_outcome_share_one_generated_time(
    tmp_path, monkeypatch, source,
):
    module = _facade_module()
    fixed = datetime(2026, 10, 4, 1, tzinfo=timezone.utc)
    calls = []

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            calls.append(tz)
            return fixed

    monkeypatch.setattr(module, "datetime", _Clock)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    presentation = importlib.import_module("qq_chat_analyzer.presentation")
    result = dataclasses.replace(
        _result_with_echo_artifact(999),
        echo_report_view=presentation.EchoReportView(
            title="Echo", conversation_name="Fictional Report Name",
            conversation_kind="private", total_message_count=120,
            active_days=8, participant_count=2,
        ),
    )

    class _WritingService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            for name in ("echo-report.html", "echo-report.json"):
                (request.output_directory / name).write_text("fictional", encoding="utf-8")
            return result

    export = _export_file(tmp_path)
    facade = _facade(
        tmp_path=tmp_path, analysis_service=_WritingService(),
        qq_service=_StubQQService(export_path=export),
        wechat_service=_StubWeChatService(export_path=export),
    )
    outcome = facade.analyze_session(
        source, "fictional-session", module.AnalysisConfig(
            scope_mode=module.AnalysisScopeMode.CUSTOM,
            start_time="2024-01-01", end_time="2024-01-31",
        ),
    )
    assert outcome.report_directory is not None
    metadata = json.loads((outcome.report_directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["source"] == source
    assert metadata["conversation_name"] == "Fictional Report Name"
    assert metadata["conversation_kind"] == "private"
    assert metadata["message_count"] == 120
    assert metadata["active_days"] == 8
    assert metadata["participant_count"] == 2
    assert metadata["analysis_scope"] == {
        "mode": "custom", "start_date": "2024-01-01", "end_date": "2024-01-31",
    }
    assert metadata["generated_at"] == fixed.isoformat()
    assert not list(tmp_path.rglob("analysis_history.jsonl"))
    assert not hasattr(outcome, "history_saved")
    assert not hasattr(outcome, "history_record_id")
    assert outcome.report_generated_at is fixed
    assert calls == [timezone.utc]


@pytest.mark.parametrize("failure", ["build", "write"])
def test_metadata_failure_keeps_retained_scratch_and_creates_no_package(
    tmp_path, monkeypatch, failure,
):
    module = _facade_module()

    class _WritingService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            for name in ("echo-report.html", "echo-report.json"):
                (request.output_directory / name).write_text("fictional", encoding="utf-8")
            return _result_with_echo_artifact()

    def fail_build(**kwargs):
        raise ValueError("fictional metadata build failure")

    write = Path.write_text

    def fail_write(path, *args, **kwargs):
        if path.name == "metadata.json":
            raise OSError("fictional metadata write failure")
        return write(path, *args, **kwargs)

    if failure == "build":
        monkeypatch.setattr(module, "build_report_metadata", fail_build, raising=False)
    else:
        monkeypatch.setattr(Path, "write_text", fail_write)
    facade, _ = _qq_session_facade(
        tmp_path, analysis_service=_WritingService(), retain_output=True,
    )
    outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    assert outcome.report_directory is None
    assert outcome.artifact_directory is not None
    assert outcome.report_path.is_file()
    assert list((tmp_path / "facade-reports").glob("*")) == []
    scratch = outcome.artifact_directory
    assert scratch.parent == tmp_path / "facade-user-data" / "transient"
    facade.shutdown()
    assert not scratch.exists()


class _StubAnalysisService:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.requests: list[object] = []

    def execute(self, request):
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._result


def _facade(
    *,
    tmp_path: Path | None = None,
    retain_output: bool = False,
    **overrides,
):
    module = _facade_module()
    defaults = {
        "analysis_service": _StubAnalysisService(result=_result()),
    }
    defaults.update(overrides)
    if tmp_path is not None:
        defaults.setdefault("report_package_catalog", module.ReportPackageCatalog(tmp_path / "facade-reports"))
    facade = module.ChatAnalyzerFacade(**defaults)
    if tmp_path is None:
        return facade

    output_directory = tmp_path / "facade-output"

    def _with_test_output(operation):
        user_data_dir = module.user_data_dir
        if retain_output:
            module.user_data_dir = lambda: tmp_path / "facade-user-data"
        try:
            return operation()
        finally:
            module.user_data_dir = user_data_dir

    def _test_config(config):
        if retain_output:
            return config or module.AnalysisConfig()
        if config is None:
            return module.AnalysisConfig(output_directory=output_directory)
        if config.output_directory is None:
            return config.with_output_directory(output_directory)
        return config

    analyze_session = facade.analyze_session

    def _analyze_session(
        source,
        session_id,
        config=None,
        progress=None,
        **kwargs,
    ):
        return _with_test_output(
            lambda: analyze_session(
                source,
                session_id,
                _test_config(config),
                progress,
                **kwargs,
            )
        )

    facade.analyze_session = _analyze_session
    return facade


def _export_file(tmp_path: Path, name: str = "export.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(qq_db_payload([])), encoding="utf-8")
    return path


_FICTIONAL_SESSION_ID = "fictional-session"


def _qq_session_facade(
    tmp_path: Path,
    *,
    export_name: str = "session-export.json",
    retain_output: bool = False,
    **overrides,
):
    """Build a facade whose QQ source yields one exported payload.

    ``analyze_session`` is the current public entry point that turns an export
    into an analysis outcome, so tests that used to hand a bare path to the
    removed ``analyze_file`` now drive it through a minimal fake QQ service.
    Returns the facade together with the exported payload path.
    """
    export_path = _export_file(tmp_path, export_name)
    overrides.setdefault("qq_service", _StubQQService(export_path=export_path))
    facade = _facade(
        tmp_path=tmp_path,
        retain_output=retain_output,
        **overrides,
    )
    return facade, export_path


# --------------------------------------------------------------- data models


def test_plain_facade_analysis_uses_test_output_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _facade_module()
    analysis_service = _StubAnalysisService(result=_result())

    def _forbidden_user_data_dir():
        raise AssertionError("plain facade tests must not resolve user_data_dir")

    monkeypatch.setattr(module, "user_data_dir", _forbidden_user_data_dir)
    facade, _ = _qq_session_facade(
        tmp_path,
        analysis_service=analysis_service,
    )

    facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)

    request = analysis_service.requests[0]
    assert request.output_directory.is_relative_to(tmp_path)


# ------------------------------------------------------------------ listing


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_member_count_is_never_presented_as_message_count(source_name):
    module = _facade_module()
    session = module._to_session_info(module.ChatSource(source_name), SimpleNamespace(
        session_id="fictional-room", display_name="Fictional Room", member_count=80,
    ))
    assert session.message_count is None


def test_list_sessions_hides_unnamed_qq_group_id() -> None:
    module = _facade_module()
    facade = _facade(
        qq_service=_StubQQService(
            groups=[_FakeQQGroup("10099", "", member_count=3)]
        )
    )

    session = facade.list_sessions(module.ChatSource.QQ)[0]

    assert session.session_id == "10099"
    assert session.display_name == "\u672a\u77e5\u7fa4\u804a"


def test_facade_wires_stale_runtime_cleaner_into_qq_auth_bridge() -> None:
    facade = _facade(
        qq_setup_service=_StubQQSetupService(),
        qq_connection_service=_StubQQConnectionService(),
    )

    bridge = facade._require_qq_auth_bridge()

    assert callable(bridge._runtime_cleaner)


def test_shutdown_qq_runtime_terminates_recorded_processes() -> None:
    registry = _RecordingProcessRegistry()
    facade = _facade(qq_process_registry=registry)

    facade.shutdown_qq_runtime()

    assert registry.terminate_calls == 1


def test_disconnect_qq_delegates_to_the_auth_bridge() -> None:
    bridge = _StubQQAuthBridge()
    facade = _facade(qq_auth_bridge=bridge)

    result = facade.disconnect_qq()

    assert bridge.calls == [2]
    connection = importlib.import_module(
        "qq_chat_analyzer.application.connection_models"
    )
    assert result.state is connection.ConnectionState.DISCONNECTED


def test_get_session_message_range_uses_qq_service_range() -> None:
    module = _facade_module()
    service = _StubQQService(message_range=(1700000000, 1700007200))
    facade = _facade(qq_service=service)

    message_range = facade.get_session_message_range(
        module.ChatSource.QQ,
        "10001",
    )

    assert message_range == (1700000000, 1700007200)


def test_get_session_message_range_uses_private_export_identity() -> None:
    module = _facade_module()
    service = _StubQQService(
        groups=[_FakeQQFriend("u_fictional_1", "Fictional Alice", "200001")],
        message_range=(1700000000, 1700007200),
    )

    message_range = _facade(qq_service=service).get_session_message_range(
        module.ChatSource.QQ,
        "u_fictional_1",
    )

    assert message_range == (1700000000, 1700007200)
    assert service.range_requests == [
        (
            "u_fictional_1",
            {
                "chat_type": 1,
                "peer_uin": "200001",
                "session_name": "Fictional Alice",
            },
        )
    ]


# --------------------------------------------------------------- connection


def test_qq_source_usable_when_wechat_builder_raises() -> None:
    module = _facade_module()
    qq_status = module.QQConnectionStatus(
        available=True,
        runtime_running=True,
        qq_online=True,
        version="4.1.0",
        message="QQ \u5df2\u8fde\u63a5",
        action_hint="",
    )
    qq_service = _StubQQService(groups=[_FakeQQGroup("10001", "Fictional")])
    qq_connection = _StubQQConnectionService(status=qq_status)
    qq_built: list[int] = []
    wechat_built: list[int] = []

    def build_qq():
        qq_built.append(1)
        return _LazySourceBundle(
            service=qq_service,
            connection=qq_connection,
        )

    def build_wechat():
        wechat_built.append(1)
        raise RuntimeError("wechat runtime missing")

    facade = module.ChatAnalyzerFacade(
        source_builders={
            module.ChatSource.QQ: build_qq,
            module.ChatSource.WECHAT: build_wechat,
        },
        analysis_service=_StubAnalysisService(result=_result()),
    )

    sessions = facade.list_sessions(module.ChatSource.QQ)
    status = facade.get_connection_status(module.ChatSource.QQ)

    assert wechat_built == []
    assert [session.session_id for session in sessions] == ["10001"]
    assert status.available is True
    assert qq_built == [1]


def test_wechat_status_usable_when_qq_builder_raises() -> None:
    module = _facade_module()
    wechat_status = module.WeChatConnectionStatus(
        available=False,
        data_found=False,
        db_key_available=False,
        runtime_available=False,
        message="\u672a\u627e\u5230\u5fae\u4fe1\u6570\u636e\u76ee\u5f55",
        action_hint="\u8bf7\u5148\u767b\u5f55\u5fae\u4fe1",
    )
    wechat_connection = _StubWeChatConnectionService(status=wechat_status)
    qq_built: list[int] = []
    wechat_built: list[int] = []

    def build_qq():
        qq_built.append(1)
        raise RuntimeError("qq runtime missing")

    def build_wechat():
        wechat_built.append(1)
        return _LazySourceBundle(connection=wechat_connection)

    facade = module.ChatAnalyzerFacade(
        source_builders={
            module.ChatSource.QQ: build_qq,
            module.ChatSource.WECHAT: build_wechat,
        },
        analysis_service=_StubAnalysisService(result=_result()),
    )

    status = facade.get_connection_status(module.ChatSource.WECHAT)

    assert qq_built == []
    assert status.available is False
    assert "\u5fae\u4fe1\u6570\u636e\u76ee\u5f55" in status.message
    assert wechat_built == [1]


# ----------------------------------------------------------------- analysis


def test_qq_session_analysis_publishes_reading_then_reporting_phase(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    progress: list[str] = []
    phases: list[object] = []
    facade, _ = _qq_session_facade(tmp_path)

    facade.analyze_session(
        module.ChatSource.QQ,
        _FICTIONAL_SESSION_ID,
        progress=progress.append,
        on_phase=phases.append,
    )

    assert phases == [
        phases_module.AnalysisPhase.READING,
        phases_module.AnalysisPhase.ANALYZING_REPORT,
    ]
    # The structured phases are additive: the Chinese progress text is unchanged.
    assert progress == [
        "正在准备分析...",
        "正在读取聊天记录...",
        "正在处理消息...",
        "正在分析聊天内容...",
        "正在生成报告...",
        "分析完成",
    ]


def test_wechat_session_analysis_publishes_reading_then_reporting_phase(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    phases: list[object] = []
    facade = _facade(
        wechat_service=_ReturnTrackingWeChatService(
            _export_file(tmp_path, "wechat_phase_export.json")
        ),
        tmp_path=tmp_path,
    )

    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_phases",
        on_phase=phases.append,
    )

    assert phases == [
        phases_module.AnalysisPhase.READING,
        phases_module.AnalysisPhase.ANALYZING_REPORT,
    ]


def test_qq_phases_bracket_the_single_direct_db_acquisition(tmp_path: Path) -> None:
    """READING precedes acquisition; the second phase runs inside its context."""
    module = _facade_module()
    service = _TrackingQQService(_export_file(tmp_path, "qq_phase_export.json"))
    facade = _facade(qq_service=service, tmp_path=tmp_path)
    observed: list[tuple[str, int, int, int]] = []

    def _on_phase(phase) -> None:
        observed.append(
            (
                phase.value,
                service.acquisition_entered,
                service.acquisition_exited,
                len(service.export_requests),
            )
        )

    facade.analyze_session(
        module.ChatSource.QQ,
        "fictional-session",
        on_phase=_on_phase,
    )

    assert observed == [
        ("reading", 0, 0, 0),
        ("analyzing_report", 1, 0, 1),
    ]
    assert service.acquisition_exited == 1


def test_wechat_phases_bracket_the_export_call(tmp_path: Path) -> None:
    module = _facade_module()
    service = _ReturnTrackingWeChatService(
        _export_file(tmp_path, "wechat_phase_export.json")
    )
    facade = _facade(wechat_service=service, tmp_path=tmp_path)
    observed: list[tuple[str, int]] = []

    def _on_phase(phase) -> None:
        observed.append((phase.value, service.export_returns))

    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_phases",
        on_phase=_on_phase,
    )

    assert observed == [("reading", 0), ("analyzing_report", 1)]


def test_failed_qq_acquisition_publishes_only_the_reading_phase(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    provider_errors = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_direct_database_import_service"
    )
    phases: list[object] = []
    facade = _facade(
        qq_service=_FailingExportQQService(
            provider_errors.QQDirectDatabaseUnavailable()
        ),
        tmp_path=tmp_path,
    )

    with pytest.raises(module.FacadeError):
        facade.analyze_session(
            module.ChatSource.QQ,
            "fictional-session",
            on_phase=phases.append,
        )

    assert phases == [phases_module.AnalysisPhase.READING]


def test_failed_wechat_export_publishes_only_the_reading_phase(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    phases: list[object] = []
    facade = _facade(
        wechat_service=_FailingExportWeChatService(
            RuntimeError("fictional export failure")
        ),
        tmp_path=tmp_path,
    )

    with pytest.raises(module.FacadeError):
        facade.analyze_session(
            module.ChatSource.WECHAT,
            "wxid_fictional_failure",
            on_phase=phases.append,
        )

    assert phases == [phases_module.AnalysisPhase.READING]


def test_reading_phase_callback_failure_stops_before_acquisition(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    service = _TrackingQQService(_export_file(tmp_path, "qq_reading_failure.json"))
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        qq_service=service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    def _on_phase(phase) -> None:
        raise RuntimeError(f"fictional phase failure: {phase.value}")

    with pytest.raises(RuntimeError, match="fictional phase failure: reading"):
        facade.analyze_session(
            module.ChatSource.QQ,
            "fictional-session",
            on_phase=_on_phase,
        )

    assert service.export_requests == []
    assert service.acquisition_entered == 0
    assert analysis_service.requests == []


def test_report_phase_callback_failure_still_releases_the_qq_acquisition(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    service = _TrackingQQService(_export_file(tmp_path, "qq_phase_failure.json"))
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        qq_service=service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    def _on_phase(phase) -> None:
        if phase is phases_module.AnalysisPhase.ANALYZING_REPORT:
            raise RuntimeError("fictional phase callback failure")

    with pytest.raises(RuntimeError, match="fictional phase callback failure"):
        facade.analyze_session(
            module.ChatSource.QQ,
            "fictional-session",
            on_phase=_on_phase,
        )

    assert service.acquisition_exited == 1
    assert analysis_service.requests == []


def test_report_phase_callback_failure_stops_before_wechat_analysis(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    phases_module = _analysis_phase_module()
    service = _ReturnTrackingWeChatService(
        _export_file(tmp_path, "wechat_phase_failure.json")
    )
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        wechat_service=service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    def _on_phase(phase) -> None:
        if phase is phases_module.AnalysisPhase.ANALYZING_REPORT:
            raise RuntimeError("fictional phase callback failure")

    with pytest.raises(RuntimeError, match="fictional phase callback failure"):
        facade.analyze_session(
            module.ChatSource.WECHAT,
            "wxid_fictional_phases",
            on_phase=_on_phase,
        )

    assert service.export_returns == 1
    assert analysis_service.requests == []


def test_default_output_keeps_generated_echo_report_after_return(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _facade_module()
    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))

    class _WritingAnalysisService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            (request.output_directory / "echo-report.html").write_text(
                "<html>fictional echo</html>",
                encoding="utf-8",
            )
            (request.output_directory / "echo-report.json").write_text(
                '{"schema_version": "echo-report.v0.7"}',
                encoding="utf-8",
            )
            (request.output_directory / "raw-chat-export.json").write_text(
                '{"messages": []}',
                encoding="utf-8",
            )
            return _result_with_echo_artifact()

    facade = _facade(
        qq_service=_StubQQService(export_path=_export_file(tmp_path)),
        analysis_service=_WritingAnalysisService(),
    )

    outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)

    assert outcome.report_path is not None
    assert outcome.report_directory is not None
    assert outcome.report_path.name == "echo-report.html"
    assert outcome.report_path.is_file()
    assert outcome.report_path == (
        outcome.report_directory / "echo-report.html"
    )
    assert outcome.report_directory.name.startswith("Echo_Report_")
    assert (outcome.report_directory / "echo-report.json").is_file()
    assert (outcome.report_directory / "README.txt").is_file()
    assert not (outcome.report_directory / "raw-chat-export.json").exists()
    assert outcome.artifact_directory != outcome.report_directory
    assert outcome.artifact_directory is not None
    assert outcome.artifact_directory.is_relative_to(
        local_app_data / "LocalChatAnalyzer" / "transient"
    )
    assert outcome.report_directory.is_relative_to(
        local_app_data / "LocalChatAnalyzer" / "reports"
    )
    listing = facade.list_report_packages()
    assert [report.package_name for report in listing.reports] == [outcome.report_directory.name]
    assert not listing.issues


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL regression")
def test_default_report_directory_inherits_current_user_access(
    tmp_path: Path,
    monkeypatch,
) -> None:
    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    module = _facade_module()

    output_directory, temporary_output = module._create_output_directory(
        module.AnalysisConfig()
    )

    try:
        acl = subprocess.run(
            ["icacls", str(output_directory)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        assert "(I)" in acl
    finally:
        if temporary_output is not None:
            temporary_output.cleanup()


def test_real_analysis_report_survives_facade_return(tmp_path: Path) -> None:
    application = importlib.import_module("qq_chat_analyzer.application")
    input_path = tmp_path / "fictional-chat.json"
    input_path.write_text(json.dumps(qq_db_payload([
        qq_db_record("Python \u6570\u636e\u5206\u6790", timestamp=1704099600,
                     nickname="Fictional-Alice"),
    ])), encoding="utf-8")
    facade = _facade(
        qq_service=_StubQQService(export_path=input_path),
        analysis_service=application.AnalysisApplicationService(),
        tmp_path=tmp_path,
    )

    outcome = facade.analyze_session(
        _facade_module().ChatSource.QQ,
        _FICTIONAL_SESSION_ID,
    )

    assert outcome.report_path is not None
    assert Path(outcome.report_path).is_file()
    assert outcome.echo_report_view is not None
    assert outcome.echo_report_view.total_message_count > 0


def test_second_analysis_updates_to_the_latest_generated_report(
    tmp_path: Path,
) -> None:
    module = _facade_module()

    class _WritingAnalysisService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            (request.output_directory / "echo-report.html").write_text(
                f"<html>report {len(self.requests)}</html>",
                encoding="utf-8",
            )
            (request.output_directory / "echo-report.json").write_text(
                '{"schema_version": "echo-report.v0.7"}',
                encoding="utf-8",
            )
            return _result_with_echo_artifact()

    facade, _ = _qq_session_facade(
        tmp_path,
        analysis_service=_WritingAnalysisService(),
        retain_output=True,
    )

    first = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    second = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)

    assert second.report_path is not None
    assert second.report_path.is_file()
    assert second.report_path != first.report_path
    assert first.report_path is not None
    assert first.report_path.exists()
    assert first.artifact_directory is not None
    assert first.artifact_directory.parent.name == "transient"
    assert not first.artifact_directory.exists()
    assert second.report_path.read_text(encoding="utf-8") == (
        "<html>report 2</html>"
    )


def test_shutdown_cleans_scratch_but_keeps_packaged_report(
    tmp_path: Path,
) -> None:
    class _WritingAnalysisService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            (request.output_directory / "echo-report.html").write_text(
                "<html>fictional echo</html>",
                encoding="utf-8",
            )
            (request.output_directory / "echo-report.json").write_text(
                '{"schema_version": "echo-report.v0.7"}',
                encoding="utf-8",
            )
            return _result_with_echo_artifact()

    module = _facade_module()
    facade, _ = _qq_session_facade(
        tmp_path,
        analysis_service=_WritingAnalysisService(),
        retain_output=True,
    )
    outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    assert outcome.report_path is not None
    assert outcome.report_directory is not None
    assert outcome.artifact_directory is not None
    scratch_directory = outcome.artifact_directory
    packaged_directory = outcome.report_directory
    assert scratch_directory.parent.name == "transient"

    facade.shutdown()

    assert not scratch_directory.exists()
    assert packaged_directory.exists()
    assert outcome.report_path.exists()


def test_default_scratch_is_transient_and_custom_output_is_unowned(tmp_path, monkeypatch):
    module = _facade_module()
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    directory, owner = module._create_output_directory(module.AnalysisConfig())
    try:
        assert directory.parent == tmp_path / "transient"
        assert len(directory.name.removeprefix("chat-analyzer-output-")) == 8
    finally:
        owner.cleanup()
    custom = tmp_path / "custom-output"
    directory, owner = module._create_output_directory(module.AnalysisConfig(output_directory=custom))
    assert directory == custom
    assert owner is None
    module.ChatAnalyzerFacade().shutdown()
    assert custom.is_dir()


def test_recovery_deletes_only_strict_owned_direct_children_and_continues(tmp_path, monkeypatch, caplog):
    module = _facade_module()
    root = tmp_path / "transient"
    root.mkdir()
    stale = root / "chat-analyzer-output-abcdef12"
    stale.mkdir()
    failed = root / "chat-analyzer-output-12345678"
    failed.mkdir()
    preserved = [root / "chat-analyzer-output-not-owned", root / "qq-acquisition",
                 root / "wechat-export", tmp_path / "custom-output",
                 tmp_path / "reports" / "Echo_Report_20261004_120000"]
    for directory in preserved:
        directory.mkdir(parents=True)
    nested = preserved[1] / "chat-analyzer-output-aaaaaaaa"
    nested.mkdir()
    original = module.shutil.rmtree
    def failing(path, *args, **kwargs):
        if Path(path) == failed:
            raise PermissionError("fictional cleanup failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(module.shutil, "rmtree", failing)
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    facade = module.ChatAnalyzerFacade(analysis_service=_StubAnalysisService(result=_result()))
    facade._analyze_path(Path("fictional.json"), module.AnalysisConfig(),
                         source=module.ChatSource.QQ, session=None, scope=module.AnalysisScope.all())
    assert not stale.exists()
    assert failed.exists()
    assert all(directory.is_dir() for directory in preserved)
    assert nested.is_dir()
    assert "fictional cleanup failure" in caplog.text


@pytest.mark.parametrize("failure", ["analysis", "presentation", "descriptor", "outcome"])
def test_exception_before_scratch_transfer_leaves_no_orphan(tmp_path, monkeypatch, failure):
    module = _facade_module()
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    facade = module.ChatAnalyzerFacade(analysis_service=_StubAnalysisService(result=_result()))
    def fail(*args, **kwargs):
        raise RuntimeError("fictional generation failure")
    if failure == "analysis":
        monkeypatch.setattr(facade._analysis_service, "execute", fail)
    elif failure == "presentation":
        monkeypatch.setattr(facade, "_build_view", fail)
    elif failure == "outcome":
        monkeypatch.setattr(module, "AnalysisOutcome", fail)
    else:
        monkeypatch.setattr(module, "_generated_echo_report_path", fail)
    with pytest.raises(Exception):
        facade._analyze_path(Path("fictional.json"), module.AnalysisConfig(),
                             source=module.ChatSource.QQ, session=None, scope=module.AnalysisScope.all())
    assert not list(tmp_path.rglob("chat-analyzer-output-*"))


def test_recovery_runs_once_before_first_default_scratch(tmp_path, monkeypatch):
    module = _facade_module()
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    calls = []
    original = module._cleanup_stale_analysis_outputs
    def recover(root):
        calls.append(root)
        return original(root)
    monkeypatch.setattr(module, "_cleanup_stale_analysis_outputs", recover)
    facade = module.ChatAnalyzerFacade(analysis_service=_StubAnalysisService(result=_result()))
    custom = tmp_path / "custom"
    for config in (module.AnalysisConfig(output_directory=custom),
                   module.AnalysisConfig(), module.AnalysisConfig()):
        facade._analyze_path(Path("fictional.json"), config, source=module.ChatSource.QQ,
                             session=None, scope=module.AnalysisScope.all())
    assert calls == [tmp_path / "transient"]
    facade.shutdown()
    assert custom.is_dir()


def test_custom_output_survives_analysis_failure_recovery_and_shutdown(tmp_path, monkeypatch):
    module = _facade_module()
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    custom = tmp_path / "external" / "chat-analyzer-output-abcdef12"
    custom.mkdir(parents=True)
    original = custom / "fictional-original.json"
    original.write_text("fictional", encoding="utf-8")
    facade = module.ChatAnalyzerFacade(
        analysis_service=_StubAnalysisService(error=RuntimeError("fictional failure")))
    with pytest.raises(module.FacadeError):
        facade._analyze_path(Path("fictional.json"), module.AnalysisConfig(output_directory=custom),
                             source=module.ChatSource.QQ, session=None, scope=module.AnalysisScope.all())
    module._cleanup_stale_analysis_outputs(tmp_path / "transient")
    facade.shutdown()
    assert original.read_text(encoding="utf-8") == "fictional"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
@pytest.mark.parametrize("location", ["candidate", "inside", "root"])
def test_stale_scratch_junction_never_follows_target(tmp_path, location, caplog):
    module = _facade_module()
    root = tmp_path / "transient"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    original = external / "fictional-original.json"
    original.write_text("fictional", encoding="utf-8")
    if location == "root":
        root.rmdir()
        link = root
    elif location == "candidate":
        link = root / "chat-analyzer-output-abcdef12"
    else:
        directory = root / "chat-analyzer-output-abcdef12"
        directory.mkdir()
        link = directory / "linked-export"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(external)],
                   check=True, capture_output=True)
    try:
        module._cleanup_stale_analysis_outputs(root)
        assert original.read_text(encoding="utf-8") == "fictional"
        assert link.exists()
        assert caplog.records
    finally:
        link.rmdir()


def test_missing_echo_artifact_returns_no_report_path(tmp_path: Path) -> None:
    facade, _ = _qq_session_facade(
        tmp_path,
        analysis_service=_StubAnalysisService(result=_result()),
    )

    outcome = facade.analyze_session(
        _facade_module().ChatSource.QQ,
        _FICTIONAL_SESSION_ID,
    )

    assert outcome.report_path is None
    assert outcome.report_directory is None


def test_echo_packaging_failure_falls_back_to_generated_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _facade_module()

    class _WritingAnalysisService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            (request.output_directory / "echo-report.html").write_text(
                "<html>fictional echo</html>",
                encoding="utf-8",
            )
            return _result_with_echo_artifact()

    def _failing_package(*args, **kwargs):
        raise OSError("fictional packaging failure")

    monkeypatch.setattr(module, "package_echo_report", _failing_package)
    facade, _ = _qq_session_facade(
        tmp_path,
        analysis_service=_WritingAnalysisService(),
        retain_output=True,
    )

    outcome = facade.analyze_session(
        _facade_module().ChatSource.QQ,
        _FICTIONAL_SESSION_ID,
    )

    assert outcome.report_path is not None
    assert outcome.report_path.name == "echo-report.html"
    assert outcome.report_path.is_file()
    assert outcome.report_directory is None
    assert outcome.artifact_directory == outcome.report_path.parent
    assert outcome.artifact_directory.parent.name == "transient"
    from qq_chat_analyzer.application.report_package_catalog import ReportPackageCatalog
    assert not ReportPackageCatalog(tmp_path / "facade-user-data" / "reports").list_reports().reports
    next_outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    assert not outcome.artifact_directory.exists()
    assert next_outcome.report_path.is_file()
    facade.shutdown()
    assert not next_outcome.artifact_directory.exists()


def test_qq_and_wechat_share_the_same_retained_report_contract(
    tmp_path: Path,
) -> None:
    module = _facade_module()

    class _WritingAnalysisService(_StubAnalysisService):
        def execute(self, request):
            self.requests.append(request)
            (request.output_directory / "echo-report.html").write_text(
                "<html>fictional source-neutral report</html>",
                encoding="utf-8",
            )
            (request.output_directory / "echo-report.json").write_text(
                '{"schema_version": "echo-report.v0.7"}',
                encoding="utf-8",
            )
            return _result_with_echo_artifact()

    analysis_service = _WritingAnalysisService()
    export_path = _export_file(tmp_path, "session-export.json")
    qq = _StubQQService(groups=[], export_path=export_path)
    wechat = _StubWeChatService(sessions=[], export_path=export_path)
    facade = _facade(
        qq_service=qq,
        wechat_service=wechat,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    qq_outcome = facade.analyze_session(module.ChatSource.QQ, "qq-fictional")
    wechat_outcome = facade.analyze_session(
        module.ChatSource.WECHAT,
        "wechat-fictional",
    )

    assert qq_outcome.report_path is not None
    assert wechat_outcome.report_path is not None
    assert qq_outcome.report_path.name == "echo-report.html"
    assert wechat_outcome.report_path.name == "echo-report.html"
    assert wechat_outcome.report_path.is_file()
    assert qq_outcome.report_directory is not None
    assert wechat_outcome.report_directory is not None
    assert qq_outcome.report_directory.is_dir()
    assert wechat_outcome.report_directory.is_dir()


def test_session_analysis_forwards_speaker_names_and_viewer_key(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    analysis_service = _StubAnalysisService(result=_result())
    facade, _ = _qq_session_facade(tmp_path, analysis_service=analysis_service)

    facade.analyze_session(
        module.ChatSource.QQ,
        _FICTIONAL_SESSION_ID,
        speaker_names={"u-fictional-1": "Fictional Alice"},
        viewer_speaker_key="u-fictional-1",
    )

    request = analysis_service.requests[0]
    assert request.speaker_names == {"u-fictional-1": "Fictional Alice"}
    assert request.viewer_speaker_key == "u-fictional-1"


def test_analyze_qq_private_forwards_conversation_kind(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    analysis_service = _StubAnalysisService(result=_result())
    qq_service = _StubQQService(
        groups=[_FakeQQFriend("u_fictional_1", "Fictional Alice", "200001")],
        export_path=_export_file(tmp_path, "qq_private_export.json"),
    )
    facade = _facade(
        qq_service=qq_service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    facade.analyze_session(module.ChatSource.QQ, "u_fictional_1")

    assert analysis_service.requests[0].conversation_kind == "private"


def test_analyze_session_dispatches_to_the_qq_service(tmp_path: Path) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path, "qq_export.json")
    qq_service = _StubQQService(export_path=export_path)
    wechat_service = _StubWeChatService(export_path=export_path)
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        qq_service=qq_service,
        wechat_service=wechat_service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    outcome = facade.analyze_session(
        module.ChatSource.QQ,
        "10001",
        module.AnalysisConfig(start_time="2024-01-01", end_time="2024-02-01"),
    )

    assert len(qq_service.export_requests) == 1
    assert wechat_service.export_requests == []
    request = qq_service.export_requests[0]
    assert request.session_id == "10001"
    # Direct DB acquisition uses inclusive epoch-second bounds.
    assert request.start_time == int(
        datetime.combine(date(2024, 1, 1), time.min).timestamp()
    )
    assert request.end_time == int(
        datetime.combine(date(2024, 2, 2), time.min).timestamp()
    ) - 1
    assert analysis_service.requests[0].input_path == export_path
    assert analysis_service.requests[0].scope == module.AnalysisScope.custom(
        date(2024, 1, 1),
        date(2024, 2, 1),
    )
    assert outcome.source is module.ChatSource.QQ
    assert outcome.session.session_id == "10001"


def test_facade_delegates_report_listing_and_clear():
    calls = []
    class Catalog:
        def list_reports(self):
            calls.append("list")
            return "listing"
        def clear_all(self):
            calls.append("clear")
    facade = _facade(report_package_catalog=Catalog())
    assert facade.list_report_packages() == "listing"
    facade.clear_report_packages()
    assert calls == ["list", "clear"]


def test_facade_translates_report_clear_failure():
    module = _facade_module()
    class Catalog:
        def clear_all(self):
            raise PermissionError("internal-path")
    facade = _facade(report_package_catalog=Catalog())
    with pytest.raises(module.FacadeError) as caught:
        facade.clear_report_packages()
    assert caught.value.public_message == "部分 Echo 报告未能删除，请稍后重试。"


def test_facade_delegates_single_report_deletion():
    calls = []
    class Catalog:
        def delete_package(self, name):
            calls.append(name)
    facade = _facade(report_package_catalog=Catalog())
    facade.delete_report_package("Echo_Report_20261004_120000")
    assert calls == ["Echo_Report_20261004_120000"]


@pytest.mark.parametrize("error", [ValueError, FileNotFoundError, PermissionError, RuntimeError])
def test_facade_translates_single_report_deletion_failure(tmp_path, error):
    module = _facade_module()
    internal_path = str(tmp_path / "internal-private-path")
    class Catalog:
        def delete_package(self, name):
            raise error(internal_path)
    facade = _facade(report_package_catalog=Catalog())
    with pytest.raises(module.FacadeError) as caught:
        facade.delete_report_package("Echo_Report_20261004_120000")
    assert caught.value.code == "report_delete_failed"
    assert caught.value.public_message == "这份 Echo 报告未能删除，请稍后重试。"
    assert internal_path not in str(caught.value)


def test_facade_delegates_explicit_report_batch_deletion():
    catalog_module = _report_catalog_module()
    calls = []
    expected = catalog_module.ReportPackageDeletionResult(
        deleted=("Echo_Report_20261004_120000",),
        failures=(
            catalog_module.ReportPackageDeletionFailure("Echo_Report_20261004_120000_2", "missing"),
        ),
    )
    class Catalog:
        def delete_packages(self, package_names):
            calls.append(list(package_names))
            return expected
    facade = _facade(report_package_catalog=Catalog())
    result = facade.delete_report_packages([
        "Echo_Report_20261004_120000", "Echo_Report_20261004_120000_2",
    ])
    assert result is expected
    assert result.deleted == ("Echo_Report_20261004_120000",)
    assert result.failures[0].reason == "missing"
    assert calls == [["Echo_Report_20261004_120000", "Echo_Report_20261004_120000_2"]]


@pytest.mark.parametrize("error", [TypeError, ValueError, FileNotFoundError, PermissionError, RuntimeError])
def test_facade_translates_explicit_report_batch_deletion_failure(tmp_path, error):
    module = _facade_module()
    internal_path = str(tmp_path / "internal-private-path")
    class Catalog:
        def delete_packages(self, package_names):
            raise error(internal_path)
    facade = _facade(report_package_catalog=Catalog())
    with pytest.raises(module.FacadeError) as caught:
        facade.delete_report_packages(["Echo_Report_20261004_120000"])
    assert caught.value.code == "report_delete_failed"
    assert caught.value.public_message == "所选 Echo 报告未能删除，请稍后重试。"
    assert internal_path not in str(caught.value)


def _analysis_over_existing_reports(tmp_path, existing):
    module = _facade_module()
    root = tmp_path / "injected-reports"
    catalog = module.ReportPackageCatalog(root)
    source = tmp_path / "old-report-source"
    source.mkdir()
    for name in ("echo-report.html", "echo-report.json"):
        (source / name).write_text("fictional", encoding="utf-8")
    old = []
    for index in range(existing):
        metadata = module.build_report_metadata(
            result=_result_with_echo_artifact(), source="qq",
            scope=module.AnalysisScope.all(),
            generated_at=datetime(
                2020, 1, 1, 0, index // 60, index % 60, tzinfo=timezone.utc,
            ),
        )
        old.append(module.package_echo_report(source, reports_root=root, metadata=metadata))
    class WritingService(_StubAnalysisService):
        def execute(self, request):
            for name in ("echo-report.html", "echo-report.json"):
                (request.output_directory / name).write_text("fictional", encoding="utf-8")
            return _result_with_echo_artifact()
    facade, _ = _qq_session_facade(
        tmp_path, analysis_service=WritingService(), report_package_catalog=catalog,
    )
    return facade, catalog, root, old


@pytest.mark.parametrize("existing", [50, 99])
def test_retention_after_successful_publication_uses_injected_root_and_preserves_new(
    tmp_path, monkeypatch, existing,
):
    module = _facade_module()
    facade, catalog, root, old = _analysis_over_existing_reports(tmp_path, existing)
    attempted = []
    original_delete = module.shutil.rmtree
    def delete(path, *args, **kwargs):
        if Path(path).parent == root and Path(path).name.startswith("Echo_Report_"):
            attempted.append(Path(path))
        return original_delete(path, *args, **kwargs)
    monkeypatch.setattr(module.shutil, "rmtree", delete)
    catalog_module = importlib.import_module("qq_chat_analyzer.application.report_package_catalog")
    def forbidden_default():
        pytest.fail("An injected Catalog must never resolve default user data")
    monkeypatch.setattr(catalog_module, "user_data_dir", forbidden_default)
    outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    assert outcome.report_directory.parent == root
    assert outcome.report_path == outcome.report_directory / "echo-report.html"
    assert all((outcome.report_directory / name).is_file() for name in (
        "echo-report.html", "echo-report.json", "metadata.json", "README.txt",
    ))
    assert attempted == []
    assert len(list(root.iterdir())) == existing + 1
    assert all(package.exists() for package in old)
    usage = facade.get_report_storage_usage()
    assert usage.package_count == existing + 1 and usage.complete
    assert usage.measured_bytes > 0


def test_retention_publication_failure_never_calls_cleanup(tmp_path, monkeypatch):
    module = _facade_module()
    facade, catalog, root, old = _analysis_over_existing_reports(tmp_path, 50)
    attempted = []
    original_delete = module.shutil.rmtree
    def delete(path, *args, **kwargs):
        if Path(path).parent == root and Path(path).name.startswith("Echo_Report_"):
            attempted.append(Path(path))
        return original_delete(path, *args, **kwargs)
    def fail_publication(*args, **kwargs):
        raise OSError("fictional publication failure")
    monkeypatch.setattr(module, "package_echo_report", fail_publication)
    monkeypatch.setattr(module.shutil, "rmtree", delete)
    outcome = facade.analyze_session(module.ChatSource.QQ, _FICTIONAL_SESSION_ID)
    assert outcome.report_directory is None
    assert outcome.report_path.is_file()
    assert attempted == []
    assert len(list(root.iterdir())) == 50
    assert all(package.exists() for package in old)


def test_analyze_private_qq_session_preserves_private_export_identity(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path, "qq_private_export.json")
    qq_service = _StubQQService(
        groups=[_FakeQQFriend("u_fictional_1", "Fictional Alice", "200001")],
        export_path=export_path,
    )

    outcome = _facade(
        qq_service=qq_service,
        tmp_path=tmp_path,
    ).analyze_session(
        module.ChatSource.QQ,
        "u_fictional_1",
    )

    request = qq_service.export_requests[0]
    assert request.session_id == "u_fictional_1"
    assert outcome.session.display_name == "Fictional Alice"
    assert outcome.session.session_type == "private"


def test_analyze_session_applies_wechat_time_range_after_export(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path, "wechat_export.json")
    wechat_service = _StubWeChatService(export_path=export_path)
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        wechat_service=wechat_service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_a",
        module.AnalysisConfig(
            start_time="2024-01-01",
            end_time="2024-02-01",
        ),
    )

    request = wechat_service.export_requests[0]
    # Scope time window is now pushed to the WeChat acquisition request.
    assert request.start_time is not None
    assert request.end_time is not None
    assert analysis_service.requests[0].scope == module.AnalysisScope.custom(
        date(2024, 1, 1),
        date(2024, 2, 1),
    )


def test_invalid_custom_scope_stops_before_source_export(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path)
    qq_service = _StubQQService(export_path=export_path)
    wechat_service = _StubWeChatService(export_path=export_path)
    analysis_service = _StubAnalysisService(result=_result())
    facade = _facade(
        qq_service=qq_service,
        wechat_service=wechat_service,
        analysis_service=analysis_service,
        tmp_path=tmp_path,
    )

    with pytest.raises(module.FacadeError) as captured:
        facade.analyze_session(
            module.ChatSource.QQ,
            "fictional-session",
            module.AnalysisConfig(
                scope_mode=module.AnalysisScopeMode.CUSTOM,
                start_time="2026-08-12",
                end_time="2026-08-11",
            ),
        )

    assert captured.value.code == "invalid_analysis_scope"
    assert captured.value.public_message == (
        "开始日期不能晚于结束日期，请重新选择。"
    )
    assert qq_service.export_requests == []
    assert wechat_service.export_requests == []
    assert analysis_service.requests == []


def test_source_analysis_uses_the_shared_application_scope_filter(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    service_module = importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )
    export_path = tmp_path / "fictional-scoped-export.json"
    export_path.write_text(json.dumps(qq_db_payload([
        qq_db_record("OutsideMarker", timestamp="2026-01-31 23:59:59"),
        qq_db_record("InsideMarker", timestamp="2026-02-01 12:00:00",
                     message_id="fictional-inside"),
    ])), encoding="utf-8")
    source = module.ChatSource.QQ
    services = {
        "qq_service": _StubQQService(export_path=export_path),
        "wechat_service": _StubWeChatService(export_path=export_path),
    }
    facade = _facade(
        analysis_service=service_module.AnalysisApplicationService(),
        **services,
        tmp_path=tmp_path,
    )

    outcome = facade.analyze_session(
        source,
        "fictional-session",
        module.AnalysisConfig(
            scope_mode=module.AnalysisScopeMode.CUSTOM,
            start_time="2026-02-01",
            end_time="2026-02-01",
        ),
    )

    assert outcome.result.processed_message_count == 1
    assert outcome.result.reports.activity.total_message_count == 1
    assert {word.word for word in outcome.result.top_words} == {
        "InsideMarker"
    }


def test_analyze_session_dispatches_to_the_wechat_service(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path, "wechat_export.json")
    qq_service = _StubQQService(export_path=export_path)
    wechat_service = _StubWeChatService(export_path=export_path)
    facade = _facade(
        qq_service=qq_service,
        wechat_service=wechat_service,
        tmp_path=tmp_path,
    )

    outcome = facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_a",
    )

    assert len(wechat_service.export_requests) == 1
    assert qq_service.export_requests == []
    request = wechat_service.export_requests[0]
    assert request.session_id == "wxid_fictional_a"
    assert request.output_path.name.endswith(".json")
    assert outcome.source is module.ChatSource.WECHAT


def test_analyze_session_hides_the_intermediate_export_file(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path)
    facade = _facade(
        wechat_service=_StubWeChatService(export_path=export_path),
        tmp_path=tmp_path,
    )

    outcome = facade.analyze_session(module.ChatSource.WECHAT, "fictional")

    public_values = [
        getattr(outcome, field.name)
        for field in dataclasses.fields(outcome)
        if field.name
        not in {"artifact_directory", "report_path", "report_directory"}
    ]
    assert not any(isinstance(value, Path) for value in public_values)
    assert not hasattr(outcome, "export_path")


def test_qq_bounded_payload_ownership_spans_successful_facade_analysis(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    direct_service = _ContextManagedQQService(
        tmp_path / "LocalChatAnalyzer" / "transient" / "qq-payloads" / "run-1"
    )
    facade = _facade(qq_service=direct_service, tmp_path=tmp_path)

    facade.analyze_session(
        module.ChatSource.QQ,
        "fictional-session",
        module.AnalysisConfig(
            start_time="2025-01-01",
            end_time="2025-01-02",
        ),
    )

    assert direct_service.entered is True
    assert direct_service.exited is True
    assert not direct_service._run_directory.exists()


def test_qq_bounded_payload_ownership_closes_when_facade_analysis_fails(
    tmp_path: Path,
) -> None:
    module = _facade_module()
    direct_service = _ContextManagedQQService(
        tmp_path / "LocalChatAnalyzer" / "transient" / "qq-payloads" / "run-2"
    )
    facade = _facade(
        qq_service=direct_service,
        analysis_service=_StubAnalysisService(error=RuntimeError("fictional failure")),
        tmp_path=tmp_path,
    )

    with pytest.raises(module.FacadeError):
        facade.analyze_session(
            module.ChatSource.QQ,
            "fictional-session",
            module.AnalysisConfig(
                start_time="2025-01-01",
                end_time="2025-01-02",
            ),
        )

    assert direct_service.entered is True
    assert direct_service.exited is True
    assert not direct_service._run_directory.exists()


# ------------------------------------------------------------------- errors


def test_unlabelled_errors_still_produce_a_safe_message() -> None:
    module = _facade_module()
    facade = _facade(wechat_service=_StubWeChatService(error=RuntimeError()))

    try:
        facade.list_sessions(module.ChatSource.WECHAT)
    except module.FacadeError as error:
        assert error.code == "runtime_error"
        assert error.public_message.strip() != ""
    else:  # pragma: no cover
        raise AssertionError("expected a FacadeError")


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("original, public_message, expected_code", [
    pytest.param(
        PermissionError(13, "Permission denied", r"C:\Users\FictionalUser\Private\chat.json"),
        "missing", "permission_error", id="private-windows-path",
    ),
    pytest.param(RuntimeError("Traceback: fictional native hook at 0xdeadbeef"),
                 "missing", "runtime_error", id="internal-details"),
    pytest.param(RuntimeError("fictional internal failure"), None, "runtime_error", id="null"),
    pytest.param(RuntimeError("fictional internal failure"), "", "runtime_error", id="empty"),
    pytest.param(RuntimeError("fictional internal failure"), " \n", "runtime_error", id="blank"),
    pytest.param(RuntimeError("fictional internal failure"), 123, "runtime_error", id="non-string"),
])
def test_untrusted_exception_text_never_becomes_a_public_message(
    source, original, public_message, expected_code,
) -> None:
    module = _facade_module()
    if public_message != "missing":
        original.public_message = public_message
    facade = _facade(**{f"{source}_service": _StubQQService(error=original)})
    chat_source = module.ChatSource(source)

    with pytest.raises(module.FacadeError) as caught:
        facade.list_sessions(chat_source)

    error = caught.value
    assert error.public_message == "操作失败，请稍后重试。"
    assert str(original) not in error.public_message
    assert error.code == expected_code
    assert error.source is chat_source
    assert error.__cause__ is original


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("public_message", ["missing", None, "", " \n", 123])
def test_application_error_without_valid_public_message_is_safe(
    source, public_message, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _facade_module()
    base_error = _errors().ApplicationServiceError

    class InternalApplicationError(base_error):
        code = "fictional_application_failure"

        def __init__(self) -> None:
            Exception.__init__(self, r"Traceback: C:\Users\FictionalUser\Private\chat.json")

    if public_message == "missing":
        monkeypatch.delattr(base_error, "public_message")
    else:
        monkeypatch.setattr(InternalApplicationError, "public_message", public_message)
    original = InternalApplicationError()
    facade = _facade(**{f"{source}_service": _StubQQService(error=original)})
    chat_source = module.ChatSource(source)

    with pytest.raises(module.FacadeError) as caught:
        facade.list_sessions(chat_source)

    error = caught.value
    assert error.public_message == "操作失败，请稍后重试。"
    assert str(original) not in error.public_message
    assert error.code == "fictional_application_failure"
    assert error.source is chat_source
    assert error.__cause__ is original


# -------------------------------------------------------- injection & layering


def test_facade_imports_no_gui_framework() -> None:
    module = _facade_module()
    source = Path(module.__file__).read_text(encoding="utf-8")

    for forbidden in ("PyQt", "PySide", "tkinter", "flask", "django"):
        assert forbidden not in source


# ---------------------------------------------------------------
# GUI-6A: snapshot Facade bridge
# ---------------------------------------------------------------

# --------------------------------------------------------------- WeChat scope push-down

def test_wechat_export_pushes_scope_time_window_to_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """When WeChat analysis uses a date scope, acquisition must receive
    inclusive epoch-second start_time/end_time.

    Regression test: the old code always passed start_time=None,
    end_time=None to WeChatExportImportRequest, bypassing the provider's
    SQL-level time filter.
    """
    module = _facade_module()
    export_path = _export_file(tmp_path, "wechat-export.json")
    wechat_service = _StubWeChatService(export_path=export_path)

    facade = _facade(
        wechat_service=wechat_service,
        tmp_path=tmp_path,
    )

    # Use a custom date scope (last_year) to trigger non-None time bounds.
    config = module.AnalysisConfig(
        scope_mode=module.AnalysisScopeMode.LAST_YEAR,
    )

    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_wechat",
        config=config,
    )

    assert len(wechat_service.export_requests) == 1
    request = wechat_service.export_requests[0]
    # The request must carry non-None time bounds derived from the scope.
    assert request.start_time is not None, (
        "WeChat acquisition must receive start_time from scope, "
        "got None (full export instead of time-windowed export)"
    )
    assert request.end_time is not None, (
        "WeChat acquisition must receive end_time from scope, "
        "got None (full export instead of time-windowed export)"
    )


def test_wechat_export_keeps_none_when_scope_is_all(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """When WeChat analysis uses ALL scope, acquisition must still pass
    start_time=None, end_time=None so the provider exports the full history.
    """
    module = _facade_module()
    export_path = _export_file(tmp_path, "wechat-export.json")
    wechat_service = _StubWeChatService(export_path=export_path)

    facade = _facade(
        wechat_service=wechat_service,
        tmp_path=tmp_path,
    )

    # ALL scope (default) should keep None/None.
    config = module.AnalysisConfig(
        scope_mode=module.AnalysisScopeMode.ALL,
    )

    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_wechat",
        config=config,
    )

    assert len(wechat_service.export_requests) == 1
    request = wechat_service.export_requests[0]
    assert request.start_time is None
    assert request.end_time is None

# --------------------------------------------------------------- WeChat scope unit contract

def test_wechat_export_scope_uses_seconds_not_milliseconds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _facade_module()
    export_path = _export_file(tmp_path, "wechat-unit-test.json")
    wechat_service = _StubWeChatService(export_path=export_path)
    facade = _facade(wechat_service=wechat_service, tmp_path=tmp_path)
    config = module.AnalysisConfig(
        scope_mode=module.AnalysisScopeMode.CUSTOM,
        start_time="2024-01-01",
        end_time="2024-02-01",
    )
    facade.analyze_session(
        module.ChatSource.WECHAT,
        "wxid_fictional_unit_test",
        config=config,
    )
    assert len(wechat_service.export_requests) == 1
    request = wechat_service.export_requests[0]
    assert request.start_time is not None
    assert request.end_time is not None
    start_dt = datetime.fromtimestamp(request.start_time)
    assert start_dt.year == 2024, (
        "WeChat start_time=%d interpreted as datetime gives %s, "
        "expected year 2024. Value appears to be milliseconds."
        % (request.start_time, start_dt)
    )
    end_dt = datetime.fromtimestamp(request.end_time)
    assert end_dt.year == 2024, (
        "WeChat end_time=%d interpreted as datetime gives %s, "
        "expected year 2024. Value appears to be milliseconds."
        % (request.end_time, end_dt)
    )
    assert end_dt >= datetime(2024, 2, 1), (
        "WeChat end_time=%d gives %s, expected >= 2024-02-01 inclusive."
        % (request.end_time, end_dt)
    )
