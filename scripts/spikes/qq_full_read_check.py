"""One wiring regression: owned native host -> event -> codec -> real report.

Only fictional records. Reuses existing native/SQLCipher fixture builders;
does not count as real QQ, real key acquisition or large-history acceptance.
"""
from contextlib import closing
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


def main():
    project = Path(__file__).resolve().parents[2]
    build, parent, dictionary = (Path(value).resolve() for value in sys.argv[1:4])
    reserve80_seed = Path(sys.argv[4]).resolve(strict=True) if len(sys.argv) > 4 else None
    with tempfile.TemporaryDirectory(prefix="qq-full-wiring-", dir=parent) as directory:
        root = Path(directory)
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            target = root / name
            target.mkdir(); os.environ[name] = str(target)
        tempfile.tempdir = os.environ["TEMP"]
        logging.disable(logging.CRITICAL)
        import qq_chat_analyzer
        assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
        sys.path.insert(0, str(project / "tests"))
        from test_qq_direct_main_wal_poc import _reserve_48_bytes
        from qq_db_test_data import synthetic_text_message_blob
        from qq_chat_analyzer.runtime.windows_job import launch_owned_process
        from qq_full_read import (finish_report, verify_dictionary, authorized_group_partition, validate_media_roots,
            audit_adapter, audit_provider_skips)
        sys.path.insert(0, str(project / "scripts/spikes/qq_native_event"))
        from run_session import compare_resources, resource_hashes, emit
        from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
        verify_dictionary(dictionary)
        # Reproduce the actual rejection with a fictional installation: a
        # serialization/atomic-rewrite change makes QQResources unequal.
        installation = root / "installation"
        active = installation / "versions/9.9.37-54395"
        (active / "resources/app").mkdir(parents=True)
        image = installation / "QQ.exe"; image.write_bytes(b"fictional executable")
        wrapper = active / "wrapper.node"; wrapper.write_bytes(b"fictional module")
        (active / "resources/app/package.json").write_text(json.dumps({"version": "9.9.37-54395"}), encoding="ascii")
        config = installation / "versions/config.json"
        values = {"curVersion": "9.9.37-54395", "readyVersion": "", "retryTimes": 0}
        config.write_text(json.dumps(values), encoding="ascii")
        baseline = read_qq_resources(image); hashes = resource_hashes(baseline)
        replacement = config.with_suffix(".temporary")
        replacement.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="ascii")
        replacement.replace(config)
        rewritten = read_qq_resources(image)
        assert baseline != rewritten  # Previous whole-resource comparison refused.
        assert compare_resources(baseline, rewritten, hashes)["resource_identity_same"]
        assert not compare_resources(baseline, replace(rewritten, version=(9, 9, 37, 54396)), hashes)["resource_identity_same"]
        values["retryTimes"] = 1
        config.write_text(json.dumps(values), encoding="ascii")
        refused = compare_resources(baseline, read_qq_resources(image), hashes)
        assert not refused["resource_identity_same"] and refused["config_changed_fields"] == ["retryTimes"]
        values["retryTimes"] = 0
        config.write_text(json.dumps(values), encoding="ascii")
        module_state = wrapper.stat()
        wrapper.write_bytes(b"FICTIONAL MODULE")  # Same size; restore metadata to exercise the hash check.
        os.utime(wrapper, ns=(module_state.st_atime_ns, module_state.st_mtime_ns))
        assert not compare_resources(baseline, read_qq_resources(image), hashes)["resource_identity_same"]
        # A later refusal appends evidence instead of replacing the completed
        # primitive authentication record. No private values enter this file.
        receipt = root / "verification.jsonl"; receipt.touch()
        args = SimpleNamespace(_receipt=receipt)
        with redirect_stdout(io.StringIO()):
            emit({"phase": "authentication", "first_page_authenticated": True}, args)
            emit({"phase": "result", "state": "refused", "code": "input_or_generation_changed"}, args)
            emit({"phase": "armed", "remaining_login_ms": 120000,
                "login_before_utc": (datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()}, args)
            # A delayed armed status must not reopen an elapsed login window.
            emit({"phase": "armed", "remaining_login_ms": 120000,
                "login_before_utc": "2000-01-01T00:00:00+00:00"}, args)
            emit({"phase": "stopped"}, args)
        retained = [json.loads(line) for line in receipt.read_text().splitlines()]
        assert retained[0]["first_page_authenticated"] and retained[1]["state"] == "refused"
        recorded = [datetime.fromisoformat(row["recorded_utc"]) for row in retained]
        assert all(value.utcoffset().total_seconds() == 0 for value in recorded)
        assert recorded[0] <= recorded[1]
        assert retained[2]["manual_login_window_open"] and 0 < retained[2]["remaining_login_ms"] <= 120000
        assert not retained[3]["manual_login_window_open"] and retained[3]["remaining_login_ms"] == 0
        assert retained[3]["login_prompt"] == "window_elapsed_do_not_login"
        assert not retained[4]["manual_login_window_open"]
        assert retained[4]["login_prompt"] == "observation_stopped_do_not_login"
        # Exercise the actual outer Job/cwd/argv boundary. A mocked native/key
        # consumer cannot reproduce a relative build path failing before Node.
        import run_session as session_runner
        path_scope = root / "path-entry"; path_scope.mkdir()
        path_selection = path_scope / "selection.json"; path_selection.write_text("{}", encoding="ascii")
        path_input = path_scope / "input.db"; path_input.write_bytes(b"fictional encrypted input")
        path_build = root / "native"; path_build.mkdir()
        path_worker = root / "path-worker.py"
        path_worker.write_text('''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
for flag in ("executable","database","build-root","metadata-selection","cancel-event"):
    p.add_argument("--"+flag,required=True)
p.add_argument("--owned-worker",action="store_true")
a=p.parse_args()
paths=[Path(value) for value in (a.executable,a.database,a.build_root,a.metadata_selection)]
assert a.owned_worker and all(path.is_absolute() and path.exists() for path in paths)
assert Path.cwd().name.startswith("qq-owner-")
assert Path(a.build_root).is_dir() and all(path.is_file() for path in (paths[0],paths[1],paths[3]))
print(json.dumps({"phase":"worker_input_paths_verified","absolute_inputs":4}),flush=True)
''', encoding="ascii")
        path_args = SimpleNamespace(executable=str(image), database=str(path_input), build_root="native",
            metadata_selection=str(path_selection), cancel_event=None, full_snapshot=None, _receipt=None)
        path_argv = [str(path_worker), "--executable", str(image), "--database", str(path_input),
                     "--build-root", "native", "--metadata-selection", str(path_selection)]
        path_output = io.StringIO()
        with patch.object(session_runner, "__file__", str(path_worker)), patch.object(sys, "argv", path_argv), \
             patch("qq_metadata_read.selection", return_value={"fictional_selection": True}), redirect_stdout(path_output):
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                session_runner.owned_worker(path_args)
            finally:
                os.chdir(previous_cwd)
        assert any(json.loads(line).get("phase") == "worker_input_paths_verified"
                   for line in path_output.getvalue().splitlines())
        assert not list(path_scope.glob("qq-owner-*"))
        plain = root / "fixture.db"
        if reserve80_seed:
            assert reserve80_seed.stat().st_size == 4096 and reserve80_seed.read_bytes()[20] == 80
            shutil.copyfile(reserve80_seed, plain)
        else:
            _reserve_48_bytes(plain)
        with closing(sqlite3.connect(plain)) as connection:
            if reserve80_seed:
                assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            connection.execute('''CREATE TABLE group_msg_table (
              "40001" INTEGER PRIMARY KEY,"40027" TEXT,"40030" TEXT,"40033" TEXT,"40050" INTEGER,"40800" BLOB,"40021" TEXT,
              "40011" INTEGER DEFAULT 2,"40012" INTEGER DEFAULT 0)''')
            connection.executemany('INSERT INTO group_msg_table ("40001","40027","40030","40033","40050","40800","40021") VALUES(?,?,?,?,?,?,?)', [
                (1, "17", "900000001", "100000001", 1800000000, synthetic_text_message_blob("虚构校园图书馆讨论"), "900000001"),
                (2, "17", "0", "100000002", 1800000060, synthetic_text_message_blob("虚构校园课程讨论"), "900000001"),
                (3, "18", "900000002", "100000003", 1800000120, synthetic_text_message_blob("其他会话禁止进入报告"), "900000002"),
                (4, "17", "0", None, 1799827200, synthetic_text_message_blob("虚构未知身份有效讨论"), "900000001"),
                (5, "17", "0", "", 1800172800, synthetic_text_message_blob("虚构长文" * 30), "900000001"),
            ])
            connection.executemany('INSERT INTO group_msg_table VALUES(?,?,?,?,?,?,?,?,?)', [
                (6, "17", "0", "0", 0, None, "900000001", 1, 0),
                (7, "17", "0", "0", 1800259200, None, "900000001", 1, 1),
            ])
            connection.commit()
        if reserve80_seed:
            assert plain.read_bytes()[18:21] == bytes((2, 2, 80))
        env = os.environ.copy()
        env.pop("NODE_OPTIONS", None); env.pop("NODE_PATH", None)
        process = launch_owned_process([shutil.which("node"), "--max-old-space-size=96",
            str(Path(__file__).parent / "qq_native_event/session_check.mjs"), str(build), "delivery", str(plain), "metadata"],
            cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+20
            while process.poll() is None:
                assert time.monotonic() < deadline, "owned wiring deadline"
                time.sleep(0.02)
            output, _ = process.communicate(timeout=1)
            assert process.returncode == 0 and len(output) < 2048
            native = json.loads(output)
            assert native["authenticated"] and native["observation_stopped"] and native["fixture_unloaded"]
            assert native["consumer_after_verified_stop"] and native["full_snapshot"]["all_pages_authenticated"]
            assert native["metadata_independent_authentication"] and native["metadata_second_source_refused"]
        finally:
            process.close_with_exit_evidence(timeout=3)
        for role in ("group_info", "profile_info"):
            metadata_plain = root / (role + ".verified.sqlite")
            with closing(sqlite3.connect(metadata_plain.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
                assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert metadata_plain.read_bytes() == (root / "snapshot.db").read_bytes()
        report = root / "report"; report.mkdir()
        statuses = []
        def record_status(status):
            statuses.append(status)
            emit(status, args)
        from qq_chat_analyzer.application import import_service
        original_parse = import_service.parse_qq_db_rich_messages_with_media_facts
        parses = 0
        def counted_parse(*args, **kwargs):
            nonlocal parses
            parses += 1
            return original_parse(*args, **kwargs)
        with patch.object(import_service, "parse_qq_db_rich_messages_with_media_facts", counted_parse):
            outcome = finish_report(root / "snapshot.db", root, report, "900000001", "100000001", dictionary,
                on_status=record_status)
            assert parses == 1
            assert import_service.parse_qq_db_rich_messages_with_media_facts is counted_parse
        assert import_service.parse_qq_db_rich_messages_with_media_facts is original_parse
        assert [s["step"] for s in statuses if s["phase"] == "analysis_progress"] == list(range(1, 7))
        assert any(s["phase"] == "analysis_completed" and s["elapsed_ms"] >= 0 for s in statuses)
        assert outcome["selected_source_rows"] == 6 and outcome["own_messages"] == 1
        assert outcome["provider_missing_body_rows"] == 2
        assert outcome["source_unknown_rows"] == 4
        assert outcome["unknown_direction_messages"] == 2
        assert outcome["imported_messages"] == 4 and outcome["analyzed_messages"] == 3
        assert any(status.get("phase") == "provider_skipped_rows"
            and status["verified_missing_body_rows"] == 2 and status["unclassified_rows"] == 0 for status in statuses)
        assert any(status.get("stage") == "adapter_accounting" and status["accounted_rows"] == 6
            and status["provider_rows"] == 4 and status["source_directions_match"] for status in statuses)
        assert any(status.get("reason") == "accepted_missing_sender" and status["rows"] == 2
            and status["native_types"]["40011:2"] == 2 for status in statuses)
        assert any(status.get("phase") == "report_verification" and status["counts_verified"]
            and status["time_range_verified"] and status["direction_verified"]
            and status["report_own_messages"] == status["report_unknown_identity_messages"] == 1
            and not status["report_endpoints_equal_adapter"] for status in statuses)
        assert all(len(json.dumps(status)) < 2048 for status in statuses)
        assert outcome["report_generated"] and outcome["direction_verified"] and outcome["time_range_verified"]
        assert process.exit_verified and process.closed
        # Identity evidence only: these tables deliberately have no body column.
        # A partition match alone cannot authorize a conflicting/missing object.
        from qq_windows_source import SourceError
        rejected_report = root / "rejected-import"; rejected_report.mkdir()
        def conflicting_parse(raw, *, on_record):
            def altered(record, message, reason, diagnostics):
                if message is not None:
                    message = replace(message, is_self=not message.is_self)
                on_record(record, message, reason, diagnostics)
            return original_parse(raw, on_record=altered)
        with patch.object(import_service, "parse_qq_db_rich_messages_with_media_facts", conflicting_parse):
            try:
                finish_report(root / "snapshot.db", root, rejected_report, "900000001", "100000001",
                    dictionary, on_status=lambda status: None)
            except SourceError as error:
                assert error.code == "adapter_field_accounting_mismatch"
            else:
                raise AssertionError("audited field conflict reached analysis")
            assert import_service.parse_qq_db_rich_messages_with_media_facts is conflicting_parse
        assert import_service.parse_qq_db_rich_messages_with_media_facts is original_parse
        assert not tuple(rejected_report.iterdir())
        from qq_db_test_data import qq_db_record, qq_db_payload, length_delimited_field, scalar_field
        import base64
        # EXPRESSION_ONLY is also a successful report in the owning application.
        # Normal filtering may leave no lexical words; the research verifier
        # must still accept the actual counters and generated HTML/JSON.
        expressions = root / "expressions.db"
        shutil.copyfile(root / "snapshot.db", expressions)
        face = length_delimited_field(40800, scalar_field(45002, 6) + scalar_field(47601, 14))
        with closing(sqlite3.connect(expressions)) as connection:
            connection.execute('UPDATE group_msg_table SET "40800"=? WHERE "40027"=? AND "40800" IS NOT NULL', (face, "17"))
            connection.commit()
        expression_report = root / "expression-report"; expression_report.mkdir()
        expression_statuses = []
        expression_outcome = finish_report(expressions, root, expression_report,
            "900000001", "100000001", dictionary, on_status=expression_statuses.append)
        assert expression_outcome["analysis_status"] == "expression_only"
        assert expression_outcome["provider_missing_body_rows"] == 2
        assert expression_outcome["imported_messages"] == expression_outcome["analyzed_messages"] == 4
        assert expression_outcome["report_generated"]
        assert any(status.get("phase") == "report_verification" and status["counts_verified"]
            and status["direction_verified"] and status["time_range_verified"] for status in expression_statuses)
        # The independent composition must retain Rich/PIC facts and explicitly
        # reuse formal media preparation, without creating a QQ connection.
        import hashlib
        from test_qq_marketface_media import gif, local_only_worker, cdn_only_worker
        from qq_chat_analyzer.application.qq import qq_marketface_media as media
        from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
        media_db = root / "media.db"
        shutil.copyfile(root / "snapshot.db", media_db)
        image = gif(); digest = hashlib.md5(image).digest()
        pic = (scalar_field(45002, 2) + scalar_field(45003, 1)
            + scalar_field(45001, 7) + length_delimited_field(45503, b"fictional-pic")
            + length_delimited_field(45406, digest))
        mface = (scalar_field(45002, 11) + scalar_field(80810, 17)
            + length_delimited_field(80903, b"\x01" * 16))
        body = length_delimited_field(40800, pic) + length_delimited_field(40800, mface)
        with closing(sqlite3.connect(media_db)) as connection:
            connection.execute('UPDATE group_msg_table SET "40800"=? WHERE "40027"=? AND "40800" IS NOT NULL', (body, "17"))
            connection.commit()
        cache_account = root / "cache" / "100000001" / "nt_qq" / "nt_data"
        pic_root = cache_account / "Pic" / "2026-01" / "Ori"; pic_root.mkdir(parents=True)
        (pic_root / (digest.hex() + ".gif")).write_bytes(image)
        # Match the real account's 60 narrow original scopes without reading
        # real directories: the existing coalescer must preserve all scopes.
        media_roots = [pic_root]
        for year in range(2022, 2027):
            for month in range(1, 13):
                original = cache_account / "Pic" / f"{year}-{month:02}" / "Ori"
                original.mkdir(parents=True, exist_ok=True)
                if original != pic_root:
                    media_roots.append(original)
        mface_root = cache_account / "Emoji" / "marketface"
        cache = mface_root / "17" / ("01" * 16)
        cache.parent.mkdir(parents=True); cache.write_bytes(media.decode_cache(image))
        media_roots.append(mface_root)
        assert len(media_roots) == 61
        def no_qq_connection(*_args, **_kwargs):
            raise AssertionError("Independent media must not construct a QQ provider")
        for recovery in ("disabled", "local", "mock_cdn"):
            if recovery == "mock_cdn":
                cache.unlink()
            media_report = root / ("media-report-" + recovery); media_report.mkdir()
            media_statuses = []
            with patch.object(media, "_worker", cdn_only_worker if recovery == "mock_cdn" else local_only_worker), \
                    patch.object(ChatAnalyzerFacade, "_qq_connected_provider", no_qq_connection):
                media_outcome = finish_report(media_db, root, media_report,
                    "900000001", "100000001", dictionary, on_status=media_statuses.append,
                    recover_sticker_media=recovery != "disabled",
                    sticker_media_roots=tuple(media_roots) if recovery != "disabled" else ())
            chapter = json.loads((media_report / "echo-report.json").read_text("utf-8"))["stickers"]
            assert chapter["total_send_count"] == 8 and chapter["unique_material_count"] == 2
            assert chapter["covered_message_count"] == media_outcome["analyzed_messages"] == 4
            receipt, = [s for s in media_statuses if s.get("phase") == "sticker_verification"]
            assert receipt["sends"] == 8 and receipt["pic_message_facts"] == 4
            assert receipt["identity_bases"] == {"qq_pic_45406_md5": 4, "qq_marketface_pack_resource": 4}
            assets = list(chapter["assets"].values())
            assert len(assets) == 2
            if recovery == "disabled":
                assert all(not a["data_uri"] for a in assets)
            else:
                stages = [s["phase"] for s in media_statuses]
                # Leave room for the frozen full-image native receipts, final
                # result and cleanup within the outer 48-line forwarding cap.
                assert len(media_statuses)+22 <= 48
                assert stages.index("provider_materialization_completed") < stages.index("analysis_started")
                assert stages.index("analysis_completed") < stages.index("media_preparation_started")
                assert stages.index("media_preparation_completed") < stages.index("report_export_started")
                assert stages.index("report_export_completed") < stages.index("sticker_media_verification")
                assert {a["status"] for a in assets} == {"available", "preview"}
                recovery_receipt, = [s for s in media_statuses if s.get("phase") == "sticker_media_verification"]
                assert recovery_receipt["categories"] == {"pic_local": 1,
                    "mface_local" if recovery == "local" else "mface_raw200_preview": 1}
                assert recovery_receipt["animated_gif_assets"] == 2
                assert recovery_receipt["media_budget_seconds"] == 30
                assert recovery_receipt["category_total_verified"] and recovery_receipt["all_media_files_exist"]
                expected_reason = ("marketface_local_resource_verified" if recovery == "local"
                    else "marketface_cdn_raw200_resource_verified")
                assert any(a["reason"] == expected_reason for a in assets)
                for asset in assets:
                    assert (media_report / asset["data_uri"]).read_bytes() == image
                    assert asset["data_uri"] in (media_report / "echo-report.html").read_text("utf-8")
            assert not media._ACTIVE
        for bad_roots, account in (((pic_root,), "100000002"), ((pic_root.parent,), "100000001")):
            try:
                validate_media_roots(bad_roots, account)
            except SourceError as error:
                assert error.code == "media_account_scope_unconfirmed"
            else:
                raise AssertionError("Unconfirmed account or media layout accepted")
        # Do not turn uninterpretable content into a guessed normal system row.
        # Capture every disposition before refusing, including endpoint causes.
        unreadable = qq_db_record(sender_id=None, timestamp=1799827200)
        unreadable["message_blob"] = "!invalid base64"
        no_semantics = qq_db_record(sender_id=0, timestamp=1800172800)
        no_semantics["message_blob"] = ""
        malformed = qq_db_record(sender_id=None, timestamp=1800000000)
        malformed["message_blob"] = base64.b64encode(b"\x80").decode("ascii")
        opaque = qq_db_record(sender_id=None, timestamp=1800000000)
        opaque["message_blob"] = base64.b64encode(length_delimited_field(40800, scalar_field(45002, 8))).decode("ascii")
        statuses = []
        try:
            audit_adapter(qq_db_payload([unreadable, no_semantics, malformed, opaque]), 4, (0, 0, 4),
                1799827200, 1800172800, "100000001", statuses.append)
        except SourceError as error:
            assert error.code == "adapter_unclassified_records"
        else:
            raise AssertionError("unexplained skips accepted")
        assert {status["reason"]: status["rows"] for status in statuses if "reason" in status} == {
            "invalid_blob": 1, "no_supported_semantics": 2, "unresolved_sender_content": 1}
        assert any(status.get("protobuf_error_rows") == {"truncated_tag": 1} for status in statuses)
        assert any(status.get("segment_type_rows") == {"8": 1} for status in statuses)
        assert any(status.get("at_raw_first") for status in statuses)
        assert any(status.get("at_raw_last") for status in statuses)
        assert statuses[-1]["accounted_rows"] == 4 and statuses[-1]["skipped_rows"] == 4
        serialized = json.dumps(statuses)
        assert "100000001" not in serialized and "invalid base64" not in serialized
        assert "1799827200" not in serialized and all(len(json.dumps(status)) < 2048 for status in statuses)
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute('CREATE TABLE group_msg_table ("40027","40033","40050","40800")')
            connection.executemany('INSERT INTO group_msg_table VALUES(?,?,?,?)', [
                ("17", None, 1799827200, None), ("17", "0", 1800172800, b""),
                ("17", "100000002", 1800000000, "fictional invalid body"),
                ("17", "100000002", 1800000000, b"usable body"),
                ("18", None, 1800000000, None),
            ])
            statuses = []
            exclusions = audit_provider_skips(connection, "17", 1799827200, 1800172800, statuses.append)
        assert len(statuses) == 1 and statuses[0]["rows"] == 3
        assert exclusions == {"missing_body_rows": 0, "unclassified_rows": 3}
        assert statuses[0]["sender_states"] == {"null_or_missing": 1, "zero": 1, "identified": 1}
        assert statuses[0]["at_raw_first_rows"] == statuses[0]["at_raw_last_rows"] == 1
        assert "fictional invalid body" not in json.dumps(statuses) and "100000002" not in json.dumps(statuses)
        # Only the observed structurally absent-body shape is reconciled.
        # A nonzero/missing sender, different native code or invalid body type
        # cannot borrow the known exclusion to hide a lost real message.
        for sender, body, native_type, subtype in [
            ("100000002", None, 1, 0), (None, None, 1, 0),
            ("0", None, 2, 0), ("0", None, 1, 2),
            ("0", b"", 1, 0), ("0", "invalid body", 1, 0),
        ]:
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.execute('CREATE TABLE group_msg_table ("40027","40033","40050","40800","40011","40012")')
                connection.execute('INSERT INTO group_msg_table VALUES(?,?,?,?,?,?)',
                    ("17", sender, 1800000000, body, native_type, subtype))
                exclusions = audit_provider_skips(connection, "17", 1800000000, 1800000000, lambda status: None)
            assert exclusions == {"missing_body_rows": 0, "unclassified_rows": 1}
            try:
                audit_adapter(qq_db_payload([]), 1, (0, 0, 1), 1800000000, 1800000000,
                    "100000001", lambda status: None, provider_exclusions=exclusions)
            except SourceError as error:
                assert error.code == "provider_unclassified_records"
            else:
                raise AssertionError("unproven body exclusion accepted")
        # Missing-body accounting cannot mask a lost usable row or an extra
        # materialized row: the exclusion is subtracted exactly once.
        valid = qq_db_payload([qq_db_record("fictional usable message", sender_id="100000001")], self_uin="100000001")
        exclusions = {"missing_body_rows": 1, "unclassified_rows": 0}
        for source_rows in (1, 3):
            try:
                audit_adapter(valid, source_rows, (1, 0, 1), 1760000000, 1760000000,
                    "100000001", lambda status: None, provider_exclusions=exclusions)
            except SourceError as error:
                assert error.code == "provider_record_accounting_mismatch"
            else:
                raise AssertionError("missing/duplicate provider row accepted")
        anchor = ("17", "900000001", "900000001", 1800000000)
        for row, reason in [
            (("17", "0", None, 1800000060), "authorized_partition_mismatch"),
            (("17", "900000002", "900000001", 1800000060), "authorized_partition_mismatch"),
            (("17", "900000001", "900000002", 1800000060), "authorized_partition_mismatch"),
            (("17", None, "900000001", 1800000060), "authorized_partition_mismatch"),
            (("18", "900000001", "900000001", 1800000060), "authorized_session_missing_or_ambiguous"),
            ((17, "900000001", "900000001", 1800000060), "authorized_partition_mismatch"),
        ]:
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.execute('CREATE TABLE group_msg_table ("40027", "40030", "40021", "40050")')
                connection.executemany('INSERT INTO group_msg_table VALUES(?,?,?,?)', [anchor, row])
                statuses = []
                try:
                    authorized_group_partition(connection, "900000001", statuses.append)
                except SourceError as error:
                    assert error.code == reason
                else:
                    raise AssertionError("unproven group mapping accepted")
                assert statuses[-1]["state"] == "refused"
                serialized = json.dumps(statuses)
                assert "900000001" not in serialized and "900000002" not in serialized
                assert len(serialized) < 2048
        # No 40021 in older layouts: all rows must still explicitly name group.
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute('CREATE TABLE group_msg_table ("40027", "40030", "40050")')
            connection.execute('INSERT INTO group_msg_table VALUES(?,?,?)', ("17", "900000001", 1800000000))
            assert authorized_group_partition(connection, "900000001", lambda status: None)[1] == 1
            connection.execute('INSERT INTO group_msg_table VALUES(?,?,?)', ("17", "0", 1800000060))
            try:
                authorized_group_partition(connection, "900000001", lambda status: None)
            except SourceError as error:
                assert error.code == "authorized_partition_mismatch"
            else:
                raise AssertionError("unwitnessed legacy zero accepted")
        # Retain a fixed SQLite failure receipt as well as successful integrity.
        # Corruption text can contain page contents; only its numeric code escapes.
        invalid = root / "invalid-sqlite.db"
        invalid.write_bytes(b"fictional invalid database".ljust(4096, b"\0"))
        statuses = []
        try:
            finish_report(invalid, root, report, "900000001", "100000001", dictionary, on_status=statuses.append)
        except SourceError as error:
            assert error.code == "sqlite_read_refused"
        else:
            raise AssertionError("invalid SQLite accepted")
        assert statuses[0]["phase"] == "database_verification_started"
        assert statuses[-1]["stage"] == "integrity_check" and isinstance(statuses[-1]["sqlite_errorcode"], int)
        assert "fictional invalid database" not in json.dumps(statuses)
    assert not root.exists()
    print(json.dumps({"native_event_to_real_analysis_wiring": "passed", "selected_conversation_only": True,
        "absolute_paths_survive_owned_worker_cwd": True,
        "per_database_passphrase_derivation_and_sqlite_integrity": True,
        "config_rewrite_allowed_semantic_and_module_changes_refused": True,
        "completed_stage_evidence_survives_later_failure": True,
        "single_audited_import_and_failure_restoration": True,
        "bounded_analysis_media_export_stage_receipts": True,
        "sqlite_failure_receipt_redacted": True,
        "group_mapping_witnesses_and_conflict_refusals": True,
        "missing_senders_preserved_without_fabrication": True,
        "filtered_report_count_and_time_window_reconciled": True,
        "unexplained_skips_refused_with_bounded_diagnostics": True,
        "observed_missing_body_rows_reconciled_other_shapes_refused": True,
        "expression_only_report_accepted": True,
        "rich_sticker_and_pic_facts_retained": True,
        "explicit_local_pic_and_local_or_mock_cdn_marketface_export": True,
        "media_recovery_without_qq_provider": True,
        "integrity_check": "ok", "normal_cleanup": True, "owned_job_released": True,
        "real_qq_accessed": False, "real_qq_report_verified": False}))


if __name__ == "__main__":
    main()
