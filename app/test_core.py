import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core import (AUTOSTART_NAME, BridgeEvents, autostart_command, bridge_command, describe, driver_mode,
                      format_duration, hidhide_script, parse_line, prune_logs, restore_xbox_script, usbip_attached)


class DisplayTests(unittest.TestCase):
    def test_virtual_ds5_is_attached_only_when_our_busid_is_imported(self):
        output = "Port 01: <device in use> at Super Speed(5000Mbps)\n       -> usbip://127.0.0.1:3240/1-1\n"
        self.assertTrue(usbip_attached(output))
        self.assertFalse(usbip_attached(output.replace("1-1", "1-2")))
        self.assertFalse(usbip_attached(""))

    def test_driver_service_maps_to_mode(self):
        self.assertEqual(driver_mode("WinUSB"), "bridge")
        self.assertEqual(driver_mode("dc1-controller"), "xbox")
        self.assertEqual(driver_mode(None), "absent")

    def test_pc_mode_is_recognised_by_its_product_id(self):
        self.assertEqual(driver_mode("usbccgp", "USB\\VID_1532&PID_0A4C\\7&31912F88&0&4"), "pc")
        self.assertEqual(driver_mode("WinUSB", "USB\\VID_1532&PID_0A3F\\0000A1B2C3D4E5F6"), "bridge")

    def test_duration_is_compact(self):
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3725), "1:02:05")


class DescribeTests(unittest.TestCase):
    def test_connected_shows_handshake_time(self):
        self.assertEqual(describe(True, True, {"state": "connected", "handshake_s": 1.78}, "bridge"),
                         ("connected", "已连接", "握手 1.78 秒"))

    def test_xbox_mode_is_a_deliberate_stop_not_an_error(self):
        key, title, detail = describe(False, False, {}, "xbox")
        self.assertEqual((key, title), ("stopped", "桥接已停止"))
        self.assertIn("Xbox 模式", detail)

    def test_bridge_dying_unexpectedly_is_an_error(self):
        self.assertEqual(describe(False, True, {"state": "connected"}, "bridge")[0], "error")

    def test_repeated_handshake_timeouts_suggest_replugging(self):
        # reconnect_loop 把 TimeoutError（OSError 子类）再报成 lost，提示要按错误内容判断。
        status = {"state": "lost", "error": "TimeoutError('GIP handshake timeout; replug the controller')"}
        key, title, detail = describe(True, True, status, "bridge")
        self.assertEqual((key, title), ("waiting", "等待手柄"))
        self.assertIn("拔插", detail)

    def test_lost_controller_reassures_game_keeps_running(self):
        self.assertIn("无需重启", describe(True, True, {"state": "lost"}, "bridge")[2])

    def test_before_the_first_device_probe_it_is_still_detecting(self):
        self.assertEqual(describe(False, False, {}, None)[:2], ("waiting", "正在检测手柄"))

    def test_pc_mode_connection_names_sensa_and_missing_triggers(self):
        key, title, detail = describe(True, True, {"state": "connected", "backend": "sensa"}, "pc")
        self.assertEqual((key, title), ("connected", "已连接"))
        self.assertIn("Sensa", detail)

    def test_pc_mode_without_synapse_asks_for_it(self):
        key, title, detail = describe(True, True, {"state": "waiting", "reason": "sensa"}, "pc")
        self.assertEqual(key, "waiting")
        self.assertIn("Synapse", detail)


class ParseLineTests(unittest.TestCase):
    def test_status_and_meter_lines_are_structured(self):
        self.assertEqual(parse_line('{"type": "status", "state": "connected"}'),
                         {"type": "status", "state": "connected"})
        self.assertEqual(parse_line('{"type": "meter", "motors": [0, 0, 0, 0]}')["type"], "meter")

    def test_other_output_is_plain_log(self):
        self.assertEqual(parse_line("GIP handshake complete in 2.38s\n"),
                         {"type": "log", "text": "GIP handshake complete in 2.38s"})
        self.assertEqual(parse_line('{"elapsed_s": 5.0}')["type"], "log")


