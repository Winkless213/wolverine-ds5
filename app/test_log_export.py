import datetime
import pathlib
import tempfile
import unittest

from app.log_export import build_diagnostic, default_export_path


class LogExportTests(unittest.TestCase):
    def test_build_includes_settings_and_truncates_bridge_tail(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        (directory / "startup.log").write_text("started\n", encoding="utf-8")
        (directory / "native-exit.log").write_text("native\n", encoding="utf-8")
        (directory / "bridge-2026-10-25.log").write_text(
            "".join(f"line {index}\n" for index in range(6000)), encoding="utf-8")
        text = build_diagnostic(directory, "1.1.12", "pc",
                                {"grip_gain": 1.0}, now=datetime.datetime(2026, 10, 25, 12, 0, 0),
                                status={"state": "connected", "backend": "sensa", "grips_ready": False})
        self.assertIn("version: 1.1.12", text)
        self.assertIn('"grip_gain": 1.0', text)
        self.assertIn('"grips_ready": false', text)
        self.assertIn("--- startup.log ---", text)
        self.assertIn("line 5999", text)
        self.assertNotIn("line 0\n", text)
        self.assertIn("仅显示最后 5000 行", text)

    def test_default_path_is_timestamped(self):
        path = default_export_path(pathlib.Path("D:/x"), now=datetime.datetime(2026, 10, 25, 1, 2, 3))
        self.assertEqual(path.name, "WolverineDS5-diagnostics-20261025-010203.txt")


if __name__ == "__main__":
    unittest.main()
