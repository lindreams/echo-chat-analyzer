"""Offline report timing at the observed row/material scale; fictional data only.

Explicit NEW work directory and pinned dictionary. No real QQ/cipher input,
account configuration or network. The caller must isolate the user environment.
"""
from contextlib import closing
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch


def main():
    project = Path(__file__).resolve().parents[2]
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
                 "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        target = root / name; target.mkdir(); os.environ[name] = str(target)
    tempfile.tempdir = os.environ["TEMP"]
    logging.disable(logging.CRITICAL)
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
    sys.path.insert(0, str(project / "tests"))
    from qq_db_test_data import synthetic_text_message_blob, scalar_field, length_delimited_field
    from test_qq_marketface_media import gif, local_only_worker
    from qq_chat_analyzer.application import import_service
    from qq_chat_analyzer.application.qq import qq_marketface_media as media
    from qq_full_read import finish_report, verify_dictionary, assert_memory_available
    dictionary = verify_dictionary(Path(sys.argv[2]))
    assert_memory_available()
    started = time.monotonic(); records = []
    with tempfile.TemporaryDirectory(prefix="fictional-report-", dir=root) as directory:
        work = Path(directory); database = work / "fixture.db"
        cache = work / "cache/100000001/nt_qq/nt_data"
        roots = []
        for year in range(2022, 2027):
            for month in range(1, 13):
                scope = cache / "Pic" / f"{year}-{month:02}" / "Ori"
                scope.mkdir(parents=True); roots.append(scope)
        image = gif(); digest = hashlib.md5(image).digest()
        (roots[0] / (digest.hex()+".gif")).write_bytes(image)
        marketface = cache / "Emoji/marketface"; pack = marketface / "17"
        pack.mkdir(parents=True); roots.append(marketface)
        cached = media.decode_cache(image)
        for index in range(1, 5677):
            (pack / index.to_bytes(16, "big").hex()).write_bytes(cached)
        pic = length_delimited_field(40800, scalar_field(45002, 2) + scalar_field(45003, 1)
            + scalar_field(45001, 7) + length_delimited_field(45503, b"fictional-pic")
            + length_delimited_field(45406, digest))
        face = length_delimited_field(40800, scalar_field(45002, 6) + scalar_field(47601, 14))
        padding = length_delimited_field(99999, b"fictional-padding" * 32)
        subjects = ("图书馆", "实验室", "课程", "论文", "社团", "操场", "食堂", "音乐", "绘画", "篮球")
        actions = ("讨论", "整理", "学习", "准备", "分享", "安排", "检查", "记录", "分析", "练习")
        def rows():
            for index in range(590238):
                # Use an alphabetic nonce: numeric counters manufacture many
                # repeated-template decisions and a different filtering load.
                value = index; nonce = ""
                for _ in range(5):
                    nonce += chr(97+value % 26); value //= 26
                text = (f"虚构同学{actions[index % 10]}{subjects[index // 10 % 10]}的计划，"
                        f"今天{subjects[index // 100 % 10]}有新的{actions[index // 1000 % 10]}内容，备注{nonce}。")
                blob = synthetic_text_message_blob(text) + padding
                if index < 58264:
                    resource = (index % 5676 + 1).to_bytes(16, "big")
                    blob += pic if index % 7 == 0 else length_delimited_field(40800,
                        scalar_field(45002, 11) + scalar_field(80810, 17) + length_delimited_field(80903, resource))
                elif index % 7 == 0:
                    blob += face
                members = 258 if index < 58264 else 538
                yield (index+1, "17", "900000001" if index % 5 else "0",
                    str(100000001+index % members), 1760000000+index*61, blob, "900000001", 2, 1)
            for index in range(27249):
                yield (590239+index, "17", "0", "0", 0 if index < 1488 else 1800000000,
                       None, "900000001", 1, 0 if index < 1488 else 1)
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('CREATE TABLE group_msg_table ("40001" INTEGER PRIMARY KEY,"40027" TEXT,'
                '"40030" TEXT,"40033" TEXT,"40050" INTEGER,"40800" BLOB,"40021" TEXT,"40011" INTEGER,"40012" INTEGER)')
            connection.executemany('INSERT INTO group_msg_table VALUES(?,?,?,?,?,?,?,?,?)', rows())
            connection.commit()
        build_ms = round((time.monotonic()-started)*1000)
        print(json.dumps({"phase": "fictional_database_ready", "rows": 617487,
            "database_bytes": database.stat().st_size, "fixture_build_ms": build_ms}), flush=True)
        report = work / "report"; report.mkdir()
        original = import_service.parse_qq_db_rich_messages_with_media_facts; parses = 0
        def counted_parse(*args, **kwargs):
            nonlocal parses
            parses += 1
            return original(*args, **kwargs)
        def status(row):
            records.append(row); print(json.dumps(row), flush=True)
        report_started = time.monotonic()
        with patch.object(media, "_worker", local_only_worker), \
                patch.object(import_service, "parse_qq_db_rich_messages_with_media_facts", counted_parse):
            outcome = finish_report(database, work, report, "900000001", "100000001", dictionary,
                on_status=status, recover_sticker_media=True, sticker_media_roots=tuple(roots))
            assert import_service.parse_qq_db_rich_messages_with_media_facts is counted_parse
        report_ms = round((time.monotonic()-report_started)*1000)
        assert import_service.parse_qq_db_rich_messages_with_media_facts is original and parses == 1
        assert outcome["selected_source_rows"] == 617487 and outcome["provider_missing_body_rows"] == 27249
        assert outcome["imported_messages"] == 590238 and outcome["report_generated"]
        receipt, = [r for r in records if r.get("phase") == "sticker_media_verification"]
        assert receipt["category_total_verified"] and receipt["media_budget_seconds"] == 45
        assert receipt["all_media_files_exist"] and receipt["usable_assets"] > 0 and not media._ACTIVE
        result = {"fictional_only": True, "single_adapter_parse": True, "report_elapsed_ms": report_ms,
            "fixture_build_ms": build_ms, "outcome": outcome, "stages": records,
            "real_qq_accessed": False, "network_accessed": False}
    result["fixture_and_report_removed"] = not work.exists()
    (root / "result.json").write_text(json.dumps(result, indent=2), encoding="ascii")
    print(json.dumps({k: v for k, v in result.items() if k not in {"stages", "outcome"}}), flush=True)


if __name__ == "__main__":
    main()
