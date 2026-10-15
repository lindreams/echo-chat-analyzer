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
