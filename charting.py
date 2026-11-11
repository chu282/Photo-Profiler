"""Axis placement and reversible per-chart outlier filtering."""
from datetime import datetime, timedelta
import math

COMMON_FOCAL_LENGTHS = (8, 10, 12, 14, 16, 18, 20, 24, 28, 35, 40, 50, 60, 70, 85,
                        100, 105, 135, 150, 180, 200, 250, 300, 400, 500, 600, 800)


def common_focal_length(value):
    return min(COMMON_FOCAL_LENGTHS, key=lambda focal: (abs(focal - value), focal))


def percentile(ordered, fraction):
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def without_outliers(photos, metric):
    if metric in ("Orientation", "Aspect ratio") or len(photos) < 8:
        return photos
    values = sorted(p.values[metric] for p in photos)
    q1, q3 = percentile(values, 0.25), percentile(values, 0.75)
    spread = q3 - q1
    if spread:
        low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    else:
        # A dominant fixed lens/setting can collapse the IQR to zero. Only
        # trim the outer 1% tails in that case, retaining normal alternatives.
        low, high = percentile(values, 0.01), percentile(values, 0.99)
    return [p for p in photos if low <= p.values[metric] <= high]


def nice_step(span, target):
    raw = max(span / max(1, target - 1), 1e-12)
    power = 10 ** math.floor(math.log10(raw))
    return min((n * power for n in (1, 2, 2.5, 5, 10)), key=lambda step: abs(math.log(step / raw)))


def setting_axis(values, metric, logarithmic, target=10, pixels=300):
    """Return bounds and ticks in original setting units, never padded labels."""
    distinct = sorted(set(values))
    low, high = distinct[0], distinct[-1]
    transform = math.log2 if logarithmic else lambda value: value
    a, b = transform(low), transform(high)
    padding = (b - a) * 0.05 if a != b else max(abs(a) * 0.08, 0.5)
    lo, hi = a - padding, b + padding
    if not logarithmic:
        lo = max(0, lo)
    # Label actual camera settings whenever they fit, so rows of points land
    # exactly on their labeled grid lines, including non-round lens lengths.
    if metric == "Shutter speed":
        candidates = [1 / n for n in (32000, 16000, 8000, 4000, 2000, 1000, 500, 250, 125, 60, 30, 15, 8, 4, 2)]
        candidates += [1, 2, 4, 8, 15, 30, 60, 120, 240, 480, 960, 1800, 3600]
    elif metric == "Aperture":
        candidates = [0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11, 16, 22, 32, 45, 64, 90, 128]
    elif logarithmic and metric == "ISO":
        candidates = [25 * 2 ** i for i in range(18)]
    elif logarithmic:
        if metric == "Focal length":
            step = max(1, nice_step(high - low if high > low else high, target))
            candidates = [float(f"{math.ceil(low / step) * step + i * step:.10g}") for i in range(math.ceil((high - low) / step) + 1)]
        else:
            candidates = sorted({n * 10 ** exponent for exponent in range(-2, 8) for n in (1, 2, 5)})
    else:
        step = nice_step(high - low if high > low else high, target)
        if metric in ("ISO", "Focal length"):
            step = max(1, step)
        lo = max(0, math.floor(lo / step) * step)
        hi = math.ceil(hi / step) * step
        count = round((hi - lo) / step)
        ticks = [float(f"{lo + i * step:.10g}") for i in range(count + 1)]
        candidates = ticks

    if len(distinct) <= target and (len(distinct) == 1 or
            min(transform(y) - transform(x) for x, y in zip(distinct, distinct[1:])) / (hi - lo) * pixels >= 23):
        ticks = list(distinct)
        for value in candidates:
            if (value > 0 or not logarithmic) and lo <= transform(value) <= hi and all(
                    abs(transform(value) - transform(existing)) / (hi - lo) * pixels >= 25 for existing in ticks):
                ticks.append(value)
        return lo, hi, sorted(ticks)

    ticks = []
    for value in candidates:
        if logarithmic and value <= 0:
            continue
        position = transform(value)
        if lo <= position <= hi and (not ticks or (position - transform(ticks[-1])) / (hi - lo) * pixels >= 25):
            ticks.append(value)
    if not ticks:
        ticks = [low] if low == high else [low, high]
    return lo, hi, ticks


def calendar_ticks(start, end, target=8):
    """Calendar-aligned hours, days, months, or years."""
    seconds = (end - start).total_seconds()
    target = max(3, target)
    if seconds <= 2 * 86400:
        candidates = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200]
        step = min(candidates, key=lambda value: abs(math.log(value / max(seconds / target, 1))))
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        tick = midnight + timedelta(seconds=math.ceil((start - midnight).total_seconds() / step) * step)
        result = []
        while tick <= end:
            result.append((tick, tick.strftime("%H:%M\n%d %b")))
            tick += timedelta(seconds=step)
        return result
    if seconds <= 120 * 86400:
        days = seconds / 86400
        step = min((1, 2, 7, 14, 28), key=lambda n: abs(math.log(n / (days / target))))
        tick = start.replace(hour=0, minute=0, second=0, microsecond=0)
        if step >= 7:
            tick -= timedelta(days=tick.weekday())
        while tick < start:
            tick += timedelta(days=step)
        result = []
        while tick <= end:
            result.append((tick, tick.strftime("%d %b\n%Y")))
            tick += timedelta(days=step)
        return result
    month_span = seconds / (86400 * 30.4375)
    step = min((1, 2, 3, 6, 12, 24, 36, 60, 120, 240, 600, 1200),
               key=lambda n: abs(math.log(n / (month_span / target))))
    index = (start.year - 1) * 12 + start.month - 1
    index = math.ceil(index / step) * step
    result = []
    while index < 9999 * 12:
        tick = datetime(index // 12 + 1, index % 12 + 1, 1)
        if tick > end:
            break
        if tick >= start:
            result.append((tick, tick.strftime("%Y" if step >= 12 else "%b\n%Y")))
        index += step
    return result
