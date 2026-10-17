"""Stage 3.5J: real acquisition seam, fictional encrypted main/WAL only."""
import json
from pathlib import Path

import pytest

from test_qq_direct_main_wal_poc import fictional_source as poc_source, _interleave

pytestmark = pytest.mark.slow_integration


@pytest.fixture
def fictional_source(poc_source):
    main, wal, output = poc_source
    directory = main.parent / 'source'
    directory.mkdir()
    for path in (main, wal, Path(f'{main}-shm')):
        path.rename(directory / path.name)
    return directory / main.name, directory / wal.name, output


def _formal(program):
    program = program.replace(
        "const result = fn({mainPath, walPath, outputPath, passphrase: process.env.ECHO_POC_PASSPHRASE, onPhase});",
        """
  const {createEchoSnapshotApi} = await import('./scripts/qq_direct_db_snapshot/snapshot.mjs');
  const path = await import('node:path');
  const root = path.join(path.dirname(outputPath), 'formal-root');
  let decryptCalls=0, mainOnly=false, mergedConsumed=false;
  const core={selfInfo:{uin:'10086'},apis:{DatabaseApi:{
    hasPassphrase:()=>true, getNtDbDir:()=>path.dirname(mainPath),
    getPassphraseBuffer:()=>Buffer.from(process.env.ECHO_POC_PASSPHRASE),
    async decryptDatabase(source,target) {
      decryptCalls++; mainOnly ||= source==='nt_msg.db' || source===mainPath;
      mergedConsumed=fs.existsSync(source) && source.endsWith('merged.db');
      if(mode==='decrypt-throw') throw new Error('fictional decrypt failure');
      if(mode==='decrypt-cleanup-failure') {
        fs.writeFileSync(target,'partial'); fs.writeFileSync(path.join(path.dirname(target),'unknown.db'),'fictional'); return false;
      }
      if(mode==='decrypt-failure') {fs.writeFileSync(target,'partial'); return false;}
      const encrypted=fs.readFileSync(source), salt=encrypted.subarray(1024,1040);
      const key=pbkdf2Sync(process.env.ECHO_POC_PASSPHRASE,salt,4000,32,'sha512');
      const pages=[];
      for(let at=1024;at<encrypted.length;at+=4096) {
        const page=encrypted.subarray(at,at+4096), first=at===1024;
        const d=createDecipheriv('aes-256-cbc',key,page.subarray(4048,4064)); d.setAutoPadding(false);
        const body=Buffer.concat([d.update(page.subarray(first?16:0,4048)),d.final()]);
        const plain=Buffer.alloc(4096); body.copy(plain,first?16:0);
        if(first) Buffer.from('SQLite format 3\\0').copy(plain);
        pages.push(plain);
      }
      fs.writeFileSync(target,Buffer.concat(pages));
      if(mode==='merged-append') fs.appendFileSync(source,'fictional change');
      if(mode==='merged-replace') {fs.unlinkSync(source); fs.writeFileSync(source,encrypted);}
      if(mode==='merged-delete') fs.unlinkSync(source);
      return true;
    }
  }}};
  const api=createEchoSnapshotApi(core,{rootDirectory:root, sourceDatabaseName:path.basename(mainPath), onCapturePhase:onPhase});
  const result=await api.acquire();
  let manifest=null, encryptedPublished=false;
  if(result.ok) {
    const dir=path.join(root,'generations',result.generation_id);
    manifest=JSON.parse(fs.readFileSync(path.join(dir,'manifest.json')));
    encryptedPublished=fs.existsSync(path.join(dir,'merged.db'));
    fs.copyFileSync(path.join(dir,'snapshot.db'),outputPath);
    const cleaned=await api.cleanup(result.generation_id);
    if(!cleaned.ok) throw new Error('cleanup');
  }
  const recovered=await api.recover();
  result.decryptCalls=decryptCalls; result.mainOnly=mainOnly; result.mergedConsumed=mergedConsumed;
  result.manifest=manifest; result.encryptedPublished=encryptedPublished;
  result.stagingCleaned=!fs.existsSync(path.join(root,'staging'));
  result.recovered=recovered.ok;
""");
    return program


def _acquire(source, action="", **kwargs):
    return _interleave(source, action, driver_transform=_formal, **kwargs)


