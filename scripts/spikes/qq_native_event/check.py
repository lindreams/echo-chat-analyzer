"""Run self-compiled native experiments in existing Echo owned Windows Jobs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    binaries = Path(sys.argv[1]).resolve()
    root = Path(sys.argv[2]).resolve()
    root.mkdir(exist_ok=False)
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        directory = root / name
        directory.mkdir()
        os.environ[name] = str(directory)
    import qq_chat_analyzer
    project = Path(__file__).resolve().parents[3]
    assert Path(qq_chat_analyzer.__file__).resolve() == project / "src/qq_chat_analyzer/__init__.py"
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    node = shutil.which("node")
    assert node
    environment = os.environ.copy()
    environment.pop("NODE_OPTIONS", None)
    environment.pop("NODE_PATH", None)
    outcomes = []
    for scenario in ("delivery", "heap_delivery", "cancel", "timeout", "invalid_layout", "install_failure", "wrong_version", "busy_stop", "production_gate"):
        process = launch_owned_process([node, "--max-old-space-size=96", str(Path(__file__).with_suffix(".mjs")), str(binaries), scenario],
            cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 10
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise AssertionError("owned native worker deadline")
                time.sleep(0.02)
            output, _ = process.communicate(timeout=1)
            assert process.returncode == 0 and len(output) < 2048, scenario
            result = json.loads(output)
            assert result["scenario"] == scenario and result["source"] == "owned_native_fixture"
            assert result["real_qq_accessed"] is False and result["raw_data_or_keys_persisted"] is False
            assert result["authenticated_event"] == (scenario in ("delivery", "heap_delivery"))
            assert all(result[key] is True for key in ("original_entry_restored", "dll_unloaded", "native_resources_released", "host_continued"))
        finally:
            process.close_with_exit_evidence(timeout=3)
        assert process.exit_verified and process.closed
        result["owned_job_released"] = True
        outcomes.append(result)
    assert not any(path.is_file() for path in root.rglob("*"))
    receipt = {"outcomes": outcomes, "qq_54395_real_event_verified": False}
    (root / "result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
