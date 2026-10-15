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


def _analysis_models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


def _dto():
    return importlib.import_module("qq_chat_analyzer.application.dto")


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


# ------------------------------------------------------------------ listing


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_member_count_is_never_presented_as_message_count(source_name):
    module = _facade_module()
    session = module._to_session_info(module.ChatSource(source_name), SimpleNamespace(
        session_id="fictional-room", display_name="Fictional Room", member_count=80,
    ))
    assert session.message_count is None


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


@pytest.mark.parametrize(
    "failure", ["analysis", "echo_view", "echo_html", "descriptor", "outcome"]
)
def test_exception_before_scratch_transfer_leaves_no_orphan(tmp_path, monkeypatch, failure):
    module = _facade_module()
    monkeypatch.setattr(module, "user_data_dir", lambda: tmp_path)
    facade = module.ChatAnalyzerFacade(analysis_service=_StubAnalysisService(result=_result()))
    def fail(*args, **kwargs):
        raise RuntimeError("fictional generation failure")
    input_path = Path("fictional.json")
    if failure == "analysis":
        monkeypatch.setattr(facade._analysis_service, "execute", fail)
    elif failure in {"echo_view", "echo_html"}:
        service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
        facade = module.ChatAnalyzerFacade(
            analysis_service=service.AnalysisApplicationService()
        )
        input_path = tmp_path / "fictional-qq.json"
        input_path.write_text(
            json.dumps(qq_db_payload([
                qq_db_record("fictional python project discussion"),
            ])),
            encoding="utf-8",
        )

        def fail_echo(*args, **kwargs):
            if failure == "echo_html":
                # JSON was already written: cleanup must also remove partial artifacts.
                assert Path(args[1]).with_suffix(".json").is_file()
            raise ValueError("fictional Echo generation failure")

        target = (
            "build_echo_report_view" if failure == "echo_view"
            else "export_echo_report_html"
        )
        monkeypatch.setattr(service, target, fail_echo)
    elif failure == "outcome":
        monkeypatch.setattr(module, "AnalysisOutcome", fail)
    else:
        monkeypatch.setattr(module, "_generated_echo_report_path", fail)
    with pytest.raises(Exception) as captured:
        facade._analyze_path(input_path, module.AnalysisConfig(),
                             source=module.ChatSource.QQ, session=None, scope=module.AnalysisScope.all())
    if failure in {"echo_view", "echo_html"}:
        assert isinstance(captured.value, module.FacadeError)
        assert captured.value.code == "artifact_generation_failed"
    assert not list(tmp_path.rglob("chat-analyzer-output-*"))


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


@pytest.mark.parametrize("existing", [50])
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


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("original, public_message, expected_code", [pytest.param(
        PermissionError(13, "Permission denied", r"C:\Users\FictionalUser\Private\chat.json"),
        "missing", "permission_error", id="private-windows-path",
    ), pytest.param(RuntimeError("fictional internal failure"), None, "runtime_error", id="null"), pytest.param(RuntimeError("fictional internal failure"), " \n", "runtime_error", id="blank"), pytest.param(RuntimeError("fictional internal failure"), 123, "runtime_error", id="non-string")])
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


# -------------------------------------------------------- injection & layering


# ---------------------------------------------------------------
# GUI-6A: snapshot Facade bridge
# ---------------------------------------------------------------

# --------------------------------------------------------------- WeChat scope push-down

# --------------------------------------------------------------- WeChat scope unit contract
