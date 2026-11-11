"""One GUI instance per installation, with cooperative updater shutdown."""
import ctypes
import hashlib
import os
from pathlib import Path
import sys


def identity(path):
    normalized = os.path.normcase(os.path.realpath(path))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateEventW.restype = ctypes.c_void_p
    kernel.OpenEventW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    kernel.OpenEventW.restype = ctypes.c_void_p
    kernel.SetEvent.argtypes = [ctypes.c_void_p]
    kernel.ResetEvent.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    return kernel


def signal_shutdown(path):
    kernel = kernel_api()
    event = kernel.OpenEventW(0x0002, False, "Local\\PhotoProfiler.Shutdown." + identity(path))
    if not event:
        return False
    try:
        return bool(kernel.SetEvent(event))
    finally:
        kernel.CloseHandle(event)


class AppInstance:
    def __init__(self):
        path = sys.executable if getattr(sys, "frozen", False) else Path(__file__).with_name("portable.py")
        key = identity(path)
        self.kernel = kernel_api()
        self.event = None
        self.mutex = self.kernel.CreateMutexW(None, False, "Local\\PhotoProfiler.Instance." + key)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.first = ctypes.get_last_error() != 183
        if self.first:
            self.event = self.kernel.CreateEventW(None, True, False, "Local\\PhotoProfiler.Shutdown." + key)
            if not self.event:
                self.close()
                raise ctypes.WinError(ctypes.get_last_error())
            self.kernel.ResetEvent(self.event)

    def shutdown_requested(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        if self.event:
            self.kernel.CloseHandle(self.event)
            self.event = None
        if self.mutex:
            self.kernel.CloseHandle(self.mutex)
            self.mutex = None


def activate_window():
    user = ctypes.windll.user32
    user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user.FindWindowW.restype = ctypes.c_void_p
    user.IsIconic.argtypes = [ctypes.c_void_p]
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    window = user.FindWindowW("TkTopLevel", "Photo Profiler")
    if window:
        user.ShowWindow(window, 9 if user.IsIconic(window) else 5)
        user.SetForegroundWindow(window)
