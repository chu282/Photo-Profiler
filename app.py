"""Minimal native desktop UI for Photo Profiler."""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import display  # Enable DPI awareness before callers create their Tk root.
from charting import COMMON_FOCAL_LENGTHS, calendar_ticks, common_focal_length, setting_axis, without_outliers
from profiler import METRICS, Photo, Result, aspect_ratio_number, distribution, distribution_key, label, moving_average, read_photo, scan
from session import load_session, save_session
import windows_files

BG = "#f5f6f8"
INK = "#202936"
MUTED = "#647184"
GRID = "#e7ebef"
BLUE = "#3876c5"
GRAPH_ORDER = ("Focal length", "ISO", "Aperture", "Shutter speed", "Orientation", "Aspect ratio")
COLORS = {"Focal length": "#2048d8", "ISO": "#dc332b", "Aperture": "#ee7426", "Shutter speed": "#008b87", "Orientation": "#8054b8", "Aspect ratio": "#357a43"}
TITLES = {"Focal length": "Focal length (mm)", "ISO": "ISO", "Aperture": "Aperture", "Shutter speed": "Shutter speed (s)", "Orientation": "Orientation", "Aspect ratio": "Aspect ratio"}
FOCAL_BIN_WIDTH = 5


class ScaledCanvas(tk.Canvas):
    """Render logical coordinates directly at the screen's native resolution."""
    def __init__(self, parent, scale, **kwargs):
        self.scale_factor = scale
        super().__init__(parent, **kwargs)

    def _create(self, item_type, args, options):
        coordinates = tuple(float(value) * self.scale_factor for value in tk._flatten(args))
        options = dict(options)
        if "width" in options:
            options["width"] *= self.scale_factor
        return super()._create(item_type, coordinates, options)

    def region(self, width, height):
        self.configure(scrollregion=(0, 0, width * self.scale_factor, height * self.scale_factor))

    def logical_size(self):
        return self.winfo_width() / self.scale_factor, self.winfo_height() / self.scale_factor


