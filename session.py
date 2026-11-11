"""Small, local-only scan cache shared by portable and installed versions."""
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path

from profiler import Photo, Result


def default_path():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "Photo Profiler" / "session.json"


def load_session(path=None):
    path = Path(path) if path else default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return None
        raw = data["result"]
        photos = [Photo(p["path"], datetime.fromisoformat(p["taken"]) if p["taken"] else None,
                        p["values"], p.get("metadata", {})) for p in raw["photos"]]
        data["result"] = Result(photos=photos, checked=raw.get("checked", 0), no_exif=raw.get("no_exif", 0),
                                errors=[tuple(item) for item in raw.get("errors", [])], cancelled=raw.get("cancelled", False))
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_session(result, folders, options, path=None):
    path = Path(path) if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = asdict(result)
    for photo in raw["photos"]:
        photo["taken"] = photo["taken"].isoformat() if photo["taken"] else None
    data = {"version": 1, "result": raw, "folders": list(folders), "options": options}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
