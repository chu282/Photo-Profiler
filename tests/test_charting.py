from datetime import datetime
import unittest

from charting import COMMON_FOCAL_LENGTHS, calendar_ticks, common_focal_length, setting_axis, without_outliers
from profiler import Photo


class ChartCalculationTests(unittest.TestCase):
    def test_common_lengths_use_the_approved_list_and_nearest_value(self):
        self.assertEqual(COMMON_FOCAL_LENGTHS, (8, 10, 12, 14, 16, 18, 20, 24, 28, 35, 40, 50, 60, 70, 85,
                                               100, 105, 135, 150, 180, 200, 250, 300, 400, 500, 600, 800))
        self.assertEqual([common_focal_length(value) for value in (5, 23, 37.5, 39.9, 49, 75, 1200)],
                         [8, 24, 35, 40, 50, 70, 800])

    def test_iqr_filter_is_per_setting_and_preserves_input(self):
        photos = [Photo(str(i), None, {"Focal length": value, "ISO": 100})
                  for i, value in enumerate([24, 35, 35, 50, 50, 50, 85, 85, 85, 5000])]
        filtered = without_outliers(photos, "Focal length")
        self.assertEqual(len(filtered), 9)
        self.assertEqual(len(photos), 10)
        self.assertEqual(len(without_outliers(photos, "ISO")), 10)

    def test_zero_iqr_keeps_normal_alternatives(self):
        values = [35] * 20 + [50] * 60 + [85] * 20 + [5000]
        photos = [Photo(str(i), None, {"Focal length": v}) for i, v in enumerate(values)]
        filtered = without_outliers(photos, "Focal length")
        self.assertEqual(len(filtered), 100)
        self.assertEqual({p.values["Focal length"] for p in filtered}, {35, 50, 85})

    def test_small_samples_and_orientation_are_not_trimmed(self):
        photos = [Photo("x", None, {"ISO": v, "Orientation": "Portrait"}) for v in [100, 100, 100, 999999]]
        self.assertEqual(without_outliers(photos, "ISO"), photos)
        self.assertEqual(without_outliers(photos * 3, "Orientation"), photos * 3)

    def test_focal_ticks_include_actual_settings_and_round_extras(self):
        actual = [24, 35, 50, 85, 135]
        lo, hi, ticks = setting_axis(actual, "Focal length", True, target=18, pixels=650)
        self.assertTrue(set(actual).issubset(ticks))
        self.assertTrue(all(value == int(value) for value in ticks))
        self.assertGreater(len(ticks), len(actual))
        self.assertLess(lo, hi)

    def test_many_focal_lengths_have_round_even_ticks(self):
        lo, hi, ticks = setting_axis(list(range(24, 136)), "Focal length", False, target=10)
        self.assertTrue(all(value % 10 == 0 for value in ticks))
        self.assertLessEqual(lo, 24)
        self.assertGreaterEqual(hi, 135)

    def test_shutter_ticks_use_camera_stops(self):
        actual = [1 / 1000, 1 / 250, 1 / 60, 1 / 15]
        _, _, ticks = setting_axis(actual, "Shutter speed", True, target=18, pixels=650)
        self.assertTrue(set(actual).issubset(ticks))
        self.assertIn(1 / 125, ticks)
        self.assertGreater(len(ticks), 4)

    def test_dates_use_quarters_instead_of_arithmetic_offsets(self):
        ticks = calendar_ticks(datetime(2023, 1, 1, 12), datetime(2025, 6, 17), 10)
        self.assertGreaterEqual(len(ticks), 8)
        self.assertTrue(all(date.day == 1 and date.month in (1, 4, 7, 10) for date, _ in ticks))

    def test_short_date_ranges_use_regular_clock_times(self):
        ticks = calendar_ticks(datetime(2024, 1, 1, 10, 12), datetime(2024, 1, 1, 18, 23), 8)
        self.assertTrue(all(date.minute == 0 and date.second == 0 for date, _ in ticks))


if __name__ == "__main__":
    unittest.main()
