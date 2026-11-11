from datetime import datetime
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image, TiffImagePlugin

from profiler import Photo, aspect_ratio, capture_date, distribution, moving_average, read_photo, scan


def make_photo(path, *, rotation=1, date="2024:03:10 12:00:00", focal=50, equivalent=None, model=None, nested=True):
    exif = Image.Exif()
    exif[271] = "Test camera"
    exif[274] = rotation
    if model:
        exif[272] = model
    camera = {33437: TiffImagePlugin.IFDRational(28, 10),
              33434: TiffImagePlugin.IFDRational(1, 250),
              34855: 400,
              37386: TiffImagePlugin.IFDRational(focal, 1)}
    if date:
        camera[36867] = date
    if equivalent is not None:
        camera[41989] = equivalent
    if nested:
        exif[34665] = camera
    else:
        for key, value in camera.items():
            exif[key] = value
    Image.new("RGB", (120, 80)).save(path, exif=exif)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".temp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_nested_exif_and_rotation(self):
        path = self.folder / "photo.jpg"
        make_photo(path, rotation=6)
        photo = read_photo(path)
        self.assertAlmostEqual(photo.values["Aperture"], 2.8)
        self.assertAlmostEqual(photo.values["Shutter speed"], 1 / 250)
        self.assertEqual(photo.values["ISO"], 400)
        self.assertEqual(photo.values["Focal length"], 50)
        self.assertEqual(photo.values["Orientation"], "Portrait")
        self.assertEqual(photo.values["Aspect ratio"], "2:3")
        self.assertEqual(photo.taken, datetime(2024, 3, 10, 12))

    def test_no_exif_images_are_ignored(self):
        for ext in ("jpg", "png", "tiff", "webp"):
            path = self.folder / f"plain.{ext}"
            Image.new("RGB", (120, 80)).save(path)
            self.assertIsNone(read_photo(path), ext)

    def test_35mm_equivalent_is_read_separately(self):
        for equivalent in (75, 0, None):
            path = self.folder / f"equivalent-{equivalent}.jpg"
            make_photo(path, focal=50, equivalent=equivalent)
            photo = read_photo(path)
            self.assertEqual(photo.values["Focal length"], 50)
            if equivalent:
                self.assertEqual(photo.values["Focal length (35mm)"], 75)
            else:
                self.assertNotIn("Focal length (35mm)", photo.values)

    def test_missing_olympus_equivalents_are_derived_not_dropped(self):
        photos = []
        for i, focal in enumerate((17.5, 20, 22.5, 24.9)):
            path = self.folder / f"olympus-{i}.jpg"
            make_photo(path, focal=focal, model="E-M5MarkII      ")
            photos.append(read_photo(path))
        self.assertEqual([p.values["Focal length (35mm)"] for p in photos], [35, 40, 45, 49.8])
        self.assertEqual(distribution(photos, "Focal length (35mm)", 5), [(35, 1), (40, 1), (45, 2)])
        self.assertTrue(all("2× sensor crop" in p.metadata["equivalent_source"] for p in photos))

    def test_explicit_equivalent_takes_priority_over_nominal_sensor(self):
        path = self.folder / "cropped.jpg"
        make_photo(path, focal=20, equivalent=60, model="E-M5MarkII")
        photo = read_photo(path)
        self.assertEqual(photo.values["Focal length (35mm)"], 60)
        self.assertEqual(photo.metadata["equivalent_source"], "EXIF")

    def test_dated_png_and_tiff(self):
        for ext in ("png", "tiff"):
            path = self.folder / f"photo.{ext}"
            make_photo(path, nested=ext != "tiff")
            photo = read_photo(path)
            self.assertEqual(photo.values["Focal length"], 50, ext)
            self.assertEqual(photo.taken, datetime(2024, 3, 10, 12), ext)

    def test_missing_fields_and_undated(self):
        path = self.folder / "minimal.jpg"
        exif = Image.Exif()
        exif[271] = "Camera"
        Image.new("RGB", (80, 80)).save(path, exif=exif)
        photo = read_photo(path)
        self.assertIsNone(photo.taken)
        self.assertEqual(photo.values, {"Orientation": "Square", "Aspect ratio": "1:1"})

    def test_recursion_dedup_corruption_and_plain_files(self):
        sub = self.folder / "nested"
        sub.mkdir()
        make_photo(self.folder / "a.jpg")
        make_photo(sub / "b.jpg")
        Image.new("RGB", (10, 10)).save(self.folder / "plain.jpg")
        (self.folder / "bad.jpg").write_bytes(b"broken")
        (self.folder / "notes.txt").write_text("ignore")
        result = scan([str(sub), str(self.folder), str(sub)], True, threading.Event())
        self.assertEqual(result.checked, 4)
        self.assertEqual(len(result.photos), 2)
        self.assertEqual(result.no_exif, 1)
        self.assertEqual(len(result.errors), 1)
        result = scan([str(self.folder)], False, threading.Event())
        self.assertEqual(len(result.photos), 1)

    def test_cancellation_and_unreadable_folder(self):
        cancel = threading.Event()
        cancel.set()
        result = scan([str(self.folder)], True, cancel)
        self.assertTrue(result.cancelled)
        self.assertEqual(result.checked, 0)
        result = scan([str(self.folder / "missing")], True, threading.Event())
        self.assertEqual(len(result.errors), 1)


