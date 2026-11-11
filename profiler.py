"""Read-only photo metadata scanning and chart calculations."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import logging
import math
import os
from pathlib import Path
import threading
from typing import Callable

import exifread
from PIL import Image

logging.getLogger("exifread").addHandler(logging.NullHandler())
logging.getLogger("exifread").propagate = False

EXTENSIONS = set(".jpg .jpeg .jpe .jfif .tif .tiff .png .webp .heic .heif .avif .jxl .dng .nef .nrw .cr2 .arw .sr2 .srf .orf .rw2 .pef .raf .3fr .erf .mos .mrw .raw .kdc .dcr .iiq .cr3".split())
METRICS = ("Aperture", "Shutter speed", "ISO", "Focal length", "Orientation", "Aspect ratio")
CAMERA_CROP_FACTORS = {
    "E-M5MARKII": 2.0,
    "E-M1MARKII": 2.0,
    "CANONEOSR10": 1.6,
    "CANONEOSREBELT2I": 1.6,
    "CANONEOS550D": 1.6,
    "CANONEOS6D": 1.0,
    "CANONEOSR6": 1.0,
}


@dataclass
class Photo:
    path: str
    taken: datetime | None
    values: dict[str, float | str]
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Result:
    photos: list[Photo] = field(default_factory=list)
    checked: int = 0
    no_exif: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


def positive(value) -> float | None:
    try:
        if isinstance(value, (list, tuple)):
            value = value[0]
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError, ZeroDivisionError, OverflowError, IndexError):
        return None


def capture_date(values) -> datetime | None:
    for value in values:
        try:
            return datetime.strptime(str(value).strip().strip("\x00")[:19], "%Y:%m:%d %H:%M:%S")
        except (ValueError, TypeError):
            pass
    return None


def aspect_ratio(width, height):
    """Displayed width:height, grouping near-standard export dimensions."""
    width, height = round(width), round(height)
    if width <= 0 or height <= 0:
        return None
    ratio = width / height
    standards = [(1, 1), (3, 2), (4, 3), (16, 9), (5, 4), (7, 5), (16, 10),
                 (2, 1), (21, 9), (3, 1), (4, 1), (239, 100)]
    candidates = standards + [(b, a) for a, b in standards if a != b]
    a, b = min(candidates, key=lambda pair: abs(math.log(ratio / (pair[0] / pair[1]))))
    if abs(ratio / (a / b) - 1) <= 0.005:
        return "2.39:1" if (a, b) == (239, 100) else "1:2.39" if (a, b) == (100, 239) else f"{a}:{b}"
    divisor = math.gcd(width, height)
    a, b = width // divisor, height // divisor
    if max(a, b) <= 100:
        return f"{a}:{b}"
    return f"{ratio:.3f}:1" if ratio >= 1 else f"1:{1 / ratio:.3f}"


def aspect_ratio_number(value):
    a, b = value.split(":")
    return float(a) / float(b)


def read_photo(path: Path) -> Photo | None:
    parser_error = None
    try:
        with path.open("rb") as stream:
            tags = exifread.process_file(stream, details=False, extract_thumbnail=False)
    except (OSError, ValueError, IndexError, KeyError, TypeError, OverflowError) as exc:
        tags = {}
        parser_error = exc

    def tag(*names):
        for name in names:
            item = tags.get(name)
            if item is not None:
                vals = getattr(item, "values", item)
                if isinstance(vals, (list, tuple)):
                    return vals[0] if vals else None
                return vals
        return None

    width = positive(tag("EXIF ExifImageWidth", "Image ImageWidth"))
    height = positive(tag("EXIF ExifImageLength", "Image ImageLength"))
    orientation = positive(tag("Image Orientation"))
    camera_model = str(tag("Image Model") or "").strip().strip("\x00").strip()
    raw_values = {
        "Aperture": tag("EXIF FNumber"),
        "Shutter speed": tag("EXIF ExposureTime"),
        "ISO": tag("EXIF ISOSpeedRatings", "EXIF PhotographicSensitivity", "EXIF RecommendedExposureIndex"),
        "Focal length": tag("EXIF FocalLength"),
        "Focal length (35mm)": tag("EXIF FocalLengthIn35mmFilm"),
    }
    dates = [tag("EXIF DateTimeOriginal"), tag("EXIF DateTimeDigitized"), tag("Image DateTime")]
    # Pillow also covers EXIF containers that the metadata-only parser may miss.
    try:
        with Image.open(path) as image:
            width, height = image.size
            exif = image.getexif()
            if exif:
                camera_model = camera_model or str(exif.get(272) or "").strip().strip("\x00").strip()
                nested = exif.get_ifd(0x8769)
                for name, key in (("Aperture", 33437), ("Shutter speed", 33434), ("ISO", 34855), ("Focal length", 37386), ("Focal length (35mm)", 41989)):
                    if raw_values[name] is None:
                        raw_values[name] = nested.get(key, exif.get(key))
                dates = [dates[0], nested.get(36867), exif.get(36867), dates[1], nested.get(36868), dates[2], exif.get(306)]
                orientation = orientation or positive(exif.get(274))
            has_exif = bool(tags) or bool(exif)
            if image.format == "TIFF":
                # TIFF pixel layout tags alone are not photographic EXIF.
                metadata_keys = {270, 271, 272, 274, 305, 306, 315, 33432, 33434, 33437, 34665, 34853, 34855, 36867, 36868, 37386}
                has_exif = bool(metadata_keys.intersection(exif)) or any(k.startswith(("EXIF ", "GPS ")) for k in tags)
    except (OSError, ValueError, SyntaxError):
        has_exif = bool(tags)
        if not has_exif:
            raise ValueError(f"Unreadable or unsupported image{': ' + str(parser_error) if parser_error else ''}")
    if not has_exif:
        return None

    values = {}
    for name, value in raw_values.items():
        number = positive(value)
        if number is not None:
            values[name] = number
    # APEX tags are fallbacks for cameras that omit FNumber or ExposureTime.
    for name, apex, factor in (("Aperture", tag("EXIF ApertureValue"), 0.5), ("Shutter speed", tag("EXIF ShutterSpeedValue"), -1)):
        if name not in values and apex is not None:
            try:
                number = positive(2 ** (float(apex) * factor))
                if number is not None:
                    values[name] = number
            except (TypeError, ValueError, OverflowError):
                pass
    if width and height:
        if orientation in (5, 6, 7, 8):
            width, height = height, width
        values["Orientation"] = "Landscape" if width > height else "Portrait" if height > width else "Square"
        ratio = aspect_ratio(width, height)
        if ratio:
            values["Aspect ratio"] = ratio
    metadata = {"camera": camera_model, "aspect_checked": "1"}
    if "Focal length (35mm)" in values:
        metadata["equivalent_source"] = "EXIF"
    elif "Focal length" in values:
        key = "".join(camera_model.upper().split())
        factor = CAMERA_CROP_FACTORS.get(key)
        if factor is not None:
            values["Focal length (35mm)"] = values["Focal length"] * factor
            metadata["equivalent_source"] = f"{camera_model}, {factor:g}× sensor crop"
    return Photo(str(path), capture_date(dates), values, metadata)


def scan(folders: list[str], recursive: bool, cancel: threading.Event,
         progress: Callable[[Result], None] | None = None) -> Result:
    result = Result()
    visited_dirs = set()
    visited_files = set()

    def walk(folder):
        if cancel.is_set():
            return
        try:
            key = os.path.normcase(os.path.realpath(folder))
            if key in visited_dirs:
                return
            visited_dirs.add(key)
            with os.scandir(folder) as entries:
                for entry in entries:
                    if cancel.is_set():
                        return
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            yield from walk(entry.path)
                    elif entry.is_file() and Path(entry.name).suffix.lower() in EXTENSIONS:
                        yield Path(entry.path)
        except OSError as exc:
            result.errors.append((str(folder), str(exc)))

    for folder in folders:
        for path in walk(folder):
            if cancel.is_set():
                break
            key = os.path.normcase(os.path.realpath(path))
            if key in visited_files:
                continue
            visited_files.add(key)
            result.checked += 1
            try:
                photo = read_photo(path)
                if photo is None:
                    result.no_exif += 1
                else:
                    result.photos.append(photo)
            except Exception as exc:
                result.errors.append((str(path), str(exc)))
            if progress and result.checked % 25 == 0:
                progress(result)
        if cancel.is_set():
            break
    result.cancelled = cancel.is_set()
    return result


def label(metric: str, value) -> str:
    if isinstance(value, str):
        return value
    if metric == "Aperture":
        return f"f/{value:g}"
    if metric == "Shutter speed":
        if value < 1:
            return f"1/{1 / value:.4g} s"
        return f"{value:.4g} s"
    if metric == "Focal length":
        return f"{value:g} mm"
    return f"{value:g}"


def distribution_key(value, bin_width=None):
    if bin_width:
        return math.floor(value / bin_width) * bin_width
    return float(f"{value:.5g}") if isinstance(value, (float, int)) else value


def distribution(photos: list[Photo], metric: str, bin_width: float | None = None):
    counts = Counter()
    for photo in photos:
        value = photo.values.get(metric)
        if value is not None:
            # Remove floating-point noise without snapping real camera settings.
            key = distribution_key(value, bin_width)
            counts[key] += 1
    if bin_width and counts:
        first, last = min(counts), max(counts)
        for index in range(round((last - first) / bin_width) + 1):
            counts.setdefault(first + index * bin_width, 0)
    return sorted(counts.items(), key=lambda item: aspect_ratio_number(item[0])) if metric == "Aspect ratio" else sorted(counts.items())


def moving_average(points: list[tuple[datetime, float]], days: int):
    """Photo-weighted mean in the trailing N calendar days, sampled daily.

    None splits the line when a window contains no photographs. Long histories
    are sampled at up to 4,000 evenly spaced dates to keep the UI responsive.
    """
    if not points:
        return []
    daily = defaultdict(lambda: [0.0, 0])
    for date, value in points:
        day = date.date().toordinal()
        daily[day][0] += value
        daily[day][1] += 1
    dates = sorted(daily)
    sums, counts = [0.0], [0]
    for day in dates:
        sums.append(sums[-1] + daily[day][0])
        counts.append(counts[-1] + daily[day][1])
    span = dates[-1] - dates[0]
    steps = min(span, 3999)
    samples = {dates[0] + round(i * span / steps) for i in range(steps + 1)} if steps else {dates[0]}
    output = []
    for day in sorted(samples):
        left = bisect_left(dates, day - max(1, days) + 1)
        right = bisect_right(dates, day)
        count = counts[right] - counts[left]
        output.append((datetime.fromordinal(day), (sums[right] - sums[left]) / count if count else None))
    return output
