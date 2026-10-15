"""Direct DB facade acquisition uses the final analysis scope in seconds."""

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

from qq_chat_analyzer.application.dto import AnalysisResultDTO, AnalysisStatus
from qq_chat_analyzer.application.facade import AnalysisConfig, ChatAnalyzerFacade, ChatSource
from qq_chat_analyzer.application.scope_filter import AnalysisScope


def _inclusive_window(start: date, end: date) -> tuple[int, int]:
    return (
        int(datetime.combine(start, time.min).timestamp()),
        int(datetime.combine(end + timedelta(days=1), time.min).timestamp()) - 1,
    )


def _export_file(tmp_path: Path) -> Path:
    # The analysis double only needs an existing payload path.
    path = tmp_path / "qq-db-payload.json"
    path.write_text('{}', encoding="utf-8")
    return path


def _analysis_result() -> AnalysisResultDTO:
    return AnalysisResultDTO(
        status=AnalysisStatus.COMPLETED,
        processed_message_count=2,
        valid_text_count=2,
    )


def _acquisition(export_path: Path) -> object:
    return type(
        "FictionalAcquisition",
        (),
        {
            "payload_path": export_path,
            "snapshot_id": None,
            "acquired_at": None,
            "reused_snapshot": False,
        },
    )()


class _RecordingQQService:
    """QQ service stub that records the acquisition request instead of exporting."""

    def __init__(self, export_path: Path | None) -> None:
        self._export_path = export_path
        self.requests: list[object] = []

    def list_sessions(self) -> list[object]:
        return []

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None, end_time=None):
        request = SimpleNamespace(
            session_id=session_id, start_time=start_time, end_time=end_time
        )
        self.requests.append(request)
        yield _acquisition(self._export_path)


class _RecordingAnalysisService:
    """Analysis service stub that records the request it is handed."""

    def __init__(self, result: AnalysisResultDTO) -> None:
        self._result = result
        self.requests: list[object] = []

    def execute(self, request):
        self.requests.append(request)
        return self._result


def _recording_facade(
    qq_service: _RecordingQQService,
    analysis_service: _RecordingAnalysisService,
) -> ChatAnalyzerFacade:
    return ChatAnalyzerFacade(
        qq_service=qq_service,
        analysis_service=analysis_service,
    )


def _two_day_config(tmp_path: Path) -> AnalysisConfig:
    return AnalysisConfig(
        start_time="2026-08-10",
        end_time="2026-08-11",
        output_directory=tmp_path / "facade-output",
    )


def test_direct_db_scope_reaches_acquisition_as_seconds(
    tmp_path: Path,
) -> None:
    """A dated QQ scope must reach Direct DB acquisition in epoch seconds."""
    qq_service = _RecordingQQService(_export_file(tmp_path))
    facade = _recording_facade(qq_service, _RecordingAnalysisService(_analysis_result()))
    expected_start, expected_end = _inclusive_window(
        date(2026, 8, 10),
        date(2026, 8, 11),
    )

    facade.analyze_session(
        ChatSource.QQ,
        "700000001",
        _two_day_config(tmp_path),
    )

    request = qq_service.requests[0]
    assert request.start_time == expected_start
    assert request.end_time == expected_end
    assert request.start_time < 10**12


def test_qq_acquisition_window_covers_both_inclusive_local_days(
    tmp_path: Path,
) -> None:
    """Direct DB boundary: local midnight through 23:59:59, inclusive."""
    qq_service = _RecordingQQService(_export_file(tmp_path))
    facade = _recording_facade(qq_service, _RecordingAnalysisService(_analysis_result()))

    facade.analyze_session(ChatSource.QQ, "700000001", _two_day_config(tmp_path))

    request = qq_service.requests[0]
    assert isinstance(request.start_time, int)
    assert isinstance(request.end_time, int)
    assert datetime.fromtimestamp(request.start_time) == datetime(
        2026, 8, 10, 0, 0
    )
    assert datetime.fromtimestamp(request.end_time + 1) == datetime(
        2026, 8, 12, 0, 0
    )
    # A mid-August window has no DST transition on any supported host.
    assert request.end_time - request.start_time == 2 * 24 * 60 * 60 - 1
