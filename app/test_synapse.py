import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import synapse

# 以下几行照抄本机雷蛇日志（2026-10-29/30，含早上雷云离线那次），格式变了这里会先失败。
ADDED = ('[2026-10-30 10:29:41.906][5312] [RzInterHaptics.RpcClient] [info] '
         'DeviceAdded "2636-{61219129-17cc-11f1-8671-444648929145}"')
REMOVED = ('[2026-10-29 22:27:12.739][20128] [RzInterHaptics.RpcClient] [info] '
           'DeviceRemoved "2636-{61219129-17cc-11f1-8671-444648929145}"')
RESTART = ('[2026-10-30 10:09:22.591][5312] [RzInterHaptics.RpcClient] [info] '
           'Establishing connection to RzInterHaptics RPC with session "TestSession"')
LOST = ('[2026-10-30 00:48:35.035][20128] [RzInterHaptics.RpcClient] [warning] '
        'RpcClient::RpcPing failed, exception code: 1722 (RPC_S_SERVER_UNAVAILABLE)')
OFFLINE = "[2026/10/30 10:21:04.896] info: No internet connection found. App is running in offline mode."
EMPTY = "[2026/10/30 10:21:41.360] info: *** ~ Dashboard ~ devices shown in dashboard []"
LISTED = ('[2026/10/30 10:29:37.208] info: *** ~ Dashboard ~ devices shown in dashboard '
          '[{"productId":2636,"realProductId":2636,"deviceContainerId":"{61219129-17CC-11F1-8671-444648929145}"}]')
MORNING = datetime.datetime(2026, 10, 30, 10, 20, 40)


class GripDiagnosisTests(unittest.TestCase):
    def diagnose(self, haptic, dashboard, started):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "haptic.log").write_text("\n".join(haptic), encoding="utf-8")
            (root / "dashboard2.log").write_text("\n".join(dashboard), encoding="utf-8")
            with patch.object(synapse, "started_at", return_value=started):
                return synapse.diagnose(root / "haptic.log", root)

    def test_registration_follows_the_latest_device_event(self):
        self.assertTrue(synapse.device_registered([REMOVED, ADDED]))
        self.assertFalse(synapse.device_registered([ADDED, REMOVED]))

    def test_service_restart_or_lost_synapse_drops_the_registration(self):
        for reset in (RESTART, LOST):
            with self.subTest(reset=reset):
                self.assertFalse(synapse.device_registered([ADDED, reset]))
                self.assertTrue(synapse.device_registered([ADDED, reset, ADDED]))

    def test_log_without_any_evidence_is_unknown(self):
        self.assertIsNone(synapse.device_registered(["[2026-10-30 10:29:41.906][5312] [info] GetMetadata"]))

    def test_offline_mode_only_counts_since_synapse_started(self):
        self.assertTrue(synapse.offline_since([OFFLINE, EMPTY], MORNING))
        self.assertFalse(synapse.offline_since([OFFLINE, EMPTY], datetime.datetime(2026, 10, 30, 10, 29, 27)))

    def test_listing_devices_after_offline_means_synapse_recovered(self):
        self.assertFalse(synapse.offline_since([OFFLINE, LISTED], MORNING))
        self.assertTrue(synapse.offline_since([LISTED, OFFLINE], MORNING))

    def test_this_mornings_outage_is_reported_as_offline(self):
        self.assertEqual(self.diagnose([REMOVED, RESTART], [OFFLINE, EMPTY], MORNING), "offline")

    def test_online_synapse_that_has_not_seen_the_pad_is_unregistered(self):
        self.assertEqual(self.diagnose([REMOVED, RESTART], [EMPTY], MORNING), "unregistered")

    def test_registered_pad_is_ready_whatever_the_dashboard_said(self):
        self.assertEqual(self.diagnose([RESTART, ADDED], [OFFLINE], MORNING), "ready")

    def test_unregistered_pad_without_synapse_running_is_stopped(self):
        self.assertEqual(self.diagnose([REMOVED], [OFFLINE], None), "stopped")

    def test_missing_logs_leave_the_decision_to_the_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(synapse.diagnose(Path(directory) / "missing.log", directory), "unknown")
        self.assertEqual(self.diagnose(["unrelated"], [OFFLINE], MORNING), "unknown")

    def test_missing_dashboard_log_is_not_mistaken_for_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            haptic = Path(directory) / "haptic.log"
            haptic.write_text(REMOVED, encoding="utf-8")
            with patch.object(synapse, "started_at", return_value=MORNING):
                self.assertEqual(synapse.diagnose(haptic, Path(directory) / "none"), "unregistered")

    def test_synapse_start_time_is_its_earliest_process(self):
        processes = [Mock(info={"name": "RazerAppEngine.exe", "cmdline": ["--razer-page-name=win-chroma"],
                                "create_time": 50}),
                     Mock(info={"name": "RazerAppEngine.exe", "cmdline": ["--razer-page-name=win-synapse"],
                                "create_time": 200}),
                     Mock(info={"name": "RazerAppEngine.exe", "cmdline": ["--url-params=apps=synapse"],
                                "create_time": 100})]
        with patch.object(synapse.psutil, "process_iter", return_value=processes):
            self.assertEqual(synapse.started_at(), datetime.datetime.fromtimestamp(100))
        with patch.object(synapse.psutil, "process_iter", return_value=processes[:1]):
            self.assertIsNone(synapse.started_at())


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
