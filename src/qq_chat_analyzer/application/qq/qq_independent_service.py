"""Own one authorized account snapshot, its declaration and conversation reads."""
from __future__ import annotations

from contextlib import contextmanager, closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import ctypes
import configparser
from ctypes import wintypes
import json
import logging
from itertools import islice
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
from ...providers.qq_independent.snapshot import prepare, _protect_new_root, _powershell, authorized_group_partition, authorized_group_partitions
from ...providers.qq_independent.metadata import scoped_names
from ...providers.qq_independent.process import verified_process, process_creation_ticks
from ...providers.qq_independent.worker import direct_runtime_files, resources_identity, runtime_files, event_api
from ...providers.qq_independent.diagnostics import failure_record, public_message, safe_code
from ...providers.qq_sqlite_reader import configure_read_connection
from ...qq_db_identity import canonical_qq_uin
from ...diagnostics import qq_session_stage
from ...resources import user_data_root
from ..connection_models import ConnectionSnapshot, ConnectionState
from ..errors import ApplicationServiceError
from ..shutdown_models import ShutdownStatus
from .qq_runtime_workspace import _lease

_ENV = ('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP','MPLCONFIGDIR','XDG_CONFIG_HOME','XDG_CACHE_HOME')
_TTL = 600
_LOGGER = logging.getLogger('qq_chat_analyzer.desktop.qq.independent')


class QQIndependentError(ApplicationServiceError):
    def __init__(self, code='qq_independent_failed', message='QQ 读取未完成，请正常退出 QQ 后重新准备。'):
        self.code, self.public_message = code, message
        super().__init__()


@dataclass(frozen=True)
class QQIndependentSelection:
    executable: Path
    account_directory: Path
    account: str
    recover_media: bool = True


@dataclass(frozen=True)
class QQIndependentAcquisition:
    payload_path: Path
    self_uin: str
    session: QQSession
    sticker_media_roots: tuple[Path, ...] = ()
    recover_qq_media: bool = True
    self_identity_basis: str = "user_declared"


@dataclass(frozen=True)
class QQIndependentDiscovery:
    accounts: tuple[Path, ...]
    executables: tuple[Path, ...]
    incompatible_executables: tuple[Path, ...] = ()
    unverified_executables: tuple[Path, ...] = ()
    location_warning: str | None = None


def _configured_data_root(config):
    """QQ's explicit storage location, not an account or credential witness."""
    if not os.path.lexists(config):return None
    try:
        _file(config)
        with config.open('rb') as stream:data=stream.read(16385)
        if len(data)>16384:raise ValueError()
        parsed=None
        for encoding in ('utf-8-sig','utf-16','gb18030'):
            try:
                parser=configparser.ConfigParser(interpolation=None)
                parser.read_string(data.decode(encoding));parsed=parser;break
            except (UnicodeError,configparser.Error):continue
        if parsed is None:raise ValueError()
        mode=parsed.get('UserDataSet','UserDataSavePathType')
        if mode!='2':
            raise QQIndependentError('qq_data_location_unverified',
                'Echo 无法自动识别 QQ 配置的保存位置类型，尚未读取聊天记录。')
        value=parsed.get('UserDataSet','UserDataSavePath').strip().strip('"')
        path=Path(os.path.expandvars(value))
        if not path.is_absolute():raise ValueError()
        path=_safe(path)
        if not path.is_dir():raise ValueError()
        return path
    except (OSError,ValueError,configparser.Error,SourceError):
        raise QQIndependentError('qq_data_location_unverified',
            '无法确认 QQ 设置的资料位置，尚未读取聊天记录。') from None


def _discovery_locations(*, use_configured_root=True):
    """Fixed local metadata locations only; no drive search or process probe."""
    documents=Path.home()/'Documents'
    images=[]
    # Honor a redirected HOME/USERPROFILE (including isolated acceptance runs).
    # HKCU belongs to the Windows profile, not an arbitrary environment profile.
    windows_profile=ctypes.create_unicode_buffer(32768)
    native_profile=(os.name=='nt' and ctypes.windll.shell32.SHGetFolderPathW(
        None,0x28,None,0,windows_profile)==0 and Path(windows_profile.value)==Path.home())
    if native_profile:
        import winreg
        from .qq_auth_bridge import _qq_install_candidates
        images.extend(_qq_install_candidates())
        for hive,key,value in (
            (winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders','Personal'),
        ):
            try:
                with winreg.OpenKey(hive,key) as handle:text,_=winreg.QueryValueEx(handle,value)
                if not isinstance(text,str):continue
                path=Path(os.path.expandvars(text.strip('"')))
                if value=='Personal':documents=path
                else:images.append(path)
            except OSError:pass
    for variable in ('ProgramFiles','ProgramFiles(x86)','ProgramW6432','LOCALAPPDATA'):
        if base:=os.environ.get(variable):
            for relative in ('Tencent/QQNT/QQ.exe','Tencent/QQNT/Bin/QQ.exe','Tencent/QQ/QQ.exe','Tencent/QQ/Bin/QQ.exe'):
                images.append(Path(base)/relative)
    roots=[documents/'Tencent Files']
    if appdata:=os.environ.get('APPDATA'):roots.append(Path(appdata)/'Tencent/QQ')
    if native_profile and use_configured_root:
        common=ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None,0x2e,None,0,common)!=0:
            raise QQIndependentError('qq_data_location_unverified','无法读取 QQ 资料位置设置。')
        configured=_configured_data_root(Path(common.value)/'Tencent/QQ/UserDataInfo.ini')
        if configured is not None:
            # The configured location takes precedence over stale defaults;
            # never combine two copies of the same account or rank by size/age.
            roots=[configured]
    return roots,images


