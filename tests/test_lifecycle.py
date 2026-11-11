import tkinter as tk
import unittest
from unittest.mock import patch
import uuid

from app import App
from lifecycle import AppInstance, signal_shutdown


class LifetimeTests(unittest.TestCase):
    def test_single_instance_and_shutdown_event_release_cleanly(self):
        handles = []
        with patch("lifecycle.identity", return_value="Test." + uuid.uuid4().hex):
            try:
                first = AppInstance()
                handles.append(first)
                second = AppInstance()
                handles.append(second)
                self.assertTrue(first.first)
                self.assertFalse(second.first)
                second.close()
                self.assertTrue(signal_shutdown("test-instance"))
                self.assertTrue(first.shutdown_requested())
                first.close()
                third = AppInstance()
                handles.append(third)
                self.assertTrue(third.first)
                self.assertFalse(third.shutdown_requested())
            finally:
                for handle in handles:
                    handle.close()

    def test_close_exits_even_if_saving_or_stopping_a_widget_fails(self):
        root = tk.Tk()
        root.withdraw()
        app = App(root, restore=False)
        try:
            with patch.object(app, "save_current_session", side_effect=RuntimeError("test save failure")), \
                    patch.object(app.progress, "stop", side_effect=tk.TclError("test timer failure")):
                app.close()
            self.assertTrue(app.closing)
            try:
                alive = bool(root.winfo_exists())
            except tk.TclError:
                alive = False
            self.assertFalse(alive)
            app.close()  # Repeated close requests are harmless.
        finally:
            if not app.closing:
                root.destroy()
