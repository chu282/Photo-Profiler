"""Native Windows DPI setup. Must run before the first Tk window is created."""
import sys


def enable_high_dpi():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        # System awareness is supported consistently by the bundled Tk 8.6.
        # A manifest sets this for the EXE; the call also covers source runs.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


enable_high_dpi()
