"""Update checks use fictional release metadata and no external network."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from urllib.error import HTTPError, URLError

import pytest

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
from qq_chat_analyzer.version import APP_VERSION


URL = "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v1.10.0"


def release(tag="v1.10.0", **changes):
    return dict(tag_name=tag, draft=False, prerelease=False, html_url=URL, **changes)


def service(tmp_path, monkeypatch, payload=None, current="1.9.0", clock=None):
    from qq_chat_analyzer.application import update_check_service as module

    monkeypatch.setattr(module, "APP_VERSION", current)
    return module.UpdateCheckService(
        state_path=tmp_path / "update-check.json",
        fetch_release=lambda: release() if payload is None else payload,
        clock=clock or (lambda: 100000.0),
    )


@pytest.mark.parametrize("current,tag,status", [("1.9.0", "v1.10.0", "update_available"), ("1.10.0", "v1.10.0", "up_to_date"), ("1.10.0-rc.10", "v1.10.0", "update_available")])
def test_semver_precedence(tmp_path, monkeypatch, current, tag, status):
    result = service(tmp_path, monkeypatch, release(tag), current).check()
    assert result.status == status
    assert result.current_version == current
    assert result.latest_version == tag.removeprefix("v")
    assert result.release_url == URL


@pytest.mark.parametrize("payload", [[], {**release(), "draft": True}, release("v2.0.0-beta"), {**release(), "html_url": "javascript:alert(1)"}, {**release(), "html_url": "https://evil.example/releases/tag/v1.10.0"}])
def test_invalid_or_nonformal_release_is_safe(tmp_path, monkeypatch, payload):
    result = service(tmp_path, monkeypatch, payload).check()
    assert result.status == "unavailable"
    assert result.error_code == "invalid_response"
    assert result.release_url is None


def test_24h_dedupe_survives_restart_and_manual_bypasses(tmp_path, monkeypatch):
    now = [100000.0]
    first = service(tmp_path, monkeypatch, clock=lambda: now[0])
    assert first.check().status == "update_available"
    assert json.loads((tmp_path / "update-check.json").read_text()) == {"last_check_time": 100000.0}
    second = service(tmp_path, monkeypatch, clock=lambda: now[0])
    now[0] += 86399
    assert second.check().status == "skipped"
    now[0] += 1
    assert second.check().status == "update_available"
    assert second.check(manual=True).status == "update_available"
    assert second.check().status == "skipped"


def test_unwritable_state_still_checks_and_deduplicates_in_memory(tmp_path, monkeypatch):
    (tmp_path / "update-check.json").mkdir()
    core = service(tmp_path, monkeypatch)
    assert core.check().status == "update_available"
    assert core.check().status == "skipped"


@pytest.mark.parametrize("failure,code,status", [(TimeoutError(), "timeout", "unavailable"), (URLError("offline"), "network_error", "unavailable"), (HTTPError("url", 403, "forbidden", {}, None), "rate_limited", "unavailable"), (ValueError("malformed"), "invalid_response", "unavailable")])
def test_network_failures_are_safe_and_attempts_are_deduplicated(tmp_path, monkeypatch, failure, code, status):
    core = service(tmp_path, monkeypatch)

    def fail():
        raise failure

    core._fetch_release = fail
    result = core.check()
    assert result.status == status
    assert result.error_code == code
    assert result.release_url is None
    assert core.check().status == "skipped"
    assert core.check(manual=True).status == status


def test_overlapping_check_returns_without_waiting(tmp_path, monkeypatch):
    core = service(tmp_path, monkeypatch)
    entered, finish = Event(), Event()

    def fetch():
        entered.set()
        assert finish.wait(3)
        return release()

    core._fetch_release = fetch
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(core.check)
        try:
            assert entered.wait(2)
            result = core.check(manual=True)
            assert result.status == "skipped"
            assert result.error_code == "in_progress"
        finally:
            finish.set()
        assert pending.result().status == "update_available"


@pytest.mark.parametrize("body,expected", [
    (json.dumps(release()).encode(), "update_available"),
    (b"not json", "unavailable"), (b"\xff", "unavailable"),
    (b"x" * 262145, "unavailable"),
], ids=["valid", "malformed-json", "invalid-utf8", "oversized"])
def test_github_request_contract_and_bounded_response(tmp_path, monkeypatch, body, expected):
    from qq_chat_analyzer.application import update_check_service as module

    def open_response(request, *, timeout):
        assert request.full_url == "https://api.github.com/repos/lindreams/echo-chat-analyzer/releases/latest"
        assert 0 < timeout <= 5
        assert request.get_header("Accept") == "application/vnd.github+json"
        assert request.get_header("User-agent")
        return io.BytesIO(body)

    monkeypatch.setattr(module, "urlopen", open_response)
    result = module.UpdateCheckService(state_path=tmp_path / "state.json").check()
    assert result.status == expected
