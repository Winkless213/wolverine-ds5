"""界面模型：档位点击必须对每一档都下发设置（曾因硬编码四档导致“平衡+”点了没反应）。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.ui_model import UiModel
from settings import PROFILES, Settings


class HapticProfileTests(unittest.TestCase):
    def test_every_profile_chip_reaches_the_settings(self):
        model = UiModel(Settings(), pathlib.Path("."))
        seen = []
        model.settingsEdited.connect(seen.append)
        for name in PROFILES:
            model.setHapticProfile(name)
        self.assertEqual([item["haptic_profile"] for item in seen], list(PROFILES))
        self.assertEqual(model.hapticProfile, PROFILES[-1])

    def test_unknown_profile_is_ignored(self):
        model = UiModel(Settings(), pathlib.Path("."))
        seen = []
        model.settingsEdited.connect(seen.append)
        model.setHapticProfile("nope")
        self.assertEqual(seen, [])
        self.assertEqual(model.hapticProfile, "full")


if __name__ == "__main__":
    unittest.main()
