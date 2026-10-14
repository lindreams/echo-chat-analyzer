"""Deterministic update admission only; no OS witnesses or updater launcher.

Witness records are assertions supplied by an explicitly injected owner, not
authentication. A future Windows implementation must acquire and retain real
handles, guards and leases. Constructing these records (or passing True) does
not establish that a process exited or that a file is trustworthy.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import math
import re
import secrets
from threading import Lock
from typing import Callable, Protocol

from .update_check_service import _parse_version


class BrokerState(Enum):
    NEW = 'new'
    READY = 'ready'
    GO = 'go'
    ARMED = 'armed'
    APPLY_APPROVED = 'apply_approved'
    REJECTED = 'rejected'


class Verification(Enum):
    VERIFIED = 'verified'
    UNKNOWN = 'unknown'
    FAILED = 'failed'


class LeaseStatus(Enum):
    PREPARED = 'prepared'
    HELD = 'held'


class PermitStatus(Enum):
    ACTIVE = 'active'
    REVOKED = 'revoked'


class WaitStatus(Enum):
    EXITED = 'exited'
    FAILED = 'failed'
    TIMED_OUT = 'timed_out'


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    created_at: int
    image: str


@dataclass(frozen=True, slots=True)
class OwnerWitness:
    identity: ProcessIdentity
    handle: object


@dataclass(frozen=True, slots=True)
class InstallationIdentity:
    root: str
    package_id: str
    channel: str
    version: str
    updater_sha256: str


@dataclass(frozen=True, slots=True)
class PackageIdentity:
    package_id: str
    channel: str
    version: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AdmissionEvidence:
    installation: InstallationIdentity
    package: PackageIdentity
    plain_paths: Verification
    package_guard: Verification
    conflicts: Verification
    lease: LeaseStatus


@dataclass(frozen=True, slots=True)
class ExitPermit:
    owner: ProcessIdentity
    authorization: str
    status: PermitStatus


@dataclass(frozen=True, slots=True)
class OwnerExit:
    owner: OwnerWitness
    status: WaitStatus
    exit_code: int | None


class WitnessSource(Protocol):
    """Calls must respect the same absolute monotonic deadline.

    inspect('initial'/'armed') reports a prepared lease; inspect('final') must
    report an exclusive held lease. Guards stay owned across these calls.
    The synchronous core detects late returns; it cannot interrupt a blocking
    implementation. Missing/unreadable observations must return None or raise.
    """
    def capture_owner(self, expected: ProcessIdentity, deadline: float) -> OwnerWitness | None: ...
    def inspect(self, phase: str, deadline: float) -> AdmissionEvidence | None: ...
    def exit_permit(self, deadline: float) -> ExitPermit | None: ...
    def wait_owner(self, owner: OwnerWitness, deadline: float) -> OwnerExit | None: ...


class HandoffAuthorization:
    """One in-memory grant, shared by all exchanges using this authorization.

    No raw token is retained. This is replay bookkeeping, not a token issuer
    or authentication boundary; copying a token into a new grant is not safe.
    """
    def __init__(self, token: str):
        if type(token) is not str or not token:
            raise ValueError('A nonempty authorization token is required')
        self._digest = self._hash(token)
        self._available = True
        self._lock = Lock()

    @staticmethod
    def _hash(token: str) -> bytes:
        return hashlib.sha256(token.encode('utf-8')).digest()

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available

    def _matches(self, token: str) -> bool:
        with self._lock:
            return (type(token) is str and self._digest is not None
                    and secrets.compare_digest(self._digest, self._hash(token)))

    def _consume(self, token: str) -> bool:
        with self._lock:
            matched = (self._available and type(token) is str and self._digest is not None
                       and secrets.compare_digest(self._digest, self._hash(token)))
            self._available = False
            return matched

    def _revoke(self) -> None:
        with self._lock:
            self._available = False
            self._digest = None


class _Denied(Exception):
    """Fixed diagnostic codes only; external exception text never escapes."""


class UpdateBroker:
    """Single exchange with a fixed deadline and a terminal rejection latch.

    apply_recorder is an injected side-effect boundary, with no default or
    production caller. APPLY_APPROVED means admission and recorder completion,
    never that Windows installed or restarted anything. Duplicate calls reject
    even after approval; they cannot undo or repeat an already attempted apply.
    """
    def __init__(self, *, owner: ProcessIdentity, installation: InstallationIdentity,
                 package: PackageIdentity, authorization: HandoffAuthorization,
                 witnesses: WitnessSource, deadline: float, clock: Callable[[], float],
                 apply_recorder: Callable[[PackageIdentity], None]):
        self._state = BrokerState.NEW
        self._reason: str | None = None
        self._expected_owner = owner
        self._installation, self._package = installation, package
        self._authorization = authorization
        self._witnesses = witnesses
        self._deadline, self._clock = deadline, clock
        self._recorder = apply_recorder
        self._owner: OwnerWitness | None = None
        self._last_time: float | None = None
        self._operation = Lock()
        self._apply_attempted = False

    @property
    def state(self) -> BrokerState:
        return self._state

    @property
    def reason(self) -> str | None:
        return self._reason

    def _reject(self, reason: str) -> BrokerState:
        if self._state is not BrokerState.REJECTED:
            self._reason = reason
        self._state = BrokerState.REJECTED
        self._authorization._revoke()
        return self._state

    def _begin(self, expected: BrokerState) -> bool:
        if not self._operation.acquire(blocking=False):
            self._reject('out_of_order')
            return False
        if self._state is not expected:
            self._reject('out_of_order')
            self._operation.release()
            return False
        return True

    def _checkpoint(self, expected: BrokerState) -> None:
        if self._state is not expected:
            raise _Denied('out_of_order')
        now = self._clock()
        if self._state is not expected:
            raise _Denied('out_of_order')
        if (type(now) not in (int, float) or not math.isfinite(now)
                or type(self._deadline) not in (int, float) or not math.isfinite(self._deadline)
                or (self._last_time is not None and now < self._last_time)):
            raise _Denied('invalid_clock')
        self._last_time = now
        if now >= self._deadline:
            raise _Denied('deadline_expired')

    def _admission(self, phase: str, state: BrokerState) -> None:
        self._checkpoint(state)
        evidence = self._witnesses.inspect(phase, self._deadline)
        self._checkpoint(state)
        if (type(evidence) is not AdmissionEvidence
                or type(evidence.installation) is not InstallationIdentity
                or type(evidence.package) is not PackageIdentity
                or evidence.installation != self._installation
                or evidence.package != self._package
                or evidence.plain_paths is not Verification.VERIFIED
                or evidence.package_guard is not Verification.VERIFIED
                or evidence.conflicts is not Verification.VERIFIED
                or evidence.lease is not (LeaseStatus.HELD if phase == 'final' else LeaseStatus.PREPARED)):
            raise _Denied('admission_evidence')

    def _permit(self, state: BrokerState) -> None:
        self._checkpoint(state)
        permit = self._witnesses.exit_permit(self._deadline)
        self._checkpoint(state)
        if (type(permit) is not ExitPermit or permit.owner != self._expected_owner
                or permit.status is not PermitStatus.ACTIVE
                or not self._authorization._matches(permit.authorization)):
            raise _Denied('exit_permission')

    def _failure(self, error: BaseException) -> BrokerState:
        return self._reject(str(error) if isinstance(error, _Denied) else 'witness_error')

    def _validate_expected(self) -> None:
        owner, installation, package = self._expected_owner, self._installation, self._package
        if (type(owner) is not ProcessIdentity or type(owner.pid) is not int or owner.pid <= 0
                or type(owner.created_at) is not int or owner.created_at <= 0
                or type(installation) is not InstallationIdentity or type(package) is not PackageIdentity):
            raise _Denied('invalid_identity')
        if any(type(value) is not str or not value for value in (
                owner.image, installation.root, installation.package_id, installation.channel,
                installation.version, package.package_id, package.channel, package.version, package.path)):
            raise _Denied('invalid_identity')
        if (any(type(value) is not str or re.fullmatch(r'[a-f0-9]{64}', value) is None
                for value in (installation.updater_sha256, package.sha256))
                or type(package.size) is not int or package.size <= 0
                or (package.package_id, package.channel) != (installation.package_id, installation.channel)
                or _parse_version(package.version)[0] <= _parse_version(installation.version)[0]):
            raise _Denied('invalid_identity')

    def ready(self) -> BrokerState:
        if not self._begin(BrokerState.NEW):
            return self.state
        try:
            self._checkpoint(BrokerState.NEW)
            self._validate_expected()
            if not self._authorization.available:
                raise _Denied('authorization_used')
            owner = self._witnesses.capture_owner(self._expected_owner, self._deadline)
            self._checkpoint(BrokerState.NEW)
            if (type(owner) is not OwnerWitness or owner.identity != self._expected_owner
                    or owner.handle is None or isinstance(owner.handle, bool)):
                raise _Denied('owner_identity')
            self._owner = owner
            self._admission('initial', BrokerState.NEW)
            self._state = BrokerState.READY
        except BaseException as error:
            self._failure(error)
        finally:
            self._operation.release()
        return self.state

    def go(self, token: str) -> BrokerState:
        if not self._begin(BrokerState.READY):
            return self.state
        try:
            self._checkpoint(BrokerState.READY)
            if not self._authorization._consume(token):
                raise _Denied('authorization_invalid')
            self._state = BrokerState.GO
        except BaseException as error:
            self._failure(error)
        finally:
            self._operation.release()
        return self.state

    def arm(self) -> BrokerState:
        if not self._begin(BrokerState.GO):
            return self.state
        try:
            self._admission('armed', BrokerState.GO)
            self._permit(BrokerState.GO)
            self._state = BrokerState.ARMED
        except BaseException as error:
            self._failure(error)
        finally:
            self._operation.release()
        return self.state

    def approve(self) -> BrokerState:
        if not self._begin(BrokerState.ARMED):
            return self.state
        try:
            self._checkpoint(BrokerState.ARMED)
            exit_evidence = self._witnesses.wait_owner(self._owner, self._deadline)
            self._checkpoint(BrokerState.ARMED)
            if (type(exit_evidence) is not OwnerExit
                    or type(exit_evidence.owner) is not OwnerWitness
                    or exit_evidence.owner.identity != self._expected_owner
                    or exit_evidence.owner.handle is not self._owner.handle
                    or exit_evidence.status is not WaitStatus.EXITED
                    or type(exit_evidence.exit_code) is not int or exit_evidence.exit_code != 0):
                raise _Denied('owner_exit')
            self._admission('final', BrokerState.ARMED)
            self._permit(BrokerState.ARMED)
            self._checkpoint(BrokerState.ARMED)
            if self._apply_attempted:
                raise _Denied('apply_already_attempted')
            self._apply_attempted = True  # Before side effects, including exceptions/reentry.
            try:
                self._recorder(self._package)
            except BaseException:
                raise _Denied('apply_error') from None
            if self._state is not BrokerState.ARMED:
                raise _Denied('out_of_order')
            self._state = BrokerState.APPLY_APPROVED
        except BaseException as error:
            self._failure(error)
        finally:
            self._operation.release()
        return self.state
