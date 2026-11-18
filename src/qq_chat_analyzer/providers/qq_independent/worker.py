"""Owned acquisition worker. This entry never launches, adopts or ends QQ."""
from __future__ import annotations

import ctypes
from contextlib import ExitStack
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import threading
import time

from ...resources import bundled_runtime_dir
from .files import SourceError, _file, _safe, _read_unchanged
from .process import verified_process, process_creation_ticks, loaded_module
from .diagnostics import failure_record

VERSION = (9, 9, 37, 54395)
WRAPPER_SHA256 = 'fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2'


def runtime_files():
    directory = _safe(bundled_runtime_dir() / 'qq-independent')
    pins = json.loads((Path(__file__).parent / 'native-pins.json').read_text(encoding='utf-8'))
    expected = {**pins['binaries'], 'node.exe': pins['node_sha256']}
    for name, digest in expected.items():
        path = directory / name
        _file(path)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise SourceError('independent_runtime_changed')
    return directory, pins['binaries']


def resources_identity(image):
    from ...application.qq.qq_version import read_qq_resources
    resource = read_qq_resources(image)
    if resource is None or resource.version != VERSION or resource.wrapper_path is None:
        raise SourceError('exact_active_version_required')
    states = []
    for index, (path, size, modified, inode) in enumerate(resource.file_states):
        before = _file(path)
        if (before.st_size,before.st_mtime_ns,before.st_ino) != (size,modified,inode):
            raise SourceError('resource_changed')
        if index == 0 and resource.config_text is not None:
            # Login may rewrite JSON formatting. Preserve the already verified
            # semantic-resource contract, including every configuration field.
            canonical = json.dumps(json.loads(resource.config_text),sort_keys=True,separators=(',',':'))
            states.append((str(path),hashlib.sha256(canonical.encode()).hexdigest()))
            continue
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = _file(path)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (
                after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise SourceError('resource_changed')
        if path == resource.wrapper_path and digest != WRAPPER_SHA256:
            raise SourceError('module_identity_refused')
        states.append((str(path), digest))
    return resource, tuple(states)


def event_api():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenEventW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def capture(request, cancelled, status):
    directory, pins = runtime_files()
    image = _safe(Path(request['image']))
    resources, before = resources_identity(image)
    with verified_process(request['pid'], image, synchronize=True) as (api, handle):
        api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        api.WaitForSingleObject.restype=wintypes.DWORD
        if (process_creation_ticks(api, handle) != request['created'] or
                not loaded_module(api, handle, resources.wrapper_path)[1]):
            raise SourceError('selected_process_changed')
        target = {'mode':'approved-qq','version':'9.9.37-54395','image':str(image),
                  'created':str(request['created']), 'pid':request['pid'],
                  'sha256':next(digest for path,digest in before if Path(path) == image)}
        body = json.dumps({'directory':str(directory),'productionPins':pins,'target':target,
                           }, ensure_ascii=True).encode('ascii')
        if len(body) > 131072:raise SourceError('selection_refused')
        if cancelled():raise SourceError('cancelled')
        env = os.environ.copy()
        env.pop('NODE_OPTIONS', None); env.pop('NODE_PATH', None)
        process = subprocess.Popen([str(directory/'node.exe'),'--max-old-space-size=512',
                                    str(Path(__file__).parent/'js/session.mjs')],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        messages = queue.Queue(maxsize=32)
        def read():
            try:
                for _ in range(16):
                    line = process.stdout.readline(2049)
                    if not line:break
                    if len(line)>2048:
                        messages.put_nowait({'phase':'protocol_failure','failure_code':'protocol_incomplete'});break
                    messages.put_nowait(json.loads(line))
            except (OSError, ValueError):
                try:messages.put_nowait({'phase':'protocol_failure','failure_code':'protocol_invalid_json'})
                except queue.Full:pass
            except queue.Full:pass
            finally: messages.put_nowait(None)
        reader = threading.Thread(target=read, daemon=True); reader.start()
        result = None
        try:
            process.stdin.write(struct.pack('<I',len(body))+body); process.stdin.flush()
            end, stopping = time.monotonic()+380, False
            frozen_sent = False
            while True:
                try:
                    message = messages.get(timeout=.05)
                    if message is None: break
                    if not isinstance(message,dict):raise SourceError('invalid_capture_status')
                    if message.get('phase') == 'result': result = message
                    elif message.get('phase') == 'protocol_failure':
                        raise SourceError(failure_record(code=message.get('failure_code'))['failure_code'])
                    elif message.get('phase') == 'awaiting_exit':
                        if frozen_sent: raise SourceError('unexpected_snapshot_request')
                        status(message)
                        # Retain only the event in Node. Wait for this exact
                        # QQ process generation; never signal or terminate it.
                        exit_end = time.monotonic()+110
                        while True:
                            wait=api.WaitForSingleObject(handle,50)
                            if wait==0: break
                            if wait!=258: raise SourceError('process_exit_unconfirmed')
                            if cancelled():raise SourceError('cancelled')
                            if time.monotonic()>=exit_end:raise SourceError('normal_qq_exit_required')
                        from .snapshot import prepare, assert_qq_exited, _read_locked, _no_sidecars
                        assert_qq_exited()
                        # Replace the exit instruction before copying a large
                        # snapshot; the user has already completed that step.
                        status({'phase':'authenticating'})
                        selections=[]
                        sources={role:Path(request['account_directory'])/'nt_qq/nt_db'/('nt_msg.db' if role=='message' else role+'.db')
                            for role in ('message','group_info','profile_info')}
                        with ExitStack() as locks:
                            for source in sources.values():
                                _no_sidecars(source);locks.enter_context(_read_locked(source))
                            for role,source in sources.items():
                                if cancelled(): raise SourceError('cancelled')
                                frozen=prepare(source,Path(request['root']))
                                if role!='message' and frozen['size']>32*1024**2: raise SourceError('metadata_snapshot_limit')
                                selections.append({'role':role,'path':frozen['snapshot'],'sha256':frozen['sha256'],
                                    'size':frozen['size'],'output':str(Path(request['root'])/(role+'.db'))})
                            for source in sources.values(): _no_sidecars(source)
                            assert_qq_exited()
                        assert_qq_exited()
                        if cancelled(): raise SourceError('cancelled')
                        packet=json.dumps({'snapshot':selections[0],'metadata':selections[1:]},ensure_ascii=True).encode('ascii')
                        if time.monotonic()>=exit_end: raise SourceError('snapshot_deadline')
                        process.stdin.write(struct.pack('<I',len(packet))+packet);process.stdin.flush()
                        frozen_sent=True
                    elif message.get('phase') in ('armed','stopped','stop_unconfirmed'): status(message)
                    else: raise SourceError('invalid_capture_status')
                except queue.Empty: pass
                if cancelled() and not stopping:
                    stopping=True; end=min(end,time.monotonic()+6)
                    process.stdin.write(b'\x01'); process.stdin.flush()
                if time.monotonic() >= end: raise SourceError('capture_stop_unconfirmed')
            code = process.wait(timeout=3)
            if cancelled(): raise SourceError('cancelled')
            if (code or not result or not all(result.get(key) is True for key in
                    ('authenticated','complete','observation_stopped','reads_stopped','hook_disabled'))
                    or result.get('inflight') != 0):
                failure=failure_record(code=result.get('failure_code') if result else 'node_result_missing',
                    stage=result.get('failure_stage','final_check') if result else 'protocol')
                if failure['failure_code']=='worker_internal_error':
                    reason=next((reason for passed,reason in (
                        (bool(result),'node_result_missing'),
                        *((result.get(key) is True,reason) for key,reason in (
                            ('authenticated','authentication_unconfirmed'),('complete','image_incomplete'),
                            ('observation_stopped','observation_unconfirmed'),('reads_stopped','reads_unconfirmed'),
                            ('hook_disabled','hook_unconfirmed'))),
                        (result.get('inflight')==0,'inflight_unconfirmed'),(not code,'node_exit_nonzero')) if not passed),'worker_not_verified')
                    failure=failure_record(code=reason,stage='final_check')
                error=SourceError(failure['failure_code']);error.diagnostic_stage=failure['failure_stage']
                if result:
                    safe=failure_record(exit_code=result.get('loader_exit_code'))
                    error.diagnostic_exit_code=safe.get('loader_exit_code')
                    if result.get('cause_code') is not None:
                        error.diagnostic_cause_code=failure_record(cause_code=result['cause_code'])['cause_code']
                raise error
            if not frozen_sent:raise SourceError('snapshot_not_sent')
            if resources_identity(image)[1] != before:raise SourceError('resource_changed')
            if process_creation_ticks(api,handle) != request['created']:raise SourceError('process_generation_changed')
            if api.WaitForSingleObject(handle,0)!=0:raise SourceError('process_exit_unconfirmed')
            for selection in selections:
                path=Path(selection['path']);_file(path);path.unlink()
        finally:
            if process.poll() is None: process.kill()  # Our Node; never QQ.
            process.wait(timeout=3); process.stdin.close(); reader.join(timeout=2)
            if reader.is_alive(): raise SourceError('capture_reader_not_released')
            process.stdout.close()


def main(root_text):
    """Request paths are private, protected, one-shot and owned by the parent."""
    stage='admission'
    def status(value):
        nonlocal stage
        stage={'armed':'transport','stopped':'event','stop_unconfirmed':'cleanup',
               'awaiting_exit':'exit','authenticating':'snapshot'}.get(value.get('phase'),stage)
        print(json.dumps(value,ensure_ascii=True),flush=True)
    try:
        root = _safe(Path(root_text))
        request_path = root/'request.json'
        _file(request_path)
        if request_path.stat().st_size > 32768: raise SourceError('request_too_large')
        request=json.loads(request_path.read_text(encoding='ascii'))
        if request.get('kind') != 'echo-qq-independent-capture-v1': raise SourceError('request_kind_invalid')
        marker=root/'owner.json'; _file(marker)
        if root.parent.name != 'qq-independent' or not re.fullmatch(r'run-[a-f0-9]{32}',root.name): raise SourceError('owner_name_invalid')
        proof={'kind':'echo-qq-independent-v1','root':[root.parent.stat().st_dev,root.parent.stat().st_ino],
               'directory':[root.stat().st_dev,root.stat().st_ino]}
        if json.loads(marker.read_text(encoding='ascii')) != proof: raise SourceError('owner_proof_invalid')
        if not re.fullmatch(r'Local\\EchoQQIndependentStop-[a-f0-9]{32}',request.get('cancel_event','')): raise SourceError('cancel_event_name_invalid')
        if Path(request.get('root',''))!=root: raise SourceError('request_root_mismatch')
        account=_safe(Path(request['account_directory']))
        if not account.is_absolute() or not re.fullmatch(r'[1-9][0-9]{4,19}',account.name): raise SourceError('account_label_invalid')
        if account.is_relative_to(root.parent) or root.parent.is_relative_to(account): raise SourceError('workspace_overlap')
        api = event_api()
        handle = api.OpenEventW(0x00100000,False,request['cancel_event'])
        if not handle: raise SourceError('cancel_event_unavailable')
        try:
            # The process itself is placed in the parent's kill-on-close Job before
            # execution. QQ is an existing unrelated process and never joins it.
            capture(request,lambda:api.WaitForSingleObject(handle,0)==0,status)
            status({'phase':'completed','verified':True})
            return 0
        except Exception as error:
            status(failure_record(error,stage=getattr(error,'diagnostic_stage',stage)))
            return 2
        finally:
            api.CloseHandle(handle)
    except Exception as error:
        status(failure_record(error,stage=getattr(error,'diagnostic_stage',stage)))
        return 2


if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1]))
