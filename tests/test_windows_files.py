from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_files


class FileActionTests(unittest.TestCase):
    def test_paths_with_spaces_and_unicode_go_directly_to_default_app(self):
        base = Path(__file__).resolve().parents[1] / ".temp"
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            path = Path(folder) / "photo 01 — edited.jpg"
            path.write_bytes(b"test")
            with patch("os.startfile") as launch:
                windows_files.open_file(path)
                launch.assert_called_once_with(str(path.absolute()))
                launch.reset_mock()
                windows_files.open_folder(path)
                launch.assert_called_once_with(str(path.absolute().parent))

    def test_missing_cached_file_reports_an_error_before_launching(self):
        path = Path(__file__).resolve().parents[1] / ".temp" / "missing-photo.jpg"
        with patch("os.startfile") as launch:
            with self.assertRaises(FileNotFoundError):
                windows_files.open_file(path)
            with self.assertRaises(FileNotFoundError):
                windows_files.reveal_file(path)
            launch.assert_not_called()
