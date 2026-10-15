"""Runtime-side Direct DB snapshot lifecycle tests (Phase 1).

These tests drive the real ``scripts/qq_direct_db_snapshot/snapshot.mjs``
template under the system Node runtime with a fictional in-process ``core``,
so they exercise the generation + atomic-publish scheme without any real QQ
account, passphrase or plaintext data.

The helper is an ESM module, so each test writes a small ``.mjs`` driver into a
temporary directory, points it at the real template via a file URL, feeds it a
JSON plan, and inspects the returned status objects plus the on-disk layout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_TEMPLATE = PROJECT_ROOT / "scripts" / "qq_direct_db_snapshot" / "snapshot.mjs"
PINS_PATH = PROJECT_ROOT / "scripts" / "qq_napcat_runtime_pins.json"

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason="the Direct DB snapshot helper tests require a system Node runtime",
)

# The one privacy-safe identity value every success test uses.  It is fictional
# and may freely appear in assertions here; it must never leak from the helper.
FICTIONAL_UIN = "10086"

# Stable error codes the helper is allowed to surface.
STABLE_CODES = {
    "passphrase_unavailable",
    "decrypt_failed",
    "snapshot_unstable",
    "identity_missing",
    "identity_changed",
    "manifest_failed",
    "publish_failed",
    "cleanup_failed",
    "generation_not_found",
    "recover_failed",
}

# Fragments that must never appear in a helper status object.
FORBIDDEN_STATUS_FRAGMENTS = (
    FICTIONAL_UIN,
    "\\",
    "/",
    "manifest.json",
    "snapshot.db",
    "passphrase",
)


_DRIVER = r"""import { createEchoSnapshotApi, registerEchoSnapshotApi } from '__SNAPSHOT_URL__';
import fs from 'node:fs';
import path from 'node:path';
import {syncBuiltinESMExports} from 'node:module';

const root = process.argv[2];
const config = JSON.parse(process.argv[3]);

let activeDecrypt = 0;
const metrics = { decryptCalls: 0, maxActiveDecrypt: 0 };
const diagnostics = [];
console.error = (...args) => {
  diagnostics.push(args.map(String).join(' '));
};

// Inject only staging-input stat failures/changes. Source capture, lease and
// cleanup still use their real filesystem operations; no production test seam.
const realStatSync = fs.statSync;
fs.statSync = (file, options) => {
  if (options?.bigint !== true || path.resolve(String(file)) !== path.join(root, 'staging', 'merged.db')) {
    return realStatSync(file, options);
  }
  const side = metrics.decryptCalls === 0 ? 'before' : 'after';
  const fault = config.witnessFault === side || config.witnessFault === 'both';
  if (fault && config.witnessInvalid === 'throw') {
    throw Object.assign(new Error('fictional stat failure'), {code: 'EACCES'});
  }
  const state = realStatSync(file, options);
  const result = {...state, isFile: () => state.isFile()};
  if (fault) {
    if (config.witnessInvalid === 'missing-field') delete result.ctimeNs;
    if (config.witnessInvalid === 'wrong-type') result.ino = Number(result.ino);
    if (config.witnessInvalid === 'directory') result.isFile = () => false;
    if (config.witnessInvalid === 'negative-size') result.size = -1n;
  }
  if (side === 'after' && config.witnessChangedField) {
    result[config.witnessChangedField] += 1n;
  }
  return result;
};
syncBuiltinESMExports();