@pytest.mark.parametrize('reserve', [48, 80])
@pytest.mark.parametrize('decoder', ['fixture', 'pinned_napcat'])
def test_complex_database_preserves_committed_structures(tmp_path, reserve, decoder, monkeypatch):
    from contextlib import closing
    import hashlib
    import os
    import sqlite3
    from test_qq_direct_main_wal_poc import _reserve_48_bytes, _run
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK', '1')

    def driver(program):
        program = _formal(program)
        if decoder == 'fixture':
            return program
        # Execute only the decoder from the hash-pinned bundle, never NapCat's
        # entrypoint, account discovery, configuration or native QQ modules.
        bundle_path = os.environ.get('ECHO_TEST_NAPCAT_BUNDLE')
        if not bundle_path:
            pytest.skip('explicit hash-pinned NapCat bundle required')
        bundle = Path(bundle_path).read_bytes()
        pins = json.loads((Path(__file__).parents[1] / 'scripts/qq_napcat_runtime_pins.json').read_text())
        assert hashlib.sha256(bundle).hexdigest() in {
            pins['napcatPatch']['upstreamSha256'], pins['napcatPatch']['patchedSha256']}
        text = bundle.decode('utf8')
        start, end = text.index('const T8 = 1024'), text.index('let tu = null')
        module = ("import {pbkdf2Sync as aI, createDecipheriv as GL} from 'node:crypto';\n"
                  "import * as $e from 'node:fs';\n" + text[start:end] + '\nexport {zE};')
        decoder_start = program.index('      const encrypted=fs.readFileSync(source)')
        decoder_end = program.index('      return true;', decoder_start)
        return program[:decoder_start] + (
            "      const {zE}=await import('data:text/javascript;base64,'+Buffer.from("
            + json.dumps(module) + ").toString('base64'));\n"
            "      if(!zE(source,Buffer.from(process.env.ECHO_POC_PASSPHRASE),target)) return false;\n"
        ) + program[decoder_end:]

    # Resolve the optional real decoder before constructing the large fixture.
    if decoder == 'pinned_napcat' and not os.environ.get('ECHO_TEST_NAPCAT_BUNDLE'):
        pytest.skip('explicit hash-pinned NapCat bundle required')
    plain = tmp_path / 'fictional.db'
    _reserve_48_bytes(plain, reserve)
    source = tmp_path / 'source'
    source.mkdir()
    main, wal, output = source / 'encrypted.db', source / 'encrypted.db-wal', tmp_path / 'snapshot.db'
    writer = sqlite3.connect(plain)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY, body TEXT NOT NULL, tag TEXT)')
        writer.execute('CREATE INDEX by_body ON entries(body)')
        writer.execute('CREATE INDEX by_tag ON entries(tag, id)')
        writer.execute('CREATE TABLE keyed(k TEXT PRIMARY KEY, payload BLOB) WITHOUT ROWID')
        writer.executemany('INSERT INTO entries VALUES(?,?,?)', (
            (i, f'fictional-{i:06}-' + 'x' * (9000 if i % 13 == 0 else 300), f'tag-{i % 97}')
            for i in range(12000)))
        writer.executemany('INSERT INTO keyed VALUES(?,?)', (
            (f'fictional-key-{i}', bytes([i % 256]) * 12000) for i in range(300)))
        writer.commit()
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        writer.execute('DELETE FROM entries WHERE id % 3 = 0')
        writer.execute('DELETE FROM keyed WHERE k < ?', ('fictional-key-200',))
        writer.commit()
        # Pin an older WAL commit: the checkpoint can backfill that commit,
        # while later growth and freed pages remain in the WAL.
        reader = sqlite3.connect(plain)
        reader.execute('BEGIN')
        reader.execute('SELECT count(*) FROM entries').fetchone()
        try:
            writer.execute("UPDATE entries SET body=body || ? WHERE id % 7 = 0", ('y' * 17000,))
            writer.commit()
            writer.execute('CREATE TABLE obsolete(payload BLOB)')
            writer.executemany('INSERT INTO obsolete VALUES(?)', [(bytes(18000),)] * 400)
            writer.commit()
            writer.execute('DROP TABLE obsolete')
            writer.commit()
            checkpoint = writer.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            assert 0 < checkpoint[2] < checkpoint[1]
            assert writer.execute('PRAGMA freelist_count').fetchone()[0] > 100
            assert writer.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            expected = writer.serialize()
            assert len(expected) > 20 * 1024 * 1024
            expected_entries = writer.execute('SELECT * FROM entries ORDER BY id').fetchall()
            expected_keyed = writer.execute('SELECT * FROM keyed ORDER BY k').fetchall()
            # Force uncommitted cache spill after the selected commit. These
            # frames must never become part of the acquired generation.
            writer.execute('PRAGMA cache_size=16')
            writer.execute('BEGIN')
            writer.execute('CREATE TABLE uncommitted(payload BLOB)')
            writer.executemany('INSERT INTO uncommitted VALUES(?)', [(bytes(18000),)] * 400)
            _run('fixture', plain, Path(f'{plain}-wal'), main, wal)
            # The encrypter regenerates salts/checksums. Preserve the real
            # checkpoint counters, which are outside the WAL-index checksum.
            index_path = Path(f'{main}-shm')
            encrypted_index = bytearray(index_path.read_bytes())
            # Do not read SQLite's locked SHM bytes 120..127 on Windows.
            with Path(f'{plain}-shm').open('rb', buffering=0) as shm:
                assert shm.read(24)[16:24] == encrypted_index[16:24]
                for offset in (96, 128):
                    shm.seek(offset)
                    encrypted_index[offset:offset + 4] = shm.read(4)
            index_path.write_bytes(encrypted_index)
            assert (wal.stat().st_size - 32) // 4120 > int.from_bytes(encrypted_index[16:20], 'little')
            result = _interleave((main, wal, output), '', driver_transform=driver)
            assert result['ok'], result
            verification = result['manifest']['integrity_probe']
            assert verification['status'] == 'verified' and verification['reserve'] == reserve
            assert verification['main_mismatches'] == verification['wal_mismatches'] == 0
            assert verification['main_pages'] > 0 and verification['wal_pages'] > 0
            assert verification['header_equal']
            with closing(sqlite3.connect(f'{output.as_uri()}?mode=ro', uri=True)) as db:
                assert db.execute('PRAGMA quick_check(1)').fetchall() == [('ok',)]
                assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                assert db.execute('SELECT * FROM entries ORDER BY id').fetchall() == expected_entries
                assert db.execute('SELECT * FROM keyed ORDER BY k').fetchall() == expected_keyed
                assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name='uncommitted'").fetchall()
            # Compare all usable bytes, including overflow and freelist trunks.
            actual = output.read_bytes()
            assert len(actual) == len(expected)
            assert actual[:18] == expected[:18]
            assert actual[18:20] == b'\x01\x01'
            for at in range(0, len(expected), 4096):
                first = 20 if at == 0 else 0
                assert actual[at + first:at + 4096 - reserve] == expected[at + first:at + 4096 - reserve]
        finally:
            reader.close()
    finally:
        writer.close()


