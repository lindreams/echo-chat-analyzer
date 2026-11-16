"""Owned acquisition worker. This entry never launches, adopts or ends QQ."""
from __future__ import annotations

import ctypes
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
    page, _ = _read_unchanged(Path(request['snapshot']['path']), prefix_bytes=5120)
    with verified_process(request['pid'], image) as (api, handle):
        if (process_creation_ticks(api, handle) != request['created'] or
                not loaded_module(api, handle, resources.wrapper_path)[1]):
            raise SourceError('selected_process_changed')
        target = {'mode':'approved-qq','version':'9.9.37-54395','image':str(image),
                  'created':str(request['created']), 'pid':request['pid'],
                  'sha256':next(digest for path,digest in before if Path(path) == image)}
        body = json.dumps({'directory':str(directory),'productionPins':pins,'target':target,
                           'snapshot':request['snapshot'],'metadata':request['metadata']}, ensure_ascii=True).encode('ascii')
        if len(body) > 131072 or len(page) != 5120 or cancelled():
            raise SourceError('selection_refused')
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
                    if not line or len(line) > 2048: break
                    messages.put_nowait(json.loads(line))
            except (OSError, ValueError, queue.Full): pass
            finally: messages.put_nowait(None)
        reader = threading.Thread(target=read, daemon=True); reader.start()
        result = None
        try:
            process.stdin.write(struct.pack('<I',len(body))+body+page); process.stdin.flush()
            end, stopping = time.monotonic()+265, False
            while True:
                try:
                    message = messages.get(timeout=.05)
                    if message is None: break
                    if message.get('phase') == 'result': result = message
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
                raise SourceError('capture_refused')
            if (resources_identity(image)[1] != before or
                    process_creation_ticks(api,handle) != request['created'] or
                    not loaded_module(api,handle,resources.wrapper_path)[1]):
                raise SourceError('input_or_generation_changed')
        finally:
            if process.poll() is None: process.kill()  # Our Node; never QQ.
            process.wait(timeout=3); process.stdin.close(); reader.join(timeout=2)
            if reader.is_alive(): raise SourceError('capture_reader_not_released')
            process.stdout.close()


def main(root_text):
    """Request paths are private, protected, one-shot and owned by the parent."""
    root = _safe(Path(root_text))
    request_path = root/'request.json'
    _file(request_path)
    if request_path.stat().st_size > 32768: return 2
    request=json.loads(request_path.read_text(encoding='ascii'))
    if request.get('kind') != 'echo-qq-independent-capture-v1': return 2
    marker=root/'owner.json'; _file(marker)
    if root.parent.name != 'qq-independent' or not re.fullmatch(r'run-[a-f0-9]{32}',root.name): return 2
    proof={'kind':'echo-qq-independent-v1','root':[root.parent.stat().st_dev,root.parent.stat().st_ino],
           'directory':[root.stat().st_dev,root.stat().st_ino]}
    if json.loads(marker.read_text(encoding='ascii')) != proof: return 2
    if not re.fullmatch(r'Local\\EchoQQIndependentStop-[a-f0-9]{32}',request.get('cancel_event','')): return 2
    from .snapshot import validate_prepared
    selections=[request['snapshot'],*request['metadata']]
    if len(selections)!=3: return 2
    for item,role in zip(selections,('message','group_info','profile_info'),strict=True):
        path=_safe(Path(item['path']))
        if (item.get('role')!=role or path.parent.parent!=root or
                Path(item['output'])!=root/(role+'.db')): return 2
        manifest=validate_prepared(path,item['sha256'])
        if manifest['size']!=item['size'] or role!='message' and item['size']>32*1024**2: return 2
    api = event_api()
    handle = api.OpenEventW(0x00100000,False,request['cancel_event'])
    if not handle: return 2
    def status(value):
        print(json.dumps(value,ensure_ascii=True),flush=True)
    try:
        # The process itself is placed in the parent's kill-on-close Job before
        # execution. QQ is an existing unrelated process and never joins it.
        capture(request,lambda:api.WaitForSingleObject(handle,0)==0,status)
        status({'phase':'completed','verified':True})
        return 0
    except Exception:
        status({'phase':'failed','verified':False})
        return 2
    finally:
        api.CloseHandle(handle)


if __name__ == '__main__':
    import sys
    raise SystemExit(main(sys.argv[1]))
