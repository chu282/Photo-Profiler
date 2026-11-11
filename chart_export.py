"""Render the chart's vector primitives and fresh font glyphs to a large PNG."""
from datetime import datetime
import math
import os
from pathlib import Path
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFont


def default_export_name():
    return f"Photo Profiler {datetime.now():%Y-%m-%d}.png"


class Renderer:
    def __init__(self, root, scale):
        self.root, self.scale = root, scale
        self.fonts = {}

    def color(self, value):
        if not value:
            return None
        return tuple(round(channel / 257) for channel in self.root.winfo_rgb(value))

    def font(self, specification):
        key = str(specification)
        if key in self.fonts:
            return self.fonts[key]
        native = tkfont.Font(root=self.root, font=specification)
        actual = native.actual()
        point_size = actual["size"]
        pixels = point_size * float(self.root.tk.call("tk", "scaling")) if point_size > 0 else -point_size
        bold, italic = actual["weight"] == "bold", actual["slant"] == "italic"
        filename = "segoeuiz.ttf" if bold and italic else "segoeuib.ttf" if bold else "segoeuii.ttf" if italic else "segoeui.ttf"
        path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / filename
        size = max(1, round(pixels * self.scale))
        try:
            face = ImageFont.truetype(str(path), size)
        except OSError:
            face = ImageFont.load_default(size=size)
        self.fonts[key] = native, face
        return native, face

    def text(self, image, x, y, text, specification, fill, anchor="center", angle=0, justify="left"):
        if not text:
            return
        native, face = self.font(specification)
        lines = text.split("\n")
        line_height = max(1, round(native.metrics("linespace") * self.scale))
        width = max(1, math.ceil(max(native.measure(line) for line in lines) * self.scale))
        height = max(1, line_height * len(lines))
        layer = Image.new("RGBA", (width, height))
        pen = ImageDraw.Draw(layer)
        baseline = round(native.metrics("ascent") * self.scale)
        for index, line in enumerate(lines):
            line_width = native.measure(line) * self.scale
            offset = (width - line_width) / 2 if justify == "center" else width - line_width if justify == "right" else 0
            pen.text((offset, baseline + index * line_height), line, font=face, fill=fill, anchor="ls")
        ax = 0.5 if anchor == "center" else 0 if "w" in anchor else 1 if "e" in anchor else 0.5
        ay = 0.5 if anchor == "center" else 0 if "n" in anchor else 1 if "s" in anchor else 0.5
        dx, dy = (ax - 0.5) * width, (ay - 0.5) * height
        if angle:
            layer = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
            theta = math.radians(angle)
            dx, dy = math.cos(theta) * dx + math.sin(theta) * dy, -math.sin(theta) * dx + math.cos(theta) * dy
        origin = round(x - layer.width / 2 - dx), round(y - layer.height / 2 - dy)
        image.paste(layer, origin, layer)

    def canvas(self, canvas):
        scale = self.scale
        image = Image.new("RGBA", (max(1, round(canvas.winfo_width() * scale)),
                                   max(1, round(canvas.winfo_height() * scale))), self.color(canvas.cget("background")))
        pen = ImageDraw.Draw(image)
        origin_x, origin_y = canvas.canvasx(0), canvas.canvasy(0)
        for item in canvas.find_all():
            if canvas.itemcget(item, "state") == "hidden":
                continue
            kind = canvas.type(item)
            coordinates = canvas.coords(item)
            points = [((coordinates[i] - origin_x) * scale, (coordinates[i + 1] - origin_y) * scale)
                      for i in range(0, len(coordinates), 2)]
            fill = self.color(canvas.itemcget(item, "fill"))
            if kind == "text":
                self.text(image, *points[0], canvas.itemcget(item, "text"), canvas.itemcget(item, "font"), fill,
                          canvas.itemcget(item, "anchor"), float(canvas.itemcget(item, "angle")), canvas.itemcget(item, "justify"))
                continue
            stroke = max(1, round(float(canvas.itemcget(item, "width") or 1) * scale))
            if kind == "line":
                if fill:
                    pen.line(points, fill=fill, width=stroke, joint="curve")
            else:
                outline = self.color(canvas.itemcget(item, "outline"))
                if kind == "rectangle":
                    pen.rectangle(points, fill=fill, outline=outline, width=stroke)
                elif kind == "oval":
                    pen.ellipse(points, fill=fill, outline=outline, width=stroke)
                elif kind == "polygon":
                    pen.polygon(points, fill=fill)
                    if outline:
                        pen.line(points + points[:1], fill=outline, width=stroke, joint="curve")
        return image


def export_charts(app, path, date_text=None):
    """Rerender at up to 3× display resolution, capped at 24 megapixels."""
    date_text = date_text or datetime.now().strftime("%Y-%m-%d")
    area = app.chart_area
    width, height = area.winfo_width(), area.winfo_height()
    footer = app.px(26)
    scale = max(1, min(3, math.sqrt(24_000_000 / max(1, width * (height + footer)))))
    renderer = Renderer(app.root, scale)
    image = Image.new("RGBA", (round(width * scale), round((height + footer) * scale)), "#f5f6f8")
    pen = ImageDraw.Draw(image)
    for metric, chart in app.charts.items():
        if not app.visible[metric].get() or not chart.winfo_ismapped():
            continue
        x = (chart.winfo_rootx() - area.winfo_rootx()) * scale
        y = (chart.winfo_rooty() - area.winfo_rooty()) * scale
        w, h = chart.winfo_width() * scale, chart.winfo_height() * scale
        pen.rectangle((x, y, x + w - 1, y + h - 1), fill="white", outline="#a5a5a5", width=max(1, round(scale)))
        heading = chart.heading
        heading_x = (heading.winfo_rootx() - area.winfo_rootx() + heading.winfo_width()) * scale
        heading_y = (heading.winfo_rooty() - area.winfo_rooty() + heading.winfo_height() / 2) * scale
        renderer.text(image, heading_x, heading_y, heading.cget("text"), ("Segoe UI", 10, "bold"), "#202936", anchor="e")
        canvas = chart.canvas
        snapshot = renderer.canvas(canvas)
        canvas_x = round((canvas.winfo_rootx() - area.winfo_rootx()) * scale)
        canvas_y = round((canvas.winfo_rooty() - area.winfo_rooty()) * scale)
        image.paste(snapshot, (canvas_x, canvas_y), snapshot)
    renderer.text(image, (width - app.px(8)) * scale, (height + footer / 2) * scale,
                  date_text, ("Segoe UI", 9), "#647184", anchor="e")
    image.convert("RGB").save(path, format="PNG", dpi=(300, 300))
    return image.size
