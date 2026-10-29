"""Build a local candidate, without release tests, installation or publication.

Machine-local tool paths live in ignored build/setup-tools.json. Always rebuild
Frozen and NapCat from current inputs; only the pinned upstream ZIP is reused.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bootstrap_qq_napcat_runtime as napcat
import package_windows_setup as setup


def isolated_environment(root: Path, dotnet: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONNOUSERSITE="1", DOTNET_ROOT=str(dotnet.parent))
    for variable, directory in (("LOCALAPPDATA", "local"), ("APPDATA", "roaming"),
                                ("USERPROFILE", "profile"), ("TEMP", "temp"), ("TMP", "temp")):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        env[variable] = str(path)
    env["PSModuleAnalysisCachePath"] = str(root / "powershell-cache")
    return env


def preflight(config: dict) -> tuple[Path, Path, Path]:
    expected = ROOT / ".venv/Scripts/python.exe"
    if Path(sys.executable).resolve() != expected.resolve():
        raise ValueError("Run with this checkout's .venv/Scripts/python.exe")
    import qq_chat_analyzer
    if Path(qq_chat_analyzer.__file__).resolve() != ROOT / "src/qq_chat_analyzer/__init__.py":
        raise ValueError("Echo import must resolve to this checkout's src")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for pin in project["optional-dependencies"]["build"] + ["velopack==" + setup.VELOPACK_VERSION]:
        name, required = pin.split("==")
        if version(name) != required:
            raise ValueError("Build dependency differs from project pin: " + name)
    from qq_chat_analyzer.version import APP_VERSION
    if APP_VERSION != project["version"]:
        raise ValueError("Refresh project metadata before building")
    dotnet, vpk, archive = (Path(config[key]).resolve() for key in ("dotnet", "vpk", "napcat_archive"))
    if not all(path.is_file() for path in (dotnet, vpk, archive)):
        raise ValueError("Configured tools/archive must exist; see DEVELOPMENT.md 4.3")
    runtime = json.loads(vpk.with_suffix(".runtimeconfig.json").read_text(encoding="utf-8"))["runtimeOptions"]
    if vpk.name != "vpk.dll" or runtime["tfm"] != "net8.0":
        raise ValueError("Use vpk tools/net8.0/any/vpk.dll, not an SDK-selected exe shim")
    with tempfile.TemporaryDirectory(prefix="echo-setup-preflight-") as temporary:
        help_text = setup._run([str(dotnet), str(vpk), "-h"],
                               env=isolated_environment(Path(temporary), dotnet))
    if not re.search(r"Velopack CLI 1\.2\.161(?:,|\s|$)", help_text):
        raise ValueError("vpk must be 1.2.161")
    # Bootstrap replaces its candidate. Never overwrite any saved user state.
    contract = json.loads((ROOT / "scripts/qq_napcat_runtime_manifest.json").read_text(encoding="utf-8"))
    candidate = ROOT / contract["target"]
    setup.portable._no_links(candidate)
    if candidate.exists():
        setup.portable._inventory(candidate)
    for name in contract["privatePaths"]:
        if (candidate / name).exists():
            raise ValueError("NapCat contains local state; preserve it before candidate building")
    return dotnet, vpk, archive


@contextmanager
def exclusive_build():
    lock = ROOT / "build/candidate-setup.lock"
    lock.parent.mkdir(exist_ok=True)
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, default=ROOT / "build/setup-tools.json")
    parser.add_argument("--output", type=Path, help="new directory; defaults to build/candidates/<unique run>")
    args = parser.parse_args()
    started = time.perf_counter()
    timings = {}
    try:
        dotnet, vpk, archive = preflight(json.loads(args.tools.read_text(encoding="utf-8")))
        timings["preflight"] = round(time.perf_counter() - started, 3)
        output = (args.output or ROOT / "build/candidates" / (time.strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8])).absolute()
        setup.portable._no_links(output)
        if ROOT == output or (ROOT in output.parents and not output.is_relative_to(ROOT / "build/candidates")):
            raise ValueError("In-repository outputs must be inside build/candidates")
        with exclusive_build():
            output.mkdir(parents=True, exist_ok=False)
            def stage(name, action):
                tick = time.perf_counter()
                result = action()
                timings[name] = round(time.perf_counter() - tick, 3)
                print(f"{name}: {timings[name]:.3f}s", flush=True)
                return result
            stage("napcat_bootstrap", lambda: napcat.build_runtime(ROOT, archive))
            env = isolated_environment(output / "isolated", dotnet)
            command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(ROOT / "scripts/build_windows_exe.ps1"), "-DistPathOverride", str(output / "dist"),
                       "-WorkPathOverride", str(output / "work")]
            def frozen():
                with (output / "frozen.log").open("w", encoding="utf-8") as log:
                    subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
            stage("frozen", frozen)
            # Explicit host + DLL avoids vpk.exe binding to the SDK used to install it.
            os.environ.update(env)
            artifact = stage("setup_and_validation", lambda: setup.package_setup(
                output / "dist/Echo", output / "setup", vpk_path=vpk, dotnet_path=dotnet,
                pack_id=setup.PRODUCTION_PACKAGE_ID, channel=setup.PRODUCTION_CHANNEL, timings=timings))
            timings["total"] = round(time.perf_counter() - started, 3)
            (output / "timings.json").write_text(json.dumps(timings, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(timings), flush=True)
            print(f"Candidate only (not release acceptance): {artifact}", flush=True)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, setup.PackageError) as error:
        print(f"Candidate build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
