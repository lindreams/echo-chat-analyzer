"""Privacy and path tests for the shared Echo diagnostic log."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from qq_chat_analyzer import diagnostics


@pytest.mark.slow_integration
def test_node_log_rotation_preserves_legacy_and_retries_locked_rename(tmp_path):
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for snapshot diagnostic retention")
    helper = Path(__file__).resolve().parents[1] / "scripts/qq_direct_db_snapshot/diagnostic_log.mjs"
    script = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
const file = process.env.QCE_LOG_FILE;
const {appendDiagnostic} = await import(process.argv[1]);
const limit = 5 * 1024 * 1024;
const legacy = Buffer.alloc(limit + 100, 'L');
fs.writeFileSync(file, legacy);
appendDiagnostic('stage=acquire outcome=failed guard_code=fictional\n');
assert.deepEqual(fs.readFileSync(file + '.1'), legacy);
assert.match(fs.readFileSync(file, 'utf8'), /guard_code=fictional/);
for (let i = 0; i < 24; i++) appendDiagnostic('x'.repeat(1024 * 1024));
const files = [file, ...[1, 2, 3].map(i => file + '.' + i)];
assert(files.every(p => fs.statSync(p).size < limit));
assert(!fs.existsSync(file + '.4'));
const history = files.slice(1).map(p => fs.readFileSync(p));
const rename = fs.renameSync;
fs.renameSync = () => { throw Object.assign(new Error('fictional lock'), {code: 'EPERM'}); };
syncBuiltinESMExports();
appendDiagnostic('z'.repeat(limit));
files.slice(1).forEach((p, i) => assert.deepEqual(fs.readFileSync(p), history[i]));
assert(fs.readFileSync(file, 'utf8').endsWith('z'.repeat(limit)));
fs.renameSync = rename;
syncBuiltinESMExports();
appendDiagnostic('stage=cleanup outcome=ok\n');
assert.equal(fs.readFileSync(file, 'utf8'), 'stage=cleanup outcome=ok\n');
assert(fs.statSync(file + '.1').size > limit);
// A logging I/O failure must never escape into acquisition.
process.env.QCE_LOG_FILE = file + '/not-a-directory';
appendDiagnostic('stage=acquire outcome=started\n');
"""
    # Keep JavaScript string escapes literal; all state remains in this test root.
    import os
    env = {**os.environ, "QCE_LOG_FILE": str(tmp_path / "qq-snapshot-diagnostics.log")}
    subprocess.run([node, "--input-type=module", "-e", script, helper.as_uri()],
                   env=env, check=True, capture_output=True, text=True, timeout=30)


def test_log_rotation_preserves_legacy_file_and_filters_all_backups(tmp_path, monkeypatch):
    from logging.handlers import RotatingFileHandler
    from qq_chat_analyzer.logging_config import build_diagnostic_handler

    path = tmp_path / "echo.log"
    legacy = b"fictional historical evidence\n" * 200000
    path.write_bytes(legacy)
    handler = build_diagnostic_handler(path)
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 5 * 1024 * 1024 and handler.backupCount == 3
        logger = logging.Logger("rotation-test", level=logging.INFO)
        logger.addHandler(handler)
        logger.info("轮转已启用 token=fictional-secret")
        assert path.with_suffix(".log.1").read_bytes() == legacy
        assert "轮转已启用" in path.read_text("utf-8")
        assert "fictional-secret" not in path.read_text("utf-8")
        # Exercise steady-state retention without writing another 20 MiB.
        handler.maxBytes = 512
        for index in range(40):
            logger.info("批次=%d token=fictional-secret | %s", index, "x" * 100)
        files = list(tmp_path.glob("echo.log*"))
        assert {item.name for item in files} == {"echo.log", "echo.log.1", "echo.log.2", "echo.log.3"}
        assert all(item.stat().st_size <= 512 for item in files)
        assert all("fictional-secret" not in item.read_text("utf-8") for item in files)
        import os
        with monkeypatch.context() as locked:
            locked.setattr(os, "rename", lambda *args: (_ for _ in ()).throw(PermissionError()))
            handler.maxBytes = 1
            logger.info("备份暂被占用 token=fictional-secret")
            assert "备份暂被占用" in path.read_text("utf-8")
            assert "fictional-secret" not in path.read_text("utf-8")
        logger.info("轮转已恢复")
        assert "轮转已恢复" in path.read_text("utf-8")
    finally:
        handler.close()


