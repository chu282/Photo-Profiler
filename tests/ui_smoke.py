"""Exercise actual Tk drawing, graph toggles, and asynchronous scanning."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from app import App
from profiler import METRICS, Photo, Result
from test_profiler import make_photo


def run():
    base = Path(__file__).resolve().parents[1]
    (base / ".temp").mkdir(exist_ok=True)
    root = tk.Tk()
    if "--scale-200" in sys.argv:
        root.tk.call("tk", "scaling", 192 / 72)
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    session_file = base / ".temp" / "ui-test-session.json"
    app = App(root, session_path=session_file, restore=False)

    def settle():
        for _ in range(10):
            root.update()
            time.sleep(0.04)

    def assert_discrete(chart):
        canvas = chart.canvas
        side = canvas.coords(canvas.find_withtag("grid-side")[0])
        depth = side[2] - side[0]
        fronts = [canvas.coords(item) for item in canvas.find_withtag("bar-front")]
        ticks = [canvas.coords(item)[0] for item in canvas.find_withtag("bar-tick")]
        labels = [canvas.coords(item)[0] for item in canvas.find_withtag("bar-label")]
        for x1, _, x2, _ in fronts:
            center = (x1 + x2 + depth) / 2
            assert any(abs(center - tick) < 0.01 for tick in ticks)
            assert any(abs(center - label) < 0.01 for label in labels)
        assert all(previous[2] + depth < following[0] for previous, following in zip(fronts, fronts[1:]))

    def right_click_names(chart, front, check_actions=False):
        canvas = chart.canvas
        x1, y1, x2, y2 = canvas.coords(front)
        canvas.event_generate("<Button-3>", x=round((x1 + x2) / 2 - canvas.canvasx(0)),
                              y=round((y1 + y2) / 2 - canvas.canvasy(0)))
        settle()
        dialogs = [child for child in root.winfo_children() if isinstance(child, tk.Toplevel)]
        assert len(dialogs) == 1
        dialog = dialogs[0]
        frame = dialog.winfo_children()[0]
        tree = next(child for child in frame.winfo_children() if isinstance(child, ttk.Treeview))
        rows = [tree.item(item, "values") for item in tree.get_children()]
        if check_actions:
            first = tree.get_children()[0]
            left, top, width, height = tree.bbox(first)
            x, y = left + 10, top + height // 2
            with patch("windows_files.open_file") as opened, patch("windows_files.reveal_file") as revealed, patch("windows_files.open_folder") as folder_opened:
                for stamp in (100000, 100100):
                    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=stamp)
                    tree.event_generate("<ButtonRelease-1>", x=x, y=y, time=stamp + 30)
                assert opened.call_count == 1, opened.call_args_list
                expected = str((base / rows[0][1] / rows[0][0]).absolute())
                assert opened.call_args.args[0] == expected
                with patch.object(tk.Menu, "tk_popup") as popup:
                    tree.event_generate("<Button-3>", x=x, y=y)
                    assert popup.call_count == 1
                menu = next(child for child in tree.winfo_children() if isinstance(child, tk.Menu))
                menu.invoke(0)
                menu.invoke(1)
                menu.invoke(2)
                assert opened.call_args.args[0] == expected
                assert revealed.call_args.args[0] == expected
                assert folder_opened.call_args.args[0] == expected
                assert [menu.entrycget(index, "label") for index in (0, 1, 2, 4, 5)] == [
                    "Open", "Show in folder", "Open folder", "Copy file name", "Copy file path"]
        dialog.destroy()
        return rows

    try:
        with tempfile.TemporaryDirectory(dir=base / ".temp") as folder:
            make_photo(Path(folder) / "sample.jpg")
            app.folders = [folder]
            app.start_scan()
            deadline = time.monotonic() + 10
            while app.running and time.monotonic() < deadline:
                root.update()
                time.sleep(0.03)
            assert not app.running and len(app.result.photos) == 1
        app.result = Result(photos=[Photo(f"photo-{i}.jpg", datetime(2023, 1, 1, 12) + timedelta(days=i * 2), {
            "Aperture": [1.8, 2.8, 4, 5.6, 8][i % 5],
            "Shutter speed": [1 / 1000, 1 / 250, 1 / 60, 1 / 15][i % 4],
            "ISO": [100, 200, 400, 800, 1600][i % 5],
            "Focal length": [24, 35, 50, 85, 135][(i // 9 + i % 3) % 5],
            "Orientation": ["Portrait", "Landscape", "Square"][i % 3],
        }) for i in range(450)])
        app.status.set("450 photos · 0 without EXIF")
        app.redraw()
        settle()
        assert sum(c.winfo_ismapped() for c in app.charts.values()) == 4
        assert all(c.canvas.find_all() for m, c in app.charts.items() if app.visible[m].get())
        assert app.chart_area.winfo_height() > root.winfo_height() * 0.83
        for metric, chart in app.charts.items():
            if not app.visible[metric].get():
                continue
            fronts = chart.canvas.find_withtag("bar-front")
            ticks = chart.canvas.find_withtag("bar-tick")
            labels = chart.canvas.find_withtag("bar-label")
            assert len(ticks) == len(labels)
            assert all(chart.canvas.bbox(item)[3] <= chart.canvas.winfo_height() for item in labels)
            tick_centers = [chart.canvas.coords(tick)[0] for tick in ticks]
            text_centers = [chart.canvas.coords(text)[0] for text in labels]
            for front in fronts:
                x1, _, x2, _ = chart.canvas.coords(front)
                assert any(abs(x1 - center) < 0.01 for center in tick_centers)
                assert any(abs(x1 - center) < 0.01 for center in text_centers)
                edges = [chart.canvas.coords(line)[0] for line in chart.canvas.find_withtag("grid-floor-line")]
                assert any(abs(x1 - edge) < 0.01 for edge in edges)
            assert chart.canvas.find_withtag("grid-back")
            assert chart.canvas.find_withtag("grid-side")
            assert chart.canvas.find_withtag("grid-floor")
            assert len(chart.canvas.find_withtag("bar-percent")) == len(fronts)
            assert len(chart.canvas.find_withtag("percent-backing")) == len(fronts)
            side = chart.canvas.coords(chart.canvas.find_withtag("grid-side")[0])
            depth = side[2] - side[0]
            for percent, front in zip(chart.canvas.find_withtag("bar-percent"), fronts):
                x1, _, x2, _ = chart.canvas.coords(front)
                assert abs(chart.canvas.coords(percent)[0] - (x1 + x2 + depth) / 2) < 0.01
                assert float(chart.canvas.itemcget(percent, "angle")) == 0
        chart = app.charts["Focal length"]
        initial_width = chart.hist_width
        pointer = chart.canvas.winfo_width() // 2
        chart.wheel(SimpleNamespace(delta=120, x=pointer))
        assert chart.hist_width > initial_width
        chart.wheel(SimpleNamespace(delta=-120, x=pointer))
        assert abs(chart.hist_width - initial_width) < 0.01
        chart.reset_zoom()
        settle()
        export_path = base / ".temp" / "export-check.png"
        app.export_image(str(export_path))
        from PIL import Image
        with Image.open(export_path) as exported:
            assert exported.width > app.chart_area.winfo_width() * 2
            assert exported.height > app.chart_area.winfo_height() * 2
            assert abs(exported.info["dpi"][0] - 300) < 1
        scale_suffix = "-200" if "--scale-200" in sys.argv else ""
        ImageGrab.grab(window=root.winfo_id()).save(base / ".temp" / f"ui-distribution{scale_suffix}.png")
        for metric, variable in app.visible.items():
            variable.set(metric in ("Focal length", "Shutter speed"))
        app.layout_charts()
        app.view.set("Over time")
        app.average.set(True)
        app.log_scale.set(True)
        app.change_view()
        settle()
        active = [c for c in app.charts.values() if c.winfo_ismapped()]
        assert len(active) == 2
        assert all(c.hits for c in active)
        chart = app.charts["Focal length"]
        full_span = chart.time_bounds[1] - chart.time_bounds[0]
        chart.wheel(SimpleNamespace(delta=120, x=chart.canvas.winfo_width() // 2))
        assert chart.time_bounds[1] - chart.time_bounds[0] < full_span
        chart.pan("moveto", "0")
        assert chart.time_bounds[0] == chart.time_full[0]
        chart.wheel(SimpleNamespace(delta=-120, x=chart.canvas.winfo_width() // 2))
        assert abs(chart.time_bounds[1] - chart.time_bounds[0] - full_span) < 0.01
        chart.reset_zoom()
        settle()
        assert all(len(c.canvas.find_withtag("date-tick")) > 4 for c in active)
        focal_labels = {c.canvas.itemcget(i, "text") for c in active if c.metric == "Focal length" for i in c.canvas.find_withtag("setting-label")}
        assert {"24 mm", "35 mm", "50 mm", "85 mm", "135 mm"}.issubset(focal_labels)
        assert all("average" in " ".join(str(c.canvas.itemcget(i, "text")) for i in c.canvas.find_all() if c.canvas.type(i) == "text") for c in active)
        ImageGrab.grab(window=root.winfo_id()).save(base / ".temp" / f"ui-time{scale_suffix}.png")
        app.visible["Shutter speed"].set(False)
        app.layout_charts()
        settle()
        assert app.charts["Focal length"].winfo_width() > root.winfo_width() * 0.9
        for variable in app.visible.values():
            variable.set(False)
        app.layout_charts()
        settle()
        assert app.empty.winfo_ismapped()
        root.geometry("760x600")
        for variable in app.visible.values():
            variable.set(True)
        app.layout_charts()
        settle()
        app.manage_folders()
        settle()
        assert app.folder_list.size() == 1
        app.folder_list.winfo_toplevel().destroy()
        app.result = Result(photos=[Photo(str(i), datetime(2024, 1, 1), {"Focal length": value})
                                  for i, value in enumerate([24] * 2 + [35] * 3 + [50] * 194 + [5000])])
        app.view.set("Distribution")
        app.change_view()
        settle()
        chart = app.charts["Focal length"]
        percentages = {chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-percent")}
        assert percentages == {"1.5%", "97.0%"}, percentages
        app.hide_outliers.set(True)
        app.redraw()
        settle()
        assert "outliers hidden" in chart.heading.cget("text")
        assert len(app.result.photos) == 200
        app.hide_outliers.set(False)
        app.redraw()
        settle()
        assert len(chart.canvas.find_withtag("bar-front")) == 4
        # Dense distributions retain every label and reveal a horizontal bar.
        app.result = Result(photos=[Photo(str(i), None, {"Focal length": i * 10 + 1}) for i in range(100)])
        app.redraw()
        settle()
        assert len(chart.canvas.find_withtag("bar-label")) == 199
        assert chart.xscroll.winfo_ismapped()
        chart.canvas.xview_moveto(0.5)
        settle()
        first_pixel = chart.canvas.canvasx(0)
        last_pixel = first_pixel + chart.canvas.winfo_width()
        visible_front = next(item for item in chart.canvas.find_withtag("bar-front")
                             if first_pixel + 5 < chart.canvas.coords(item)[0] < last_pixel - 40)
        rows = right_click_names(chart, visible_front)
        assert len(rows) == 1
        app.result = Result(photos=[Photo("crop.jpg", datetime(2024, 1, 1), {"Focal length": 50, "Focal length (35mm)": 75}),
                                  Photo("unknown.jpg", None, {"Focal length": 35})])
        app.equivalent_35mm.set(True)
        app.redraw()
        settle()
        equivalent, _ = app.photos_for_metric("Focal length")
        assert len(equivalent) == 1 and equivalent[0].values["Focal length"] == 75
        assert app.result.photos[0].values["Focal length"] == 50
        assert "35 mm equivalent" in chart.heading.cget("text")
        assert "1 missing" in chart.heading.cget("text")
        assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-label")] == ["75"]
        assert [row[0] for row in right_click_names(chart, chart.canvas.find_withtag("bar-front")[0], check_actions=True)] == ["crop.jpg"]
        saved_result = app.result
        app.result = Result(photos=[Photo("folder-a/same.jpg", None, {"Focal length": 35, "Focal length (35mm)": 35}),
                                   Photo("folder-b/same.jpg", None, {"Focal length": 39.9, "Focal length (35mm)": 39.9}),
                                   Photo("next-bin.jpg", None, {"Focal length": 40, "Focal length (35mm)": 40})])
        app.redraw()
        settle()
        rows = right_click_names(chart, chart.canvas.find_withtag("bar-front")[0])
        assert len(rows) == 2 and all(row[0] == "same.jpg" for row in rows)
        assert {row[1] for row in rows} == {"folder-a", "folder-b"}
        app.result = saved_result
        app.common_focals.set(True)
        app.redraw()
        settle()
        assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-label")] == ["70"]
        assert [row[0] for row in right_click_names(chart, chart.canvas.find_withtag("bar-front")[0])] == ["crop.jpg"]
        assert app.result.photos[0].values["Focal length (35mm)"] == 75
        assert_discrete(chart)
        common_source = app.result
        app.result = Result(photos=[Photo(f"common-{value}.jpg", datetime(2024, 1, 1),
                                         {"Focal length": value, "Focal length (35mm)": value}) for value in (24, 28, 35)])
        app.redraw()
        settle()
        assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-label")] == ["24", "28", "35"]
        assert_discrete(chart)
        assert [row[0] for row in right_click_names(chart, chart.canvas.find_withtag("bar-front")[0])] == ["common-24.jpg"]
        app.export_image(str(base / ".temp" / "discrete-common-export.png"))
        app.result = common_source
        app.redraw()
        settle()
        app.view.set("Over time")
        app.change_view()
        settle()
        assert chart.hits
        assert all(int(chart.canvas.itemcget(item, "text").split()[0]) in
                   (8, 10, 12, 14, 16, 18, 20, 24, 28, 35, 40, 50, 60, 70, 85, 100, 105, 135, 150, 180, 200, 250, 300, 400, 500, 600, 800)
                   for item in chart.canvas.find_withtag("setting-label"))
        app.view.set("Distribution")
        app.common_focals.set(False)
        app.change_view()
        app.equivalent_35mm.set(False)
        app.redraw()
        settle()
        assert len(app.photos_for_metric("Focal length")[0]) == 2
        app.equivalent_35mm.set(True)
        app.common_focals.set(True)
        app.close()
        root = tk.Tk()
        app = App(root, session_path=session_file)
        settle()
        assert len(app.result.photos) == 2
        assert app.equivalent_35mm.get()
        assert app.common_focals.get()
        assert app.folders
        with tempfile.TemporaryDirectory(dir=base / ".temp") as folder:
            path = Path(folder) / "aspect-portrait.jpg"
            make_photo(path, rotation=6)
            # Simulate a session saved by an earlier release: enrich only the
            # new field without replacing the saved exposure settings.
            app.result = Result(photos=[Photo(str(path), datetime(2024, 1, 1), {"ISO": 320})])
            for metric, variable in app.visible.items():
                variable.set(metric == "Aspect ratio")
            app.layout_charts()
            deadline = time.monotonic() + 5
            while app.aspect_loading and time.monotonic() < deadline:
                root.update()
                time.sleep(0.03)
            settle()
            assert not app.aspect_loading
            assert app.result.photos[0].values["Aspect ratio"] == "2:3"
            assert app.result.photos[0].values["ISO"] == 320
            chart = app.charts["Aspect ratio"]
            assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-label")] == ["2:3"]
            assert [row[0] for row in right_click_names(chart, chart.canvas.find_withtag("bar-front")[0])] == ["aspect-portrait.jpg"]
            assert_discrete(chart)
            aspect_source = app.result
            app.result = Result(photos=[Photo(f"ratio-{i}.jpg", datetime(2024, 1, 1), {"Aspect ratio": ratio})
                                       for i, ratio in enumerate(("3:2", "16:9", "3:2"))])
            app.redraw()
            settle()
            assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("bar-label")] == ["3:2", "16:9"]
            assert_discrete(chart)
            assert [row[0] for row in right_click_names(chart, chart.canvas.find_withtag("bar-front")[0])] == ["ratio-0.jpg", "ratio-2.jpg"]
            app.export_image(str(base / ".temp" / "discrete-aspect-export.png"))
            app.result = aspect_source
            app.hide_outliers.set(True)
            app.view.set("Over time")
            app.change_view()
            settle()
            assert chart.hits
            assert [chart.canvas.itemcget(i, "text") for i in chart.canvas.find_withtag("setting-label")] == ["2:3"]
            app.export_image(str(base / ".temp" / "aspect-export-check.png"))
            assert (base / ".temp" / "aspect-export-check.png").exists()
        assert not errors, errors
        print("UI OK: scan, charts, dates, average, toggles, single-graph resize, empty view, minimum window.")
    finally:
        app.close()


if __name__ == "__main__":
    run()
