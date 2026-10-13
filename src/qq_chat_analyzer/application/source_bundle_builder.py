"""Own admission to an inert production source constructor, not its services."""
from threading import Lock

from .shutdown_models import ShutdownStatus


class SourceBundleBuilder:
    """Factory contract: construction itself owns no resources before __call__.

    Only the composition root wraps known inert factories. Once invoked, its
    services require their own evidence; unpublished/in-flight work is UNKNOWN.
    This does not certify arbitrary externally supplied callable builders.
    """
    def __init__(self, factory, *, setup_reader=None):
        self._factory = factory
        self._setup_reader = setup_reader
        self._lock = Lock()
        self._used = False
        self._closing = False

    def __call__(self):
        with self._lock:
            if self._closing:
                raise RuntimeError('Source construction is closed')
            self._used = True
        return self._factory()

    @property
    def is_unused(self) -> bool:
        with self._lock:
            return not self._used and not self._closing

    @property
    def has_setup_reader(self):
        return self._setup_reader is not None

    def read_setup_status(self):
        """Read configuration only, serialized with sealing; no source build."""
        with self._lock:
            if self._closing or self._setup_reader is None:
                raise RuntimeError('Source metadata query is unavailable')
            return self._setup_reader()

    def shutdown(self) -> ShutdownStatus:
        with self._lock:
            self._closing = True
            return ShutdownStatus.UNKNOWN if self._used else ShutdownStatus.SUCCESS
