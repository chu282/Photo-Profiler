"""Exercise real HEIC EXIF parsing without requiring compressed image pixels."""
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, TiffImagePlugin

from profiler import label, read_photo


def heic_metadata(path, exposure, apex):
    def box(kind, data):
        return struct.pack(">I4s", len(data) + 8, kind) + data

    exif = Image.Exif()
    exif[271] = "Test camera"
    fields = {34855: 32, 37377: TiffImagePlugin.IFDRational(apex)}
    if exposure is not None:
        fields[33434] = TiffImagePlugin.IFDRational(exposure)
    exif[34665] = fields
    payload = struct.pack(">I", 6) + exif.tobytes()
    ftyp = box(b"ftyp", b"heic" + bytes(4) + b"heicmif1")
    infe = box(b"infe", b"\x02\0\0\0" + struct.pack(">HH", 1, 0) + b"ExifExif\0")
    iinf = box(b"iinf", bytes(4) + struct.pack(">H", 1) + infe)

    def meta(offset):
        iloc = box(b"iloc", bytes(4) + b"\x44\0" + struct.pack(">HHHHII", 1, 1, 0, 1, offset, len(payload)))
        return box(b"meta", bytes(4) + iinf + iloc)

    metadata = meta(len(ftyp) + len(meta(0)) + 8)
    path.write_bytes(ftyp + metadata + box(b"mdat", payload))


class ShutterTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".temp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.path = Path(self.temp.name) / "test.heic"

    def tearDown(self):
        self.temp.cleanup()

    def test_heic_primary_exposure_wins_over_disagreeing_apex(self):
        heic_metadata(self.path, 1 / 8000, math.log2(7299))
        photo = read_photo(self.path)
        self.assertAlmostEqual(photo.values["Shutter speed"], 1 / 8000, places=12)
        self.assertEqual(photo.values["ISO"], 32)
        self.assertEqual(photo.metadata["shutter_source"], "ExposureTime")
        self.assertEqual(label("Shutter speed", photo.values["Shutter speed"]), "1/8000 s")

    def test_actual_nonstandard_exposure_is_preserved(self):
        heic_metadata(self.path, 1 / 7299, math.log2(8000))
        photo = read_photo(self.path)
        self.assertAlmostEqual(photo.values["Shutter speed"], 1 / 7299, places=12)
        self.assertEqual(label("Shutter speed", photo.values["Shutter speed"]), "1/7299 s")

    def test_apex_fallback_including_zero_and_negative(self):
        for exposure in (None, 0):
            for apex, seconds in ((13, 1 / 8192), (0, 1), (-2, 4)):
                with self.subTest(exposure=exposure, apex=apex):
                    heic_metadata(self.path, exposure, apex)
                    photo = read_photo(self.path)
                    self.assertEqual(photo.values["Shutter speed"], seconds)
                    self.assertEqual(photo.metadata["shutter_source"], "ShutterSpeedValue (APEX)")

    def test_invalid_first_reader_uses_valid_second_reader_exposure(self):
        path = self.path.with_suffix(".jpg")
        exif = Image.Exif()
        exif[34665] = {33434: TiffImagePlugin.IFDRational(1, 8000)}
        Image.new("RGB", (10, 10)).save(path, exif=exif)
        for invalid in (0, "invalid", None):
            with patch("profiler.exifread.process_file", return_value={
                "EXIF ExposureTime": invalid, "EXIF ShutterSpeedValue": math.log2(7299)
            }):
                self.assertEqual(read_photo(path).values["Shutter speed"], 1 / 8000)

    def test_rational_string_and_plain_labels(self):
        self.path.write_bytes(b"metadata fixture")
        with patch("profiler.exifread.process_file", return_value={"EXIF ExposureTime": "1/8000"}):
            self.assertEqual(read_photo(self.path).values["Shutter speed"], 1 / 8000)
        for seconds, expected in ((1 / 250, "1/250 s"), (1 / 16000, "1/16000 s"),
                                  (1 / 100000, "1/100000 s"), (10000, "10000 s"), (1.5, "1.5 s")):
            self.assertEqual(label("Shutter speed", seconds), expected)
