"""Synthetic-only independent QQ source spike; no real discovery or key capture.

Run from the repository root with the verified Echo interpreter/PYTHONPATH.
Reuses existing fixture builders and the unchanged production analysis path.
All databases, user directories and reports live in one owned temporary root.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


def main() -> None:
    project = Path(__file__).resolve().parents[2]
    node = shutil.which('node')
    if node is None:
        raise RuntimeError('Existing Node.js required; no automatic provisioning.')
    with tempfile.TemporaryDirectory(prefix='echo-qq-independent-synthetic-') as directory:
        root = Path(directory)
        # Isolate before importing application code; never discover user data.
        for name in ('USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP',
                     'MPLCONFIGDIR', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'):
            target = root / name.lower()
            target.mkdir()
            os.environ[name] = str(target)
        tempfile.tempdir = os.environ['TEMP']
        for name in tuple(os.environ):
            if name.startswith(('ECHO_', 'WECHAT_', 'QQ_', 'NAPCAT_')) or name == 'WX_DB_KEY':
                os.environ.pop(name)

        import qq_chat_analyzer
        assert Path(qq_chat_analyzer.__file__).resolve() == project / 'src/qq_chat_analyzer/__init__.py'
        sys.path.insert(0, str(project / 'tests'))
        from qq_db_test_data import synthetic_text_message_blob
        from test_qq_direct_main_wal_poc import _reserve_48_bytes
        from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
        from qq_chat_analyzer.application.dto import AnalysisRequestDTO, AnalysisStatus
        from qq_chat_analyzer.application.import_request import ImportRequest
        from qq_chat_analyzer.application.import_service import ImportService
        from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider

        # Explicit fixture vocabulary: exercise real jieba without depending on
        # a globally installed dictionary or changing the shared environment.
        import jieba
        dictionary = root / 'fictional-dictionary.txt'
        dictionary.write_text('fictional 10 eng\ngarden 10 eng\npicnic 10 eng\n'
                              'library 10 eng\nmeeting 10 eng\n', encoding='utf-8')
        jieba.set_dictionary(str(dictionary))

        plain, restored = root / 'fictional.db', root / 'restored.db'
        _reserve_48_bytes(plain)
        with closing(sqlite3.connect(plain)) as connection:
            for table in ('group_msg_table', 'c2c_msg_table'):
                connection.execute(f'''CREATE TABLE {table} (
                    "40001" INTEGER PRIMARY KEY, "40027" TEXT, "40030" TEXT,
                    "40033" TEXT, "40050" INTEGER, "40800" BLOB)''')
                for index, text in enumerate(('fictional garden picnic', 'fictional library meeting')):
                    connection.execute(f'INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?)',
                        (index + 1, '17', '900000001', str(100000001 + index),
                         1800000000 + index * 60, synthetic_text_message_blob(text)))
            connection.commit()
        completed = subprocess.run(
            [node, str(Path(__file__).with_name('qq_independent_codec.mjs')), str(plain), str(restored)],
            capture_output=True, text=True, check=True, timeout=30)
        codec = json.loads(completed.stdout)
        assert QQDatabaseProvider.quick_check(restored) == 'ok'
        provider = QQDatabaseProvider(restored)
        sessions = provider.list_sessions(self_uin='100000001')
        assert {session.session_type for session in sessions} == {'group', 'private'}
        stopwords = root / 'empty-stopwords.txt'
        stopwords.write_text('', encoding='utf-8')
        reports = 0
        for session in sessions:
            payload = root / f'{session.session_type}.json'
            provider.materialize_session_payload(session, payload, self_uin='100000001')
            imported = ImportService().execute(ImportRequest(input_path=payload, platform='qq'))
            assert len(imported.messages) == len(imported.rich_messages) == 2
            assert [message.text for message in imported.messages] == [
                'fictional garden picnic', 'fictional library meeting']
            assert [message.is_self for message in imported.rich_messages] == [True, False]
            result = AnalysisApplicationService().execute(AnalysisRequestDTO(
                input_path=payload, output_directory=root / session.session_type,
                stopwords_path=stopwords, conversation_kind=session.session_type))
            assert result.status == AnalysisStatus.COMPLETED
            assert result.processed_message_count == 2
            for artifact in result.artifacts:
                assert (root / session.session_type / artifact.filename).is_file()
                reports += 1
        print(json.dumps({**codec, 'production_provider_adapter_analysis': 'passed',
            'sessions': len(sessions), 'report_files': reports,
            'tokenizer_dictionary': 'synthetic_vocabulary', 'real_data_accessed': False}))
    print('Owned synthetic temporary root removed.')


if __name__ == '__main__':
    main()
