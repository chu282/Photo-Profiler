"""Isolated install/update QA; uses only disposable project-local app copies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update_helper import Processes, normalized, request_window_close

BASE = Path(__file__).resolve().parents[1]
TEMP = BASE / ".temp"
INSTALL = (TEMP / "upgrade-qa" / "installed").resolve()
OTHER = (TEMP / "upgrade-qa" / "unrelated-copy").resolve()
HELPER = BASE / "build" / "update" / "PhotoProfilerUpdate.exe"
FIXTURE = TEMP / "legacy-dist" / "Photo Profiler.exe"
SETUP = TEMP / "Photo Profiler Test Setup.exe"


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for a lifecycle condition")


def hidden(args):
    return subprocess.Popen([str(arg) for arg in args], creationflags=subprocess.CREATE_NO_WINDOW)


def run(args, timeout=40):
    process = hidden(args)
    result = process.wait(timeout=timeout)
    assert result == 0, (str(args[0]), result)


def main():
    for directory in (INSTALL, OTHER):
        assert directory.is_relative_to(BASE) and directory != BASE
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FIXTURE, directory / "Photo Profiler.exe")
    api = Processes()
    target = INSTALL / "Photo Profiler.exe"
    other = OTHER / "Photo Profiler.exe"
    unrelated = hidden([other])
    legacy = hidden([target])
    live = None
    setup_args = [SETUP, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS", f"/DIR={INSTALL}"]
    try:
        wait_for(lambda: len(api.matching(normalized(target))) == 2 and len(api.matching(normalized(other))) == 2)
        print("Legacy fixture reproduced two background processes.", flush=True)
        run(setup_args)
        wait_for(lambda: not api.matching(normalized(target)))
        assert unrelated.poll() is None and api.matching(normalized(other))
        print("Installer cleared the old wrapper and left the unrelated copy running.", flush=True)

        report = TEMP / "installed-lifecycle-qa.json"
        if report.exists():
            report.unlink()
        live = hidden([target, "--smoke-lifecycle", report])
        wait_for(lambda: report.exists() and json.loads(report.read_text()).get("started"))
        assert api.matching(normalized(target)) == {live.pid}
        duplicate = hidden([target, "--smoke-lifecycle", TEMP / "duplicate-lifecycle-qa.json"])
        assert duplicate.wait(timeout=8) == 0
        assert api.matching(normalized(target)) == {live.pid}
        print("Installed app uses one process; a second launch does not duplicate it.", flush=True)

        run(setup_args)
        assert live.wait(timeout=8) == 0
        assert json.loads(report.read_text())["closed"]
        assert report.with_suffix(".session.json").exists()
        assert not api.matching(normalized(target))
        print("Updating a running app saved its session and exited cleanly.", flush=True)

        report.unlink()
        live = hidden([target, "--smoke-lifecycle", report])
        wait_for(lambda: report.exists() and json.loads(report.read_text()).get("started"))
        request_window_close({live.pid})
        assert live.wait(timeout=8) == 0
        assert json.loads(report.read_text())["closed"]
        assert not api.matching(normalized(target))
        print("Normal window close left no background process.", flush=True)

        run([target, "--check-package", TEMP / "installed-1.11-check.json"])
        check = json.loads((TEMP / "installed-1.11-check.json").read_text())
        assert check["ok"] and check["high_resolution_export"]
        run([INSTALL / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        print("Installed package and uninstall checks passed.", flush=True)
    finally:
        # Exact installation paths only. These are the disposable copies that
        # this test created, never the user's installed application.
        for path in (target, other):
            if api.matching(normalized(path)):
                run([HELPER, path])


if __name__ == "__main__":
    main()
