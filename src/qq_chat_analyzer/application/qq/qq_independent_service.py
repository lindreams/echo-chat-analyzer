"""Product owner of one explicitly selected, independent QQ group acquisition."""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

from ...providers.qq_database_provider import QQDatabaseProvider, QQSession, attach_sender_names
from ...providers.qq_independent.files import SourceError, _file, _safe, _no_sidecars
from ...providers.qq_independent.snapshot import prepare, _protect_new_root, _powershell, authorized_group_partition
from ...providers.qq_independent.metadata import scoped_names
from ...providers.qq_independent.process import verified_process, process_creation_ticks
from ...providers.qq_independent.worker import resources_identity, runtime_files, event_api
from ...providers.qq_sqlite_reader import configure_read_connection
from ...qq_db_identity import canonical_qq_uin
from ...resources import user_data_root
from ..connection_models import ConnectionSnapshot, ConnectionState
from ..errors import ApplicationServiceError
from ..shutdown_models import ShutdownStatus
from .qq_runtime_workspace import _lease

_ENV = ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP','MPLCONFIGDIR','XDG_CONFIG_HOME','XDG_CACHE_HOME')
_TTL = 600


class QQIndependentError(ApplicationServiceError):
    def __init__(self, code='qq_independent_failed', message='QQ 读取未完成，请正常退出 QQ 后重新准备。'):
        self.code, self.public_message = code, message
        super().__init__()


@dataclass(frozen=True)
class QQIndependentSelection:
    executable: Path
    account_directory: Path
    account: str
    group: str
    recover_media: bool = True


@dataclass(frozen=True)
class QQIndependentAcquisition:
    payload_path: Path
    self_uin: str
    session: QQSession
    sticker_media_roots: tuple[Path, ...] = ()
    recover_qq_media: bool = True


def _positive(value):
    return isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{4,19}',value) is not None


def _remove_run(root, parent):
    """Only our marker-bound tree and fixed files may be recovered/deleted."""
    _safe(parent); _safe(root)
    marker=root/'owner.json'; _file(marker)
    if root.parent != parent or not re.fullmatch(r'run-[a-f0-9]{32}',root.name):
        raise SourceError('workspace_owner_mismatch')
    proof=json.loads(marker.read_text(encoding='ascii'))
    if proof != {'kind':'echo-qq-independent-v1','root':list((parent.stat().st_dev,parent.stat().st_ino)),
                 'directory':list((root.stat().st_dev,root.stat().st_ino))}:
        raise SourceError('workspace_owner_mismatch')
    allowed={'owner.json','request.json','message.db','group_info.db','profile_info.db','payload.json'}
    for child in root.iterdir():
        _safe(child)
        if child.is_file():
            _file(child)
            if child.name not in allowed: raise SourceError('workspace_unknown_file')
        elif child.is_dir() and child.name in _ENV:
            if any(child.iterdir()): raise SourceError('workspace_unknown_file')
        elif child.is_dir() and re.fullmatch(r'qq-authorized-full-[a-f0-9]{32}',child.name):
            if json.loads((child/'owner.json').read_text()) != {'kind':'echo-qq-full-read','version':1}:
                raise SourceError('workspace_owner_mismatch')
            for item in child.iterdir():
                _file(item)
                if item.name not in {'owner.json','snapshot.json','encrypted.db'}:
                    raise SourceError('workspace_unknown_file')
        else: raise SourceError('workspace_unknown_file')
    # Keep identity proofs until all their sensitive data has been removed.
    # A failed unlink must remain recoverable on the next owned attempt.
    for child in root.iterdir():
        if child.is_dir():
            for item in sorted(child.iterdir(),key=lambda p:p.name=='owner.json'):
                _file(item)
                item.unlink()
            child.rmdir()
        elif child.name!='owner.json':
            _file(child)
            child.unlink()
    marker.unlink()
    root.rmdir()


