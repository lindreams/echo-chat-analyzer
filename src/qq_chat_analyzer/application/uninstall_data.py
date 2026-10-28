"""Windows uninstall cleanup of fixed Echo assets, without following user paths.

Keep ancestors open without delete sharing. Delete the verified object through
its handle, never a subsequently resolved pathname. Unknown assets stay put and
make cleanup incomplete; ownership proofs are removed after their data.
"""
from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import threading

_HELD = threading.local()


class CleanupIncomplete(Exception):
    """No path, chat content or credential escapes the cleanup boundary."""


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
               ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
               ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
               ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
               ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


class _Object:
    def __init__(self, path, *, delete=False, write=False):
        self.path = path
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        for name in ('CloseHandle', 'GetFileInformationByHandle', 'SetFileInformationByHandle',
                     'ReadFile', 'WriteFile', 'SetFilePointer', 'SetEndOfFile', 'FlushFileBuffers'):
            getattr(self.kernel, name).argtypes = [wintypes.HANDLE] + {
                'CloseHandle': [], 'GetFileInformationByHandle': [ctypes.POINTER(_FileInfo)],
                'SetFileInformationByHandle': [ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                'ReadFile': [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p],
                'WriteFile': [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p],
                'SetFilePointer': [wintypes.LONG, ctypes.c_void_p, wintypes.DWORD],
                'SetEndOfFile': [], 'FlushFileBuffers': [],
            }[name]
        self.kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                                          wintypes.DWORD, wintypes.DWORD]
        access = 0x80 | (0x10000 if delete else 0) | (0xC0000000 if write else 0)
        # Backup semantics + OPEN_REPARSE_POINT; no delete sharing, no following
        # a last-component junction. Ancestors are pinned by _pinned below.
        self.handle = self.kernel.CreateFileW(str(path), access, 3 if not write else 1,
                                              None, 3, 0x02200000, None)
        if self.handle == wintypes.HANDLE(-1).value:
            self.handle = None
            raise CleanupIncomplete()
        try:
            info = _FileInfo()
            buffer = ctypes.create_unicode_buffer(32768)
            size = self.kernel.GetFinalPathNameByHandleW(self.handle, buffer, len(buffer), 0)
            if (not self.kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info))
                    or info.attributes & 0x400 or not size or size >= len(buffer)
                    or Path(buffer.value.removeprefix('\\\\?\\')) != path):
                raise CleanupIncomplete()
            self.directory = bool(info.attributes & 0x10)
            if not self.directory and info.links != 1:
                raise CleanupIncomplete()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def remove(self):
        disposition = wintypes.BOOL(True)
        if not self.kernel.SetFileInformationByHandle(self.handle, 4, ctypes.byref(disposition),
                                                     ctypes.sizeof(disposition)):
            raise CleanupIncomplete()

    def read_bytes(self):
        if self.directory:
            raise CleanupIncomplete()
        buffer, count = ctypes.create_string_buffer(65537), wintypes.DWORD()
        if (not self.kernel.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None)
                or count.value > 65536):
            raise CleanupIncomplete()
        return buffer.raw[:count.value]

    def read_json(self):
        return json.loads(self.read_bytes())

    def write_json(self, value):
        body = json.dumps(value, ensure_ascii=True, indent=2).encode('utf-8')
        count = wintypes.DWORD()
        self.kernel.SetFilePointer(self.handle, 0, None, 0)
        if (not self.kernel.WriteFile(self.handle, body, len(body), ctypes.byref(count), None)
                or count.value != len(body) or not self.kernel.SetEndOfFile(self.handle)
                or not self.kernel.FlushFileBuffers(self.handle)):
            raise CleanupIncomplete()

    @contextmanager
    def stream(self):
        """Borrow a duplicate handle for the existing staging lease/proof API."""
        import msvcrt
        process = self.kernel.GetCurrentProcess
        process.restype = wintypes.HANDLE
        duplicate = self.kernel.DuplicateHandle
        duplicate.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                              ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = wintypes.HANDLE()
        if not duplicate(process(), self.handle, process(), ctypes.byref(handle), 0, False, 2):
            raise CleanupIncomplete()
        try:
            descriptor = msvcrt.open_osfhandle(handle.value, os.O_RDWR | os.O_BINARY)
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise
        with os.fdopen(descriptor, 'r+b') as stream:
            yield stream


@contextmanager
def _pinned(path, **options):
    path = Path(path).absolute()
    if os.name != 'nt' or path.drive.startswith('\\\\') or '..' in path.parts:
        raise CleanupIncomplete()
    held = getattr(_HELD, 'paths', None)
    if held is None:
        held = _HELD.paths = {}
    with ExitStack() as stack:
        for current in (*reversed(path.parents), path):
            if current in held:
                continue
            item = _Object(current, **options if current == path else {})
            held[current] = item
            stack.callback(held.pop, current)
            stack.callback(item.close)
            if current != path and not item.directory:
                raise CleanupIncomplete()
        yield held[path]


