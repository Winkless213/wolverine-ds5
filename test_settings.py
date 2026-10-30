import json
import pathlib
import tempfile
import unittest

import settings
from settings import Settings, load, save


class SettingsTests(unittest.TestCase):
    def test_defaults_keep_native_scale(self):
        settings = Settings()
        self.assertEqual((settings.grip_gain, settings.grip_gain_left, settings.grip_gain_right,
                          settings.trigger_gain), (1.0, 1.0, 1.0, 1.0))
        self.assertFalse(settings.trigger_follow)
        self.assertFalse(settings.grip_soft)
        self.assertTrue(settings.audio_guard)

    def test_legacy_single_gain_migrates_to_both_sides(self):
        settings = Settings.from_dict({"grip_gain": .6})
        self.assertEqual((settings.grip_gain_left, settings.grip_gain_right), (.6, .6))

    def test_left_and_right_gains_are_independent(self):
        settings = Settings.from_dict({"grip_gain": 1.0, "grip_gain_left": .3, "grip_gain_right": 1.2})
        self.assertEqual((settings.grip_gain_left, settings.grip_gain_right), (.3, 1.2))

    def test_explicit_full_scale_is_not_overwritten_by_legacy_gain(self):
        settings = Settings(grip_gain=.4, grip_gain_left=1.0, grip_gain_right=1.0)
        self.assertEqual((settings.grip_gain_left, settings.grip_gain_right), (1.0, 1.0))

    def test_out_of_range_values_are_clamped(self):
        settings = Settings.from_dict({"grip_gain": 9, "trigger_gain": -1, "follow_ratio": 2})
        self.assertEqual((settings.grip_gain, settings.trigger_gain, settings.follow_ratio), (1.5, 0.0, 1.0))

    def test_unknown_and_wrongly_typed_fields_fall_back_to_defaults(self):
        settings = Settings.from_dict({"grip_gain": "loud", "trigger_follow": "yes", "colour": "red",
                                       "hidden_devices": [1, "USB\\X"]})
        self.assertEqual(settings, Settings())

    def test_haptic_profile_defaults_to_full_and_rejects_unknown(self):
        # 2026-10-30 实机确认“打击”档战斗不丢震动、打击反馈正常，设为默认。
        self.assertEqual(Settings().haptic_profile, "full")
        self.assertEqual(Settings.from_dict({}).haptic_profile, "full")
        self.assertEqual(Settings.from_dict({"haptic_profile": "dynamic"}).haptic_profile, "dynamic")
        self.assertEqual(Settings.from_dict({"haptic_profile": "balanced_plus"}).haptic_profile, "balanced_plus")
        self.assertEqual(Settings.from_dict({"haptic_profile": "nope"}).haptic_profile, "full")

    def test_a_saved_profile_choice_is_kept(self):
        # 改默认值不迁移已保存的选择：用户明确选过的档位（包括旧版）保持不变。
        self.assertEqual(Settings.from_dict({"haptic_profile": "legacy"}).haptic_profile, "legacy")

    def test_settings_profiles_match_the_encoder(self):
        import pcm_encoder

        self.assertEqual(settings.PROFILES, pcm_encoder.PROFILES)

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