class Chart(ttk.Frame):
    def __init__(self, parent, metric, app):
        super().__init__(parent, padding=app.px(3), style="Card.TFrame", relief="solid", borderwidth=1)
        self.metric, self.app = metric, app
        self.pending = None
        self.hits = {}
        self.bar_members = {}
        self.hist_width = None
        self.time_range = None
        self.time_full = None
        self.time_bounds = None
        self.data_key = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.heading = ttk.Label(self, text=metric, style="Heading.TLabel")
        self.heading.grid(row=0, column=0, sticky="e", padx=app.px(8), pady=(app.px(3), 0))
        self.canvas = ScaledCanvas(self, app.scale, bg="white", highlightthickness=0, height=app.px(180))
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        # Both distributions and time plots fit the panel without scrolling.
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.pan)
        self.canvas.configure(xscrollcommand=self.xscroll.set)
        self.canvas.bind("<Configure>", self.schedule)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Double-Button-1>", self.reset_zoom)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Button-3>", self.show_bar_files)
        self.canvas.bind("<Leave>", lambda _: self.app.clear_hint())

    def schedule(self, _=None):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(100, self.draw)

    def wheel(self, event):
        if not event.delta:
            return "break"
        factor = 1.25 ** max(-5, min(5, event.delta / 120))
        width, _ = self.canvas.logical_size()
        pointer = event.x / self.app.scale
        if self.app.view.get() == "Distribution" and self.hist_width:
            old = self.hist_width
            fraction = (self.canvas.canvasx(event.x) / self.app.scale - 58) / old
            self.hist_width = max(width - 83, min(200000, old * factor))
            self.draw()
            offset = 58 + fraction * self.hist_width - pointer
            self.canvas.xview_moveto(max(0, offset) / (self.hist_width + 83))
        elif self.time_bounds and self.time_full:
            lo, hi = self.time_bounds
            fraction = max(0, min(1, (pointer - 85) / max(1, width - 110)))
            anchor = lo + fraction * (hi - lo)
            span = max(1, min(self.time_full[1] - self.time_full[0], (hi - lo) / factor))
            start = max(self.time_full[0], min(anchor - fraction * span, self.time_full[1] - span))
            self.time_range = (start, start + span)
            self.draw()
        return "break"

    def reset_zoom(self, _=None):
        self.hist_width = None
        self.time_range = None
        self.canvas.xview_moveto(0)
        self.draw()

    def pan(self, *args):
        if self.app.view.get() == "Distribution":
            self.canvas.xview(*args)
        elif self.time_range and self.time_full:
            lo, hi = self.time_range
            span = hi - lo
            full_lo, full_hi = self.time_full
            if args[0] == "moveto":
                start = full_lo + float(args[1]) * (full_hi - full_lo)
            else:
                start = lo + int(args[1]) * span * (0.8 if args[2] == "pages" else 0.1)
            start = max(full_lo, min(start, full_hi - span))
            self.time_range = start, start + span
            self.draw()

    def hover(self, event):
        if not self.hits:
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        radius = self.app.px(5)
        nearest = self.canvas.find_overlapping(x - radius, y - radius, x + radius, y + radius)
        for item in reversed(nearest):
            if item in self.hits:
                self.app.show_hint(self.hits[item])
                return
        self.app.clear_hint()

    def text(self, x, y, text, **kwargs):
        font = kwargs.pop("font", ("Segoe UI", 9))
        return self.canvas.create_text(x, y, text=text, fill=MUTED, font=font, **kwargs)

    def show_bar_files(self, event):
        if self.app.view.get() != "Distribution":
            return "break"
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            if item in self.bar_members:
                setting, photos = self.bar_members[item]
                self.app.show_files(self.metric, setting, photos)
                break
        return "break"

    def draw(self):
        self.pending = None
        c = self.canvas
        c.delete("all")
        self.hits.clear()
        self.bar_members.clear()
        key = (id(self.app.result), self.app.hide_outliers.get(), self.app.equivalent_35mm.get(), self.app.common_focals.get())
        if key != self.data_key:
            self.hist_width = None
            self.time_range = None
            self.time_full = None
            self.data_key = key
        if not self.winfo_ismapped():
            return
        if self.app.view.get() == "Distribution":
            self.draw_bars()
        else:
            self.scroll.grid_remove()
            self.xscroll.grid_remove()
            c.xview_moveto(0)
            c.yview_moveto(0)
            c.region(*c.logical_size())
            self.draw_time()

    def draw_bars(self):
        photos, hidden = self.app.photos_for_metric(self.metric)
        binned = self.metric == "Focal length"
        common = binned and self.app.common_focals.get()
        discrete = common or self.metric == "Aspect ratio"
        groups = {}
        for photo in photos:
            key = common_focal_length(photo.values[self.metric]) if common else distribution_key(photo.values[self.metric], FOCAL_BIN_WIDTH if binned else None)
            groups.setdefault(key, []).append(photo)
        if common and groups:
            rows = [(value, len(groups.get(value, []))) for value in COMMON_FOCAL_LENGTHS if min(groups) <= value <= max(groups)]
        else:
            rows = distribution(photos, self.metric, bin_width=FOCAL_BIN_WIDTH if binned else None)
        total = sum(count for _, count in rows)
        missing = len(self.app.result.photos) - total - hidden
        suffix = f" · {missing:,} missing" if missing else ""
        if hidden:
            suffix += f" · {hidden:,} outliers hidden"
        if common:
            suffix += " · common"
        self.heading.configure(text=f"{self.app.metric_title(self.metric)}   ·   {total:,} photos{suffix}")
        c = self.canvas
        width, height = c.logical_size()
        if not rows:
            self.xscroll.grid_remove()
            self.text(width / 2, height / 2, "No data")
            c.region(width, height)
            return
        maximum = max(count for _, count in rows)
        raw_step = maximum * 1.15 / 6
        power = 10 ** math.floor(math.log10(max(raw_step, 1)))
        step = next(n * power for n in (1, 2, 5, 10) if n * power >= max(raw_step, 1))
        ceiling = math.ceil(maximum * 1.15 / step) * step
        labels = [f"{value:g}" if binned else label(self.metric, value).removesuffix(" mm").removesuffix(" s") for value, _ in rows]
        if self.hist_width is None:
            self.hist_width = max(width - 83, len(rows) * 32)
        self.hist_width = max(width - 83, self.hist_width)
        virtual_width = self.hist_width + 83
        if virtual_width > width + 1:
            self.xscroll.grid(row=2, column=0, sticky="ew")
        else:
            self.xscroll.grid_remove()
            c.xview_moveto(0)
        slot = (virtual_width - 83) / len(rows)
        angle = 65 if not binned and (len(rows) > 14 or slot < 46) else 0
        bottom_margin = 80 if angle else 32
        left, right, top, bottom = 58, virtual_width - 25, 26, height - bottom_margin
        if right <= left or bottom <= top:
            return
        slot = (right - left) / len(rows)
        depth = min(18, slot * 0.24)
        self.draw_distribution_grid(left, right, top, bottom, depth, slot, len(rows), ceiling, step, discrete)
        for tick in range(0, ceiling + 1, step):
            y = bottom - tick / ceiling * (bottom - top)
            self.text(left - 7, y, f"{tick:,}", anchor="e")
        self.text(13, (top + bottom) / 2, "Photos", angle=90)
        color = COLORS[self.metric]
        # Front-face height is the count; the deeper roof and side are visual.
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        dark = "#" + "".join(f"{int(v * 0.65):02x}" for v in rgb)
        light = "#" + "".join(f"{min(255, int(v * 0.85 + 38)):02x}" for v in rgb)
        annotations = []
        for i, (value, count) in enumerate(rows):
            if discrete:
                category_x = left + (i + 0.5) * slot
                bar_width = slot * 0.56
                x1 = category_x - (bar_width + depth) / 2
                x2 = x1 + bar_width
                tick_x = category_x
            else:
                x1 = left + i * slot
                x2 = x1 + slot if self.metric != "Orientation" else x1 + slot - depth - 2
                tick_x = x1
            x = (x1 + x2) / 2
            c.create_line(tick_x, bottom, tick_x, bottom + 5, fill="#8e98a4", tags="bar-tick")
            self.text(tick_x, bottom + 8, labels[i], anchor="ne" if angle else "n", angle=angle,
                      font=("Segoe UI", 8 if binned else 9), tags="bar-label")
            if count == 0:
                continue
            y = bottom - count / ceiling * (bottom - top)
            setting = f"Nearest to {value:g} mm" if common else f"{value:g} ≤ focal length < {value + FOCAL_BIN_WIDTH:g} mm" if binned else label(self.metric, value)
            description = f"{setting} · {count:,} photos · {100 * count / total:.1f}%"
            members = setting, groups[value]
            if slot >= 7:
                for item in (
                    c.create_polygon(x2, bottom, x2 + depth, bottom - depth, x2 + depth, y - depth, x2, y, fill=dark, outline=dark, tags="bar-depth"),
                    c.create_polygon(x1, y, x1 + depth, y - depth, x2 + depth, y - depth, x2, y, fill=light, outline=dark, tags="bar-depth"),
                ):
                    self.hits[item] = description
                    self.bar_members[item] = members
            item = c.create_rectangle(x1, y, x2, bottom, fill=color, outline=dark if slot >= 7 else "", tags="bar-front")
            self.hits[item] = description
            self.bar_members[item] = members
            if count / total > 0.01:
                percent = f"{100 * count / total:.1f}%"
                annotations.append((x + depth / 2, y - depth - 5, percent, members))
        c.create_line(left, top, left, bottom, right, bottom, fill="#8e98a4")
        for x, y, percent, members in annotations:
            item = self.text(x, y, percent, anchor="s", angle=0,
                             font=("Segoe UI", 8 if slot < 40 else 9), tags="bar-percent")
            self.bar_members[item] = members
            bounds = c.bbox(item)
            scale = self.app.scale
            c.create_rectangle(bounds[0] / scale, bounds[1] / scale,
                               bounds[2] / scale, bounds[3] / scale,
                               fill="#eeeeee", outline="", tags="percent-backing")
        # Backings hide grid/ticks, but must never paint over any bar face.
        # Preserve the original ordering of the projected faces, then put
        # percentage text on top with no extra backing padding.
        for face in sorted((*c.find_withtag("bar-depth"), *c.find_withtag("bar-front"))):
            c.tag_raise(face)
        c.tag_raise("bar-percent")
        c.region(virtual_width, height)

    def draw_distribution_grid(self, left, right, top, bottom, depth, slot, columns, ceiling, step, discrete=False):
        c = self.canvas
        # The back wall, left wall, floor, and bars all share one projection.
        # A front bin boundary projects onto the corresponding back grid line.
        c.create_rectangle(left + depth, top - depth, right + depth, bottom - depth,
                           fill="#eeeeee", outline="", tags="grid-back")
        c.create_polygon(left, top, left + depth, top - depth, left + depth, bottom - depth,
                         left, bottom, fill="#e6e6e6", outline="#969b9f", tags="grid-side")
        c.create_polygon(left, bottom, right, bottom, right + depth, bottom - depth,
                         left + depth, bottom - depth, fill="#d4d4d4", outline="#969b9f", tags="grid-floor")
        for tick in range(0, ceiling + 1, step):
            y = bottom - tick / ceiling * (bottom - top)
            c.create_line(left, y, left + depth, y - depth, right + depth, y - depth,
                          fill="#a0a4a8", tags="grid-horizontal")
        for index in range(columns if discrete else columns + 1):
            x = left + (index + 0.5 if discrete else index) * slot
            c.create_line(x + depth, top - depth, x + depth, bottom - depth,
                          fill="#a0a4a8", tags="grid-vertical")
            c.create_line(x, bottom, x + depth, bottom - depth, fill="#969b9f", tags="grid-floor-line")
        c.create_rectangle(left + depth, top - depth, right + depth, bottom - depth,
                           outline="#747c83", tags="grid-border")

    def draw_time(self):
        selected, hidden = self.app.photos_for_metric(self.metric)
        photos = [p for p in selected if p.taken]
        omitted = len(self.app.result.photos) - len(photos) - hidden
        suffix = f" · {omitted:,} omitted" if omitted else ""
        if hidden:
            suffix += f" · {hidden:,} outliers hidden"
        self.heading.configure(text=f"{self.app.metric_title(self.metric)}   ·   {len(photos):,} dated photos{suffix}")
        c = self.canvas
        width, height = c.logical_size()
        if not photos:
            self.text(width / 2, height / 2, "No dated data")
            return
        if width < 220 or height < 100:
            return
        categories = {"Landscape": 0, "Portrait": 1, "Square": 2}
        if self.metric == "Aspect ratio":
            ratios = sorted({p.values[self.metric] for p in photos}, key=aspect_ratio_number)
            categories = {value: i for i, value in enumerate(ratios)}
        categorical = self.metric in ("Orientation", "Aspect ratio")
        log = self.app.log_scale.get() and not categorical

        def number(value):
            return categories[value] if categorical else math.log2(value) if log else value

        epoch = datetime(1970, 1, 1)
        points = [((p.taken - epoch).total_seconds(), number(p.values[self.metric]), p) for p in photos]
        xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
        if xmin == xmax:
            xmin -= 43200
            xmax += 43200
        self.time_full = xmin, xmax
        if self.time_range:
            xmin, xmax = self.time_range
        self.time_bounds = xmin, xmax
        left, right, top, bottom = 85, width - 25, 15, height - 46
        if categorical:
            ymin, ymax = -0.35, len(categories) - 0.65
            ticks = list(categories.items())
            if self.metric == "Aspect ratio":
                stride = max(1, math.ceil(len(ticks) / max(3, (bottom - top) / 25)))
                visible_ticks = ticks[::stride]
                if ticks[-1] != visible_ticks[-1]:
                    visible_ticks.append(ticks[-1])
                ticks = visible_ticks
        else:
            ymin, ymax, values = setting_axis([p.values[self.metric] for p in photos], self.metric, log,
                                              target=max(5, min(18, int((bottom - top) / 30))), pixels=bottom - top)
            if self.metric == "Focal length" and self.app.common_focals.get():
                first = common_focal_length(min(p.values[self.metric] for p in photos))
                last = common_focal_length(max(p.values[self.metric] for p in photos))
                ymin, ymax = min(ymin, number(first)), max(ymax, number(last))
                values = []
                for value in COMMON_FOCAL_LENGTHS:
                    if ymin <= number(value) <= ymax and (not values or
                            (number(value) - number(values[-1])) / (ymax - ymin) * (bottom - top) >= 25):
                        values.append(value)
            ticks = [(label(self.metric, value), number(value)) for value in values]

        def xy(x, y):
            return left + (x - xmin) / (xmax - xmin) * (right - left), bottom - (y - ymin) / (ymax - ymin) * (bottom - top)

        for name, value in ticks:
            _, y = xy(xmin, value)
            c.create_line(left, y, right, y, fill=GRID)
            c.create_line(left - 5, y, left, y, fill="#8e98a4", tags="setting-tick")
            self.text(left - 8, y, name, anchor="e", tags="setting-label")
        dates = calendar_ticks(epoch + timedelta(seconds=xmin), epoch + timedelta(seconds=xmax), target=max(5, int((right - left) / 45)))
        for stamp, date_label in dates:
            value = (stamp - epoch).total_seconds()
            x, _ = xy(value, ymin)
            c.create_line(x, top, x, bottom, fill=GRID)
            c.create_line(x, bottom, x, bottom + 5, fill="#8e98a4", tags="date-tick")
            self.text(x, bottom + 9, date_label, anchor="n", tags="date-label")
        c.create_line(left, top, left, bottom, right, bottom, fill="#b9c2ce")

        # One point per screen pixel keeps large libraries fast. The count and
        # optional mean still use every photograph, including overlapping ones.
        pixels = {}
        for xvalue, yvalue, photo in points:
            if not xmin <= xvalue <= xmax:
                continue
            x, y = xy(xvalue, yvalue)
            key = (round(x), round(y))
            if key in pixels:
                pixels[key][1] += 1
            else:
                pixels[key] = [photo, 1]
        for (x, y), (photo, count) in pixels.items():
            item = c.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill="#78a5db", outline="")
            extra = f" · {count:,} overlapping photos" if count > 1 else ""
            self.hits[item] = f"{photo.taken:%Y-%m-%d %H:%M} · {label(self.metric, photo.values[self.metric])} · {Path(photo.path).name}{extra}"

        if self.app.average.get() and not categorical:
            days = self.app.window_days()
            series = moving_average([(p.taken, p.values[self.metric]) for p in photos], days)
            segment = []

            def flush():
                if len(segment) >= 4:
                    c.create_line(*segment, fill="#c75028", width=2.5)
                elif len(segment) == 2:
                    x, y = segment
                    c.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#c75028", outline="")
                segment.clear()

            for date, value in series:
                if value is None:
                    flush()
                    continue
                # The rolling mean is for calendar days, positioned at the
                # last capture time on boundary days to keep it in the plot.
                timestamp = (date - epoch).total_seconds() + 43200
                if not xmin <= timestamp <= xmax:
                    flush()
                    continue
                segment.extend(xy(timestamp, number(value)))
            flush()
            c.create_text(right, top + 3, text=f"{days}-day average", anchor="ne", fill="#a34324", font=("Segoe UI", 9))
        if self.time_range and xmax - xmin < self.time_full[1] - self.time_full[0] - 0.01:
            self.xscroll.grid(row=2, column=0, sticky="ew")
            full_lo, full_hi = self.time_full
            self.xscroll.set((xmin - full_lo) / (full_hi - full_lo), (xmax - full_lo) / (full_hi - full_lo))