def test_formal_generation_uses_merged_input_and_keeps_manifest_contract(fictional_source):
    import sqlite3
    result = _acquire(fictional_source)
    assert result["ok"] is True, result
    assert result["mergedConsumed"] and not result["mainOnly"]
    assert not result["encryptedPublished"]
    assert result["stagingCleaned"] and result["recovered"]
    manifest = result["manifest"]
    assert manifest == {"schema_version": 1, "generation_id": result["generation_id"],
                        "state": "ready", "database": "snapshot.db",
                        "identity": {"namespace": "qq_uin", "value": "10086"}}
    with sqlite3.connect(fictional_source[2]) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT body FROM entries").fetchone() == ("fictional selected",)


def test_formal_append_after_boundary_succeeds(fictional_source):
    result = _acquire(fictional_source, "appendFrame(true);")
    assert result["ok"] is True, result
    import sqlite3
    with sqlite3.connect(fictional_source[2]) as db:
        assert db.execute("SELECT body FROM entries").fetchone() == ("fictional selected",)


@pytest.mark.parametrize('origin', ['main', 'wal', 'none'])
def test_probe_detects_decoder_difference_by_page_origin(fictional_source, monkeypatch, origin):
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK', '1')

    def driver(program):
        program = _formal(program).replace(
            "  const core={selfInfo:",
            "  const borrowed=Buffer.from(process.env.ECHO_POC_PASSPHRASE);\n  const core={selfInfo:",
        ).replace('getPassphraseBuffer:()=>Buffer.from(process.env.ECHO_POC_PASSPHRASE)',
                  'getPassphraseBuffer:()=>borrowed')
        if origin != 'none':
            # This fixture takes page 1 from main and page 2 from WAL. Change
            # a usable byte without disturbing finalizer's header invariants.
            offset = 110 if origin == 'main' else 4096 + 110
            program = program.replace('fs.writeFileSync(target,Buffer.concat(pages));',
                f'const altered=Buffer.concat(pages); altered[{offset}]^=1; fs.writeFileSync(target,altered);')
        return program.replace('  const recovered=await api.recover();',
            "  if(!borrowed.equals(Buffer.from(process.env.ECHO_POC_PASSPHRASE))) throw new Error('borrowed credential modified');\n"
            '  const recovered=await api.recover();')

    result = _interleave(fictional_source, '', driver_transform=driver)
    assert result['ok'], result
    verification = result['manifest']['integrity_probe']
    assert verification == {'status': 'verified', 'pages': 2, 'reserve': 48,
        'main_pages': 1, 'wal_pages': 1, 'main_mismatches': int(origin == 'main'),
        'wal_mismatches': int(origin == 'wal'), 'header_equal': True}
    assert 'fictional-local-passphrase' not in json.dumps(result)
    assert result['stagingCleaned'] and result['recovered'] and not result['encryptedPublished']