def _positive(value):
    return isinstance(value,str) and re.fullmatch(r'[1-9][0-9]{4,19}',value) is not None


def _environment_directories(directory):
    """Only empty, fixed Windows profile scaffolding may join our empty roots."""
    allowed={'AppData','AppData/Roaming'} if directory.name=='USERPROFILE' else set()
    directories=[directory]
    for current in directories:
        _safe(current)
        for child in current.iterdir():
            _safe(child)
            if child.relative_to(directory).as_posix() not in allowed or not child.is_dir():
                raise SourceError('workspace_unknown_file')
            directories.append(child)
    return sorted(directories,key=lambda p:len(p.parts),reverse=True)


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
    allowed={'owner.json','request.json','message.db','group_info.db','profile_info.db','payload.json',
             'read-request.json','read-request.pending'}
    for child in root.iterdir():
        _safe(child)
        if child.is_file():
            _file(child)
            if child.name not in allowed: raise SourceError('workspace_unknown_file')
        elif child.is_dir() and child.name in _ENV:
            _environment_directories(child)
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
        if child.is_dir() and child.name in _ENV:
            for directory in _environment_directories(child):
                _safe(directory)
                directory.rmdir()
        elif child.is_dir():
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
    """No QQ launch/kill or persisted key; one authorized, expiring snapshot."""
    independent = True

    def __init__(self, *, workspace: Path | None = None, read_originals=False):
        self._parent=workspace or user_data_root()/'qq-independent'
        self._lock=threading.RLock()
        self._root=None; self._lease=None; self._selection=None; self._frozen=[]
        self._payload=None; self._sessions=[]; self._confirmed=None; self._media=()
        self._cancel=threading.Event(); self._busy=False; self._closing=False
        self._timer=None; self._generation=None; self._generation_handle=None
        self._worker=None; self._worker_reader=None; self._worker_exited=False
        self._read_originals=read_originals
        self._worker_messages=None; self._worker_stop=None; self._request_number=0
        self._originals=None
        self._state=ConnectionState.DISCONNECTED

    def _cancelled(self, external=lambda:False):
        return self._cancel.is_set() or self._closing or external()

    def discover_local_profiles(self, data_root=None, *, cancelled=lambda:False):
        """List profile labels and file presence, never read database contents.

        Discovery is not authorization, account attestation or key matching.
        A custom root is expanded one level, without following linked paths.
        """
        location_warning = None
        try:
            roots,images=_discovery_locations(use_configured_root=data_root is None)
        except QQIndependentError as error:
            if data_root is not None or error.code!='qq_data_location_unverified':raise
            # Default locations are candidates for explicit confirmation only.
            location_warning=error.public_message
            roots,images=_discovery_locations(use_configured_root=False)
        if data_root is not None:roots=[Path(data_root)]
        accounts=[];executables=[];incompatible=[];unverified=[]
        def stopped():
            if self._closing or cancelled():raise QQIndependentError('analysis_cancelled','已取消资料发现。')
        for root in dict.fromkeys(roots):
            stopped()
            try:
                root=_safe(root)
                if _positive(root.name):candidates=[root]
                else:
                    with os.scandir(root) as entries:
                        entries=list(islice(entries,1025))
                        if len(entries)>1024:raise QQIndependentError('qq_discovery_limit','资料候选过多，请直接选择一个账号目录。')
                        candidates=[root/entry.name for entry in entries if _positive(entry.name)]
                        if len(candidates)>256:raise QQIndependentError('qq_discovery_limit','资料候选过多，请直接选择一个账号目录。')
                for candidate in sorted(candidates):
                    stopped()
                    try:
                        _safe(candidate)
                        for name in ('nt_msg.db','group_info.db','profile_info.db'):
                            _file(candidate/'nt_qq/nt_db'/name)
                    except (OSError,SourceError):continue
                    if candidate not in accounts:accounts.append(candidate)
            except (OSError,SourceError):continue
        for image in dict.fromkeys(images):
            stopped()
            try:
                image=_safe(image)
                _file(image)
            except (OSError,SourceError):continue
            if image.name.lower()!='qq.exe':continue
            try:
                resources_identity(image)
            except SourceError as error:
                if error.code=='exact_active_version_required':
                    from .qq_version import read_qq_resources
                    from ...providers.qq_independent.worker import VERSION
                    try:resource=read_qq_resources(image)
                    except (OSError,ValueError):resource=None
                    (incompatible if resource and resource.version and resource.version!=VERSION
                     else unverified).append(image)
                else:unverified.append(image)
            except (OSError,ValueError):unverified.append(image)
            else:
                if image not in executables:executables.append(image)
        return QQIndependentDiscovery(tuple(accounts),tuple(executables),tuple(incompatible),tuple(unverified),location_warning)

    def prepare(self, selection: QQIndependentSelection, *, cancelled=lambda:False):
        with self._lock:
            if self._busy or self._closing: raise QQIndependentError('qq_independent_busy')
            self._busy=True
        try:
            self._clear()
            if self._closing or cancelled():
                raise QQIndependentError('analysis_cancelled','已取消 QQ 准备。')
            if self.runtime_release_status() is not ShutdownStatus.SUCCESS:
                raise QQIndependentError('qq_normal_exit_required','请先正常退出上次读取的 QQ，使组件完全释放。')
            self._cancel.clear()
            if not _positive(selection.account):
                raise QQIndependentError('qq_identity_required','请选择有效的 QQ 账号资料目录。')
            account=_safe(Path(selection.account_directory))
            if account.name != selection.account or not account.is_dir():
                raise QQIndependentError('qq_account_scope_mismatch','请选择以当前 QQ 账号命名的数据目录。')
            for name in ('nt_msg.db','group_info.db','profile_info.db'):
                _file(account/'nt_qq/nt_db'/name)
            image=_safe(Path(selection.executable)); _file(image)
            resources_identity(image)
            runtime_files()
            if self._read_originals: direct_runtime_files()
            # The snapshot and its ACL helper must share a Windows-compatible
            # path budget. Refuse before a login/capture, never after QQ exits.
            longest=self._parent.absolute()/('run-'+'0'*32)/('qq-authorized-full-'+'0'*32)/'encrypted.db'
            if os.name=='nt' and len(str(longest))>=260:
                raise QQIndependentError('qq_workspace_path_too_long',
                    '临时资料目录过长，连接尚未开始。请缩短验收或数据目录后再连接。')
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
            self._selection=QQIndependentSelection(image,account,selection.account,selection.recover_media)
            if account.is_relative_to(self._parent) or self._parent.is_relative_to(account):
                raise SourceError('workspace_overlap')
            if self._cancelled(cancelled): raise QQIndependentError('analysis_cancelled','已取消 QQ 准备。')
            self._state=ConnectionState.STARTING
            self._expire_later()
            return self.get_snapshot()
        except QQIndependentError:
            self._clear(); raise
        except Exception:
            self._clear()
            raise QQIndependentError(message='准备未通过：请检查 54395 版本、账号目录和完整组件。') from None
        finally:
            with self._lock: self._busy=False

    def _expire_later(self):
        if self._timer: self._timer.cancel()
        def expire():
            with self._lock:
                if self._timer is not timer or self._busy: return
                try: self._clear()
                except Exception: self._state=ConnectionState.ERROR
        timer=threading.Timer(_TTL,expire); timer.daemon=True
        self._timer=timer; timer.start()

    def capture(self, *, progress=lambda value:None, cancel_event=None, wait_for_process=False):
        with self._lock:
            if self._busy or self._closing or not self._root or self._state is not ConnectionState.STARTING:
                raise QQIndependentError('qq_independent_not_prepared')
            self._busy=True
        external=cancel_event or threading.Event()
        try:
            if self._cancelled(external.is_set): raise QQIndependentError('analysis_cancelled','已取消 QQ 获取。')
            if wait_for_process:
                self._wait_for_process(progress,external)
            offline_started=None
            def report(value):
                nonlocal offline_started
                if value.get('phase')=='authenticating' and offline_started is None:
                    offline_started=time.perf_counter()
                progress(value)
            self._run_capture(report,external)
            if offline_started is not None:
                _LOGGER.info('[qq independent] stage=qq_offline_read elapsed_ms=%d',int((time.perf_counter()-offline_started)*1000))
            if self._cancelled(external.is_set): raise QQIndependentError('analysis_cancelled','QQ 读取已取消。')
            if not self._read_originals:
                progress({'phase':'authenticating','message':'正在校验授权数据库…'})
                with qq_session_stage(_LOGGER,'qq_database_validation'):
                    self._validate_databases(external.is_set)
            self._state=ConnectionState.CONNECTED; self._expire_later()
            return self.get_snapshot()
        except Exception as error:
            _LOGGER.warning('[qq independent] stage=capture failure_code=%s error_type=%s',
                safe_code(error.code) if isinstance(error,SourceError) else
                error.code if isinstance(error,QQIndependentError) else 'unexpected_error',
                type(error).__name__)
            self._state=ConnectionState.ERROR
            self._clear()
            if isinstance(error,QQIndependentError): raise
            if isinstance(error,(SourceError,OSError,subprocess.TimeoutExpired)):
                failure=failure_record(error,code='worker_timeout' if isinstance(error,subprocess.TimeoutExpired) else None,
                    stage=getattr(error,'diagnostic_stage','admission'))
                _LOGGER.warning('[qq independent] stage=%s failure_code=%s',failure['failure_stage'],failure['failure_code'])
                if 'loader_exit_code' in failure:
                    _LOGGER.warning('[qq independent] stage=%s loader_exit_code=%d',failure['failure_stage'],failure['loader_exit_code'])
                if 'cause_code' in failure:
                    _LOGGER.warning('[qq independent] stage=%s cause_code=%s',failure['failure_stage'],failure['cause_code'])
                raise QQIndependentError('qq_capture_'+failure['failure_code'],public_message(failure['failure_code'])) from None
            raise QQIndependentError() from None
        finally:
            with self._lock: self._busy=False

    def _process_candidates(self, *, include_children=False):
        """Inspect process metadata only for the explicitly selected image."""
        parents="" if include_children else " | Where-Object { $_.CommandLine -notmatch '--type=' }"
        raw=_powershell("Get-CimInstance Win32_Process -Filter \"Name='QQ.exe'\""+parents+" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress")
        rows=json.loads(raw) if raw else []
        if isinstance(rows,dict): rows=[rows]
        rows=[row for row in rows if row.get('ExecutablePath') and
              os.path.normcase(row['ExecutablePath'])==os.path.normcase(str(self._selection.executable))]
        return rows

    def _wait_for_process(self, progress, external):
        # Existing QQ may already be logged in. Require a clean manual exit;
        # process presence is not evidence of login state or a fresh login.
        if self._process_candidates(include_children=True):
            progress({'phase':'preparation_exit'})
            deadline=time.monotonic()+120
            while self._process_candidates(include_children=True):
                if self._cancelled(external.is_set):
                    raise QQIndependentError('analysis_cancelled','已取消 QQ 获取。')
                if time.monotonic()>=deadline:
                    raise QQIndependentError('qq_preparation_exit_timeout','等待退出 QQ 已超时。请从系统托盘完全退出 QQ 后重新连接。')
                external.wait(.5)
        if self._cancelled(external.is_set):
            raise QQIndependentError('analysis_cancelled','已取消 QQ 获取。')
        progress({'phase':'waiting_for_qq'})
        deadline=time.monotonic()+120
        while not self._cancelled(external.is_set):
            rows=self._process_candidates()
            if len(rows)==1:return
            if len(rows)>1:
                raise QQIndependentError('qq_process_selection_required','检测到多个 QQ 窗口，请完全退出多余的 QQ 后重新连接。')
            if time.monotonic()>=deadline:
                raise QQIndependentError('qq_process_timeout','等待打开 QQ 已超时，请重新连接。')
            external.wait(.5)
        raise QQIndependentError('analysis_cancelled','已取消 QQ 获取。')

    def _select_process(self):
        """Explicit installed image only; no login-state or arbitrary memory scan."""
        rows=self._process_candidates()
        if len(rows)!=1:
            raise QQIndependentError('qq_process_selection_required','QQ 状态已变化，请重新连接并停留在登录页面。')
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
        process=None; reader=None; keep=False
        try:
            request={'kind':'echo-qq-independent-capture-v1','image':str(self._selection.executable),
                     'pid':pid,'created':created,'cancel_event':name,
                     'account_directory':str(self._selection.account_directory),'root':str(root),
                     'direct':self._read_originals}
            (root/'request.json').write_text(json.dumps(request,ensure_ascii=True),encoding='ascii')
            env=os.environ.copy(); env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
            for variable in _ENV:
                directory=root/variable; directory.mkdir(); env[variable]=str(directory)
            if self._read_originals:
                env['OPENSSL_CONF']='NUL'
                env['OPENSSL_MODULES']=env['TEMP']
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
                    limit=8*1024**2 if self._read_originals else 2048
                    for _ in range(1024 if self._read_originals else 16):
                        line=process.stdout.readline(limit+1)
                        if not line:break
                        if len(line)>limit:
                            messages.put_nowait(failure_record(code='protocol_incomplete'));break
                        messages.put_nowait(json.loads(line))
                except (OSError,ValueError):
                    try:messages.put_nowait(failure_record(code='protocol_invalid_json'))
                    except queue.Full:pass
                except queue.Full:pass
                finally: messages.put_nowait(None)
            reader=threading.Thread(target=read,daemon=True); process.set_external_readers((reader,)); reader.start()
            self._worker_reader=reader
            end=time.monotonic()+400; completed=False; stopping=False; failure=None
            while True:
                try:
                    value=messages.get(timeout=.05)
                    if value is None: break
                    if not isinstance(value,dict):raise SourceError('invalid_capture_status')
                    phase=value.get('phase')
                    if phase=='armed':
                        deadline=datetime.fromisoformat(value['login_before_utc'])
                        remaining=min(value['remaining_login_ms'],int((deadline-datetime.now(timezone.utc)).total_seconds()*1000))
                        if type(value.get('remaining_login_ms')) is not int or remaining<=0:
                            raise SourceError('login_window_elapsed')
                        progress({'phase':'armed','login_before_utc':value['login_before_utc'],
                                  'remaining_login_ms':remaining})
                    elif phase=='stopped': progress({'phase':phase,'message':'登录捕获已停止。'})
                    elif phase=='awaiting_exit': progress({'phase':phase,'message':'已收到登录信息，请在 110 秒内从托盘完全退出 QQ；Echo 不会自动退出 QQ。',
                                                          'reading_originals':self._read_originals})
                    elif phase=='authenticating': progress({'phase':phase,'message':'QQ 已退出，正在校验并读取授权资料…'})
                    elif phase=='direct_ready' and self._read_originals and value.get('verified') is True:
                        if stopping or failure is not None or self._cancelled(external.is_set):
                            raise SourceError('cancelled')
                        self._worker_messages=messages; self._worker_stop=(api,cancel); self._request_number=0
                        keep=True
                        return
                    elif phase=='completed' and not self._read_originals: completed=value.get('verified') is True
                    elif phase=='failed':failure=failure_record(code=value.get('failure_code'),stage=value.get('failure_stage'),
                        exit_code=value.get('loader_exit_code'),cause_code=value.get('cause_code'))
                    elif phase not in ('failed','stop_unconfirmed'): raise SourceError('invalid_capture_status')
                except queue.Empty: pass
                if (self._cancelled(external.is_set)) and not stopping:
                    stopping=True; api.SetEvent(cancel); end=min(end,time.monotonic()+9)
                if time.monotonic()>=end: raise SourceError('capture_deadline')
            code=process.wait(timeout=3)
            if code or not completed or stopping or failure is not None:
                failure=failure or failure_record(code='cancelled' if stopping else
                    'worker_exit_nonzero' if code else 'worker_result_missing',stage='final_check')
                error=SourceError(failure['failure_code']);error.diagnostic_stage=failure['failure_stage']
                error.diagnostic_exit_code=failure.get('loader_exit_code')
                error.diagnostic_cause_code=failure.get('cause_code');raise error
        finally:
            if not keep:
                try:
                    self._release_worker()
                finally:
                    api.CloseHandle(cancel)

    def _request_read(self, operation, cancelled, **fields):
        if self._cancelled(cancelled):
            raise SourceError('cancelled')
        if self._worker_messages is None or self._worker is None or self._worker.poll() is not None:
            raise SourceError('worker_result_missing')
        number=self._request_number+1
        pending=self._root/'read-request.pending'
        command=self._root/'read-request.json'
        with pending.open('x',encoding='ascii') as stream:
            json.dump({'id':number,'op':operation,**fields},stream,ensure_ascii=True,allow_nan=False)
        pending.rename(command)
        end=time.monotonic()+125
        while time.monotonic()<end:
            if self._cancelled(cancelled):
                api,handle=self._worker_stop
                api.SetEvent(handle)
                raise SourceError('cancelled')
            try: result=self._worker_messages.get(timeout=.05)
            except queue.Empty: continue
            if not isinstance(result,dict): raise SourceError('worker_result_missing')
            if result.get('phase')=='failed': raise SourceError(safe_code(result.get('failure_code')))
            if result.get('phase')!='direct_reply' or result.get('id')!=number:
                raise SourceError('invalid_capture_status')
            self._request_number=number
            return result['value']
        raise SourceError('capture_deadline')

    def _release_worker(self):
        # A failed Job query/close retains the owner and its plaintext lease.
        # Later cleanup may retry these same resources, never start a new run.
        process=self._worker
        if process is None:return
        if not self._worker_exited:
            if self._worker_stop:
                api,handle=self._worker_stop
                if api.SetEvent(handle):
                    try: process.wait(timeout=.25)
                    except subprocess.TimeoutExpired: pass
            if not self._worker_stop or process.active_process_count()!=0:
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
        self._worker_messages=None; self._request_number=0
        if self._worker_stop:
            api,handle=self._worker_stop
            api.CloseHandle(handle)
            self._worker_stop=None

    def _validate_databases(self, external=lambda:False):
        end=time.monotonic()+180
        for name in ('message','group_info','profile_info'):
            path=self._root/(name+'.db'); _file(path); _no_sidecars(path)
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
                db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF'); configure_read_connection(db)
                db.set_progress_handler(lambda:int(self._cancelled(external) or time.monotonic()>=end),10000)
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]: raise SourceError('sqlite_integrity_failed')
        if self._cancelled(external): raise SourceError('cancelled')

    def confirm_account(self, account, *, cancelled=lambda:False):
        with self._lock:
            if self._busy or self._closing or self._state is not ConnectionState.CONNECTED or self._confirmed:
                raise QQIndependentError('qq_confirmation_unavailable','请先按引导完成 QQ 数据获取。')
            self._busy=True
        try:
            if not _positive(account) or account!=self._selection.account:
                raise QQIndependentError('qq_declaration_mismatch','本人 QQ 号须与所选账号资料标签一致；如资料选错，请重新选择。')
            if self._read_originals:
                sessions=[QQSession(**entry) for entry in self._request_read('list',cancelled,account=account)]
            else:
                sessions=self._discover_sessions(account,cancelled)
            if self._cancelled(cancelled): raise SourceError('cancelled')
            self._confirmed=account; self._sessions=sessions
            self._media=self._media_roots() if self._selection.recover_media else ()
            self._expire_later()
            return self.get_snapshot()
        except Exception as error:
            _LOGGER.warning('[qq independent] stage=confirm failure_code=%s error_type=%s',
                error.code if isinstance(error,(SourceError,QQIndependentError)) else 'unexpected_error',
                type(error).__name__)
            if isinstance(error,sqlite3.Error):
                trace=error.__traceback__
                while trace and trace.tb_next:trace=trace.tb_next
                detail=str(error).casefold()
                reason=next((category for prefix,category in (
                    ('no such table:','missing_table'),('no such column:','missing_column'),
                    ('no such collation sequence:','missing_collation'),('no such function:','missing_function'),
                    ('interrupted','interrupted'),('database is locked','locked'),
                    ('unable to open database file','open_failed'),('too many sql variables','variable_limit'),
                    ('database disk image is malformed','malformed'),
                ) if detail.startswith(prefix)),'other')
                # Fixed source filenames and categories only, never SQLite's
                # message (which may contain identifiers or query values).
                filename=Path(trace.tb_frame.f_code.co_filename).name if trace else 'unknown'
                if filename not in {'qq_independent_service.py','metadata.py','snapshot.py',
                                    'qq_database_provider.py','qq_sqlite_reader.py'}:filename='other'
                _LOGGER.warning('[qq independent] stage=confirm sqlite_code=%d file=%s site=%s line=%d reason=%s',
                    getattr(error,'sqlite_errorcode',0),
                    filename, trace.tb_frame.f_code.co_name if trace else 'unknown',
                    trace.tb_lineno if trace else 0, reason)
            self._clear()
            if isinstance(error,QQIndependentError): raise
            raise QQIndependentError('qq_session_validation_failed','会话身份存在冲突或资料无法读取，请重新选择账号资料。') from None
        finally:
            with self._lock: self._busy=False

    def _discover_sessions(self, account, cancelled):
        started=time.perf_counter()
        provider=self._message_provider(cancelled)
        sessions=[];unnamed_groups=0
        with self._message_database(cancelled) as db:
            discovered=provider.list_sessions(self_uin=account)
            groups={}
            for session in discovered:
                if session.session_type!='group':continue
                if self._cancelled(cancelled): raise SourceError('cancelled')
                group=session.session_object
                if not group:
                    candidates=db.execute('SELECT DISTINCT CAST("40021" AS TEXT) FROM group_msg_table WHERE CAST("40027" AS TEXT)=? LIMIT 2',(session.internal_key,)).fetchall()
                    if len(candidates)!=1: raise SourceError('ambiguous_group')
                    group=candidates[0][0]
                if not _positive(group): raise SourceError('invalid_group')
                groups[session.internal_key]=group
            with qq_session_stage(_LOGGER,'partition_validation'):
                partitions=authorized_group_partitions(db,groups.values(),native=self._originals is not None)
            for session in discovered:
                if self._cancelled(cancelled): raise SourceError('cancelled')
                if session.session_type=='group':
                    group=groups[session.internal_key]
                    key,count,first,last=partitions[group]
                    if key!=session.internal_key: raise SourceError('partition_mismatch')
                    # Listing needs the group title only. Member identities
                    # remain scoped and resolved when that chat is analyzed.
                    _,title,_=self._scoped_names(group,set())
                    if not title:unnamed_groups+=1
                    session=replace(session,session_object=group,display_name=title or group)
                else:
                    peers={canonical_qq_uin(row[0]) for row in db.execute('SELECT DISTINCT "40033" FROM c2c_msg_table WHERE CAST("40027" AS TEXT)=?',(session.internal_key,))}
                    peers-={None,'0',account}
                    if len(peers)>1: raise SourceError('ambiguous_private_participants')
                    peer=next(iter(peers),session.peer_uin)
                    names,_,_=self._scoped_names(None,{peer} if peer else set())
                    session=replace(session,peer_uin=peer,display_name=names[peer].display_name if peer in names else session.display_name)
                sessions.append(session)
        _LOGGER.info('[qq independent] stage=session_inventory group_sessions=%d private_sessions=%d message_rows=%d unresolved_group_names=%d elapsed_ms=%d',
            sum(s.session_type=='group' for s in sessions),sum(s.session_type=='private' for s in sessions),
            sum(s.message_count or 0 for s in sessions),unnamed_groups,int((time.perf_counter()-started)*1000))
        return sessions

    @contextmanager
    def _message_database(self, external=lambda:False):
        if self._originals is not None:
            _, db = self._originals['message']
            end=time.monotonic()+180
            db.set_progress_handler(lambda:self._cancelled(external) or time.monotonic()>=end,10000)
            yield db
            return
        path=self._root/'message.db';_file(path);_no_sidecars(path)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF');configure_read_connection(db)
            end=time.monotonic()+180
            db.set_progress_handler(lambda:int(self._cancelled(external) or time.monotonic()>=end),10000)
            yield db

    def _message_provider(self, external):
        if self._originals is None:
            return QQDatabaseProvider(self._root/'message.db',cancelled=lambda:self._cancelled(external))
        path, connection = self._originals['message']
        return QQDatabaseProvider(path,cancelled=lambda:self._cancelled(external),connection=connection)

    def _scoped_names(self, group, members):
        if self._originals is None:
            return scoped_names(self._root/'group_info.db',self._root/'profile_info.db',group,members)
        group_path, group_db = self._originals['group_info']
        profile_path, profile_db = self._originals['profile_info']
        return scoped_names(group_path,profile_path,group,members,connections=(group_db,profile_db))

    def _materialize(self, session, external, start_time, end_time):
        table='group_msg_table' if session.session_type=='group' else 'c2c_msg_table'
        with self._message_database(external) as db:
            if session.session_type=='group':
                with qq_session_stage(_LOGGER,'analysis_partition'):
                    key,count,first,last=authorized_group_partition(db,session.session_object,lambda _:None)
                if key!=session.internal_key: raise SourceError('partition_mismatch')
            rows=db.execute(f'SELECT "40033" FROM {table} WHERE CAST("40027" AS TEXT)=?',(session.internal_key,))
            members={uin for (raw,) in rows if (uin:=canonical_qq_uin(raw)) not in (None,'0')}
            with qq_session_stage(_LOGGER,'analysis_names'):
                names,_,self.names_summary=self._scoped_names(session.session_object if session.session_type=='group' else None,members)
            provider=self._message_provider(external)
            # Connecting a selected profile supplies user-declared context,
            # never a QQ attestation of the current online identity.
            with qq_session_stage(_LOGGER,'analysis_records'):
                payload=provider.read_session_payload(session,self_uin=self._confirmed,start_time=start_time,end_time=end_time)
            payload['self']['basis']='user_declared'
            predicate='CAST("40027" AS TEXT)=?';values=[session.internal_key]
            if start_time is not None: predicate+=' AND "40050">=?';values.append(start_time)
            if end_time is not None: predicate+=' AND "40050"<=?';values.append(end_time)
            count=db.execute(f'SELECT COUNT(*) FROM {table} WHERE '+predicate,values).fetchone()[0]
            # Do not silently discard unfamiliar NULL-body records.
            missing=0
            with closing(db.execute(f'SELECT * FROM {table} WHERE '+predicate+' AND ("40800" IS NULL OR typeof("40800")!=\'blob\' OR length("40800")=0)',values)) as excluded:
                for row in excluded:
                    columns=[d[1] for d in db.execute(f'PRAGMA table_info({table})')]
                    raw=dict(zip(columns,row))
                    if (raw.get('40800') is not None or raw.get('40033')!=0
                        or type(raw.get('40011')) is not int or raw['40011']!=1
                        or type(raw.get('40012')) is not int or raw['40012'] not in (0,1)):
                        body=raw.get('40800')
                        body_kind=('null' if body is None else 'empty_blob' if isinstance(body,bytes) and not body
                                   else 'text' if isinstance(body,str) else 'other')
                        # Only bounded message-type flags, never sender UINs,
                        # timestamps, message IDs, text or BLOB bytes.
                        flags=[]
                        for field in ('40011','40012'):
                            value=raw.get(field)
                            flags.append('missing' if field not in raw else 'null' if value is None
                                         else value if type(value) is int and 0<=value<=255 else 'other')
                        sender=raw.get('40033')
                        sender_kind=('zero' if type(sender) is int and sender==0 else 'null' if sender is None
                                     else 'nonzero' if canonical_qq_uin(sender) not in (None,'0') else 'other')
                        _LOGGER.warning('[qq independent] stage=analysis_exclusions session_kind=%s body_kind=%s flag_40011=%s flag_40012=%s sender_kind=%s',
                            session.session_type,body_kind,*flags,sender_kind)
                        raise SourceError('unclassified_provider_exclusions')
                    missing+=1
            if len(payload['records'])+missing!=count:
                _LOGGER.warning('[qq independent] stage=analysis_exclusions database_rows=%d provider_messages=%d verified_missing_body_rows=%d',count,len(payload['records']),missing)
                raise SourceError('unclassified_provider_exclusions')
            self.read_counts={'database_rows':count,'provider_messages':len(payload['records']),
                'verified_missing_body_rows':missing,'unclassified_exclusions':0}
        if self._cancelled(external): raise SourceError('cancelled')
        self._payload=self._root/'payload.json'
        with qq_session_stage(_LOGGER,'analysis_payload'):
            attach_sender_names(self._payload,payload,names,self._confirmed)

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
        with self._lock:
            state=self._state
            if (self._read_originals and state is ConnectionState.CONNECTED and
                    (self._cancel.is_set() or self._worker is None or self._worker.poll() is not None)):
                state=ConnectionState.ERROR
        message={ConnectionState.DISCONNECTED:'QQ 尚未准备。',
            ConnectionState.STARTING:'正在准备连接 QQ，请按 Echo 的当前提示操作，等待允许登录的提示。',
            ConnectionState.CONNECTED:('账号资料已认证，正在加载聊天列表。' if not self._confirmed else '会话已就绪；本人上下文来自所选账号资料，非 QQ 系统认证。'),
            ConnectionState.ERROR:'QQ 读取未完成，请重新准备。'}.get(state,'正在读取 QQ 本地快照…')
        return ConnectionSnapshot(state,'qq',message,version='9.9.37-54395')

    def check_status(self):
        snapshot=self.get_snapshot()
        ready=bool(self._confirmed) and snapshot.state is ConnectionState.CONNECTED
        return SimpleNamespace(available=ready,direct_db_ready=ready,
            runtime_running=False,qq_online=False,message=snapshot.message)

    def list_sessions(self, *, cancelled=lambda:False):
        with self._lock:
            if self._cancelled(cancelled): raise QQIndependentError('analysis_cancelled','已取消。')
            return list(self._sessions) if self._confirmed and not self._busy else []

    def get_session_message_range(self, session_id, **_options):
        with self._lock:
            if self._busy or not self._confirmed: return None
            session=next((s for s in self._sessions if s.session_id==session_id),None)
            if session is None:return None
            if self._read_originals:
                try:
                    result=self._request_read('range',lambda:False,session=session_id)
                    self._expire_later()
                    return tuple(result) if result else None
                except Exception:
                    self._clear()
                    raise QQIndependentError('qq_snapshot_expired','本次读取已结束，请重新连接 QQ。') from None
            table='group_msg_table' if session.session_type=='group' else 'c2c_msg_table'
            with self._message_database() as db:
                with closing(db.execute(f'SELECT MIN("40050"),MAX("40050") FROM {table} WHERE CAST("40027" AS TEXT)=?',
                                        (session.internal_key,))) as rows:
                    return rows.fetchone()

    @contextmanager
    def acquired_session(self, session_id, *, start_time=None,end_time=None,cancelled=lambda:False):
        with self._lock:
            session=next((s for s in self._sessions if s.session_id==session_id),None)
            if self._busy or not self._confirmed or not session or self._cancelled(cancelled):
                raise QQIndependentError('qq_snapshot_expired','本次快照已失效，请重新获取 QQ 资料。')
            self._busy=True
        try:
            try:
                with qq_session_stage(_LOGGER,'analysis_export'):
                    if self._read_originals:
                        self.read_counts=self._request_read('materialize',cancelled,session=session_id,start=start_time,end=end_time)
                        self._payload=self._root/'payload.json'
                        _file(self._payload)
                    else:
                        self._materialize(session,cancelled,start_time,end_time)
            except ApplicationServiceError:
                raise
            except Exception as error:
                code=(safe_code(error.code) if isinstance(error,SourceError) else
                      'sqlite_error' if isinstance(error,sqlite3.Error) else
                      'file_missing' if isinstance(error,FileNotFoundError) else
                      'permission_denied' if isinstance(error,PermissionError) else
                      'io_error' if isinstance(error,OSError) else 'unexpected_error')
                trace=error.__traceback__
                while trace and trace.tb_next:trace=trace.tb_next
                filename=Path(trace.tb_frame.f_code.co_filename).name if trace else 'unknown'
                if filename not in {'qq_independent_service.py','metadata.py','snapshot.py',
                                    'qq_database_provider.py','qq_sqlite_reader.py'}:filename='other'
                _LOGGER.warning('[qq independent] stage=analysis_export failure_code=%s error_type=%s file=%s line=%d sqlite_code=%d',
                    code,type(error).__name__,filename,trace.tb_lineno if trace else 0,getattr(error,'sqlite_errorcode',0))
                message=('所选会话包含尚无法识别的消息记录，已停止生成报告，避免遗漏统计。' if code=='unclassified_provider_exclusions'
                         else '所选会话读取失败，已停止本次分析。')
                raise QQIndependentError('qq_analysis_'+code,message+'（错误码：qq_analysis_'+code+'）') from None
            yield QQIndependentAcquisition(self._payload,self._confirmed,session,self._media,self._selection.recover_media)
        except BaseException:
            self._cancel.set()  # A failed source/consumer never retains a usable generation.
            raise
        finally:
            try:
                if self._payload:
                    _file(self._payload);self._payload.unlink();self._payload=None
                if self._cancelled(cancelled):self._clear()
                else:self._expire_later()
            except BaseException:
                self._cancel.set()
                self._release_worker()
                raise
            finally:
                with self._lock:self._busy=False

    def cancel(self):
        self._cancel.set()

    def _clear(self):
        self._release_worker()
        if self._timer: self._timer.cancel(); self._timer=None
        self._payload=None; self._sessions=[]; self._confirmed=None; self._media=(); self._state=ConnectionState.DISCONNECTED
        if self._root:
            _remove_run(self._root,self._parent); self._root=None
        if self._lease:
            lease=self._lease; self._lease=None; lease.__exit__(None,None,None)
        self._frozen=[]
        self._selection=None

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