class App:
    def __init__(self, root, session_path=None, restore=True, shutdown_requested=None):
        self.root = root
        self.closing = False
        self.shutdown_requested = shutdown_requested
        self.session_path = session_path
        restored = load_session(session_path) if restore else None
        self.scale = root.winfo_fpixels("1i") / 96
        root.title("Photo Profiler")
        root.geometry(f"{min(self.px(1140), root.winfo_screenwidth() - self.px(40))}x{min(self.px(850), root.winfo_screenheight() - self.px(90))}")
        root.minsize(self.px(760), self.px(600))
        root.configure(bg=BG)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Segoe UI", 10))
        style.configure("Card.TFrame", background="white")
        style.configure("Heading.TLabel", background="white", foreground=INK, font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        self.result = Result()
        self.folders = []
        self.running = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.aspect_loading = False
        self.visible = {metric: tk.BooleanVar(value=metric not in ("Orientation", "Aspect ratio")) for metric in METRICS}
        self.view = tk.StringVar(value="Distribution")
        self.average = tk.BooleanVar(value=False)
        self.days = tk.StringVar(value="30")
        self.log_scale = tk.BooleanVar(value=False)
        self.hide_outliers = tk.BooleanVar(value=False)
        self.equivalent_35mm = tk.BooleanVar(value=False)
        self.common_focals = tk.BooleanVar(value=False)
        self.metric_cache = {}
        self.cache_source = None
        self.recursive = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Add folders to scan.")
        if restored:
            self.result = restored["result"]
            self.folders = restored.get("folders", [])
            options = restored.get("options", {})
            for name in ("average", "days", "log_scale", "hide_outliers", "equivalent_35mm", "common_focals", "recursive"):
                if name in options:
                    getattr(self, name).set(options[name])
            self.view.set(options.get("view", "Distribution") if options.get("view") in ("Distribution", "Over time") else "Distribution")
            for metric, enabled in options.get("visible", {}).items():
                if metric in self.visible:
                    self.visible[metric].set(enabled)
            self.status.set(f"{len(self.result.photos):,} photos · restored last scan")

        shell = ttk.Frame(root, padding=self.px(4))
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        top = ttk.Frame(shell)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.folder_list = None
        self.folder_button = ttk.Button(top, text=f"Folders ({len(self.folders)})…", command=self.manage_folders)
        self.folder_button.pack(side="left", padx=(0, self.px(6)))
        self.scan_button = ttk.Button(top, text="Scan", command=self.start_scan, state="normal" if self.folders else "disabled")
        self.scan_button.pack(side="left", padx=(0, self.px(10)))
        self.recursive_button = ttk.Checkbutton(top, text="Subfolders", variable=self.recursive)
        self.recursive_button.pack(side="left", padx=(0, self.px(14)))
        self.export_button = ttk.Button(top, text="Export image", command=self.export_image)
        self.export_button.pack(side="right", padx=(self.px(8), 0))

        toggles = ttk.Frame(shell)
        toggles.grid(row=1, column=0, sticky="ew", pady=(self.px(3), self.px(3)))
        for column, metric in enumerate(GRAPH_ORDER):
            ttk.Checkbutton(toggles, text=metric, variable=self.visible[metric], command=self.layout_charts).grid(row=0, column=column, padx=(0, self.px(18)), sticky="w")
        filters = ttk.Frame(shell)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, self.px(3)))
        ttk.Checkbutton(filters, text="Hide outliers", variable=self.hide_outliers, command=self.redraw).pack(side="left", padx=(0, self.px(14)))
        ttk.Checkbutton(filters, text="35 mm equivalent", variable=self.equivalent_35mm, command=self.redraw).pack(side="left", padx=(0, self.px(14)))
        ttk.Checkbutton(filters, text="Common focal lengths only", variable=self.common_focals, command=self.redraw).pack(side="left")
        controls = ttk.Frame(top)
        controls.pack(side="left")
        selector = ttk.Combobox(controls, textvariable=self.view, values=("Distribution", "Over time"), state="readonly", width=16)
        selector.pack(side="left", padx=(0, self.px(14)))
        selector.bind("<<ComboboxSelected>>", self.change_view)
        self.time_controls = ttk.Frame(controls)
        ttk.Checkbutton(self.time_controls, text="Average", variable=self.average, command=self.redraw).pack(side="left")
        spin = ttk.Spinbox(self.time_controls, from_=1, to=36500, width=5, textvariable=self.days, command=self.redraw)
        spin.pack(side="left", padx=(self.px(6), self.px(4)))
        spin.bind("<Return>", self.redraw)
        spin.bind("<FocusOut>", self.redraw)
        ttk.Label(self.time_controls, text="days").pack(side="left", padx=(0, self.px(14)))
        ttk.Checkbutton(self.time_controls, text="Log scale", variable=self.log_scale, command=self.redraw).pack(side="left")

        self.chart_area = ttk.Frame(shell)
        self.chart_area.grid(row=3, column=0, sticky="nsew")
        self.charts = {metric: Chart(self.chart_area, metric, self) for metric in METRICS}
        self.empty = ttk.Label(self.chart_area, text="Select a graph.", anchor="center")
        footer = ttk.Frame(shell)
        footer.grid(row=4, column=0, sticky="ew", pady=(self.px(2), 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status).grid(row=0, column=0, sticky="w")
        self.errors_button = ttk.Button(footer, text="Details", command=self.show_errors)
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=self.px(100))
        self.layout_charts()
        if self.view.get() == "Over time":
            self.time_controls.pack(side="left")
        if self.result.errors:
            self.errors_button.grid(row=0, column=2, padx=(10, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(100, self.poll)
        self.restore_id = None
        if restored and restored.get("options", {}).get("chart_views"):
            self.restore_id = root.after(300, lambda: self.restore_chart_views(restored["options"]["chart_views"]))

    def px(self, value):
        return round(value * self.scale)

    def photos_for_metric(self, metric):
        if self.cache_source is not self.result:
            self.metric_cache.clear()
            self.cache_source = self.result
        equivalent = metric == "Focal length" and self.equivalent_35mm.get()
        key = (metric, self.hide_outliers.get(), equivalent)
        if key not in self.metric_cache:
            if equivalent:
                photos = [Photo(p.path, p.taken, {**p.values, "Focal length": p.values["Focal length (35mm)"]}, p.metadata)
                          for p in self.result.photos if "Focal length (35mm)" in p.values]
            else:
                photos = [p for p in self.result.photos if metric in p.values]
            filtered = without_outliers(photos, metric) if self.hide_outliers.get() else photos
            self.metric_cache[key] = filtered, len(photos) - len(filtered)
        return self.metric_cache[key]

    def ensure_aspect_ratios(self):
        pending = [(index, photo.path) for index, photo in enumerate(self.result.photos)
                   if "Aspect ratio" not in photo.values and photo.metadata.get("aspect_checked") != "1"]
        if self.aspect_loading or not pending:
            return
        self.aspect_loading = True
        source = self.result
        if not self.running:
            self.status.set("Reading aspect ratios…")

        def work():
            updates = []
            for index, path in pending:
                if self.closing:
                    return
                try:
                    photo = read_photo(Path(path))
                    ratio = photo.values.get("Aspect ratio") if photo else None
                except Exception:
                    ratio = None
                updates.append((index, ratio))
            self.events.put(("aspect_ready", (source, updates)))

        threading.Thread(target=work, daemon=True).start()

    def save_current_session(self):
        options = {name: getattr(self, name).get() for name in
                   ("view", "average", "days", "log_scale", "hide_outliers", "equivalent_35mm", "common_focals", "recursive")}
        options["visible"] = {name: value.get() for name, value in self.visible.items()}
        options["chart_views"] = {
            metric: {"zoom": chart.hist_width / max(1, chart.canvas.logical_size()[0] - 83) if chart.hist_width else None,
                     "scroll": chart.canvas.xview()[0], "time_range": chart.time_range}
            for metric, chart in self.charts.items()}
        save_session(self.result, self.folders, options, self.session_path)

    def restore_chart_views(self, views):
        self.restore_id = None
        for metric, view in views.items():
            if metric not in self.charts:
                continue
            chart = self.charts[metric]
            if view.get("zoom"):
                chart.hist_width = max(1, chart.canvas.logical_size()[0] - 83) * view["zoom"]
            if view.get("time_range"):
                chart.time_range = tuple(view["time_range"])
            chart.data_key = (id(self.result), self.hide_outliers.get(), self.equivalent_35mm.get(), self.common_focals.get())
            if self.visible[metric].get():
                chart.draw()
                if self.view.get() == "Distribution":
                    chart.canvas.xview_moveto(view.get("scroll", 0))

    def export_image(self, path=None):
        if not any(value.get() for value in self.visible.values()):
            return
        if path is None:
            from chart_export import default_export_name
            path = filedialog.asksaveasfilename(title="Export charts", defaultextension=".png",
                                              initialfile=default_export_name(), filetypes=[("PNG image", "*.png")])
        if not path:
            return
        try:
            from chart_export import export_charts
            self.root.update_idletasks()
            for metric, chart in self.charts.items():
                if self.visible[metric].get():
                    chart.draw()
            self.root.update_idletasks()
            export_charts(self, path)
            self.clear_hint()
            self.status.set(f"Exported {Path(path).name}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export failed", str(exc))

    def metric_title(self, metric):
        if metric == "Focal length" and self.equivalent_35mm.get():
            return "Focal length (35 mm equivalent)"
        return TITLES[metric]

    def show_files(self, metric, setting, photos):
        window = tk.Toplevel(self.root)
        window.title(f"{self.metric_title(metric)} — files")
        window.geometry(f"{self.px(820)}x{self.px(440)}")
        window.minsize(self.px(500), self.px(250))
        window.transient(self.root)
        frame = ttk.Frame(window, padding=self.px(10))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text=f"{setting} · {len(photos):,} files").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, self.px(8)))
        style = ttk.Style(window)
        style.configure("Files.Treeview", font=("Segoe UI", 9), rowheight=self.px(24))
        style.configure("Files.Treeview.Heading", font=("Segoe UI", 9))
        tree = ttk.Treeview(frame, columns=("name", "folder"), show="headings", selectmode="extended", style="Files.Treeview")
        tree.heading("name", text="File name")
        tree.heading("folder", text="Folder")
        tree.column("name", width=self.px(270), minwidth=self.px(140))
        tree.column("folder", width=self.px(480), minwidth=self.px(180))
        tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        paths = {}
        for photo in sorted(photos, key=lambda p: (Path(p.path).name.casefold(), p.path.casefold())):
            path = Path(photo.path)
            item = tree.insert("", "end", values=(path.name, str(path.parent)))
            paths[item] = str(path.absolute())

        def copy_names(_):
            selected = tree.selection() or tree.get_children()
            window.clipboard_clear()
            window.clipboard_append("\n".join(tree.item(item, "values")[0] for item in selected))
            return "break"

        def focused_path():
            return paths.get(tree.focus())

        def act(action):
            path = focused_path()
            if path:
                self.file_action(path, action, window)

        def open_clicked(event):
            row = tree.identify_row(event.y)
            if row:
                tree.focus(row)
                tree.selection_set(row)
                act("open")
            return "break"

        def copy_paths():
            selected = tree.selection() or (tree.focus(),)
            window.clipboard_clear()
            window.clipboard_append("\n".join(paths[item] for item in selected if item in paths))

        menu = tk.Menu(tree, tearoff=False)
        menu.add_command(label="Open", command=lambda: act("open"))
        menu.add_command(label="Show in folder", command=lambda: act("reveal"))
        menu.add_command(label="Open folder", command=lambda: act("folder"))
        menu.add_separator()
        menu.add_command(label="Copy file name", command=lambda: copy_names(None))
        menu.add_command(label="Copy file path", command=copy_paths)

        def show_context(event):
            row = tree.identify_row(event.y)
            if not row:
                return "break"
            if row not in tree.selection():
                tree.selection_set(row)
            tree.focus(row)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
            return "break"

        tree.bind("<Control-c>", copy_names)
        tree.bind("<Double-Button-1>", open_clicked)
        tree.bind("<Return>", lambda _: act("open"))
        tree.bind("<Button-3>", show_context)
        window.bind("<Escape>", lambda _: window.destroy())
        tree.focus_set()
        return window

    def file_action(self, path, action, parent=None):
        try:
            {"open": windows_files.open_file, "reveal": windows_files.reveal_file,
             "folder": windows_files.open_folder}[action](path)
        except OSError as exc:
            messagebox.showerror("Could not open file", str(exc), parent=parent or self.root)

    def show_hint(self, text):
        if not hasattr(self, "saved_status"):
            self.saved_status = self.status.get()
        if not self.running:
            self.status.set(text)

    def clear_hint(self):
        if hasattr(self, "saved_status"):
            if not self.running:
                self.status.set(self.saved_status)
            del self.saved_status

    def window_days(self):
        try:
            return max(1, min(36500, int(self.days.get())))
        except ValueError:
            return 30

    def manage_folders(self):
        window = tk.Toplevel(self.root)
        window.title("Photo folders")
        window.geometry(f"{self.px(700)}x{self.px(250)}")
        window.transient(self.root)
        window.grab_set()
        frame = ttk.Frame(window, padding=self.px(10))
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.folder_list = tk.Listbox(frame, selectmode="extended", font=("Segoe UI", 10), exportselection=False)
        self.folder_list.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, self.px(8)))
        for folder in self.folders:
            self.folder_list.insert("end", folder)
        ttk.Button(frame, text="Add folder", command=self.add_folder).grid(row=1, column=0, sticky="w")
        ttk.Button(frame, text="Remove selected", command=self.remove_folder).grid(row=1, column=1, padx=self.px(8))
        ttk.Button(frame, text="Done", command=window.destroy).grid(row=1, column=2, sticky="e")

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select photo folder", mustexist=True)
        if folder and folder not in self.folders:
            self.folders.append(folder)
            self.folder_list.insert("end", folder)
            self.folder_button.configure(text=f"Folders ({len(self.folders)})…")
            self.scan_button.configure(state="normal")

    def remove_folder(self):
        for index in reversed(self.folder_list.curselection()):
            del self.folders[index]
            self.folder_list.delete(index)
        self.scan_button.configure(state="normal" if self.folders else "disabled")
        self.folder_button.configure(text=f"Folders ({len(self.folders)})…")

    def layout_charts(self):
        selected = [m for m in GRAPH_ORDER if self.visible[m].get()]
        for chart in self.charts.values():
            chart.grid_forget()
        self.empty.grid_forget()
        for index in range(3):
            self.chart_area.rowconfigure(index, weight=0, uniform="")
        for index in range(2):
            self.chart_area.columnconfigure(index, weight=0, uniform="")
        if not selected:
            self.empty.grid(row=0, column=0, sticky="nsew")
            self.chart_area.rowconfigure(0, weight=1)
            self.chart_area.columnconfigure(0, weight=1)
            return
        columns = min(2, len(selected))
        for index, metric in enumerate(selected):
            row, col = divmod(index, columns)
            # An odd final graph fills the last row.
            span = 2 if columns == 2 and index == len(selected) - 1 and len(selected) % 2 else 1
            self.charts[metric].grid(row=row, column=col, columnspan=span, sticky="nsew", padx=(0 if col == 0 else self.px(1), 0 if col == 1 or span == 2 else self.px(1)), pady=(0, self.px(2)))
            self.chart_area.rowconfigure(row, weight=1, uniform="charts")
            self.chart_area.columnconfigure(col, weight=1, uniform="charts")
        if "Aspect ratio" in selected:
            self.ensure_aspect_ratios()
        self.redraw()

    def change_view(self, _=None):
        if self.view.get() == "Over time":
            self.time_controls.pack(side="left")
        else:
            self.time_controls.pack_forget()
        for chart in self.charts.values():
            chart.canvas.yview_moveto(0)
        self.redraw()

    def redraw(self, _=None):
        if self.average.get():
            self.days.set(str(self.window_days()))
        for metric, chart in self.charts.items():
            if self.visible[metric].get():
                chart.schedule()

    def start_scan(self):
        if self.running:
            self.cancel.set()
            self.scan_button.configure(state="disabled", text="Stopping…")
            return
        if not self.folders:
            return
        self.running = True
        self.cancel.clear()
        self.scan_button.configure(text="Stop")
        for widget in (self.folder_button, self.recursive_button):
            widget.configure(state="disabled")
        self.errors_button.grid_remove()
        self.progress.grid(row=0, column=1, padx=(10, 0))
        self.progress.start(15)
        self.status.set("Scanning…")
        folders, recursive = list(self.folders), self.recursive.get()

        def work():
            try:
                result = scan(folders, recursive, self.cancel, lambda r: self.events.put(("progress", (r.checked, len(r.photos)))))
                self.events.put(("done", result))
            except Exception as exc:
                self.events.put(("failed", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closing:
            return
        if self.shutdown_requested and self.shutdown_requested():
            self.close()
            return
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "aspect_ready":
                    self.aspect_loading = False
                    source, updates = data
                    if source is self.result:
                        for index, ratio in updates:
                            photo = self.result.photos[index]
                            if ratio:
                                photo.values["Aspect ratio"] = ratio
                            photo.metadata["aspect_checked"] = "1"
                        self.metric_cache.clear()
                        try:
                            self.save_current_session()
                        except OSError:
                            pass
                        if not self.running:
                            self.clear_hint()
                            self.status.set(f"{len(self.result.photos):,} photos · aspect ratios updated")
                        self.redraw()
                    continue
                if kind == "progress":
                    self.status.set(f"Scanning… {data[0]:,} checked · {data[1]:,} with EXIF")
                else:
                    self.running = False
                    self.progress.stop()
                    self.progress.grid_remove()
                    self.scan_button.configure(text="Scan", state="normal" if self.folders else "disabled")
                    for widget in (self.folder_button, self.recursive_button):
                        widget.configure(state="normal")
                    if kind == "failed":
                        self.status.set("Scan failed.")
                        messagebox.showerror("Scan failed", data)
                        continue
                    self.result = data
                    undated = sum(p.taken is None for p in data.photos)
                    pieces = [f"{len(data.photos):,} photos", f"{data.no_exif:,} without EXIF"]
                    if undated:
                        pieces.append(f"{undated:,} undated")
                    if data.errors:
                        pieces.append(f"{len(data.errors):,} unreadable")
                        self.errors_button.grid(row=0, column=2, padx=(10, 0))
                    if data.cancelled:
                        pieces.append("stopped; partial results")
                    self.status.set(" · ".join(pieces))
                    try:
                        self.save_current_session()
                    except OSError:
                        self.status.set(self.status.get() + " · session could not be saved")
                    self.redraw()
        except queue.Empty:
            pass
        self.poll_id = self.root.after(100, self.poll)

    def show_errors(self):
        window = tk.Toplevel(self.root)
        window.title("Unreadable files / folders")
        window.geometry("760x340")
        text = tk.Text(window, wrap="word", font=("Segoe UI", 10), padx=12, pady=12)
        scrollbar = ttk.Scrollbar(window, command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(fill="both", expand=True)
        text.insert("1.0", "\n\n".join(f"{path}\n{reason}" for path, reason in self.result.errors))
        text.configure(state="disabled")

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.cancel.set()
        try:
            self.save_current_session()
        except Exception as exc:
            self.shutdown_error = str(exc)
        finally:
            callbacks = [(self.root, self.poll_id), (self.root, self.restore_id)]
            callbacks.extend((chart, chart.pending) for chart in self.charts.values())
            for widget, callback in callbacks:
                if callback:
                    try:
                        widget.after_cancel(callback)
                    except tk.TclError:
                        pass
            for action in (self.progress.stop, self.root.quit, self.root.destroy):
                try:
                    action()
                except tk.TclError:
                    pass


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
