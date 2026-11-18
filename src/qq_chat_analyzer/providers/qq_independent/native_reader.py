"""Read-only SQL adapter for the QQ-layout engine inside the owned worker."""

from __future__ import annotations

import ctypes as c
from collections.abc import Mapping
from contextlib import closing
import os
from pathlib import Path
import re
import sqlite3

from .files import SourceError, _file, _format, _identity, _no_sidecars
from .snapshot import _read_locked


_HANDLE = c.c_void_p
_STATUS = c.c_int
_PROGRESS = c.CFUNCTYPE(c.c_int, c.c_void_p)
_TRANSIENT = c.c_void_p(-1)
_FILES = {'message':'nt_msg.db', 'group_info':'group_info.db', 'profile_info':'profile_info.db'}


class Originals:
    """Bind the three opened files to their pathname identities for one worker."""

    def __init__(self, account_directory, lifetime):
        self._files = {}
        for role, filename in _FILES.items():
            path = account_directory / 'nt_qq' / 'nt_db' / filename
            _no_sidecars(path)
            named = _identity(_file(path))
            limit = 5 * 1024**3 + 64 * 1024 if role == 'message' else 32 * 1024**2
            if not 5120 <= named[2] <= limit:
                raise SourceError('full_snapshot_size_limit' if role == 'message' else 'metadata_snapshot_limit')
            stream = lifetime.enter_context(_read_locked(path))
            opened = _identity(os.fstat(stream.fileno()))
            if named[:4] != opened[:4] or _format(stream.read(5120), opened[2]) != 'key_required':
                raise SourceError('snapshot_identity_refused')
            self._files[role] = path, stream, named, opened
        if len({item[2][:2] for item in self._files.values()}) != len(_FILES):
            raise SourceError('snapshot_identity_refused')
        self.recheck()

    def selections(self):
        return [{'role':role, 'path':str(path), 'size':opened[2]}
                for role, (path, _, _, opened) in self._files.items()]

    def recheck(self):
        for path, stream, named, opened in self._files.values():
            _no_sidecars(path)
            if _identity(_file(path)) != named or _identity(os.fstat(stream.fileno())) != opened:
                raise SourceError('snapshot_changed')

    def open_readers(self, dll, receipts, pipe, lifetime, cancelled):
        if not isinstance(receipts, list) or len(receipts) != len(_FILES):
            raise SourceError('authentication_unconfirmed')
        self.recheck()
        keys = bytearray(32 * len(_FILES) + 1)
        try:
            used = 0
            with memoryview(keys) as raw:
                while used < len(raw) and (count := pipe.readinto(raw[used:])):
                    used += count
                if used != 32 * len(_FILES):
                    raise SourceError('authentication_unconfirmed')
                databases = {}
                for i, ((role, (path, _, _, opened)), receipt) in enumerate(zip(self._files.items(), receipts)):
                    if (not isinstance(receipt, dict) or receipt.get('bytes') != opened[2] or
                            type(receipt.get('pages')) is not int or not 0 < receipt['pages'] <= (opened[2]-1024)//4096 or
                            not re.fullmatch(r'[a-f0-9]{64}', str(receipt.get('sha256')))):
                        raise SourceError('authentication_unconfirmed')
                    with raw[i*32:(i+1)*32] as key:
                        database = lifetime.enter_context(closing(Database(dll, path, key, cancelled)))
                        key[:] = bytes(32)
                    if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                        raise SourceError('sqlite_integrity_failed')
                    databases[role] = path, database
        finally:
            keys[:] = bytes(len(keys))
        self.recheck()
        return databases


def _check(code):
    if code:
        error = sqlite3.DatabaseError("QQ native database read failed.")
        error.sqlite_errorcode = code
        raise error


def load_reader(path: Path):
    """Load an already verified app-local DLL with restricted dependency lookup."""
    dll = c.CDLL(str(path), winmode=0x0900)  # DLL load directory and System32 only.
    signatures = {
        'echo_qq_open': (_STATUS, c.c_char_p, _HANDLE, c.POINTER(_HANDLE)),
        'echo_qq_prepare': (_STATUS, _HANDLE, c.c_char_p, c.POINTER(_HANDLE)),
        'sqlite3_close': (_STATUS, _HANDLE),
        'sqlite3_finalize': (_STATUS, _HANDLE),
        'sqlite3_step': (_STATUS, _HANDLE),
        'sqlite3_progress_handler': (None, _HANDLE, c.c_int, _PROGRESS, _HANDLE),
        'sqlite3_bind_parameter_count': (c.c_int, _HANDLE),
        'sqlite3_bind_parameter_name': (c.c_char_p, _HANDLE, c.c_int),
        'sqlite3_bind_null': (_STATUS, _HANDLE, c.c_int),
        'sqlite3_bind_int64': (_STATUS, _HANDLE, c.c_int, c.c_int64),
        'sqlite3_bind_double': (_STATUS, _HANDLE, c.c_int, c.c_double),
        'sqlite3_bind_text': (_STATUS, _HANDLE, c.c_int, c.c_char_p, c.c_int, _HANDLE),
        'sqlite3_column_count': (c.c_int, _HANDLE),
        'sqlite3_column_name': (c.c_char_p, _HANDLE, c.c_int),
        'sqlite3_column_type': (c.c_int, _HANDLE, c.c_int),
        'sqlite3_column_int64': (c.c_int64, _HANDLE, c.c_int),
        'sqlite3_column_double': (c.c_double, _HANDLE, c.c_int),
        'sqlite3_column_text': (_HANDLE, _HANDLE, c.c_int),
        'sqlite3_column_blob': (_HANDLE, _HANDLE, c.c_int),
        'sqlite3_column_bytes': (c.c_int, _HANDLE, c.c_int),
    }
    for name, (result, *arguments) in signatures.items():
        symbol = getattr(dll, name)
        symbol.restype = result
        symbol.argtypes = arguments
    return dll