class CalculationTests(unittest.TestCase):
    def test_aspect_ratio_groups_pixel_rounding_and_keeps_portrait_distinct(self):
        self.assertEqual(aspect_ratio(6000, 4000), "3:2")
        self.assertEqual(aspect_ratio(4000, 6000), "2:3")
        self.assertEqual(aspect_ratio(4000, 2667), "3:2")
        self.assertEqual(aspect_ratio(4032, 3024), "4:3")
        self.assertEqual(aspect_ratio(1920, 1080), "16:9")
        self.assertEqual(aspect_ratio(1080, 1920), "9:16")
        self.assertEqual(aspect_ratio(800, 800), "1:1")
        self.assertEqual(aspect_ratio(900, 500), "9:5")
        self.assertIsNone(aspect_ratio(0, 500))

    def test_aspect_distribution_uses_numeric_order(self):
        photos = [Photo(str(i), None, {"Aspect ratio": value}) for i, value in enumerate(("16:9", "3:2", "1:1", "2:3", "3:2"))]
        self.assertEqual(distribution(photos, "Aspect ratio"), [("2:3", 1), ("1:1", 1), ("3:2", 2), ("16:9", 1)])

    def test_ten_mm_bins_have_equal_intervals_including_empty_bins(self):
        values = [19.9, 20, 24, 29.9, 30, 50]
        photos = [Photo(str(i), None, {"Focal length": v}) for i, v in enumerate(values)]
        self.assertEqual(distribution(photos, "Focal length", bin_width=10),
                         [(10, 1), (20, 3), (30, 1), (40, 0), (50, 1)])
        self.assertEqual(sum(c for _, c in distribution(photos, "Focal length", bin_width=10)), len(values))

    def test_five_mm_bins_preserve_boundaries_and_gaps(self):
        values = [19.9, 20, 24.9, 25, 35]
        photos = [Photo(str(i), None, {"Focal length": v}) for i, v in enumerate(values)]
        self.assertEqual(distribution(photos, "Focal length", bin_width=5),
                         [(15, 1), (20, 2), (25, 1), (30, 0), (35, 1)])

    def test_calendar_window_is_photo_weighted_and_breaks_gaps(self):
        points = [(datetime(2024, 1, 1, 18), 20),
                  (datetime(2024, 1, 1, 19), 40),
                  (datetime(2024, 1, 2, 9), 90),
                  (datetime(2024, 1, 6, 12), 100)]
        result = dict(moving_average(points, 2))
        self.assertEqual(result[datetime(2024, 1, 1)], 30)
        self.assertEqual(result[datetime(2024, 1, 2)], 50)
        self.assertEqual(result[datetime(2024, 1, 3)], 90)
        self.assertIsNone(result[datetime(2024, 1, 4)])
        self.assertEqual(result[datetime(2024, 1, 6)], 100)

    def test_missing_settings_not_zero_and_dates_fall_back(self):
        photos = [Photo("a", None, {"ISO": 400}), Photo("b", None, {}), Photo("c", None, {"ISO": 100})]
        self.assertEqual(distribution(photos, "ISO"), [(100, 1), (400, 1)])
        self.assertEqual(capture_date(["bad", "2024:05:10 10:11:12"]), datetime(2024, 5, 10, 10, 11, 12))


if __name__ == "__main__":
    unittest.main()
