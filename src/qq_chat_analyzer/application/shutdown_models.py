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


_UPDATE_REQUIRED_STEPS = frozenset({
    'direct_db_cleanup', 'retained_output_cleanup', 'qq_runtime_termination',
    'source_lifecycle', 'gui_workers',
})


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    steps: tuple[ShutdownStepResult, ...] = ()

    @property
    def status(self) -> ShutdownStatus:
        """Aggregate supplied evidence, without claiming it is complete."""
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
        """Require each desktop shutdown proof exactly once, all successful.

        This is shutdown admission only; the caller must still stop producers
        before collecting evidence. Source lifecycle gaps remain UNKNOWN.
        """
        names = tuple(step.name for step in self.steps)
        return (
            self.status is ShutdownStatus.SUCCESS
            and len(names) == len(_UPDATE_REQUIRED_STEPS)
            and frozenset(names) == _UPDATE_REQUIRED_STEPS
        )
