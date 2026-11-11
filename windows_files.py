"""Open local photos and reveal them using the Windows shell."""
import os
from pathlib import Path


def open_file(path):
    path = Path(path).absolute()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    os.startfile(str(path))


def open_folder(path):
    folder = Path(path).absolute().parent
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    os.startfile(str(folder))


def reveal_file(path):
    import ctypes
    path = Path(path).absolute()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    shell = ctypes.windll.shell32
    ole = ctypes.windll.ole32
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    shell.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong, ctypes.c_void_p]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_ulong]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    item = ctypes.c_void_p()
    try:
        result = shell.SHParseDisplayName(str(path), None, ctypes.byref(item), 0, None)
        if result >= 0:
            result = shell.SHOpenFolderAndSelectItems(item, 0, None, 0)
        if result < 0:
            raise OSError(f"Windows could not show this file (0x{result & 0xffffffff:08X}): {path}")
    finally:
        if item:
            ole.CoTaskMemFree(item)
        if initialized >= 0:
            ole.CoUninitialize()
