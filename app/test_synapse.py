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
    def setUp(self):
        # 默认没有计划任务：快捷方式那批用例说的就是回退路径。
        patcher = patch.object(synapse, "trigger_task", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 默认不建任务：建任务要 UAC，测试里不能真弹。
        register = patch.object(synapse, "register_task", return_value=False)
        register.start()
        self.addCleanup(register.stop)

    def test_running_synapse_is_not_launched_again(self):
        with patch.object(synapse, "is_running", return_value=True), \
                patch.object(synapse, "find_shortcut") as find, patch.object(synapse.os, "startfile") as launch:
            self.assertEqual(synapse.ensure_running(), "running")
        find.assert_not_called()
        launch.assert_not_called()

    def ensure(self, alive_after, dies_after=None, shortcut=Path("C:/Start Menu/Razer/Razer Synapse.lnk")):
        """alive_after=None 表示一直不活；dies_after 表示活到这里又退出。时钟和等待都是假的，不真的睡。"""
        state = {"t": 0.0, "launched": False}

        def wait(seconds):
            state["t"] += seconds

        def clock():
            return state["t"]

        def probe():
            if not state["launched"] or alive_after is None:
                return False
            return alive_after <= state["t"] < (dies_after if dies_after is not None else float("inf"))

        def launch(path, show_cmd=0):
            state["launched"] = True

        with patch.object(synapse, "find_shortcut", return_value=shortcut), \
                patch.object(synapse.os, "startfile", side_effect=launch) as started:
            result = synapse.ensure_running(wait=wait, clock=clock, probe=probe)
        return result, started

    def test_installed_synapse_starts_through_its_shortcut(self):
        result, launch = self.ensure(alive_after=0)
        self.assertEqual(result, "started")
        launch.assert_called_once_with(str(Path("C:/Start Menu/Razer/Razer Synapse.lnk")), show_cmd=0)

    def test_engine_that_never_comes_up_is_reported_as_failed(self):
        self.assertEqual(self.ensure(alive_after=None)[0], "failed")

    def test_engine_that_dies_again_is_not_reported_as_started(self):
        # 实测：拉起来 6 秒后自己退出；只看到它出现就报 started，界面会前后矛盾。
        self.assertEqual(self.ensure(alive_after=0, dies_after=1.0)[0], "failed")

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


class TriggerTaskTests(unittest.TestCase):
    def test_registered_task_is_triggered_by_name(self):
        run = Mock(return_value=Mock(returncode=0))
        self.assertTrue(synapse.trigger_task(run=run))
        run.assert_called_once_with(["schtasks.exe", "/run", "/tn", synapse.TASK_NAME],
                                    stdout=synapse.subprocess.DEVNULL, stderr=synapse.subprocess.DEVNULL,
                                    timeout=synapse.TASK_TIMEOUT, creationflags=synapse.CREATE_NO_WINDOW)

    def test_task_that_is_not_registered_is_not_triggered(self):
        self.assertFalse(synapse.trigger_task(run=Mock(return_value=Mock(returncode=1))))

    def test_scheduler_that_cannot_be_called_is_not_triggered(self):
        self.assertFalse(synapse.trigger_task(run=Mock(side_effect=OSError("no scheduler"))))
        self.assertFalse(synapse.trigger_task(run=Mock(side_effect=TimeoutError)))

    def test_slow_scheduler_is_treated_as_submitted(self):
        # 任务拉起的雷云继承句柄时 schtasks 可能一直不退出；这时不能报“没触发”。
        self.assertTrue(synapse.trigger_task(run=Mock(side_effect=synapse.subprocess.TimeoutExpired("schtasks", 15))))

    def test_task_start_needs_no_shortcut(self):
        state = {"t": 0.0}

        def wait(seconds):
            state["t"] += seconds

        def clock():
            return state["t"]

        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=Path("Razer Synapse.lnk")), \
                patch.object(synapse.os, "startfile") as launch:
            result = synapse.ensure_running(wait=wait, clock=clock, probe=lambda: state["t"] >= 0.5,
                                            trigger=lambda: True)
        self.assertEqual(result, "started")
        launch.assert_not_called()

    def test_task_that_cannot_wake_synapse_falls_back_to_the_shortcut(self):
        state = {"t": 0.0, "launched": False}

        def wait(seconds):
            state["t"] += seconds

        def clock():
            return state["t"]

        def probe():
            # 任务那次没拉起来；只有快捷方式拉起的引擎站得住。
            return state["launched"]

        def launch(path, show_cmd=0):
            state["launched"] = True

        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=Path("Razer Synapse.lnk")), \
                patch.object(synapse.os, "startfile", side_effect=launch) as started:
            result = synapse.ensure_running(wait=wait, clock=clock, probe=probe, trigger=lambda: True)
        self.assertEqual(result, "started")
        started.assert_called_once()


