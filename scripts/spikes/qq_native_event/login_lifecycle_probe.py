"""Separately approved, one-shot native login metadata experiment.

No key observer, protocol payload, database path query, WAL lock or QQ control.
Commands 1/2/3/4/q annotate user actions; they never operate QQ or prove login.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time
import uuid

from identity_probe import (SourceError, digest, emit, private_environment,
    process_candidates, read_owner_reference, native_api, process_creation_ticks)
from qq_chat_analyzer.runtime.windows_job import launch_owned_process

HERE = Path(__file__).resolve().parent
MAGIC, RECORD_MAGIC = 0x32535145, 0x314c5145
NAMES = {1: 'login_succeeded', 2: 'login_state', 3: 'logout_succeeded',
         4: 'disconnected', 5: 'connecting', 6: 'connected'}
FAILURES = {1: 'listener_role_or_pointer_invalid', 2: 'listener_source_changed',
            3: 'listener_record_limit', 4: 'listener_event_contention', 5: 'listener_identity_missing'}


def checked_build(root):
    root = root.resolve(strict=True)
    if not root.is_relative_to(HERE.parents[2]/'build'):
        raise SourceError('isolated_build_required')
    receipt = json.loads((root/'build-receipt.json').read_text(encoding='utf-8-sig'))
    if (receipt.get('login_lifecycle_metadata_only') is not True or receipt.get('identity_metadata_only') is not False
            or receipt.get('build') != '9.9.37-54395'
            or receipt.get('login_success_object_observer') != 1):
        raise SourceError('lifecycle_component_required')
    for name in ('echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll', 'echo_event_loader.exe'):
        if digest(root/name) != receipt['binaries'].get(name):
            raise SourceError('component_hash_mismatch')
    return root


class Evidence:
    """Experimental, conservative invalidation; no production identity issuer.

    Every state/transport/logout event invalidates the previous candidate. No
    guessed enum or directory can revalidate it; only a fresh success callback can.
    Operator annotations corroborate observed events and never create them.
    """
    def __init__(self, expected):
        self.expected = int(expected)
        self.sequence = self.tick = self.success_sequence = self.logout_sequence = self.logout_tick = 0
        self.current = False
        self.counts = dict.fromkeys(NAMES.values(), 0)
        self.states = {}
        self.stage = self.cut_sequence = self.cut_tick = self.first_success = 0

    def accept(self, payload):
        self.current = False
        if len(payload) != 32:
            raise SourceError('lifecycle_record_invalid')
        magic, version, sequence, kind, value, tick = struct.unpack('<4I2Q', payload)
        if magic != RECORD_MAGIC or version != 1 or sequence != self.sequence+1 or tick < self.tick:
            self.current = False
            raise SourceError('lifecycle_sequence_invalid')
        self.sequence, self.tick = sequence, tick
        if kind == 0:
            self.current = False
            raise SourceError(FAILURES.get(value, 'lifecycle_record_invalid'))
        if kind not in NAMES or sequence > 64 or (kind == 2 and value > 0xffffffff) or (kind >= 3 and value):
            raise SourceError('lifecycle_record_invalid')
        self.counts[NAMES[kind]] += 1
        # Invalidate BEFORE interpreting every event, including duplicate successes.
        self.current = False
        if kind == 1:
            if value != self.expected:
                raise SourceError('runtime_owner_mismatch')
            self.success_sequence = sequence
            self.current = True
        elif kind == 2:
            self.states[value] = self.states.get(value, 0)+1
        elif kind == 3:
            self.logout_sequence, self.logout_tick = sequence, tick
        return {'event': NAMES[kind], 'sequence': sequence,
                'current_candidate': self.current,
                **({'owner_reference_matches': True} if kind == 1 else {}),
                **({'raw_state_code': value} if kind == 2 else {})}

    def annotate(self, command, tick):
        if command == '1' and self.stage == 0 and self.current:
            self.first_success = self.success_sequence; self.stage = 1
            return 'first_login_corroborated'
        if command == '2' and self.stage == 1:
            self.cut_sequence, self.cut_tick = self.sequence, tick; self.stage = 2
            return 'logout_observation_started'
        if (command == '3' and self.stage == 2 and not self.current
                and self.logout_sequence > self.cut_sequence and self.logout_tick >= self.cut_tick):
            self.stage = 3
            return 'logout_invalidation_corroborated'
        if (command == '4' and self.stage == 3 and self.current
                and self.success_sequence > self.logout_sequence > self.first_success):
            self.stage = 4
            return 'relogin_new_candidate_corroborated'
        self.current = False
        raise SourceError('operator_phase_without_native_evidence')

    def clear(self):
        self.expected = 0; self.current = False


def frames(process):
    messages = queue.Queue(maxsize=68)
    def exact(n):
        result = bytearray()
        while len(result) < n:
            part = process.stdout.read(n-len(result))
            if not part: raise EOFError
            result.extend(part)
        return result
    def read():
        try:
            for _ in range(68):
                magic, kind, size, reserved = struct.unpack('<4I', exact(16))
                if magic != MAGIC or reserved or (kind, size) not in ((1, 0), (2, 32), (3, 16)):
                    raise ValueError
                messages.put((kind, exact(size)))
                if kind == 3: break
        except (EOFError, OSError, ValueError):
            pass
        finally: messages.put(None)
    reader = threading.Thread(target=read, daemon=True); reader.start()
    return messages, reader


def open_loader(root, pid, created, image, *, fixture):
    # This worker and every child are already inside the outer owned Job.
    # The production Job launcher deliberately accepts only DEVNULL stdin.
    return subprocess.Popen([str(root/'echo_event_loader.exe'), '--fixture' if fixture else '--approved-qq',
        str(pid), str(created), str(image), str(root/('echo_event_fixture.dll' if fixture else 'echo_event_54395.dll')),
        '9.9.37-54395'], env=private_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


def close_loader(process, reader):
    if process.poll() is None:
        process.terminate()  # Owned loader only, never QQ.
    process.wait(timeout=4)
    if reader:
        reader.join(timeout=2)
        if reader.is_alive(): raise SourceError('loader_reader_release_unconfirmed')
    for stream in (process.stdin, process.stdout):
        if stream and not stream.closed: stream.close()


def self_check(root):
    checks = 0
    finish = struct.pack('<4I', MAGIC, 1, 1, 0)
    for scenario in ('delivery', 'conflict', 'overflow', 'cancel', 'timeout', 'install_failure', 'production_gate',
                     'object_null', 'object_unreadable', 'object_zero', 'object_partial'):
        dll = 'echo_event_54395.dll' if scenario == 'production_gate' else 'echo_event_fixture.dll'
        result = subprocess.run([root/'echo_qq_event_host.exe', root/dll, scenario], env=private_environment(),
            capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or result.stdout != finish:
            emit('fixture_native_refused', scenario=scenario, returncode=result.returncode,
                 output_bytes=len(result.stdout))
            raise SourceError('lifecycle_fixture_refused')
        checks += 1
    for scenario in ('session-delivery', 'session-cancel', 'session-timeout'):
        host = subprocess.Popen([root/'echo_qq_event_host.exe', root/'echo_event_fixture.dll', scenario],
            env=private_environment(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        loader = reader = None
        try:
            magic, pid, created = struct.unpack('<IIQ', host.stdout.read(16))
            if magic != MAGIC: raise SourceError('fixture_identity_invalid')
            loader = open_loader(root, pid, created, root/'echo_qq_event_host.exe', fixture=True)
            messages, reader = frames(loader)
            loader.stdin.write(struct.pack('<4I32s', MAGIC, 54395, 2000, 0, bytes.fromhex(digest(root/'echo_qq_event_host.exe')))); loader.stdin.flush()
            ready = complete = False; count = 0; evidence = Evidence(b'100000001')
            while True:
                item = messages.get(timeout=5)
                if item is None: break
                kind, payload = item
                if kind == 1 and not ready:
                    ready = True
                    if scenario == 'session-cancel': loader.stdin.write(b'X'); loader.stdin.flush()
                elif kind == 2 and ready:
                    evidence.accept(payload); count += 1
                    if count == 7: loader.stdin.write(b'X'); loader.stdin.flush()
                elif kind == 3:
                    complete = struct.unpack('<4I', payload) == (1, 1, 0, 1)
            loader.wait(timeout=3)
            if loader.returncode or not ready or not complete or count != (7 if scenario == 'session-delivery' else 0):
                emit('fixture_transport_refused', scenario=scenario, ready=ready, complete=complete,
                     record_count=count, event_counts=evidence.counts, loader_returncode=loader.returncode)
                raise SourceError('lifecycle_transport_fixture_refused')
            tail, _ = host.communicate(timeout=5)
            if host.returncode or tail != finish: raise SourceError('fixture_component_release_unconfirmed')
            checks += 1
        finally:
            if loader: close_loader(loader, reader)
            if host.poll() is None:
                host.stdin.write(b'X'); host.stdin.flush(); host.wait(timeout=4)
            for stream in (host.stdin, host.stdout):
                if not stream.closed: stream.close()
    def record(n, kind, value=0): return struct.pack('<4I2Q', RECORD_MAGIC, 1, n, kind, value, n*10)
    evidence = Evidence(b'100000001')
    evidence.accept(record(1, 1, 100000001)); evidence.annotate('1', 10); evidence.annotate('2', 15)
    evidence.accept(record(2, 3)); assert not evidence.current
    evidence.annotate('3', 20); evidence.accept(record(3, 1, 100000001)); evidence.annotate('4', 30)
    assert evidence.stage == 4 and evidence.success_sequence != evidence.first_success
    for kind, value in ((2, 999), (3, 0), (4, 0), (5, 0), (6, 0)):
        evidence = Evidence(b'100000001'); evidence.accept(record(1, 1, 100000001))
        evidence.accept(record(2, kind, value)); assert not evidence.current
    for payload in (record(1, 1, 100000002), record(2, 1, 100000001), record(1, 0, 2)):
        try: Evidence(b'100000001').accept(payload)
        except SourceError: pass
        else: raise SourceError('lifecycle_rejection_fixture_failed')
    try: Evidence(b'100000001').annotate('1', 1)
    except SourceError: pass
    else: raise SourceError('operator_confirmation_fabricated_identity')
    emit('lifecycle_offline_verified', native_scenarios=checks, conservative_invalidation=True,
         operator_cannot_create_identity=True, real_qq_accessed=False, fixture_components_unloaded=True)


def approved_probe(root, controls):
    expected = bytearray(os.environ.pop('ECHO_METADATA_OWNER', ''), 'ascii')
    if not expected.isdigit() or expected.startswith(b'0') or not 5 <= len(expected) <= 20:
        expected[:] = b'\0'*len(expected)
        raise SourceError('independent_owner_reference_required')
    evidence = Evidence(expected)
    expected[:] = b'\0'*len(expected)
    try:
        with (root/'login-lifecycle-attempt-started').open('x', encoding='ascii') as stream:
            stream.write('one login metadata lifecycle; no key, database or chat\n')
        pid, created, image, _ = process_candidates()
        api = native_api()
        api.GetTickCount64.restype = ctypes.c_ulonglong
        generation = api.OpenProcess(0x101000, False, pid)
        if not generation:
            raise SourceError('generation_handle_unavailable')
        try:
            if process_creation_ticks(api, generation) != created:
                raise SourceError('generation_handle_unavailable')
        except BaseException:
            api.CloseHandle(generation)
            raise
        return observe_generation(root, controls, evidence, pid, created, image, api, generation)
    finally:
        evidence.clear()


def observe_generation(root, controls, evidence, pid, created, image, api, generation):
    loader = reader = None; stopped = observed = False
    reason = None
    try:
        loader = open_loader(root, pid, created, image, fixture=False)
        messages, reader = frames(loader)
        end = time.monotonic()+120
        loader.stdin.write(struct.pack('<4I32s', MAGIC, 54395, 120000, 0, bytes.fromhex(digest(image)))); loader.stdin.flush()
        ready = False; done = False; armed_tick = 0
        while time.monotonic()<end+3:
            if api.WaitForSingleObject(generation, 0) == 0:
                evidence.current = False
                raise SourceError('bound_process_exited_no_followup_injection')
            try: item = messages.get(timeout=.05)
            except queue.Empty: item = 'waiting'
            if item is None: break
            if item != 'waiting':
                kind, payload = item
                if kind == 1 and not ready:
                    ready = True
                    armed_tick = api.GetTickCount64()
                    remaining = max(0, int((end-time.monotonic())*1000))
                    if not remaining: raise SourceError('armed_window_elapsed')
                    emit('armed', remaining_observation_ms=remaining, login_prompt='login_now',
                         hook_profile='login_success_object_metadata_only', directory_scan=False, key_capture=False)
                elif kind == 2 and ready:
                    try:
                        value = evidence.accept(payload)
                        if value['event'] == 'login_succeeded' and evidence.tick <= armed_tick:
                            raise SourceError('login_callback_preceded_armed_confirmation')
                        emit('login_metadata', **value, callback_since_armed_ms=evidence.tick-armed_tick)
                    finally:
                        payload[:] = b'\0'*len(payload)
                elif kind == 3 and ready:
                    stopped = struct.unpack('<4I', payload) == (1, 1, 0, 1)
                    break
                else: raise SourceError('lifecycle_transport_invalid')
            for command in tuple(controls):
                status = api.WaitForSingleObject(controls[command], 0)
                if status == 258: continue
                if status != 0: raise SourceError('operator_control_unavailable')
                controls.pop(command)
                if command == 'q': raise SourceError('operator_cancelled')
                if not ready: raise SourceError('operator_confirmation_before_armed')
                stage = evidence.annotate(command, api.GetTickCount64())
                emit(stage, process_generation_same=True, old_candidate_invalidated=command in '34')
                if command == '4':
                    observed = True; loader.stdin.write(b'X'); loader.stdin.flush(); done = True
            if done: continue
        loader.wait(timeout=4)
        if loader.returncode or not stopped or not observed:
            raise SourceError('lifecycle_incomplete_or_stop_unconfirmed')
    except SourceError as error:
        reason = error.code
    except Exception:
        reason = 'lifecycle_probe_refused'
    finally:
        evidence.clear()
        helpers_released = loader is None
        try:
            if loader:
                if loader.poll() is None:
                    try: loader.stdin.write(b'X'); loader.stdin.flush(); loader.wait(timeout=4)
                    except (OSError, subprocess.TimeoutExpired): pass
                close_loader(loader, reader); helpers_released = True
                while reader and not messages.empty():
                    pending = messages.get_nowait()
                    if isinstance(pending, tuple):
                        if pending[0] == 3:
                            stopped = struct.unpack('<4I', pending[1]) == (1, 1, 0, 1)
                        pending[1][:] = b'\0'*len(pending[1])
            emit('lifecycle_observation_stopped', success=reason is None, reason=reason,
                 event_counts=evidence.counts, raw_state_counts=evidence.states,
                 native_stop_confirmed=stopped, loader_released=helpers_released, current_candidate_retired=True,
                 production_identity_enabled=False, directory_binding_rechecked=False)
        finally:
            # Disabled does not mean unloaded. No second injection, no QQ control.
            if loader and api.WaitForSingleObject(generation, 0) != 0:
                emit('awaiting_normal_qq_exit', component_unloaded=False, qq_controlled=False)
                release_deadline = time.monotonic()+900
                while api.WaitForSingleObject(generation, 200) == 258 and time.monotonic()<release_deadline: pass
            released = api.WaitForSingleObject(generation, 0) == 0
            api.CloseHandle(generation)
            emit('lifecycle_resources_released', bound_generation_exited=released,
                 component_unloaded=released, helpers_released=helpers_released,
                 keys_or_plaintext_created=False)
            if loader and not released: raise SourceError('bound_generation_release_unconfirmed')
    if reason: raise SourceError(reason)


def run_owned(root, *, real):
    """Use the established DEVNULL Job owner and one-shot operator events."""
    environment = private_environment()
    handles = {}
    api = native_api()
    if real:
        environment['ECHO_METADATA_OWNER'] = read_owner_reference()
    try:
        if real:
            api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            prefix = 'Local\\EchoQQLoginLifecycle-'+uuid.uuid4().hex
            for command in '1234q':
                name = prefix+'-'+command
                ctypes.set_last_error(0)
                handle = api.CreateEventW(None, True, False, name)
                if not handle: raise SourceError('operator_control_unavailable')
                handles[command] = handle
                if ctypes.get_last_error() == 183: raise SourceError('operator_control_already_exists')
                environment['ECHO_LIFECYCLE_CONTROL_'+command] = name
        command = [sys.executable, str(Path(__file__).resolve()), '--build-root', str(root), '--worker',
                   '--approved-single-run' if real else '--self-check']
        process = launch_owned_process(command, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='ascii', external_readers=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        environment.pop('ECHO_METADATA_OWNER', None)
        messages = queue.Queue(maxsize=160)
        def forward():
            try:
                for _ in range(160):
                    line = process.stdout.readline(2049)
                    if not line: break
                    if len(line) > 2048: break
                    messages.put(json.loads(line))
            except (OSError, ValueError): pass
            finally: messages.put(None)
        reader = threading.Thread(target=forward, daemon=True)
        process.set_external_readers((reader,)); reader.start()
        try:
            end = time.monotonic()+(1040 if real else 40)
            while time.monotonic()<end:
                try:
                    try: item = messages.get(timeout=.05)
                    except queue.Empty: item = 'waiting'
                    if item is None: break
                    if item != 'waiting':
                        phase = item.pop('phase')
                        emit(phase, **item)
                    if real:
                        import msvcrt
                        if msvcrt.kbhit():
                            value = msvcrt.getwch()
                            if value in '\r\n': continue
                            if value not in handles or not api.SetEvent(handles[value]):
                                api.SetEvent(handles['q'])
                                emit('operator_command_refused_stop_requested')
                except KeyboardInterrupt:
                    if not real: raise
                    if not api.SetEvent(handles['q']): raise SourceError('operator_control_unavailable')
                    emit('operator_stop_requested', awaiting_cleanup=True)
            else: raise SourceError('lifecycle_worker_deadline')
            process.wait(timeout=4)
            if process.returncode: raise SourceError('lifecycle_worker_refused')
        finally:
            process.terminate_tree()  # QQ is never a child or Job member.
            end = time.monotonic()+4
            while process.active_process_count() and time.monotonic()<end: time.sleep(.01)
            if process.active_process_count() != 0: raise SourceError('owned_helpers_release_unconfirmed')
            reader.join(timeout=2)
            process.close_after_readers((reader,), deadline=time.monotonic()+2)
            emit('owned_helpers_released', active_helpers=0)
    finally:
        environment.pop('ECHO_METADATA_OWNER', None)
        for handle in handles.values(): api.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', required=True, type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--approved-single-run', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = checked_build(args.build_root)
    if not (args.self_check ^ args.approved_single_run):
        raise SourceError('separate_login_metadata_approval_required')
    if not args.worker:
        return run_owned(root, real=args.approved_single_run)
    if args.self_check:
        return self_check(root)
    api = native_api(); controls = {}
    try:
        for command in '1234q':
            name = os.environ.pop('ECHO_LIFECYCLE_CONTROL_'+command, '')
            if not name.startswith('Local\\EchoQQLoginLifecycle-'):
                raise SourceError('operator_control_unavailable')
            handle = api.OpenEventW(0x100000, False, name)
            if not handle: raise SourceError('operator_control_unavailable')
            controls[command] = handle
        return approved_probe(root, controls.copy())
    finally:
        for handle in controls.values(): api.CloseHandle(handle)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        emit('refused', reason=error.code if isinstance(error, SourceError) else 'lifecycle_probe_refused')
        raise SystemExit(1)
