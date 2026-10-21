from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import synapse


class SynapseTests(unittest.TestCase):
    def test_running_synapse_is_not_launched_again(self):
        with patch.object(synapse, "is_running", return_value=True), \
                patch.object(synapse, "find_shortcut") as find, patch.object(synapse.os, "startfile") as launch:
            self.assertEqual(synapse.ensure_running(), "running")
        find.assert_not_called()
        launch.assert_not_called()

    def test_installed_synapse_starts_through_its_shortcut(self):
        shortcut = Path("C:/Start Menu/Razer/Razer Synapse.lnk")
        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=shortcut), \
                patch.object(synapse.os, "startfile") as launch:
            self.assertEqual(synapse.ensure_running(), "started")
        launch.assert_called_once_with(str(shortcut), show_cmd=0)

    def test_missing_install_does_not_download_or_launch(self):
        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=None), \
                patch.object(synapse.os, "startfile") as launch:
            self.assertEqual(synapse.ensure_running(), "missing")
        launch.assert_not_called()

    def test_common_and_user_start_menu_are_both_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {"APPDATA": str(root / "user"), "PROGRAMDATA": str(root / "common")}
            with patch.dict(synapse.os.environ, env):
                self.assertIsNone(synapse.find_shortcut())
                for folder in env.values():
                    shortcut = Path(folder) / "Microsoft/Windows/Start Menu/Programs/Razer/Razer Synapse.lnk"
                    shortcut.parent.mkdir(parents=True)
                    shortcut.touch()
                    self.assertEqual(synapse.find_shortcut(), shortcut)
                    shortcut.unlink()

    def test_unrelated_razer_app_engine_does_not_count_as_synapse(self):
        process = Mock(info={"name": "RazerAppEngine.exe", "cmdline": ["--razer-page-name=win-chroma"]})
        with patch.object(synapse.psutil, "process_iter", return_value=[process]):
            self.assertFalse(synapse.is_running())

    def test_synapse_main_process_or_renderer_is_recognized(self):
        for command in ("--url-params=apps=synapse", "--type=renderer --razer-page-name=win-synapse"):
            process = Mock(info={"name": "RazerAppEngine.exe", "cmdline": command.split()})
            with self.subTest(command=command), patch.object(synapse.psutil, "process_iter", return_value=[process]):
                self.assertTrue(synapse.is_running())

    def test_detection_failure_is_not_mistaken_for_missing_install(self):
        with patch.object(synapse.psutil, "process_iter", side_effect=OSError("process query failed")), \
                patch.object(synapse.os, "startfile") as launch:
            with self.assertRaises(OSError):
                synapse.ensure_running()
        launch.assert_not_called()

    def test_launch_failure_is_not_reported_as_started(self):
        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=Path("Razer Synapse.lnk")), \
                patch.object(synapse.os, "startfile", side_effect=OSError("launch failed")):
            with self.assertRaises(OSError):
                synapse.ensure_running()
