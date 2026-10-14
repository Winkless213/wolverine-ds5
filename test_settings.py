import json
import pathlib
import tempfile
import unittest

from settings import Settings, load, save


class SettingsTests(unittest.TestCase):
    def test_defaults_keep_native_scale(self):
        settings = Settings()
        self.assertEqual((settings.grip_gain, settings.trigger_gain), (1.0, 1.0))
        self.assertFalse(settings.trigger_follow)
        self.assertTrue(settings.audio_guard)

    def test_out_of_range_values_are_clamped(self):
        settings = Settings.from_dict({"grip_gain": 9, "trigger_gain": -1, "follow_ratio": 2})
        self.assertEqual((settings.grip_gain, settings.trigger_gain, settings.follow_ratio), (1.5, 0.0, 1.0))

    def test_unknown_and_wrongly_typed_fields_fall_back_to_defaults(self):
        settings = Settings.from_dict({"grip_gain": "loud", "trigger_follow": "yes", "colour": "red",
                                       "hidden_devices": [1, "USB\\X"]})
        self.assertEqual(settings, Settings())

    def test_hidden_devices_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "settings.json"
            save(Settings(hidden_devices=("USB\\A", "USB\\B"), hidden_app="C:/W/bridge.exe"), path)
            self.assertEqual(load(path).hidden_devices, ("USB\\A", "USB\\B"))
            self.assertEqual(load(path).hidden_app, "C:/W/bridge.exe")

    def test_saved_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "nested" / "settings.json"
            save(Settings(grip_gain=.5, trigger_follow=True, follow_ratio=.3), path)
            self.assertEqual(load(path), Settings(grip_gain=.5, trigger_follow=True, follow_ratio=.3))

    def test_missing_or_corrupt_file_loads_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "settings.json"
            self.assertEqual(load(path), Settings())
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load(path), Settings())

    def test_saved_file_is_plain_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "settings.json"
            save(Settings(), path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["grip_gain"], 1.0)


if __name__ == "__main__":
    unittest.main()