def _delete(path):
    with _pinned(path, delete=True) as item:
        if item.directory:
            _delete_children(path)
        item.remove()


def _delete_children(path):
    for child in sorted(path.iterdir(), key=lambda p: p.name):
        _delete(child)


def _json(path):
    with _pinned(path, write=True) as item:
        return item.read_json()


def _identity(path):
    info = path.stat()
    return [info.st_dev, info.st_ino]


def _report_staging(root):
    from .report_staging import _MARKER_NAME, _read_proof, _try_lock, _ARTIFACTS
    from ..media_content import MEDIA_FILE_NAME
    for marker in root.iterdir():
        if not _MARKER_NAME.fullmatch(marker.name):
            continue
        with _pinned(marker, write=True, delete=True) as proof_file:
            with proof_file.stream() as stream:
                if not _try_lock(stream):
                    raise CleanupIncomplete()
                staging, proof = _read_proof(root, marker, stream)
                if os.path.lexists(staging):
                    with _pinned(staging, delete=True) as owned:
                        if not owned.directory or _identity(staging) != proof['directory_identity']:
                            raise CleanupIncomplete()
                        for child in staging.iterdir():
                            if child.name in _ARTIFACTS:
                                with _pinned(child) as artifact:
                                    if artifact.directory:
                                        raise CleanupIncomplete()
                            elif child.name == 'media':
                                with _pinned(child) as media:
                                    if not media.directory:
                                        raise CleanupIncomplete()
                                    for asset in child.iterdir():
                                        if not MEDIA_FILE_NAME.fullmatch(asset.name):
                                            raise CleanupIncomplete()
                            else:
                                raise CleanupIncomplete()
                        _delete_children(staging)
                        owned.remove()
                proof_file.remove()


def _runtime(root):
    """Use the QQ owning layer's identity-bound workspace proofs."""
    from .qq.qq_runtime_workspace import _owned, _owner_proof, _LOCK_HEADER
    if not os.path.lexists(root):
        return
    with _pinned(root):
        for marker in sorted(root.glob('*.owner.json')):
            name = marker.name.removesuffix('.owner.json')
            component = name.removeprefix('.').removesuffix('.staging')
            if not re.fullmatch('[0-9a-f]{64}', component):
                raise CleanupIncomplete()
            directory = root / name
            with _pinned(marker, write=True):
                validated = _owner_proof(root, marker, component)
                if os.path.lexists(directory):
                    with _pinned(directory, delete=True) as owned:
                        _owned(root, directory, marker, component)
                        _delete_children(directory)
                        owned.remove()
            with _pinned(marker, write=True, delete=True) as proof:
                if (proof.read_json() != validated
                        or _identity(marker) != validated['marker_identity']):
                    raise CleanupIncomplete()
                proof.remove()
        for child in root.iterdir():
            if re.fullmatch(r'\.[0-9a-f]{64}\.prepare\.lock', child.name):
                # The preparer's OS lease must have been released.
                with _pinned(child, write=True, delete=True) as lease:
                    if lease.read_bytes() != _LOCK_HEADER:
                        raise CleanupIncomplete()
                    lease.remove()
            else:
                raise CleanupIncomplete()


def _snapshots(root):
    """Offline verification of the snapshot workspace's published ownership.

    Uses workspace.mjs' exact owner/manifest/file contracts. Never opens a
    database, asks QQ for a key, or invokes a helper during uninstall.
    """
    if not os.path.lexists(root):
        return
    with _pinned(root):
        if not any(root.iterdir()):
            return
        owner = {'kind': 'echo-qq-snapshot', 'version': 1}
        marker = _json(root / 'owner.json')
        if marker != owner or type(marker.get('version')) is not int:
            raise CleanupIncomplete()
        # The live snapshot owner uses FileShare.None; our lease open fails
        # closed while it is still held. Keep it pinned throughout cleanup.
        lease = root / 'lease.lock'
        if not os.path.lexists(lease):
            if {child.name for child in root.iterdir()} != {'owner.json'}:
                raise CleanupIncomplete()
            _delete(root / 'owner.json')
            return
        with _pinned(lease, write=True, delete=True) as lease_file:
            for child in root.iterdir():
                if child.name in ('owner.json', 'lease.lock'):
                    continue
                if child.name == 'generations':
                    with _pinned(child):
                        for generation in child.iterdir():
                            _snapshot_directory(generation, 'generation', owner)
                    _delete(child)
                elif child.name in ('staging', 'decrypted'):
                    _snapshot_directory(child, child.name, owner)
                else:
                    raise CleanupIncomplete()
            lease_file.remove()
        _delete(root / 'owner.json')


