"""Standalone entry point, including a noninteractive packaging check."""
import sys


def check_package(output):
    import json
    from pathlib import Path
    import tempfile
    import threading
    import traceback
    import tkinter as tk
    from app import App
    from PIL import Image, TiffImagePlugin
    from profiler import scan

    report = {}
    root = None
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jpg"
            exif = Image.Exif()
            exif[271] = "Packaging check"
            exif[34665] = {33437: TiffImagePlugin.IFDRational(28, 10),
                           33434: TiffImagePlugin.IFDRational(1, 250),
                           34855: 400, 37386: 50,
                           36867: "2024:03:10 12:00:00"}
            Image.new("RGB", (120, 80)).save(path, exif=exif)
            result = scan([folder], True, threading.Event())
            assert len(result.photos) == 1 and not result.errors, result.errors
            assert result.photos[0].values["Focal length"] == 50
            assert result.photos[0].taken.year == 2024
            root = tk.Tk()
            root.withdraw()
            app = App(root, restore=False)
            app.result = result
            root.update_idletasks()
            assert len(app.charts) == 6
            report = {"ok": True, "metadata": True, "tk": True, "charts": 6, "display_scale": round(app.scale, 3)}
            from chart_export import export_charts
            exported = Path(folder) / "chart-export.png"
            export_charts(app, exported)
            with Image.open(exported) as png:
                assert png.format == "PNG" and abs(png.info["dpi"][0] - 300) < 1
            report["high_resolution_export"] = True
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
                user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                report["dpi_awareness"] = user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext())
                assert report["dpi_awareness"] == 1, report
    except Exception:
        report = {"ok": False, "error": traceback.format_exc()}
    finally:
        if root:
            root.destroy()
    Path(output).write_text(json.dumps(report), encoding="utf-8")
    return 0 if report.get("ok") else 1


def run_gui(test_report=None):
    import json
    import os
    from pathlib import Path
    from lifecycle import AppInstance, activate_window

    instance = AppInstance()
    try:
        if not instance.first:
            activate_window()
            return 0
        import tkinter as tk
        from app import App
        root = tk.Tk()
        if test_report:
            root.withdraw()
        app = App(root, session_path=Path(test_report).with_suffix(".session.json") if test_report else None,
                  restore=not bool(test_report), shutdown_requested=instance.shutdown_requested)
        if test_report:
            Path(test_report).write_text(json.dumps({"pid": os.getpid(), "started": True, "closed": False}))
        root.mainloop()
        # Also cover an unexpected end of the event loop, and make closing
        # idempotent so an updater and a window-close request can arrive together.
        app.close()
        if test_report:
            Path(test_report).write_text(json.dumps({"pid": os.getpid(), "started": True, "closed": True}))
        return 0
    finally:
        instance.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-package":
        sys.exit(check_package(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-lifecycle":
        sys.exit(run_gui(sys.argv[2]))
    sys.exit(run_gui())
