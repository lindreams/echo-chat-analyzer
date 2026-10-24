"""Echo-only local readiness/metadata. No QCE auth, export or GUI dependency."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import binascii
import json
import re
import time
import tempfile
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .bridge_credential import authorization_headers, resolve_bridge_credential
from .qq_direct_snapshot_runtime import QQDirectSnapshotRuntimeClient, QQSnapshotRuntimeUnavailable

DEFAULT_BRIDGE_URL = "http://127.0.0.1:40655"


class NapCatQQError(Exception):
    code = "napcat_qq_unavailable"
    public_message = "QQ local runtime is unavailable. Please finish QQ login and retry."

    def __init__(self, rpc_error: str | None = None):
        super().__init__(self.public_message)
        # The bridge's fixed error label, if it sent one. Never shown to users.
        self.rpc_error = rpc_error


class NapCatQQAuthRejected(NapCatQQError):
    """The bridge refused this client's credential.

    Echo-owned bridges authenticate every method, so a missing, stale or foreign
    credential is rejected before any method runs.  The public message stays the
    privacy-safe base message: no credential, URL, path or account is added.
    """

    code = "napcat_qq_auth_rejected"


class NapCatQQWorkerGenerationChanged(NapCatQQError):
    code = "napcat_qq_worker_generation_changed"
    public_message = "QQ runtime restarted. Please reconnect explicitly."


# Fixed stages a media fetch may fail at. The bridge owns these labels; only a
# whitelisted one survives, so no path, message ID or kernel text can leak.
_MEDIA_STAGES = frozenset({
    "probe_timeout", "probe_api_unavailable",
    "media_mapping_rejected", "media_message_query_failed", "media_api_unavailable",
    "media_busy", "media_budget_exhausted", "media_download_timeout",
    "media_download_failed", "media_download_no_path", "media_download_no_cache_hint", "media_path_type_invalid",
    "media_path_not_absolute", "media_path_invalid", "media_file_missing",
    "media_open_failed", "media_file_type_rejected", "media_file_identity_changed",
    "media_file_empty", "media_file_too_large", "media_read_incomplete",
    "media_file_changed", "media_file_rejected", "media_transfer_invalid",
})


class NapCatQQMediaStageError(NapCatQQError):
    """One media fetch failed at a fixed, sanitised stage."""

    def __init__(self, stage: str) -> None:
        super().__init__()
        self.stage = stage


@dataclass(frozen=True)
class NapCatStatus:
    bridge_ready: bool
    qq_online: bool
    self_info: dict[str, str]
    database_api_ready: bool
    passphrase_ready: bool
    snapshot_api_ready: bool
    runtime_id: str | None = None
    boot_id: str | None = None

    @property
    def ready(self) -> bool:
        return all((self.bridge_ready, self.qq_online, self.self_info.get("uin"),
                    self.database_api_ready, self.passphrase_ready, self.snapshot_api_ready))


@dataclass(frozen=True)
class NapCatFriend:
    uid: str
    uin: str
    nickname: str
    remark: str

    @property
    def display_name(self) -> str:
        return self.remark or self.nickname or self.uin or self.uid


@dataclass(frozen=True)
class NapCatGroup:
    group_code: str
    group_name: str
    member_count: int | None


@dataclass(frozen=True)
class PicMessageMapping:
    """Read-only message-element identity check used before a media fetch.

    The result contains only booleans, counts and a fixed basis label. Real
    message IDs, UIDs, digests, paths, URLs and element IDs never leave the
    runtime bridge.
    """

    passed: bool
    found: bool
    unique: bool
    msg_id_matches: bool
    time_matches: bool
    peer_matches: bool
    sender_matches: bool | None
    pic_element_count: int
    matched_pic_count: int
    segment_id_matches: bool | None
    file_uuid_matches: bool | None
    md5_matches: bool
    match_basis: str


_PROBE_BASES = frozenset({
    "none", "md5", "segment_id", "file_uuid", "segment_id+md5",
    "file_uuid+md5", "segment_id+file_uuid", "segment_id+file_uuid+md5",
})


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


MAX_PIC_MEDIA_BYTES = 32 * 1024 * 1024
MAX_PIC_CHUNK_BYTES = 256 * 1024


def _valid_pic_request(
    *, msg_id: Any, peer_uid: Any, expected_time: Any, expected_md5: Any,
    expected_file_uuid: Any, expected_segment_id: Any, expected_self: Any,
    chat_type: Any = 1, expected_sender_uin: Any = None, expected_sender_uid: Any = None,
) -> bool:
    """Fixed private/group PIC locators shared by identity check and fetch."""
    return (
        type(chat_type) is int and chat_type in (1, 2)
        and (
            (chat_type == 1 and expected_sender_uin is None and expected_sender_uid is None)
            or (chat_type == 2
                and isinstance(expected_sender_uin, str)
                and re.fullmatch(r"[1-9][0-9]{4,19}", expected_sender_uin) is not None
                and (expected_sender_uid is None or (
                    isinstance(expected_sender_uid, str)
                    and re.fullmatch(r"u_[A-Za-z0-9_-]{10,64}", expected_sender_uid) is not None))
                and expected_file_uuid is not None and expected_segment_id is not None)
        )
        and isinstance(msg_id, str)
        and re.fullmatch(r"[1-9][0-9]{0,19}", msg_id) is not None
        and isinstance(peer_uid, str)
        and re.fullmatch(r"u_[A-Za-z0-9_-]{10,64}" if chat_type == 1 else r"[1-9][0-9]{4,19}", peer_uid) is not None
        and isinstance(expected_time, int)
        and not isinstance(expected_time, bool)
        and 0 < expected_time <= 99_999_999_999
        and isinstance(expected_md5, str)
        and re.fullmatch(r"[0-9a-fA-F]{32}", expected_md5) is not None
        and (expected_file_uuid is None or (
            isinstance(expected_file_uuid, str)
            and re.fullmatch(r"[A-Za-z0-9_.:+=\/-]{1,128}", expected_file_uuid) is not None
            and ".." not in expected_file_uuid
            and not expected_file_uuid.startswith("/")))
        and (expected_segment_id is None or (
            isinstance(expected_segment_id, str)
            and re.fullmatch(r"[1-9][0-9]{0,19}", expected_segment_id) is not None))
        and (expected_self is None or isinstance(expected_self, bool))
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NapCatQQError()


class NapCatQQProvider:
    def __init__(self, base_url: str = DEFAULT_BRIDGE_URL, *, timeout: float = 30,
                 transport: Callable[[str, bytes, float], tuple[int, str]] | None = None,
                 credential: object | None = None):
        self._credential_source = credential
        self._verified_credential = None
        self._boot_id = None
        self._runtime_id = None
        self._generation_changed = False
        try:
            parsed = urllib.parse.urlsplit(base_url)
            valid = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
                     and not parsed.username and not parsed.password and parsed.path in {"", "/"}
                     and not parsed.query and not parsed.fragment and parsed.port is not None)
            if not valid or timeout <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise NapCatQQError() from None
        self._base_url = f"http://{parsed.hostname}:{parsed.port}"
        self._timeout = timeout
        self._transport = transport

    @property
    def requires_reconnect(self) -> bool:
        return self._generation_changed

    def _request(self, url: str, body: bytes, timeout: float) -> tuple[int, str]:
        if url not in {self._base_url + "/rpc", self._base_url + "/rpc/" + str(self._runtime_id)}:
            raise NapCatQQError()
        credential = resolve_bridge_credential(self._credential_source)
        if credential is None:
            # Fail closed: without a live credential no request leaves at all,
            # so the client can never take part in an unauthenticated call.
            raise NapCatQQError()
        if self._transport is not None:
            return self._transport(url, body, timeout)
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **authorization_headers(credential)},
        )
        # This provider admits only the validated loopback HTTP URL. A default
        # opener also builds HTTPSHandler and repeatedly scans Windows' trust
        # stores for every chunk, despite TLS never being used here.
        opener = urllib.request.OpenerDirector()
        for handler in (urllib.request.ProxyHandler({}), urllib.request.HTTPHandler(),
                        urllib.request.HTTPDefaultErrorHandler(), _NoRedirect(),
                        urllib.request.HTTPErrorProcessor()):
            opener.add_handler(handler)
        try:
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise NapCatQQError("transport_limit")
                return response.status, data.decode("utf-8")
        except TimeoutError:
            raise NapCatQQError("transport_timeout") from None
        except urllib.error.URLError as error:
            raise NapCatQQError("transport_timeout" if isinstance(error.reason, TimeoutError) else None) from None
        except (OSError, ValueError):
            raise NapCatQQError() from None

    def _rpc(self, method: str, params: list[Any] | None = None, *, timeout: float | None = None) -> Any:
        maximum = 135.0 if method == "EchoMediaProbe.downloadPicMedia" else self._timeout
        deadline = time.monotonic() + (maximum if timeout is None else min(timeout, maximum))
        credential = resolve_bridge_credential(self._credential_source)
        if self._generation_changed:
            raise NapCatQQWorkerGenerationChanged()
        if self._boot_id is not None and self._verified_credential != credential:
            self._generation_changed = True
            raise NapCatQQWorkerGenerationChanged()
        if method != "Core.status" and self._boot_id is None:
            self.status(timeout=max(0, deadline - time.monotonic()))
        try:
            body = {"method": method, "params": params or []}
            if self._boot_id is not None:
                body["boot_id"] = self._boot_id
            url = self._base_url + "/rpc"
            if self._runtime_id is not None:
                url += "/" + self._runtime_id
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NapCatQQError()
            status, text = self._request(url, json.dumps(body).encode(), remaining)
            if status == 401:
                # The bridge rejected this client's credential.  No retry and no
                # fallback: the caller must re-establish an owned instance.
                raise NapCatQQAuthRejected()
            value = json.loads(text)
            if status == 409 and isinstance(value, dict) and value.get("error") == "worker_generation_mismatch":
                self._generation_changed = True
                raise NapCatQQWorkerGenerationChanged()
            if status != 200 or not isinstance(value, dict) or value.get("ok") is not True:
                error = value.get("error") if isinstance(value, dict) else None
                raise NapCatQQError(
                    error if isinstance(error, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,39}", error) else None)
            result = value["result"]
            if method == "Core.status":
                if not isinstance(result, dict) or result.get("rpc_auth") != "bearer-v1":
                    raise NapCatQQAuthRejected()
                boot = result.get("boot_id")
                if not isinstance(boot, str) or re.fullmatch(r"[0-9a-f]{64}", boot) is None:
                    raise NapCatQQError()
                if self._boot_id is not None and boot != self._boot_id:
                    self._generation_changed = True
                    raise NapCatQQWorkerGenerationChanged()
                runtime = result.get("runtime_id")
                if runtime is not None and (not isinstance(runtime, str) or re.fullmatch(r"[0-9a-f]{64}", runtime) is None):
                    raise NapCatQQError()
                fields = ("bridge_ready", "qq_online", "database_api_ready", "passphrase_ready", "snapshot_api_ready")
                if any(not isinstance(result.get(f), bool) for f in fields) or not isinstance(result.get("self_info"), dict):
                    raise NapCatQQError()
                self._boot_id = boot
                self._runtime_id = runtime
                self._verified_credential = credential
            return result
        except (NapCatQQAuthRejected, NapCatQQWorkerGenerationChanged):
            raise
        except NapCatQQError as error:
            # Keep the bridge's fixed label; it is a whitelisted code only.
            raise NapCatQQError(error.rpc_error) from None
        except TimeoutError:
            raise NapCatQQError("transport_timeout") from None
        except (OSError, ValueError, KeyError, TypeError):
            raise NapCatQQError() from None

    def status(self, *, timeout: float | None = None) -> NapCatStatus:
        value = self._rpc("Core.status", timeout=timeout)
        fields = ("bridge_ready", "qq_online", "database_api_ready", "passphrase_ready", "snapshot_api_ready")
        if not isinstance(value, dict) or any(not isinstance(value.get(f), bool) for f in fields) or not isinstance(value.get("self_info"), dict):
            raise NapCatQQError()
        identity = {key: _text(value["self_info"].get(key)) for key in ("uin", "uid", "nickname")}
        return NapCatStatus(value["bridge_ready"], value["qq_online"], identity,
                            value["database_api_ready"], value["passphrase_ready"], value["snapshot_api_ready"],
                            _text(value.get("runtime_id")) or None, self._boot_id)

    def list_friends(self, *, timeout: float | None = None) -> list[NapCatFriend]:
        rows = self._rpc("EchoMetadata.listFriends", timeout=timeout)
        if not isinstance(rows, list):
            raise NapCatQQError()
        return [NapCatFriend(*(_text(row.get(k)) for k in ("uid", "uin", "nickname", "remark"))) for row in rows if isinstance(row, dict)]

    def list_groups(self, *, timeout: float | None = None) -> list[NapCatGroup]:
        rows = self._rpc("EchoMetadata.listGroups", timeout=timeout)
        if not isinstance(rows, list):
            raise NapCatQQError()
        return [NapCatGroup(_text(row.get("group_code")), _text(row.get("group_name")),
                            row.get("member_count") if type(row.get("member_count")) is int else None)
                for row in rows if isinstance(row, dict)]

    def get_group_member_all(self, group_code: str) -> dict[str, Any]:
        result = self._rpc("GroupApi.getGroupMemberAll", [group_code])
        if not isinstance(result, dict):
            raise NapCatQQError()
        return result

    def resolve_pic_message(
        self,
        *,
        msg_id: str,
        peer_uid: str,
        expected_time: int,
        expected_md5: str,
        expected_file_uuid: str | None = None,
        expected_segment_id: str | None = None,
        expected_self: bool | None = None,
        chat_type: int = 1,
        expected_sender_uin: str | None = None,
        expected_sender_uid: str | None = None,
        timeout: float | None = 8,
    ) -> PicMessageMapping:
        """Ask the runtime to map one DB message to its live PIC element.

        This only calls ``MsgApi.getMsgsByMsgId`` through the fixed, read-only
        bridge method. It never downloads media, reads a path/URL, queries any
        other message, or retries with neighbouring IDs.
        """
        if not _valid_pic_request(
            msg_id=msg_id, peer_uid=peer_uid, expected_time=expected_time,
            expected_md5=expected_md5, expected_file_uuid=expected_file_uuid,
            expected_segment_id=expected_segment_id, expected_self=expected_self,
            chat_type=chat_type, expected_sender_uin=expected_sender_uin, expected_sender_uid=expected_sender_uid,
        ):
            raise NapCatQQError()
        result = self._rpc(
            "EchoMediaProbe.resolvePicMessage",
            [{
                "msgId": msg_id,
                "chatType": chat_type,
                "peerUid": peer_uid,
                "expectedTime": expected_time,
                "expectedMd5": expected_md5,
                "expectedFileUuid": expected_file_uuid,
                "expectedSegmentId": expected_segment_id,
                "expectedSelf": expected_self,
                **({"expectedSenderUin": expected_sender_uin, "expectedSenderUid": expected_sender_uid}
                   if chat_type == 2 else {}),
            }],
            timeout=timeout,
        )
        bool_fields = (
            "passed", "found", "unique", "msg_id_matches", "time_matches",
            "peer_matches", "md5_matches",
        )
        count_fields = ("pic_element_count", "matched_pic_count")
        if (
            not isinstance(result, dict)
            or any(not isinstance(result.get(key), bool) for key in bool_fields)
            or any(type(result.get(key)) is not int or result[key] < 0 for key in count_fields)
            or result["matched_pic_count"] > result["pic_element_count"]
            or (result.get("sender_matches") is not None
                and not isinstance(result.get("sender_matches"), bool))
            or (result.get("segment_id_matches") is not None
                and not isinstance(result.get("segment_id_matches"), bool))
            or (result.get("file_uuid_matches") is not None
                and not isinstance(result.get("file_uuid_matches"), bool))
            or result.get("match_basis") not in _PROBE_BASES
            or (result["unique"] and not result["found"])
        ):
            raise NapCatQQError()
        # Recompute the verdict instead of trusting the bridge's own label.
        passed = all((
            result["unique"],
            result["msg_id_matches"],
            result["time_matches"],
            result["peer_matches"],
            result["matched_pic_count"] == 1,
            result["md5_matches"],
        )) and result["sender_matches"] is not False
        if chat_type == 2:
            passed = (passed and result["sender_matches"] is True
                      and result["segment_id_matches"] is True and result["file_uuid_matches"] is True)
        if result["passed"] is not passed:
            raise NapCatQQError()
        return PicMessageMapping(
            passed=passed,
            found=result["found"],
            unique=result["unique"],
            msg_id_matches=result["msg_id_matches"],
            time_matches=result["time_matches"],
            peer_matches=result["peer_matches"],
            sender_matches=result["sender_matches"],
            pic_element_count=result["pic_element_count"],
            matched_pic_count=result["matched_pic_count"],
            segment_id_matches=result["segment_id_matches"],
            file_uuid_matches=result["file_uuid_matches"],
            md5_matches=result["md5_matches"],
            match_basis=result["match_basis"],
        )

    def download_pic_media(
        self,
        *,
        msg_id: str,
        peer_uid: str,
        element_id: str,
        expected_time: int,
        expected_md5: str,
        expected_file_uuid: str | None = None,
        expected_self: bool | None = None,
        chat_type: int = 1,
        expected_sender_uin: str | None = None,
        expected_sender_uid: str | None = None,
        timeout: float | None = 135,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> bytes:
        """Fetch the bytes of one already located private/group PIC element.

        The bridge re-locates the same message and requires the one PIC element
        matching this element ID, digest and file UUID before asking QQ for the
        media. Only bounded bytes return; the runtime's local path, URL, file
        name and account IDs never cross the bridge.

        The client deadline stays above the bridge's own 120 s media budget so a
        timeout is reported by the bridge as a stage instead of being lost here.
        """
        if (
            not _valid_pic_request(
                msg_id=msg_id, peer_uid=peer_uid, expected_time=expected_time,
                expected_md5=expected_md5, expected_file_uuid=expected_file_uuid,
                expected_segment_id=element_id, expected_self=expected_self,
                chat_type=chat_type, expected_sender_uin=expected_sender_uin, expected_sender_uid=expected_sender_uid,
            )
            or not isinstance(element_id, str)
        ):
            raise NapCatQQError()
        def call(method, params):
            try:
                budget = timeout if method == "EchoMediaProbe.downloadPicMedia" else 10
                return self._rpc(method, params, timeout=budget)
            except NapCatQQError as error:
                stage = getattr(error, "rpc_error", None)
                if stage in {"transport_timeout", "transport_limit"}:
                    raise NapCatQQMediaStageError("media_" + stage) from None
                if stage in _MEDIA_STAGES:
                    raise NapCatQQMediaStageError(stage) from None
                raise

        if cancelled():
            raise NapCatQQMediaStageError("media_cancelled")
        result = call(
                "EchoMediaProbe.downloadPicMedia",
                [{
                    "msgId": msg_id,
                    "chatType": chat_type,
                    "peerUid": peer_uid,
                    "elementId": element_id,
                    "expectedTime": expected_time,
                    "expectedMd5": expected_md5,
                    "expectedFileUuid": expected_file_uuid,
                    "expectedSelf": expected_self,
                    **({"expectedSenderUin": expected_sender_uin, "expectedSenderUid": expected_sender_uid}
                       if chat_type == 2 else {}),
                }],
            )
        if not isinstance(result, dict) or set(result) != {"transfer_id", "size", "chunk_size"}:
            raise NapCatQQMediaStageError("media_transport_invalid")
        transfer, size, chunk_size = (result[k] for k in ("transfer_id", "size", "chunk_size"))
        if not isinstance(transfer, str) or re.fullmatch(r"[0-9a-f]{64}", transfer) is None:
            raise NapCatQQMediaStageError("media_transport_invalid")
        try:
            if type(size) is int and size > MAX_PIC_MEDIA_BYTES:
                raise NapCatQQMediaStageError("media_transport_limit")
            if (type(size) is not int or not 0 < size <= MAX_PIC_MEDIA_BYTES
                    or type(chunk_size) is not int or not 0 < chunk_size <= MAX_PIC_CHUNK_BYTES):
                raise NapCatQQMediaStageError("media_transport_invalid")
            # Partial transfers are never published. Disk spooling avoids a
            # second full-file bytearray and its resize/copy peaks.
            with tempfile.TemporaryFile() as stream:
                offset = 0
                while offset < size:
                    if cancelled():
                        raise NapCatQQMediaStageError("media_cancelled")
                    chunk = call("EchoMediaProbe.readPicMediaChunk", [{"transfer_id": transfer, "offset": offset}])
                    if not isinstance(chunk, dict) or set(chunk) != {"offset", "base64", "eof"}:
                        raise NapCatQQMediaStageError("media_transport_invalid")
                    expected = min(chunk_size, size - offset)
                    encoded = chunk["base64"]
                    if (type(chunk["offset"]) is not int or chunk["offset"] != offset
                            or type(chunk["eof"]) is not bool or chunk["eof"] != (offset + expected == size)
                            or not isinstance(encoded, str) or len(encoded) != 4 * ((expected + 2) // 3)):
                        raise NapCatQQMediaStageError("media_transport_invalid")
                    try:
                        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
                    except (binascii.Error, ValueError, UnicodeEncodeError):
                        raise NapCatQQMediaStageError("media_transport_invalid") from None
                    if len(raw) != expected:
                        raise NapCatQQMediaStageError("media_transport_invalid")
                    stream.write(raw)
                    offset += len(raw)
                if cancelled():
                    raise NapCatQQMediaStageError("media_cancelled")
                stream.seek(0)
                return stream.read()
        finally:
            try:
                call("EchoMediaProbe.releasePicMedia", [{"transfer_id": transfer}])
            except NapCatQQError:
                pass  # A disconnected/generation-changed transfer expires on its owner.

    def wait_media_ready(self, *, cancelled: Callable[[], bool] = lambda: False) -> None:
        """Pace the serial queue without discarding targets or overlapping QQ."""
        while True:
            if cancelled():
                raise NapCatQQMediaStageError("media_cancelled")
            status = self._rpc("Core.status", timeout=5)
            busy, delay = status.get("media_busy"), status.get("media_retry_after_ms")
            if type(busy) is not bool or type(delay) is not int or not 0 <= delay <= 60000:
                raise NapCatQQMediaStageError("media_transport_invalid")
            if not busy and delay == 0:
                return
            until = time.monotonic() + (0.1 if busy else delay / 1000)
            while time.monotonic() < until:
                if cancelled():
                    raise NapCatQQMediaStageError("media_cancelled")
                time.sleep(min(0.1, max(0, until - time.monotonic())))

    def snapshot_client(self, snapshot_root: str | Path) -> QQDirectSnapshotRuntimeClient:
        def transport(url: str, body: bytes, timeout: float) -> tuple[int, str]:
            try:
                return self._request(url, body, timeout)
            except NapCatQQError:
                raise QQSnapshotRuntimeUnavailable() from None
        return QQDirectSnapshotRuntimeClient(
            self._base_url,
            snapshot_root=snapshot_root,
            timeout=self._timeout,
            transport=transport if self._transport is not None else None,
            credential=self._credential_source,
            runtime_id=self._runtime_id,
            boot_id=self._boot_id,
        )