def test_published_single_file_needs_no_wal_or_shm(fictional_source):
    """A merged WAL image must remain readable when sidecars cannot be created."""
    import sqlite3
    from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider

    main, wal, output = fictional_source
    original = (main.read_bytes(), wal.read_bytes())
    def driver(program):
        return _formal(program).replace(
            'fs.writeFileSync(target,Buffer.concat(pages));',
            "fs.writeFileSync(target,Buffer.concat(pages));fs.copyFileSync(target,outputPath+'.raw');")

    result = _interleave(fictional_source, 'appendFrame(false);', driver_transform=driver)
    assert result['ok'], result
    # Deterministically deny SQLite's auxiliary file namespace, without changing
    # the user's ACLs or requiring administrator privileges on Windows.
    Path(f'{output}-wal').mkdir()
    Path(f'{output}-shm').mkdir()
    assert QQDatabaseProvider.quick_check(output) == 'ok'
    with sqlite3.connect(f'{output.as_uri()}?mode=ro', uri=True) as reader:
        assert reader.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert reader.execute('SELECT body FROM entries').fetchone() == ('fictional selected',)
    header = output.read_bytes()[:100]
    assert header[18:20] == b'\x01\x01'
    assert header[20] == 48
    assert int.from_bytes(header[28:32], 'big') == output.stat().st_size // 4096
    raw = Path(f'{output}.raw').read_bytes()
    final = output.read_bytes()
    assert raw[18:20] == b'\x02\x02'
    assert raw[:18] == final[:18] and raw[20:] == final[20:]
    assert main.read_bytes() == original[0]
    assert wal.read_bytes().startswith(original[1])


@pytest.mark.parametrize('mutation', [
    "fs.truncateSync(target,4096);",
    "fs.appendFileSync(target,Buffer.alloc(4096));",
    "const b=fs.readFileSync(target);b[0]^=1;fs.writeFileSync(target,b);",
    "const b=fs.readFileSync(target);b[19]=3;fs.writeFileSync(target,b);",
    "const b=fs.readFileSync(target);b[19]=1;fs.writeFileSync(target,b);",
    "const b=fs.readFileSync(target);b.writeUInt32BE(99,28);fs.writeFileSync(target,b);",
    "fs.writeFileSync(target+'-wal','fictional unexpected WAL');",
    "fs.linkSync(target,outputPath+'.alias');",
])
def test_invalid_decrypted_image_is_not_published(fictional_source, mutation):
    def driver(program):
        return _formal(program).replace(
            'fs.writeFileSync(target,Buffer.concat(pages));',
            'fs.writeFileSync(target,Buffer.concat(pages));' + mutation)

    result = _interleave(fictional_source, '', driver_transform=driver)
    assert not result['ok'] and result['code'] == 'decrypt_failed', result
    assert result['manifest'] is None
    assert result['stagingCleaned'] and result['recovered']
    assert not fictional_source[2].exists()


