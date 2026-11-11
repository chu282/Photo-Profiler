"""Installer helper: stop only processes executing the target installation."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import time

from lifecycle import signal_shutdown


def normalized(path):
    return os.path.normcase(os.path.realpath(path))


class Processes:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]

    def matching(self, target):
        size = 4096
        while True:
            ids = (wintypes.DWORD * size)()
            used = wintypes.DWORD()
            if not self.psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(used)):
                raise ctypes.WinError(ctypes.get_last_error())
            if used.value < ctypes.sizeof(ids):
                break
            size *= 2
        matches = set()
        for pid in ids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
            if not pid or pid == os.getpid():
                continue
            handle = self.kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                continue
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(buffer))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)) and normalized(buffer.value) == target:
                    matches.add(pid)
            finally:
                self.kernel.CloseHandle(handle)
        return matches

    def terminate(self, pid, target):
        # Recheck the image path after opening a termination handle so a reused
        # PID can never redirect termination to a different application.
        handle = self.kernel.OpenProcess(0x1001, False, pid)
        if not handle:
            return
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)) and normalized(buffer.value) == target:
                self.kernel.TerminateProcess(handle, 0)
        finally:
            self.kernel.CloseHandle(handle)


def request_window_close(pids):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def close(window, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value in pids:
            user.PostMessageW(window, 0x0010, 0, 0)
        return True

    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(close, 0)


def close_installation(path, grace_seconds=5):
    path = Path(path).absolute()
    if path.suffix.casefold() != ".exe" or not path.name.casefold().startswith("photo profiler"):
        raise ValueError("Expected a Photo Profiler executable")
    target = normalized(path)
    processes = Processes()
    matches = processes.matching(target)
    if not matches:
        return True
    signal_shutdown(path)
    request_window_close(matches)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        matches = processes.matching(target)
        if not matches:
            return True
        time.sleep(0.1)
    # Older one-file releases can leave a background wrapper without a GUI.
    # The exact target path prevents touching another app or portable copy.
    for pid in processes.matching(target):
        processes.terminate(pid, target)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not processes.matching(target):
            return True
        time.sleep(0.1)
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if len(sys.argv) == 2 and close_installation(sys.argv[1]) else 1)
    except Exception:
        sys.exit(1)