function buildCore() {
  const startedAt = Date.now();
  const core = { selfInfo: { uin: config.uin }, apis: {} };
  const sourceDirectory = config.sourceDirectory;
  if (config.identityReadyAfterMs !== undefined) {
    core.selfInfo.uin = null;
    setTimeout(() => { core.selfInfo.uin = config.uin; }, config.identityReadyAfterMs);
  }
  if (config.databaseApiPresent !== false) {
    const databaseApi = {
      getNtDbDir() {
        return sourceDirectory;
      },
      hasPassphrase() {
        return config.passphrase !== false &&
          (config.passphraseReadyAfterMs === undefined ||
           Date.now() - startedAt >= config.passphraseReadyAfterMs);
      },
      async decryptDatabase(source, target) {
        metrics.decryptCalls += 1;
        activeDecrypt += 1;
        metrics.maxActiveDecrypt = Math.max(metrics.maxActiveDecrypt, activeDecrypt);
        try {
          if (config.decryptDelayMs) {
            await new Promise((resolveDelay) => setTimeout(resolveDelay, config.decryptDelayMs));
          }
          if (config.decryptInputMutation === 'append') fs.appendFileSync(source, 'fictional change');
          if (config.decryptInputMutation === 'replace') {
            const bytes = fs.readFileSync(source);
            fs.unlinkSync(source);
            fs.writeFileSync(source, bytes);
          }
          if (config.decryptInputMutation === 'delete') fs.unlinkSync(source);
          if (config.decryptCreatesUnknownFile) {
            fs.writeFileSync(path.join(path.dirname(target), 'unknown.db'), 'fictional unrelated file');
          }
          if (config.decrypt === 'false') {
            return false;
          }
          if (config.decrypt === 'throw') {
            throw new Error('fictional decrypt failure');
          }
          if (config.decrypt === 'no-output') return true;
          fs.mkdirSync(path.dirname(target), { recursive: true });
          fs.writeFileSync(target, 'fictional-sqlite-db');
          if (config.decryptMutateUin !== undefined) {
            core.selfInfo.uin = config.decryptMutateUin;
          }
          if (config.decryptCreatesManifestDir) {
            fs.mkdirSync(path.join(path.dirname(target), 'manifest.json'));
          }
          if (config.decryptCreatesGenerationsFile) {
            fs.writeFileSync(path.join(root, 'generations'), 'conflict');
          }
          return true;
        } finally {
          activeDecrypt -= 1;
        }
      },
    };
    core.apis.DatabaseApi = config.databaseApiUnknownMethodFallback
      ? new Proxy({}, {
          get(_target, methodName) {
            const realMethod = databaseApi[methodName];
            if (typeof realMethod === 'function') {
              return realMethod.bind(databaseApi);
            }
            // Mirrors the API namespace fallback, including for `then`.
            return async () => ({ result: 0, errMsg: '' });
          },
        })
      : databaseApi;
  }
  return core;
}

const out = {};

if (config.register === true) {
  const runtimeCore = { apis: {} };
  const returned = registerEchoSnapshotApi(runtimeCore);
  const api = runtimeCore.apis.EchoSnapshotApi;
  out.registered = {
    isObject: !!(api && typeof api === 'object'),
    hasAcquire: typeof (api && api.acquire) === 'function',
    hasCleanup: typeof (api && api.cleanup) === 'function',
    hasRecover: typeof (api && api.recover) === 'function',
    sameAsReturned: api === returned,
  };
  out.metrics = metrics;
  out.results = [];
  out.diagnostics = diagnostics;
} else {
  const core = buildCore();
  const api = createEchoSnapshotApi(core, {
    rootDirectory: root,
    timeouts: config.timeouts || {},
  });
  const results = [];
  for (const op of config.operations) {
    if (op.op === 'acquire') {
      results.push({ op: 'acquire', result: await api.acquire() });
    } else if (op.op === 'cleanup') {
      results.push({ op: 'cleanup', result: await api.cleanup(op.arg) });
    } else if (op.op === 'recover') {
      results.push({ op: 'recover', result: await api.recover() });
    } else if (op.op === 'concurrent-acquire') {
      const pair = await Promise.all([api.acquire(), api.acquire()]);
      results.push({ op: 'concurrent-acquire', result: pair });
    }
  }
  out.results = results;
  out.metrics = metrics;
  out.diagnostics = diagnostics;
}

