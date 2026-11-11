from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from profiler import Photo, Result
from session import load_session, save_session


class SessionTests(unittest.TestCase):
    def test_round_trip_keeps_histogram_inputs_and_view_settings(self):
        root = Path(__file__).resolve().parents[1] / ".temp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path = Path(folder) / "session.json"
            original = Result(photos=[Photo("sample.jpg", datetime(2024, 2, 3, 10, 20),
                                           {"Focal length": 20, "Focal length (35mm)": 40},
                                           {"camera": "E-M5MarkII", "equivalent_source": "sensor"})],
                              checked=3, no_exif=1, errors=[("bad.jpg", "error")])
            options = {"view": "Over time", "equivalent_35mm": True, "visible": {"ISO": False}}
            save_session(original, [folder], options, path)
            restored = load_session(path)
            self.assertEqual(restored["result"], original)
            self.assertEqual(restored["options"], options)
            self.assertEqual(restored["folders"], [folder])
            self.assertFalse(path.with_suffix(".tmp").exists())
            path.write_text("invalid json")
            self.assertIsNone(load_session(path))
