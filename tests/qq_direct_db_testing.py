"""Shared fictional fixtures for QQ Direct DB snapshot-lease tests.

Every database, identity and message produced here is fictional.  The fake
runtime client mirrors the frozen ``EchoSnapshotApi`` contract so service-level
tests can drive ``QQDirectDatabaseImportService.list_sessions`` without a real
NapCat bridge: ``acquire`` allocates an opaque generation under a root and
writes ``snapshot.db`` + ``manifest.json``, and ``cleanup`` removes it again.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from qq_chat_analyzer.qq_db_identity import QQ_DB_SELF_NAMESPACE


#: A fictional identity value; safe to appear in assertions, never in logs.
FICTIONAL_UIN = "10086"

#: The single generation layout the service expects under a snapshot root.
GENERATIONS_DIR_NAME = "generations"


class FakeSnapshotRuntime:
    """Configurable in-memory stand-in for the snapshot runtime client."""

    def __init__(
        self,
        root: Path,
        *,
        snapshot_path: Path | None = None,
        identity_value: str | int = FICTIONAL_UIN,
        auto_write: bool = True,
    ) -> None:
        self.root = root
        self.snapshot_path = snapshot_path
        self.identity_value = identity_value
        self.auto_write = auto_write
        self._counter = 0
        self.acquired: list[str] = []
        self.cleaned: list[str] = []
        self.recover_calls = 0
        self.recover_deadlines: list[float | None] = []
        # Override hooks for failure scenarios.
        self.acquire_error: Exception | None = None
        self.acquire_result: str | None = None
        self.cleanup_error: Exception | None = None
        self.cleanup_result: object | None = None
        self.recover_error: Exception | None = None
        self.manifest_overrides: dict | None = None

    def acquire(self) -> str:
        if self.acquire_error is not None:
            raise self.acquire_error
        if self.acquire_result is not None:
            generation_id = self.acquire_result
        else:
            self._counter += 1
            generation_id = f"gen-{self._counter:04d}"
        self.acquired.append(generation_id)
        if self.auto_write:
            self.write_generation(generation_id)
        return generation_id

    def cleanup(self, generation_id: str) -> None:
        self.cleaned.append(generation_id)
        if self.cleanup_error is not None:
            raise self.cleanup_error
        if self.cleanup_result is not None:
            return None
        shutil.rmtree(self.generation_directory(generation_id), ignore_errors=True)
        return None

    def recover(self, *, deadline: float | None = None) -> None:
        self.recover_calls += 1
        self.recover_deadlines.append(deadline)
        if self.recover_error is not None:
            raise self.recover_error
        return None

    def generation_directory(self, generation_id: str) -> Path:
        return self.root / GENERATIONS_DIR_NAME / generation_id

    def write_generation(
        self,
        generation_id: str,
        *,
        snapshot_path: Path | None = None,
        manifest_overrides: dict | None = None,
    ) -> Path:
        """Write one generation directory with a snapshot and a manifest."""
        generation = self.generation_directory(generation_id)
        generation.mkdir(parents=True, exist_ok=True)
        source = snapshot_path if snapshot_path is not None else self.snapshot_path
        if source is not None:
            shutil.copyfile(source, generation / "snapshot.db")
        else:
            (generation / "snapshot.db").write_bytes(b"fictional-snapshot-db")
        manifest = {
            "schema_version": 1,
            "generation_id": generation_id,
            "state": "ready",
            "database": "snapshot.db",
            "identity": {
                "namespace": QQ_DB_SELF_NAMESPACE,
                "value": self.identity_value,
            },
        }
        overrides = (
            manifest_overrides
            if manifest_overrides is not None
            else self.manifest_overrides
        )
        if overrides:
            manifest.update(overrides)
        (generation / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        return generation