def test_pipeline_timing_keeps_nested_boundaries_outcomes_and_private_errors(monkeypatch, caplog):
    from qq_chat_analyzer import analysis_diagnostics as timing

    caplog.set_level(logging.DEBUG, logger=timing._LOGGER.name)
    clock = iter((10.0, 11.0, 13.0, 15.0))
    monkeypatch.setattr(timing, "perf_counter", lambda: next(clock))
    with timing.timed_stage("outer"):
        with timing.timed_stage("inner"):
            pass
    assert "[analysis-timing] stage=inner elapsed_ms=2000" in caplog.messages
    assert "[analysis-timing] stage=outer elapsed_ms=5000" in caplog.messages
    for error, outcome in ((ValueError("PRIVATE_DETAIL"), "failed"),
                           (OSError("PRIVATE_PATH"), "failed"),
                           (TimeoutError("PRIVATE_TIMEOUT"), "timeout"),
                           (InterruptedError("PRIVATE_CANCEL"), "cancelled")):
        caplog.clear()
        clock = iter((100.0, 100.125))
        with pytest.raises(type(error)) as caught:
            with timing.timed_stage("operation"):
                raise error
        assert caught.value is error
        assert "stage=operation outcome=started" in caplog.messages[0]
        assert f"stage=operation outcome={outcome}" in caplog.messages[1]
        assert caplog.messages[1].endswith("elapsed_ms=125")
        assert "PRIVATE" not in caplog.text
    clock = iter((1.0, 2.0))
    monkeypatch.setattr(timing._LOGGER, "log", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    with timing.timed_stage("logging_unavailable"):
        pass

    # Default logs keep one timing per phase and failure reasons per material.
    caplog.clear()
    caplog.set_level(logging.INFO, logger=timing._LOGGER.name)
    monkeypatch.undo()
    with timing.timed_stage("report"):
        pass
    with timing.timed_stage("material", detail=True):
        pass
    with pytest.raises(OSError):
        with timing.timed_stage("material", detail=True):
            raise OSError("PRIVATE_PATH")
    assert len(caplog.messages) == 2
    assert caplog.messages[0].startswith("[analysis-timing] stage=report ")
    assert "stage=material outcome=failed failure_code=io_error" in caplog.messages[1]
    assert "PRIVATE" not in caplog.text


def test_runtime_provenance_is_written_once_without_local_paths(tmp_path, monkeypatch):
    path = tmp_path / 'echo.log'
    monkeypatch.setattr(diagnostics, 'log_path', lambda: path)
    names = set(diagnostics.DESKTOP_DIAGNOSTIC_LOGGERS) | {diagnostics.LOGGER_NAME}
    saved = {name: list(logging.getLogger(name).handlers) for name in names}
    try:
        diagnostics.configure_diagnostics()
        diagnostics.configure_diagnostics()
        text = path.read_text(encoding='utf-8')
        assert text.count('[runtime] echo_version=') == 1
        assert 'python_version=' in text and 'windows_build=' in text
        assert str(tmp_path) not in text and sys.executable not in text
    finally:
        created = set()
        for name, handlers in saved.items():
            logger = logging.getLogger(name)
            created.update(handler for handler in logger.handlers if handler not in handlers)
            logger.handlers[:] = handlers
        for handler in created:
            handler.close()


def test_frozen_log_uses_local_app_data_without_creating_install_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Echo" / "Echo.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    expected_root = tmp_path / "local-app-data" / "LocalChatAnalyzer"
    assert diagnostics.runtime_root() == expected_root
    assert diagnostics.log_path() == expected_root / "logs" / "echo.log"
    assert not expected_root.exists()
    assert not executable.parent.exists()


def test_sensitive_filter_redacts_key_paths_and_helper_stderr() -> None:
    secret_key = "ab12" * 16
    database_path = r"C:\Users\Fictional\Documents\xwechat_files\session.db"
    helper_stderr = "native helper failed for fictional account"
    record = logging.LogRecord(
        name="qq_chat_analyzer.diagnostics.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="key=%s database_path=%s helper_stderr=%s token=%s",
        args=(secret_key, database_path, helper_stderr, "fictional-token"),
        exc_info=None,
    )

    diagnostics.SensitiveDataFilter().filter(record)
    text = record.getMessage()

    assert secret_key not in text
    assert database_path not in text
    assert helper_stderr not in text
    assert "fictional-token" not in text
    assert "[REDACTED]" in text


def test_sensitive_filter_removes_exception_message() -> None:
    try:
        raise RuntimeError("fictional secret exception detail")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="qq_chat_analyzer.diagnostics.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="wechat.import.failed",
        args=(),
        exc_info=exc_info,
    )

    diagnostics.SensitiveDataFilter().filter(record)

    assert record.exc_info is None
    assert record.exc_text is None
    assert "fictional secret exception detail" not in record.getMessage()
