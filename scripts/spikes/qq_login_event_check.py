"""Focused fictional event experiment, with the existing owned Windows Job.

No real QQ mode, target PID, account discovery or database path is accepted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(exist_ok=False)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        target = root / name
        target.mkdir()
        os.environ[name] = str(target)
    project = Path(__file__).resolve().parents[2]
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process

    node = shutil.which("node")
    assert node
    environment = os.environ.copy()
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    fixture = Path(__file__).with_name("qq_login_event_fixture.mjs")
    outcomes = []
    expected = {
        "matching": ("authenticated_event", None),
        "wrong_key": ("refused", "key_not_authenticated"),
        "malformed": ("refused", "invalid_event_wire"),
        "absent": ("event_absent", None),
        "wrong_session": ("refused", "event_session_mismatch"),
        "stall": ("refused", "event_deadline_reached"),
    }
    for scenario, (state, code) in expected.items():
        process = launch_owned_process([node, "--max-old-space-size=96", str(fixture), scenario],
            cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 8
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise AssertionError("fixture worker deadline")
                time.sleep(0.02)
            output, _ = process.communicate(timeout=1)
            assert process.returncode == 0 and len(output) < 2048
            result = json.loads(output)
            assert set(result) == {"state", "code", "target_events", "child_exited", "cooperative_release",
                                   "source", "qq_54395_observed", "key_material_persisted"}
            assert result["state"] == state and result["code"] == code, (scenario, result["state"], result["code"])
            assert result["child_exited"] is True and result["key_material_persisted"] is False
            assert result["qq_54395_observed"] is False and result["source"] == "owned_fictional_child"
            if scenario in ("matching", "absent"):
                assert result["cooperative_release"] is True
        finally:
            process.close_with_exit_evidence(timeout=3)
        assert process.exit_verified and process.closed
        outcomes.append({"scenario": scenario, "state": state, "code": code, "owned_tree_released": True})
    # No fixture DB, raw packet, key or account file is produced by this run.
    assert not any(p.is_file() for p in root.rglob("*"))
    receipt = {"outcomes": outcomes, "source": "owned_fictional_child", "real_qq_accessed": False,
               "qq_54395_database_event_verified": False, "raw_data_or_keys_persisted": False}
    (root / "result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
