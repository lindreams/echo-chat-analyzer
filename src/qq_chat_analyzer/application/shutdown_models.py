"""Resource evidence for shutdown; task completion alone never permits updates."""
from dataclasses import dataclass
from enum import Enum


class ShutdownStatus(Enum):
    SUCCESS = 'success'
    FAILED = 'failed'
    TIMED_OUT = 'timed_out'
    UNKNOWN = 'unknown'


@dataclass(frozen=True, slots=True)
class ShutdownStepResult:
    name: str
    status: ShutdownStatus


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    steps: tuple[ShutdownStepResult, ...] = ()

    @property
    def status(self) -> ShutdownStatus:
        if not self.steps:
            return ShutdownStatus.UNKNOWN
        for status in (ShutdownStatus.FAILED, ShutdownStatus.TIMED_OUT,
                       ShutdownStatus.UNKNOWN):
            if any(step.status is status for step in self.steps):
                return status
        if all(step.status is ShutdownStatus.SUCCESS for step in self.steps):
            return ShutdownStatus.SUCCESS
        return ShutdownStatus.UNKNOWN

    @property
    def can_apply_update(self) -> bool:
        return self.status is ShutdownStatus.SUCCESS