@pytest.mark.parametrize('corrupt', [False, True])
def test_encrypted_wal_capture_reaches_sessions_and_report(tmp_path, corrupt, monkeypatch):
    """Drive synthetic encrypted pages through publication and the real facade."""
    import sqlite3
    from contextlib import closing
    from test_qq_direct_main_wal_poc import _reserve_48_bytes, _run
    from test_qq_direct_database_facade import _create_plaintext_snapshot
    from qq_direct_db_testing import FakeSnapshotRuntime
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource, AnalysisConfig, FacadeError
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseImportService
    from qq_chat_analyzer.providers import qq_snapshot_integrity_probe as probe

    monkeypatch.setattr(probe, '_claimed', False)
    monkeypatch.setattr(probe, '_pending', None)
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK', '1')
    result_file = tmp_path / 'safe-result.json'
    monkeypatch.setenv('ECHO_QQ_INTEGRITY_CHECK_OUTPUT', str(result_file))

    plain, output = tmp_path / 'plain.db', tmp_path / 'snapshot.db'
    source = tmp_path / 'source'
    source.mkdir()
    main, wal = source / 'encrypted.db', source / 'encrypted.db-wal'
    _reserve_48_bytes(plain)
    _create_plaintext_snapshot(plain)
    with closing(sqlite3.connect(plain)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # Include page growth and overflow pages in the committed view.
        writer.execute('CREATE TABLE padding(body TEXT)')
        writer.execute('INSERT INTO padding VALUES (?)', ('fictional ' * 9000,))
        writer.execute('UPDATE group_msg_table SET "40050"="40050"+1')
        writer.commit()
        _run('fixture', plain, Path(f'{plain}-wal'), main, wal)
        captured = _acquire((main, wal, output))
        assert captured['ok']
        verification = captured['manifest']['integrity_probe']
        assert verification['status'] == 'verified'
        assert verification['main_mismatches'] == verification['wal_mismatches'] == 0
        assert verification['header_equal']
    if corrupt:
        data = bytearray(output.read_bytes())
        data[4096] = 0xff  # Invalid b-tree page type; a valid header cannot hide it.
        output.write_bytes(data)
    runtime = FakeSnapshotRuntime(tmp_path / 'consumer', snapshot_path=output)
    runtime.manifest_overrides = {'integrity_probe': verification}
    facade = ChatAnalyzerFacade(
        qq_service=QQDirectDatabaseImportService(runtime_client=runtime),
        analysis_service=AnalysisApplicationService(),
        stopwords_directory=Path(__file__).resolve().parents[1],
    )
    if corrupt:
        with pytest.raises(FacadeError) as caught:
            facade.list_sessions(ChatSource.QQ)
        assert caught.value.code == 'qq_direct_snapshot_invalid'
    else:
        sessions = {s.session_type: s for s in facade.list_sessions(ChatSource.QQ)}
        assert set(sessions) == {'group', 'private'}
        for kind, session in sessions.items():
            outcome = facade.analyze_session(ChatSource.QQ, session.session_id,
                                            AnalysisConfig(output_directory=tmp_path / f'{kind}-report'))
            assert outcome.result.processed_message_count == 1
            assert outcome.report_path.is_file()
    assert runtime.cleaned == runtime.acquired
    assert not any((runtime.root / 'generations').glob('*'))
    result = json.loads(result_file.read_text())
    assert result['initial_check'] == ('failed' if corrupt else 'ok')
    assert result['category'] == ('btree' if corrupt else 'ok')
    assert result['cleanup'] == 'confirmed'
    assert result['repeat_matches']
    assert result['page_verification'] == verification


@pytest.mark.parametrize('mode', ['merged-append', 'merged-replace'])
def test_formal_changed_decrypt_input_never_publishes(fictional_source, mode):
    result = _acquire(fictional_source, mode=mode)
    assert result['ok'] is False and result['code'] == 'snapshot_unstable'
    assert result['decryptCalls'] == 1 and result['mergedConsumed']
    assert result['manifest'] is None and not result['encryptedPublished']
    assert result['stagingCleaned'] and result['recovered']
    assert not fictional_source[2].exists()


@pytest.mark.parametrize("action", [
    "const b=fs.readFileSync(mainPath); b[1100]^=1; fs.writeFileSync(mainPath,b);",
    "const b=fs.readFileSync(mainPath+'-shm'); b.writeUInt32LE(1,128); fs.writeFileSync(mainPath+'-shm',b);",
    "fs.truncateSync(walPath,32);",
    "const b=fs.readFileSync(walPath); fs.renameSync(walPath,walPath+'.retired'); fs.writeFileSync(walPath,b);",
])
def test_formal_invalid_capture_fails_closed_without_decrypt(fictional_source, action):
    result = _acquire(fictional_source, action, phase="main_baseline_read")
    assert result["ok"] is False, result
    assert result["code"] == "snapshot_unstable"
    assert result["decryptCalls"] == 0 and not result["mainOnly"]
    assert result["stagingCleaned"] and result["recovered"]
    assert not fictional_source[2].exists()


@pytest.mark.parametrize('mode', ['decrypt-failure', 'decrypt-throw'])
def test_formal_decrypt_failure_cleans_both_artifacts(fictional_source, mode):
    result = _acquire(fictional_source, mode=mode)
    assert result["ok"] is False and result["code"] == "decrypt_failed"
    assert result["decryptCalls"] == 1 and result["mergedConsumed"]
    assert result["stagingCleaned"] and result["recovered"]


def test_formal_cleanup_failure_is_reported_and_recovery_stays_closed(fictional_source):
    result = _acquire(fictional_source, mode='decrypt-cleanup-failure')
    assert not result['ok'] and result['code'] == 'cleanup_failed'
    assert not result['recovered'] and not result['stagingCleaned']
    assert (fictional_source[2].parent / 'formal-root/staging/owner.json').is_file()
    assert not fictional_source[2].exists()