console.log(JSON.stringify(out));
"""


def _snapshot_url() -> str:
    assert SNAPSHOT_TEMPLATE.is_file(), (
        "the Direct DB snapshot template is missing: "
        "scripts/qq_direct_db_snapshot/snapshot.mjs"
    )
    return SNAPSHOT_TEMPLATE.as_uri()


def _run_node(root: Path, config: dict, driver_dir: Path | None = None) -> dict:
    # ``root`` is the snapshot root handed to the helper; ``driver_dir`` is a
    # real directory where the .mjs driver can be written.  They only differ
    # when a test intentionally passes a non-directory root to trigger the
    # fail-closed cleanup path.
    driver_dir = driver_dir or root
    driver = driver_dir / "driver.mjs"
    driver.write_text(
        _DRIVER.replace("__SNAPSHOT_URL__", _snapshot_url()),
        encoding="utf-8",
    )
    from test_qq_direct_main_wal_poc import _reserve_48_bytes, _run
    with tempfile.TemporaryDirectory() as source_dir:
        source = Path(source_dir)
        plain = source / 'plain.db'
        _reserve_48_bytes(plain)
        with closing(sqlite3.connect(plain)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE entries(body TEXT)')
            writer.commit()
            writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            writer.execute("INSERT INTO entries VALUES('fictional')")
            writer.commit()
            _run('fixture', plain, Path(f'{plain}-wal'), source / 'nt_msg.db', source / 'nt_msg.db-wal')
        config = {**config, 'sourceDirectory': str(source)}
        completed = subprocess.run(
            [NODE, str(driver), str(root), json.dumps(config)],
            capture_output=True, text=True, encoding='utf-8', check=False, timeout=30,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _test_timeouts(**overrides) -> dict:
    timeouts = {"passphraseMs": 200, "identityMs": 200, "pollIntervalMs": 10}
    timeouts.update(overrides)
    return timeouts


def _generation_ids(root: Path) -> list[str]:
    generations = root / "generations"
    if not generations.is_dir():
        return []
    return sorted(entry.name for entry in generations.iterdir() if entry.is_dir())


def _read_manifest(root: Path, generation_id: str) -> dict:
    manifest = root / "generations" / generation_id / "manifest.json"
    return json.loads(manifest.read_text(encoding="utf-8"))


def _acquire(config: dict) -> dict:
    config.setdefault("operations", [{"op": "acquire"}])
    config.setdefault("timeouts", _test_timeouts())
    return config


def _seed_legacy_plaintext(root: Path) -> None:
    legacy = root / "decrypted"
    legacy.mkdir(parents=True)
    (legacy / "nt_msg.before.plaintext.db").write_bytes(b"fictional-legacy-db")
    (legacy / "nt_msg.before.plaintext.db-wal").write_bytes(b"fictional-wal")
    (legacy / "nt_msg.before.plaintext.db-shm").write_bytes(b"fictional-shm")
    (legacy / "self_identity.json").write_text(
        json.dumps({"namespace": "qq_uin", "value": FICTIONAL_UIN}),
        encoding="utf-8",
    )


def _seed_staging(root: Path) -> None:
    staging = root / "staging"
    staging.mkdir(parents=True)
    (staging / 'owner.json').write_text(json.dumps({'kind': 'echo-qq-snapshot', 'version': 1}))
    (staging / "snapshot.db").write_bytes(b"fictional-partial-db")


def _seed_generation(root: Path, generation_id: str) -> None:
    generation = root / "generations" / generation_id
    generation.mkdir(parents=True)
    (generation / "snapshot.db").write_bytes(b"fictional-snapshot-db")
    (generation / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "state": "ready",
                "database": "snapshot.db",
                "identity": {"namespace": "qq_uin", "value": FICTIONAL_UIN},
            }
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ acquire


@pytest.mark.slow_integration
def test_stable_staging_input_succeeds_without_native_telemetry(tmp_path: Path) -> None:
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN,
    }))
    result = output["results"][0]["result"]
    assert result["ok"] is True, result
    assert output["metrics"]["decryptCalls"] == 1
    assert _generation_ids(tmp_path) == [result["generation_id"]]
    assert not (tmp_path / "generations" / result["generation_id"] / "merged.db").exists()
    assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("invalid", ["throw", "missing-field", "wrong-type", "directory", "negative-size"])
@pytest.mark.slow_integration
def test_invalid_staging_witness_fails_closed(tmp_path: Path, side: str, invalid: str) -> None:
    # `both` + `throw` specifically guards against null === null admission.
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN, "witnessFault": side, "witnessInvalid": invalid,
    }))
    assert output["results"][0]["result"] == {
        "ok": False, "code": "snapshot_unstable", "status": "failed",
    }
    assert output["metrics"]["decryptCalls"] == (1 if side == "after" else 0)
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("field", ["dev", "ino", "size", "mtimeNs", "ctimeNs"])
@pytest.mark.slow_integration
def test_single_staging_witness_field_change_prevents_publication(tmp_path: Path, field: str) -> None:
    # Only the named bigint field changes: ino catches identity replacement,
    # ctimeNs catches an overwrite even when size and mtimeNs are preserved.
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN, "witnessChangedField": field,
    }))
    assert output["results"][0]["result"] == {
        "ok": False, "code": "snapshot_unstable", "status": "failed",
    }
    assert output["metrics"]["decryptCalls"] == 1
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("mutation", ["append", "replace", "delete"])
@pytest.mark.slow_integration
def test_staging_input_mutated_during_decrypt_is_rejected(tmp_path: Path, mutation: str) -> None:
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN, "decryptInputMutation": mutation,
    }))
    assert output["results"][0]["result"] == {
        "ok": False, "code": "snapshot_unstable", "status": "failed",
    }
    assert output["metrics"]["decryptCalls"] == 1
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()


@pytest.mark.parametrize("decrypt", ["false"])
@pytest.mark.slow_integration
def test_changed_staging_input_remains_unstable_when_decrypt_fails(tmp_path: Path, decrypt: str) -> None:
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN, "decrypt": decrypt, "decryptInputMutation": "append",
    }))
    assert output["results"][0]["result"] == {
        "ok": False, "code": "snapshot_unstable", "status": "failed",
    }
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()


@pytest.mark.slow_integration
def test_staging_cleanup_failure_takes_precedence(tmp_path: Path) -> None:
    failure = {"witnessFault": "after", "witnessInvalid": "throw"}
    output = _run_node(tmp_path, _acquire({
        "uin": FICTIONAL_UIN, "decryptCreatesUnknownFile": True, **failure,
    }))
    assert output["results"][0]["result"] == {
        "ok": False, "code": "cleanup_failed", "status": "failed",
    }
    assert _generation_ids(tmp_path) == []
    assert (tmp_path / "staging/owner.json").is_file()
    assert (tmp_path / "staging/unknown.db").read_text() == "fictional unrelated file"


@pytest.mark.slow_integration
def test_passphrase_unavailable_removes_previous_plaintext_first(
    tmp_path: Path,
) -> None:
    """When the passphrase never arrives, the fail-closed cleanup still ran."""
    _seed_legacy_plaintext(tmp_path)
    _seed_staging(tmp_path)
    _seed_generation(tmp_path, "previous-generation")

    output = _run_node(
        tmp_path,
        _acquire({"passphrase": False, "uin": FICTIONAL_UIN}),
    )

    result = output["results"][0]["result"]
    assert result == {"ok": False, "code": "passphrase_unavailable", "status": "failed"}
    # The previous plaintext, staging and generation were all deleted first.
    assert not (tmp_path / "decrypted").exists()
    assert not (tmp_path / "staging").exists()
    assert _generation_ids(tmp_path) == []
    assert output["metrics"]["decryptCalls"] == 0


@pytest.mark.parametrize("decrypt", ["false", "throw", "no-output"])
@pytest.mark.slow_integration
def test_decrypt_failure_never_publishes_a_ready_generation(
    tmp_path: Path,
    decrypt: str,
) -> None:
    output = _run_node(
        tmp_path,
        _acquire({"decrypt": decrypt, "uin": FICTIONAL_UIN}),
    )

    result = output["results"][0]["result"]
    assert result == {"ok": False, "code": "decrypt_failed", "status": "failed"}
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()


@pytest.mark.slow_integration
def test_missing_identity_fails_closed_without_decrypting(tmp_path: Path) -> None:
    output = _run_node(
        tmp_path,
        _acquire({"uin": None, "passphrase": True}),
    )

    result = output["results"][0]["result"]
    assert result == {"ok": False, "code": "identity_missing", "status": "failed"}
    assert _generation_ids(tmp_path) == []
    assert output["metrics"]["decryptCalls"] == 0


@pytest.mark.slow_integration
def test_identity_changed_during_decrypt_fails_closed(tmp_path: Path) -> None:
    output = _run_node(
        tmp_path,
        _acquire(
            {"uin": "111111", "decryptMutateUin": "222222", "passphrase": True}
        ),
    )

    result = output["results"][0]["result"]
    assert result == {"ok": False, "code": "identity_changed", "status": "failed"}
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()
    assert output["metrics"]["decryptCalls"] == 1


@pytest.mark.parametrize(
    "failure_flag",
    ["decryptCreatesManifestDir", "decryptCreatesGenerationsFile"],
)
@pytest.mark.slow_integration
def test_manifest_or_publish_failure_leaves_no_ready_generation(
    tmp_path: Path,
    failure_flag: str,
) -> None:
    config = _acquire({"uin": FICTIONAL_UIN, "passphrase": True})
    config[failure_flag] = True

    output = _run_node(tmp_path, config)

    result = output["results"][0]["result"]
    assert result["ok"] is False
    assert result["status"] == "failed"
    # A directory injected where the manifest should be is unknown ownership;
    # fail-closed cleanup must preserve it and report the cleanup failure.
    expected = 'cleanup_failed' if failure_flag == 'decryptCreatesManifestDir' else 'publish_failed'
    assert result["code"] == expected
    if failure_flag == 'decryptCreatesManifestDir':
        assert (tmp_path / 'staging/owner.json').is_file()
        assert (tmp_path / 'staging/manifest.json').is_dir()
    assert _generation_ids(tmp_path) == []


@pytest.mark.slow_integration
def test_success_publishes_database_and_identity_in_one_generation(
    tmp_path: Path,
) -> None:
    output = _run_node(
        tmp_path,
        _acquire({"uin": FICTIONAL_UIN, "passphrase": True}),
    )

    result = output["results"][0]["result"]
    assert result["ok"] is True
    assert result["status"] == "ready"
    generation_id = result["generation_id"]

    assert _generation_ids(tmp_path) == [generation_id]
    assert (tmp_path / "generations" / generation_id / "snapshot.db").is_file()
    manifest = _read_manifest(tmp_path, generation_id)
    assert manifest == {
        "schema_version": 1,
        "generation_id": generation_id,
        "state": "ready",
        "database": "snapshot.db",
        "identity": {"namespace": "qq_uin", "value": FICTIONAL_UIN},
    }
    # No staging or legacy plaintext survives a successful acquire.
    assert not (tmp_path / "staging").exists()
    assert not (tmp_path / "decrypted").exists()


@pytest.mark.slow_integration
def test_acquire_rejects_replaced_staging_input(
    tmp_path: Path,
) -> None:
    output = _run_node(
        tmp_path,
        _acquire({
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "traceSourceFileState": True,
            "decryptInputMutation": "replace",
        }),
    )

    assert output["results"][0]["result"] == {
        "ok": False, "code": "snapshot_unstable", "status": "failed"
    }
    assert _generation_ids(tmp_path) == []


@pytest.mark.slow_integration
def test_concurrent_acquire_never_decrypts_in_parallel(tmp_path: Path) -> None:
    output = _run_node(
        tmp_path,
        {
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "decryptDelayMs": 30,
            "timeouts": _test_timeouts(),
            "operations": [{"op": "concurrent-acquire"}],
        },
    )

    first, second = output["results"][0]["result"]
    assert first["ok"] and second["ok"]
    assert first["generation_id"] != second["generation_id"]
    assert output["metrics"]["maxActiveDecrypt"] == 1
    assert output["metrics"]["decryptCalls"] == 2
    # Only the latest generation survives; earlier ones were cleaned first.
    assert _generation_ids(tmp_path) == [second["generation_id"]]


# ------------------------------------------------------------------ cleanup


@pytest.mark.slow_integration
def test_cleanup_removes_only_the_requested_generation(tmp_path: Path) -> None:
    _seed_generation(tmp_path, "keep-me")
    _seed_generation(tmp_path, "delete-me")

    output = _run_node(
        tmp_path,
        {
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "timeouts": _test_timeouts(),
            "operations": [{"op": "cleanup", "arg": "delete-me"}],
        },
    )

    result = output["results"][0]["result"]
    assert result == {"ok": True, "status": "cleaned"}
    assert _generation_ids(tmp_path) == ["keep-me"]


@pytest.mark.slow_integration
def test_cleanup_rejects_path_traversal_and_leaves_everything_untouched(
    tmp_path: Path,
) -> None:
    _seed_generation(tmp_path, "keep-me")

    output = _run_node(
        tmp_path,
        {
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "timeouts": _test_timeouts(),
            "operations": [{"op": "cleanup", "arg": "../keep-me"}],
        },
    )

    result = output["results"][0]["result"]
    assert result == {"ok": False, "code": "generation_not_found", "status": "failed"}
    assert _generation_ids(tmp_path) == ["keep-me"]


# ------------------------------------------------------------------ recover


@pytest.mark.slow_integration
def test_recover_removes_orphan_staging_and_legacy_plaintext(
    tmp_path: Path,
) -> None:
    _seed_legacy_plaintext(tmp_path)
    _seed_staging(tmp_path)
    _seed_generation(tmp_path, "orphan-generation")

    output = _run_node(
        tmp_path,
        {
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "timeouts": _test_timeouts(),
            "operations": [{"op": "recover"}],
        },
    )

    result = output["results"][0]["result"]
    assert result == {"ok": True, "status": "recovered"}
    assert _generation_ids(tmp_path) == []
    assert not (tmp_path / "staging").exists()
    assert not (tmp_path / "decrypted").exists()


# ----------------------------------------------------------- status privacy


@pytest.mark.slow_integration
def test_status_objects_never_leak_identity_or_paths(tmp_path: Path) -> None:
    output = _run_node(
        tmp_path,
        {
            "uin": FICTIONAL_UIN,
            "passphrase": True,
            "decrypt": "throw",
            "timeouts": _test_timeouts(),
            "operations": [{"op": "acquire"}],
        },
    )

    serialized = json.dumps(output)
    for fragment in FORBIDDEN_STATUS_FRAGMENTS:
        assert fragment not in serialized, fragment


# -------------------------------------------------- registration seam (static)