def _snapshot_directory(directory, kind, owner):
    with _pinned(directory, delete=True) as item:
        if not item.directory:
            raise CleanupIncomplete()
        children = list(directory.iterdir())
        if children and kind != 'decrypted':
            if os.path.lexists(directory / 'owner.json'):
                marker = _json(directory / 'owner.json')
                if marker != owner or type(marker.get('version')) is not int:
                    raise CleanupIncomplete()
            else:
                manifest = _json(directory / 'manifest.json')
                if (kind != 'generation' or type(manifest.get('schema_version')) is not int
                        or manifest.get('schema_version') != 1
                        or manifest.get('generation_id') != directory.name
                        or manifest.get('state') != 'ready' or manifest.get('database') != 'snapshot.db'
                        or manifest.get('identity', {}).get('namespace') != 'qq_uin'
                        or not isinstance(manifest.get('identity', {}).get('value'), str)):
                    raise CleanupIncomplete()
        allowed = {'owner.json', 'snapshot.db', 'manifest.json', 'snapshot.db-wal',
                   'snapshot.db-shm', 'snapshot.db-journal'}
        if kind == 'staging':
            allowed.add('merged.db')
        for child in children:
            if kind == 'decrypted':
                valid = child.name == 'self_identity.json' or re.fullmatch(
                    r'nt_msg\.[a-zA-Z0-9_-]+\.plaintext\.db(?:-(?:wal|shm|journal))?', child.name)
            else:
                valid = child.name in allowed
            with _pinned(child) as entry:
                if not valid or entry.directory:
                    raise CleanupIncomplete()
        # Keep proof for a retry after an interrupted/partially failed delete.
        for child in sorted(children, key=lambda p: p.name in ('owner.json', 'manifest.json')):
            _delete(child)
        item.remove()


def cleanup_local_data(root: Path, *, purge: bool) -> None:
    """Return only if all selected owned data was cleared; never log contents."""
    if type(purge) is not bool:
        raise CleanupIncomplete()
    root = Path(root).absolute()
    if not os.path.lexists(root):
        return
    try:
        with _pinned(root):
            if any(child.name not in {'config', 'runtime', 'transient', 'logs', 'reports',
                                       'update-check.json'} for child in root.iterdir()):
                raise CleanupIncomplete()
            config = root / 'config'
            if os.path.lexists(config):
                with _pinned(config) as settings:
                    if not settings.directory or any(child.name not in {'qq.json', 'wechat.json'}
                                                      for child in config.iterdir()):
                        raise CleanupIncomplete()
            for name, fields in (
                ('wechat.json', ('data_root', 'wcdb_cli_path', 'wcdb_dll_path', 'sticker_media_roots')),
                ('qq.json', ('qq_install_path', 'runtime_directory', 'runtime_mode', 'version',
                             'qq_install_path_explicit')),
            ):
                path = root / 'config' / name
                if os.path.lexists(path):
                    if purge:
                        _delete(path)
                    else:
                        with _pinned(path, write=True) as item:
                            saved = item.read_json()
                            if not isinstance(saved, dict):
                                raise CleanupIncomplete()
                            item.write_json({key: saved[key] for key in fields if key in saved})
            _runtime(root / 'runtime' / 'qq')
            transient = root / 'transient'
            if os.path.lexists(transient):
                with _pinned(transient):
                    _snapshots(transient / 'qq-direct-db')
                    for child in transient.iterdir():
                        if re.fullmatch('chat-analyzer-output-[0-9a-f]{8}', child.name):
                            _delete(child)
                        elif child.name == 'qq-direct-db' and not any(child.iterdir()):
                            _delete(child)
                        else:
                            raise CleanupIncomplete()
            logs = root / 'logs'
            if os.path.lexists(logs):
                with _pinned(logs):
                    for child in logs.iterdir():
                        if not re.fullmatch(r'echo\.log(?:\.[0-9]+)?|wcdb-diagnostic\.txt', child.name):
                            raise CleanupIncomplete()
                        _delete(child)
            if os.path.lexists(root / 'update-check.json'):
                _delete(root / 'update-check.json')
            reports = root / 'reports'
            if os.path.lexists(reports):
                from .report_package_catalog import _is_package_name
                with _pinned(reports):
                    _report_staging(reports)
                    if purge:
                        for child in reports.iterdir():
                            if not _is_package_name(child.name):
                                raise CleanupIncomplete()
                            _delete(child)
            # Preserve unknown entries. In purge mode, empty owned containers
            # may go, but an unrecognized file is never implicitly consented to.
            if purge:
                for name in ('config', 'runtime/qq', 'runtime', 'transient', 'logs', 'reports'):
                    path = root / name
                    if os.path.lexists(path):
                        with _pinned(path, delete=True) as item:
                            if not item.directory or any(path.iterdir()):
                                raise CleanupIncomplete()
                            item.remove()
                if any(root.iterdir()):
                    raise CleanupIncomplete()
    except Exception:
        raise CleanupIncomplete() from None