class TaskCleanupTests(unittest.TestCase):
    def test_delete_removes_the_registered_task(self):
        run = Mock(return_value=Mock(returncode=0))
        with patch.object(synapse, "task_registered", return_value=False):
            self.assertTrue(synapse.delete_task(run=run))
        run.assert_called_once_with(["schtasks.exe", "/delete", "/tn", synapse.TASK_NAME, "/f"],
                                    stdout=synapse.subprocess.DEVNULL, stderr=synapse.subprocess.DEVNULL,
                                    timeout=synapse.TASK_TIMEOUT, creationflags=synapse.CREATE_NO_WINDOW)

    def test_delete_reports_failure_when_the_task_is_still_there(self):
        with patch.object(synapse, "task_registered", return_value=True):
            self.assertFalse(synapse.delete_task(run=Mock(return_value=Mock(returncode=1))))

    def test_task_that_never_existed_counts_as_deleted(self):
        with patch.object(synapse, "task_registered", return_value=False):
            self.assertTrue(synapse.delete_task(run=Mock(return_value=Mock(returncode=1))))


class RegisterTaskTests(unittest.TestCase):
    def test_registration_creates_a_highest_privilege_logon_task(self):
        seen = {}

        def elevate(executable, arguments):
            seen["exe"], seen["args"] = executable, arguments
            return True

        state = {"queries": 0}

        def task_query(run=None):
            state["queries"] += 1
            return state["queries"] > 1

        with patch.object(synapse, "launcher_path", return_value=Path(r"C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe")), \
                patch.object(synapse, "task_registered", side_effect=task_query):
            self.assertTrue(synapse.register_task(elevate=elevate, wait=lambda seconds: None))
        self.assertEqual(seen["exe"], "schtasks.exe")
        for part in ("/create", synapse.TASK_NAME, "/sc onlogon", "/rl HIGHEST",
                     r"C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe", "--url-params=apps=synapse"):
            self.assertIn(part, seen["args"])

    def test_cancelled_consent_is_reported_as_failure(self):
        with patch.object(synapse, "launcher_path", return_value=Path("RazerAppEngine.exe")), \
                patch.object(synapse, "task_registered", return_value=False):
            self.assertFalse(synapse.register_task(elevate=lambda exe, args: False, wait=lambda seconds: None))

    def test_missing_synapse_install_never_asks_for_consent(self):
        elevate = Mock()
        with patch.object(synapse, "task_registered", return_value=False), \
                patch.object(synapse, "launcher_path", return_value=None):
            self.assertFalse(synapse.register_task(elevate=elevate))
        elevate.assert_not_called()

    def test_wake_creates_the_task_when_the_shortcut_cannot_start_synapse(self):
        state = {"t": 0.0, "triggers": 0}

        def wait(seconds):
            state["t"] += seconds

        def clock():
            return state["t"]

        def trigger():
            state["triggers"] += 1
            return state["triggers"] >= 2  # 任务建好后的第二次触发才真的拉起引擎

        def probe():
            return state["triggers"] >= 2

        register = Mock(return_value=True)
        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=Path("Razer Synapse.lnk")), \
                patch.object(synapse.os, "startfile"):
            result = synapse.ensure_running(wait=wait, clock=clock, probe=probe,
                                            trigger=trigger, register=register)
        self.assertEqual(result, "started")
        register.assert_called_once()

    def test_shortcut_that_works_never_asks_for_admin(self):
        state = {"t": 0.0, "launched": False}

        def wait(seconds):
            state["t"] += seconds

        def clock():
            return state["t"]

        def probe():
            return state["launched"]

        def launch(path, show_cmd=0):
            state["launched"] = True

        register = Mock(return_value=True)
        with patch.object(synapse, "is_running", return_value=False), \
                patch.object(synapse, "find_shortcut", return_value=Path("Razer Synapse.lnk")), \
                patch.object(synapse.os, "startfile", side_effect=launch):
            result = synapse.ensure_running(wait=wait, clock=clock, probe=probe,
                                            trigger=lambda: False, register=register)
        self.assertEqual(result, "started")
        register.assert_not_called()