class QQIndependentService:
    """No QQ launch/kill, no persisted key, one-shot capture and bounded payload."""
    independent = True

    def __init__(self, *, workspace: Path | None = None):
        self._parent=workspace or user_data_root()/'qq-independent'
        self._lock=threading.RLock()
        self._root=None; self._lease=None; self._selection=None; self._frozen=[]
        self._payload=None; self._session=None; self._range=None; self._media=()
        self._cancel=threading.Event(); self._busy=False; self._closing=False
        self._timer=None; self._generation=None; self._generation_handle=None
        self._worker=None; self._worker_reader=None; self._worker_exited=False
        self._state=ConnectionState.DISCONNECTED

    def _cancelled(self, external=lambda:False):
        return self._cancel.is_set() or self._closing or external()

    def prepare(self, selection: QQIndependentSelection, *, cancelled=lambda:False):
        with self._lock:
            if self._busy or self._closing: raise QQIndependentError('qq_independent_busy')
            self._busy=True
        try:
            self._clear()
            if self.runtime_release_status() is not ShutdownStatus.SUCCESS:
                raise QQIndependentError('qq_normal_exit_required','请先正常退出上次读取的 QQ，使组件完全释放。')
            self._cancel.clear()
            if not _positive(selection.account) or not _positive(selection.group):
                raise QQIndependentError('qq_identity_required','请输入正确的 QQ 账号和授权群号。')
            account=_safe(Path(selection.account_directory))
            if account.name != selection.account or not account.is_dir():
                raise QQIndependentError('qq_account_scope_mismatch','请选择以当前 QQ 账号命名的数据目录。')
            image=_safe(Path(selection.executable)); _file(image)
            resources_identity(image); runtime_files()
            self._parent.mkdir(parents=True,exist_ok=True); _safe(self._parent)
            lease=_lease(self._parent/'.independent.lock',0); lease.__enter__(); self._lease=lease
            # The OS lease excludes every other live owner, including cleanup.
            for child in self._parent.iterdir():
                if child.name == '.independent.lock': continue
                _remove_run(child,self._parent)
            root=self._parent/('run-'+uuid4().hex); root.mkdir(); _protect_new_root(root)
            proof={'kind':'echo-qq-independent-v1','root':list((self._parent.stat().st_dev,self._parent.stat().st_ino)),
                   'directory':list((root.stat().st_dev,root.stat().st_ino))}
            (root/'owner.json').write_text(json.dumps(proof),encoding='ascii'); self._root=root
            self._selection=QQIndependentSelection(image,account,selection.account,selection.group,selection.recover_media)
            for role in ('message','group_info','profile_info'):
                if self._cancelled(cancelled): raise QQIndependentError('analysis_cancelled','已取消 QQ 准备。')
                source=account/'nt_qq/nt_db'/('nt_msg.db' if role=='message' else role+'.db')
                frozen=prepare(source,root)
                if role!='message' and frozen['size']>32*1024**2: raise SourceError('metadata_snapshot_limit')
                self._frozen.append({'role':role,'path':frozen['snapshot'],'sha256':frozen['sha256'],
                                     'size':frozen['size'],'output':str(root/(role+'.db'))})
            if self._cancelled(cancelled): raise QQIndependentError('analysis_cancelled','已取消 QQ 准备。')
            self._state=ConnectionState.STARTING
            self._expire_later()
            return self.get_snapshot()
        except QQIndependentError:
            self._clear(); raise
        except Exception:
            self._clear()
            raise QQIndependentError(message='准备未通过：请先正常退出 QQ，检查 54395 版本、账号目录和完整组件。') from None
        finally:
            with self._lock: self._busy=False

    def _expire_later(self):
        if self._timer: self._timer.cancel()
        def expire():
            with self._lock:
                if self._busy: return
                try: self._clear()
                except Exception: self._state=ConnectionState.ERROR
        self._timer=threading.Timer(_TTL,expire); self._timer.daemon=True; self._timer.start()

    def capture(self, *, progress=lambda value:None, cancel_event=None):
        with self._lock:
            if self._busy or self._closing or not self._root or self._payload:
                raise QQIndependentError('qq_independent_not_prepared')
            self._busy=True
        external=cancel_event or threading.Event()
        try:
            self._run_capture(progress,external)
            if self._cancelled(external.is_set): raise QQIndependentError('analysis_cancelled','QQ 读取已取消。')
            progress('正在校验数据库与授权群身份…')
            self._materialize(external.is_set)
            self._state=ConnectionState.CONNECTED; self._expire_later()
            return self.get_snapshot()
        except Exception as error:
            self._state=ConnectionState.ERROR
            self._clear()
            if isinstance(error,QQIndependentError): raise
            raise QQIndependentError() from None
        finally:
            with self._lock: self._busy=False

    def _select_process(self):
        """Explicit installed image only; no login-state or arbitrary memory scan."""
        raw=_powershell("Get-CimInstance Win32_Process -Filter \"Name='QQ.exe'\" | Where-Object { $_.CommandLine -notmatch '--type=' } | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress")
        rows=json.loads(raw) if raw else []
        if isinstance(rows,dict): rows=[rows]
        rows=[row for row in rows if row.get('ExecutablePath') and
              os.path.normcase(row['ExecutablePath'])==os.path.normcase(str(self._selection.executable))]
        if len(rows)!=1:
            raise QQIndependentError('qq_process_selection_required','请打开所选 QQ，停留在登录页面，再点击等待登录。')
        pid=int(rows[0]['ProcessId'])
        with verified_process(pid,self._selection.executable) as (api,handle):
            created=process_creation_ticks(api,handle)
            api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            api.OpenProcess.restype=wintypes.HANDLE
            owned=api.OpenProcess(0x101000,False,pid)  # synchronize + query limited
            if not owned: raise SourceError('process_exit_handle_unavailable')
            try:
                if process_creation_ticks(api,owned)!=created: raise SourceError('process_generation_changed')
            except BaseException:
                api.CloseHandle(owned); raise
            self._generation_handle=(api,owned)
        self._generation=(pid,created,self._selection.executable)
        return pid,created

    def _run_capture(self, progress, external):
        from ...runtime.windows_job import launch_owned_process
        pid,created=self._select_process()
        root=self._root
        api=event_api()
        api.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
        api.CreateEventW.restype=wintypes.HANDLE
        api.SetEvent.argtypes=[wintypes.HANDLE]
        name='Local\\EchoQQIndependentStop-'+uuid4().hex
        cancel=api.CreateEventW(None,True,False,name)
        if not cancel: raise SourceError('cancel_event_unavailable')
        process=None; reader=None
        try:
            request={'kind':'echo-qq-independent-capture-v1','image':str(self._selection.executable),
                     'pid':pid,'created':created,'cancel_event':name,
                     'snapshot':self._frozen[0],'metadata':self._frozen[1:]}
            (root/'request.json').write_text(json.dumps(request,ensure_ascii=True),encoding='ascii')
            env=os.environ.copy(); env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
            for variable in _ENV:
                directory=root/variable; directory.mkdir(); env[variable]=str(directory)
            if getattr(sys,'frozen',False):
                command=[sys.executable,'--echo-qq-independent-worker',str(root)]
            else:
                env['PYTHONPATH']=str(Path(__file__).resolve().parents[3])
                command=[sys.executable,'-m','qq_chat_analyzer.providers.qq_independent.worker',str(root)]
            process=launch_owned_process(command,cwd=root,env=env,stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
                                         creationflags=subprocess.CREATE_NO_WINDOW,external_readers=True)
            self._worker=process; self._worker_exited=False
            messages=queue.Queue(maxsize=32)
            def read():
                try:
                    for _ in range(16):
                        line=process.stdout.readline(2049)
                        if not line or len(line)>2048: break
                        messages.put_nowait(json.loads(line))
                except (OSError,ValueError,queue.Full): pass
                finally: messages.put_nowait(None)
            reader=threading.Thread(target=read,daemon=True); process.set_external_readers((reader,)); reader.start()
            self._worker_reader=reader
            end=time.monotonic()+280; completed=False; stopping=False
            while True:
                try:
                    value=messages.get(timeout=.05)
                    if value is None: break
                    phase=value.get('phase')
                    if phase=='armed':
                        deadline=datetime.fromisoformat(value['login_before_utc'])
                        remaining=min(value['remaining_login_ms'],int((deadline-datetime.now(timezone.utc)).total_seconds()*1000))
                        if type(value.get('remaining_login_ms')) is not int or remaining<=0:
                            raise SourceError('login_window_elapsed')
                        progress({'phase':'armed','login_before_utc':value['login_before_utc'],
                                  'remaining_login_ms':remaining})
                    elif phase=='stopped': progress('已停止登录观察，正在认证并解密本地快照…')
                    elif phase=='completed': completed=value.get('verified') is True
                    elif phase not in ('failed','stop_unconfirmed'): raise SourceError('invalid_capture_status')
                except queue.Empty: pass
                if (self._cancelled(external.is_set)) and not stopping:
                    stopping=True; api.SetEvent(cancel); end=min(end,time.monotonic()+9)
                if time.monotonic()>=end: raise SourceError('capture_deadline')
            if process.wait(timeout=3) or not completed or stopping: raise SourceError('capture_refused')
        finally:
            try:
                self._release_worker()
            finally:
                api.CloseHandle(cancel)

    def _release_worker(self):
        # A failed Job query/close retains the owner and its plaintext lease.
        # Later cleanup may retry these same resources, never start a new run.
        process=self._worker
        if process is None:return
        if not self._worker_exited:
            process.terminate_tree()
            end=time.monotonic()+3
            while process.active_process_count()!=0 and time.monotonic()<end:time.sleep(.01)
            if process.active_process_count()!=0:raise SourceError('owned_tree_not_released')
            self._worker_exited=True
        reader=self._worker_reader
        if reader:reader.join(timeout=1)
        process.close_after_readers((reader,) if reader else (),deadline=time.monotonic()+2)
        if not process.closed or reader and reader.is_alive():raise SourceError('owned_reader_not_released')
        self._worker=None; self._worker_reader=None; self._worker_exited=False

    def _materialize(self, external=lambda:False):
        root=self._root; selection=self._selection
        end=time.monotonic()+180
        for name in ('message','group_info','profile_info'):
            path=root/(name+'.db'); _file(path); _no_sidecars(path)
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
                db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF'); configure_read_connection(db)
                db.set_progress_handler(lambda:int(self._cancelled(external) or time.monotonic()>=end),10000)
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]: raise SourceError('sqlite_integrity_failed')
                if name=='message':
                    key,count,first,last=authorized_group_partition(db,selection.group,lambda _:None)
                    missing_body=db.execute('SELECT COUNT(*) FROM group_msg_table WHERE CAST("40027" AS TEXT)=? '
                        'AND "40800" IS NULL AND CAST("40033" AS TEXT)=\'0\' '
                        'AND typeof("40011")=\'integer\' AND "40011"=1 '
                        'AND typeof("40012")=\'integer\' AND "40012" IN (0,1)',(key,)).fetchone()[0]
                    # Names are queried only for this group's explicit numeric identities.
                    members={uin for (raw,) in db.execute('SELECT DISTINCT "40033" FROM group_msg_table WHERE CAST("40027" AS TEXT)=?',(key,))
                             if (uin:=canonical_qq_uin(raw)) is not None}
        if self._cancelled(external): raise SourceError('cancelled')
        names,title,summary=scoped_names(root/'group_info.db',root/'profile_info.db',selection.group,members)
        session=QQSession(key,selection.group,title or selection.group,'group',count,last)
        provider=QQDatabaseProvider(root/'message.db',cancelled=lambda:self._cancelled(external))
        payload=provider.read_session_payload(session,self_uin=selection.account)
        if len(payload['records'])+missing_body!=count:
            raise SourceError('unclassified_provider_exclusions')
        self.read_counts={'database_rows':count,'provider_messages':len(payload['records']),
                          'verified_missing_body_rows':missing_body,'unclassified_exclusions':0}
        # Reuse the existing name priority / own-name fallback and serializer.
        destination=root/'payload.json'
        attach_sender_names(destination,payload,names,selection.account)
        if self._cancelled(external): raise SourceError('cancelled')
        self._session=session; self._payload=destination; self._range=(first,last)
        self.names_summary=summary
        self._media=self._media_roots() if selection.recover_media else ()
        for name in ('message','group_info','profile_info'):
            (root/(name+'.db')).unlink()
        # Encrypted input copies are no longer needed either.
        for frozen in self._frozen:
            Path(frozen['path']).unlink()
        self._frozen=[]

    def _media_roots(self):
        base=self._selection.account_directory/'nt_qq/nt_data'
        if not base.exists(): return ()
        base=_safe(base)
        roots=[]
        for relative in ('Pic','Emoji/emoji-recv'):
            parent=base/relative
            if parent.exists():
                _safe(parent)
                entries=list(parent.iterdir())
                if len(entries)>256: raise SourceError('media_scope_limit')
                for month in sorted(entries):
                    if re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',month.name):
                        original=month/'Ori'
                        if original.exists() and _safe(original).is_dir(): roots.append(original)
        face=base/'Emoji/marketface'
        if face.exists() and _safe(face).is_dir(): roots.append(face)
        if len(roots)>128: raise SourceError('media_scope_limit')
        return tuple(roots)

    def get_snapshot(self):
        message={ConnectionState.DISCONNECTED:'QQ 尚未准备。',ConnectionState.STARTING:'快照已准备。请打开 QQ，暂不登录，然后点击等待登录。',
                 ConnectionState.CONNECTED:'授权群快照已就绪，可以生成报告。',ConnectionState.ERROR:'QQ 读取未完成，请正常退出 QQ 后重新准备。'}.get(self._state,'正在读取 QQ 本地快照…')
        return ConnectionSnapshot(self._state,'qq',message,version='9.9.37-54395')

    def check_status(self):
        return SimpleNamespace(available=bool(self._payload),direct_db_ready=bool(self._payload),
                               runtime_running=False,qq_online=False,message=self.get_snapshot().message)

    def list_sessions(self, *, cancelled=lambda:False):
        if self._cancelled(cancelled): raise QQIndependentError('analysis_cancelled','已取消。')
        return [self._session] if self._payload and self._session else []

    def get_session_message_range(self, session_id):
        return self._range if self._session and self._session.session_id==session_id else None

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None,end_time=None,cancelled=lambda:False):
        with self._lock:
            if self._busy or not self._payload or not self._session or self._session.session_id!=session_id or self._cancelled(cancelled):
                raise QQIndependentError('qq_snapshot_expired','本次快照已失效，请正常退出 QQ 后重新准备。')
            self._busy=True
        try:
            yield QQIndependentAcquisition(self._payload,self._selection.account,self._session,self._media,self._selection.recover_media)
        finally:
            try: self._clear()
            finally:
                with self._lock: self._busy=False

    def cancel(self):
        self._cancel.set()

    def _clear(self):
        self._release_worker()
        if self._timer: self._timer.cancel(); self._timer=None
        self._payload=None; self._session=None; self._media=(); self._state=ConnectionState.DISCONNECTED
        if self._root:
            _remove_run(self._root,self._parent); self._root=None
        if self._lease:
            lease=self._lease; self._lease=None; lease.__exit__(None,None,None)
        self._frozen=[]

    def disconnect(self):
        self.cancel()
        with self._lock:
            if self._busy: raise QQIndependentError('qq_independent_busy','正在停止读取，请稍候。')
            self._clear()
        return self.get_snapshot()

    def shutdown(self):
        self._closing=True; self.cancel()
        end=time.monotonic()+4
        while self._busy and time.monotonic()<end: time.sleep(.02)
        if self._busy: return ShutdownStatus.TIMED_OUT
        try: self._clear()
        except Exception: return ShutdownStatus.FAILED
        return ShutdownStatus.SUCCESS

    def runtime_release_status(self, *, final=False):
        # A disabled hook remains mapped until normal QQ exit. Never terminate
        # QQ to manufacture release evidence or claim that Stop unloaded it.
        if not self._generation: return ShutdownStatus.SUCCESS
        if not self._generation_handle: return ShutdownStatus.UNKNOWN
        api,handle=self._generation_handle
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        api.WaitForSingleObject.restype=wintypes.DWORD
        if api.WaitForSingleObject(handle,0)!=0:
            if final and api.CloseHandle(handle): self._generation_handle=None
            return ShutdownStatus.UNKNOWN
        code=wintypes.DWORD()
        api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        api.GetExitCodeProcess.restype=wintypes.BOOL
        if not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259:
            return ShutdownStatus.UNKNOWN
        if not api.CloseHandle(handle): return ShutdownStatus.FAILED
        self._generation_handle=None
        self._generation=None
        return ShutdownStatus.SUCCESS