class BridgeEventsTests(unittest.TestCase):
    def test_disconnect_and_reconnect_produce_one_notification_each(self):
        notify = Mock()
        events = BridgeEvents(notify)
        for state in ("waiting", "handshake", "connected", "lost", "waiting", "handshake", "connected"):
            events.status(state)
        self.assertEqual([call.args[0] for call in notify.call_args_list], ["connected", "lost", "reconnected"])

    def test_handshake_timeouts_while_waiting_do_not_spam(self):
        notify = Mock()
        events = BridgeEvents(notify)
        for _ in range(5):
            events.status("handshake")
            events.status("waiting")
        notify.assert_not_called()


class CommandTests(unittest.TestCase):
    def test_bridge_runs_from_source_with_unbuffered_python(self):
        command = bridge_command(frozen=False, executable="python.exe", root=pathlib.Path("C:/app"))
        self.assertEqual(command, ["python.exe", "-u", str(pathlib.Path("C:/app/gip_bridge.py"))])

    def test_frozen_bridge_is_the_console_exe_beside_the_app(self):
        # 托盘程序无控制台；桥接用同目录的控制台版 exe，子进程（capture、usbip）才会继承隐藏的控制台。
        self.assertEqual(bridge_command(frozen=True, executable="C:/W/WolverineDS5.exe", root=None),
                         [str(pathlib.Path("C:/W/WolverineDS5-bridge.exe"))])

    def test_bridge_uses_console_python_even_when_the_app_runs_windowless(self):
        command = bridge_command(frozen=False, executable="C:/Python314/pythonw.exe", root=pathlib.Path("C:/app"))
        self.assertEqual(command[0], "C:/Python314/python.exe")

    def test_pc_mode_runs_the_sensa_bridge(self):
        command = bridge_command(frozen=False, executable="python.exe", root=pathlib.Path("C:/app"), pc=True)
        self.assertEqual(command[-1], str(pathlib.Path("C:/app/pc_bridge.py")))
        self.assertEqual(bridge_command(frozen=True, executable="C:/W.exe", pc=True),
                         [str(pathlib.Path("C:/WolverineDS5-bridge.exe")), "--pc"])

    def test_hiding_whitelists_the_bridge_and_hides_only_the_pc_mode_gamepad(self):
        script = hidhide_script("C:/Python314/python.exe", hide=True)
        self.assertIn("--app-reg", script)
        self.assertIn("C:/Python314/python.exe", script)
        self.assertIn("USB\\VID_1532&PID_0A4C&MI_00\\*", script)
        self.assertIn("HID\\VID_1532&PID_0A4C&IG_*", script)
        self.assertIn("--dev-hide", script)
        self.assertIn("--cloak-on", script)

    def test_unhiding_restores_the_gamepad_without_touching_other_hidhide_users(self):
        script = hidhide_script("C:/Python314/python.exe", hide=False)
        self.assertIn("--dev-unhide", script)
        self.assertNotIn("--cloak", script)
        self.assertNotIn("--app-unreg", script)

    def test_autostart_launches_minimised_to_tray(self):
        self.assertTrue(autostart_command(["C:/WolverineDS5.exe"]).endswith('"C:/WolverineDS5.exe" --tray'))
        self.assertEqual(AUTOSTART_NAME, "WolverineDS5")

    def test_restore_script_removes_only_the_razer_device_and_rescans(self):
        script = restore_xbox_script("USB\\VID_1532&PID_0A3F\\0000A1B2C3D4E5F6")
        self.assertIn('pnputil /remove-device "USB\\VID_1532&PID_0A3F\\0000A1B2C3D4E5F6"', script)
        self.assertIn("pnputil /scan-devices", script)


class LogTests(unittest.TestCase):
    def test_only_recent_daily_logs_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            for day in range(1, 11):
                (root / f"bridge-2026-10-{day:02d}.log").write_text("x")
            (root / "settings.json").write_text("{}")
            prune_logs(root, keep=7)
            names = sorted(path.name for path in root.iterdir())
            self.assertEqual(names[0], "bridge-2026-10-04.log")
            self.assertEqual(len(names), 8)


if __name__ == "__main__":
    unittest.main()
