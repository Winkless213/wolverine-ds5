import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core import (AUTOSTART_NAME, BridgeEvents, autostart_command, bridge_command, parse_line,
                      prune_logs, restore_xbox_script)


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

    def test_frozen_bridge_reuses_the_app_executable(self):
        self.assertEqual(bridge_command(frozen=True, executable="C:/WolverineDS5.exe", root=None),
                         ["C:/WolverineDS5.exe", "--bridge"])

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
