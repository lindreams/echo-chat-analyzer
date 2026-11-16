"""Single separately approved path/lock metadata probe. No hook or key capture.

Owner confirmation is experimental evidence, not product automatic binding.
No database content is read; the optional existing lock probe reads SHM metadata.
QQ is never launched, stopped, restarted, injected into or placed in our Job.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from identity_probe import (
    HERE, MODULE_HASH, SourceError, bind_paths, child, digest, emit,
    private_environment, process_candidates, process_creation_ticks,
    probe_lock_metadata, query_paths, read_owner_reference, verified_process,
)
from qq_chat_analyzer.runtime.windows_job import launch_owned_process


def validate_paths(pid, created, image, expected, *, locks):
    with verified_process(pid, image) as (api, process):
        if process_creation_ticks(api, process) != created:
            raise SourceError('process_generation_changed')
        paths = query_paths(pid, created, image)
        main = bind_paths(paths, expected)
        emit('path_binding', authorized_account_matches=True, unique_account_directory=True,
            database_path_count=len(paths), evidence='owner_confirmed_experiment',
            automatic_current_identity_proven=False)
        if locks:
            probe_lock_metadata(main)
        if bind_paths(query_paths(pid, created, image), expected) != main:
            raise SourceError('post_probe_account_binding_changed')
        if process_creation_ticks(api, process) != created:
            raise SourceError('process_generation_changed')
    emit('path_validation_complete', account_binding_rechecked=True, lock_probe_requested=locks,
         hook_installed=False, keys_extracted=False, database_content_read=False,
         production_prerequisites_complete=False)


def self_check(root, fixture_build, *, graphics, network_device):
    # Only an owned fictional process, using the existing fixture file holder.
    command = [sys.executable, HERE/'identity_probe.py', '--build-root', fixture_build, '--fixture-file-holder']
    if graphics:
        command += ['--fixture-graphics']
    if network_device:
        command += ['--fixture-network-device']
    holder = child(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        identity = json.loads(holder.stdout.readline(4096))
        if not Path(identity['main']).is_relative_to(fixture_build/'fictional'):
            raise SourceError('fixture_source_scope_invalid')
        validate_paths(identity['pid'], identity['created'], Path(identity['image']), b'100000001', locks=True)
        # Wrong owner must fail before the lock phase, using the same entry.
        try:
            validate_paths(identity['pid'], identity['created'], Path(identity['image']), b'100000002', locks=True)
        except SourceError as error:
            if error.code != 'database_account_mismatch':
                raise
        else:
            raise SourceError('fixture_wrong_owner_accepted')
        # A real SHM refusal in fictional data must retain its code AND release
        # the source. This is not a production fallback for an empty real WAL.
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(identity['main'])) as connection:
            if connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise SourceError('fixture_checkpoint_failed')
        try:
            validate_paths(identity['pid'], identity['created'], Path(identity['image']), b'100000001', locks=True)
        except SourceError as error:
            if error.code != 'checkpoint_state_invalid':
                raise
        else:
            raise SourceError('fixture_empty_wal_accepted')
    finally:
        holder.stdin.close(); holder.wait(timeout=5); holder.stdout.close()
    if holder.returncode:
        raise SourceError('fixture_source_release_failed')
    emit('path_entry_offline_verified', real_qq_accessed=False, wrong_owner_rejected=True,
         source_handles_released=True, hook_installed=False, witness_refusal_preserved=True)


def worker(args):
    if args.self_check:
        self_check(args.attempt_root, args.fixture_build_root.resolve(strict=True),
            graphics=args.fixture_graphics, network_device=args.fixture_network_device)
        return
    expected = os.environ.pop('ECHO_METADATA_OWNER', '').encode('ascii')
    if not expected.isdigit() or expected.startswith(b'0') or not 5 <= len(expected) <= 20:
        raise SourceError('independent_owner_reference_required')
    # Exclusive marker, no automated second process selection/query attempt.
    with (args.attempt_root/'path-attempt-started').open('x', encoding='ascii') as stream:
        stream.write('path/lock metadata only; no hook, key or database content\n')
    try:
        pid, created, image, resources = process_candidates()
        if digest(resources.wrapper_path) != MODULE_HASH:
            raise SourceError('module_hash_mismatch')
        validate_paths(pid, created, image, expected, locks=args.probe_locks)
    finally:
        expected = b''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt-root', type=Path, required=True)
    parser.add_argument('--approved-single-run', action='store_true')
    parser.add_argument('--probe-locks', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--fixture-build-root', type=Path)
    parser.add_argument('--fixture-graphics', action='store_true')
    parser.add_argument('--fixture-network-device', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.attempt_root.resolve(strict=True)
    if not root.is_relative_to(HERE.parents[2]/'build'):
        raise SourceError('isolated_build_root_required')
    args.attempt_root = root
    if not args.self_check and not args.approved_single_run:
        raise SourceError('separate_path_metadata_approval_required')
    if args.worker:
        worker(args)
        return
    command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--attempt-root', str(root)]
    if args.self_check:
        command += ['--self-check', '--fixture-build-root', str(args.fixture_build_root.resolve(strict=True))]
        if args.fixture_graphics:
            command += ['--fixture-graphics']
        if args.fixture_network_device:
            command += ['--fixture-network-device']
    else:
        command += ['--approved-single-run']
        if args.probe_locks:
            command += ['--probe-locks']
    environment = private_environment()
    if not args.self_check:
        environment['ECHO_METADATA_OWNER'] = read_owner_reference()
    process = launch_owned_process(command, cwd=root, env=environment, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding='ascii', external_readers=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    environment.pop('ECHO_METADATA_OWNER', None)
    def forward():
        for _ in range(16):
            line = process.stdout.readline(2049)
            if not line:
                return
            if len(line) > 2048:
                return
            print(line.rstrip(), flush=True)
    reader = threading.Thread(target=forward, daemon=True)
    process.set_external_readers((reader,)); reader.start()
    try:
        process.wait(timeout=45)
        reader.join(timeout=2)
        if process.returncode:
            raise SourceError('path_metadata_run_refused')
    finally:
        process.terminate_tree() # Only this owned worker and helpers; never QQ.
        end = time.monotonic()+4
        while process.active_process_count() and time.monotonic() < end:
            time.sleep(.01)
        if process.active_process_count():
            raise SourceError('owned_helpers_release_unconfirmed')
        reader.join(timeout=1)
        process.close_after_readers((reader,), deadline=time.monotonic()+2)
        emit('path_helpers_released', active_helpers=0, hook_installed=False,
             no_keys_or_plaintext_created=True, qq_exit_required=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        emit('refused', reason=error.code if isinstance(error, SourceError) else 'path_metadata_probe_refused')
        sys.exit(1)