class Database:
    """One guarded original. Its caller keeps the source lock for its lifetime."""

    def __init__(self, dll, path: Path, key: bytearray, cancelled):
        if len(key) != 32 or not path.is_absolute():
            raise ValueError('Invalid QQ reader input.')
        self._dll = dll
        self._db = _HANDLE()
        self._cursors = set()
        self._progress = None
        self._cancelled = cancelled
        uri = (path.as_uri() + '?mode=ro&immutable=1&qq_prefix=1').encode('utf-8')
        view = (c.c_ubyte * 32).from_buffer(key)
        _check(dll.echo_qq_open(uri, view, c.byref(self._db)))
        self.set_progress_handler(lambda: False, 10000)

    def set_progress_handler(self, cancelled, steps):
        @_PROGRESS
        def progress(_):
            try:
                return int(bool(self._cancelled() or cancelled()))
            except Exception:
                return 1

        self._dll.sqlite3_progress_handler(self._db, steps, progress, None)
        self._progress = progress

    def execute(self, sql, parameters=()):
        if not self._db or self._cancelled() or '\x00' in sql:
            raise sqlite3.DatabaseError('QQ native statement unavailable.')
        statement = _HANDLE()
        _check(self._dll.echo_qq_prepare(self._db, sql.encode('utf-8'), c.byref(statement)))
        try:
            count = self._dll.sqlite3_bind_parameter_count(statement)
            if count != len(parameters):
                raise sqlite3.ProgrammingError('Invalid QQ native parameter count.')
            if isinstance(parameters, Mapping):
                names = [self._dll.sqlite3_bind_parameter_name(statement, i) for i in range(1, count + 1)]
                if any(not name or name[1:].decode('utf-8') not in parameters for name in names):
                    raise sqlite3.ProgrammingError('Invalid QQ native parameter name.')
                parameters = [parameters[name[1:].decode('utf-8')] for name in names]
            for index, value in enumerate(parameters, 1):
                if value is None:
                    code = self._dll.sqlite3_bind_null(statement, index)
                elif isinstance(value, str):
                    encoded = value.encode('utf-8')
                    code = self._dll.sqlite3_bind_text(statement, index, encoded, len(encoded), _TRANSIENT)
                elif isinstance(value, int) and -(1 << 63) <= value < (1 << 63):
                    code = self._dll.sqlite3_bind_int64(statement, index, value)
                elif isinstance(value, float):
                    code = self._dll.sqlite3_bind_double(statement, index, value)
                else:
                    raise sqlite3.ProgrammingError('Invalid QQ native parameter type.')
                _check(code)
            cursor = _Cursor(self, statement)
        except BaseException:
            self._dll.sqlite3_finalize(statement)
            raise
        self._cursors.add(cursor)
        return cursor

    def close(self):
        if self._db:
            for cursor in tuple(self._cursors):
                cursor.close()
            _check(self._dll.sqlite3_close(self._db))
            self._db = _HANDLE()
            self._progress = None


class _Cursor:
    def __init__(self, database, statement):
        self._database = database
        self._dll = database._dll
        self._statement = statement
        self.description = tuple((self._dll.sqlite3_column_name(statement, i).decode('utf-8'),)
                                 for i in range(self._dll.sqlite3_column_count(statement)))

    def _column(self, index):
        dll, statement = self._dll, self._statement
        kind = dll.sqlite3_column_type(statement, index)
        if kind == 1:
            return dll.sqlite3_column_int64(statement, index)
        if kind == 2:
            return dll.sqlite3_column_double(statement, index)
        if kind in (3, 4):
            pointer = (dll.sqlite3_column_text if kind == 3 else dll.sqlite3_column_blob)(statement, index)
            data = c.string_at(pointer, dll.sqlite3_column_bytes(statement, index))
            return data.decode('utf-8') if kind == 3 else data
        return None

    def fetchone(self):
        if not self._statement:
            return None
        code = self._dll.sqlite3_step(self._statement)
        if code == 100:
            return tuple(self._column(i) for i in range(len(self.description)))
        self.close()
        if code != 101:
            _check(code)
        return None

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def fetchall(self):
        return list(self)

    def close(self):
        if self._statement:
            self._dll.sqlite3_finalize(self._statement)
            self._statement = _HANDLE()
            self._database._cursors.discard(self)
