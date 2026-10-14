import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import settings
from app import core
from app.bridge import Bridge
from app.main import App
from app.window import draw_status_icon

QT = QApplication.instance() or QApplication([])


def wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QT.processEvents()
        time.sleep(.02)
    return condition()


class FakeBridge(QObject):
    status = Signal(dict)
    meter = Signal(dict)
    running = Signal(bool)
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.started = 0
        self.sent = []
        self.command = []
        self.pc = None
        self.is_running = False

    def set_pc(self, pc):
        self.pc = pc
        self.command = core.bridge_command(frozen=False, executable="python.exe", pc=pc)

    def start(self):
        self.started += 1
        self.is_running = True
        self.running.emit(True)

    def stop(self):
        self.is_running = False
        self.running.emit(False)

    def shutdown(self):
        self.stop()

    def send(self, message):
        self.sent.append(message)


class FakeSystem:
    def __init__(self, mode="bridge"):
        self.service = {"bridge": "WINUSB", "xbox": "dc1-controller", "pc": "usbccgp", "absent": None}[mode]
        self.instance = "USB\\VID_1532&PID_0A4C\\TEST" if mode == "pc" else "USB\\VID_1532&PID_0A3F\\TEST"
        self.autostart = False
        self.opened = []
        self.elevated = []
        self.elevated_code = 0

    def find_controller(self):
        return (self.instance, self.service) if self.service else (None, None)

    def run_elevated(self, script):
        self.elevated.append(script)
        return self.elevated_code

    def usbip_attached(self):
        return True

    def autostart_enabled(self):
        return self.autostart

    def set_autostart(self, enabled):
        self.autostart = enabled

    def open_folder(self, path):
        self.opened.append(path)


class AppTests(unittest.TestCase):
    def make_app(self, mode="bridge", saved=None):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "settings.json"
        if saved:
            settings.save(saved, path)
        bridge, system = FakeBridge(), FakeSystem(mode)
        app = App(bridge, system, settings_path=path, log_dir=directory)
        app.start(show=False)
        self.addCleanup(app.close)
        return app, bridge, system, path

    def test_slider_change_reaches_the_bridge_and_is_saved(self):
        app, bridge, _, path = self.make_app()
        app.window.vibration_page.grip_gain.slider.setValue(40)
        self.assertEqual(json.loads(bridge.sent[-1])["settings"]["grip_gain"], .4)
        app.flush_save()
        self.assertEqual(settings.load(path).grip_gain, .4)

    def test_xbox_mode_at_startup_does_not_start_the_bridge(self):
        app, bridge, _, _ = self.make_app(mode="xbox")
        self.assertEqual(bridge.started, 0)
        self.assertEqual(app.window.status_page.title.text(), "桥接已停止")

    def test_bridge_mode_at_startup_starts_the_bridge(self):
        _, bridge, _, _ = self.make_app(mode="bridge")
        self.assertEqual(bridge.started, 1)

    def test_disconnect_and_reconnect_notify_once_each(self):
        app, bridge, _, _ = self.make_app()
        notes = []
        app.notify = notes.append
        for state in ("waiting", "handshake", "connected", "lost", "waiting", "connected"):
            bridge.status.emit({"type": "status", "state": state})
        self.assertEqual(notes, ["connected", "lost", "reconnected"])
        self.assertEqual(app.window.status_page.title.text(), "已连接")

    def test_bridge_exit_while_connected_counts_as_lost_and_restarts(self):
        app, bridge, _, _ = self.make_app()
        notes = []
        app.notify = notes.append
        bridge.status.emit({"type": "status", "state": "connected"})
        bridge.stop()
        self.assertEqual(notes, ["connected", "lost"])
        self.assertTrue(wait_for(lambda: bridge.started == 2, timeout=5))

    def test_grip_and_trigger_tests_are_exclusive(self):
        app, bridge, _, _ = self.make_app()
        bridge.status.emit({"type": "status", "state": "connected"})
        page = app.window.vibration_page
        page.grip_test.button.click()
        page.trigger_test.button.click()
        page.trigger_test.button.click()
        self.assertEqual([json.loads(line)["target"] for line in bridge.sent], ["grip", "trigger", None])
        self.assertEqual(page.grip_test.button.text(), "开始测试")

    def test_test_needs_a_connection_and_ends_on_disconnect(self):
        app, bridge, _, _ = self.make_app()
        page = app.window.vibration_page
        self.assertFalse(page.grip_test.button.isEnabled())
        bridge.status.emit({"type": "status", "state": "connected"})
        page.grip_test.button.click()
        bridge.status.emit({"type": "status", "state": "lost"})
        self.assertEqual(json.loads(bridge.sent[-1]), {"type": "test", "target": None})
        self.assertFalse(page.grip_test.button.isEnabled())

    def test_meter_updates_the_motor_bars(self):
        app, bridge, _, _ = self.make_app()
        app.window.show()
        bridge.status.emit({"type": "status", "state": "connected"})
        bridge.meter.emit({"type": "meter", "motors": [.5, 0, 1, 0], "l2": 0, "r2": 255, "buttons": 0, "dpad": 0,
                           "sticks": [0, 0, 0, 0]})
        self.assertEqual(app.window.status_page.motors.values, [.5, 0, 1, 0])

    def test_window_shows_saved_settings(self):
        saved = settings.Settings(grip_enabled=False, trigger_gain=1.2, trigger_follow=True, follow_ratio=.3,
                                  audio_guard=False)
        app, _, _, _ = self.make_app(saved=saved)
        page = app.window.vibration_page
        self.assertFalse(page.grip_enabled.switch.isChecked())
        self.assertEqual(page.trigger_gain.slider.value(), 120)
        self.assertTrue(page.trigger_follow.switch.isChecked())
        self.assertEqual(page.follow_ratio.slider.value(), 30)
        self.assertFalse(app.window.device_page.audio_guard.switch.isChecked())

    def test_autostart_switch_is_read_back_from_the_system(self):
        app, _, system, _ = self.make_app()
        app.window.device_page.autostart.switch.setChecked(True)
        self.assertTrue(system.autostart)
        self.assertTrue(app.window.device_page.autostart.switch.isChecked())

    def test_tray_icon_differs_per_state(self):
        images = [draw_status_icon(state, 32).toImage() for state in ("connected", "waiting", "error", "stopped")]
        self.assertEqual(len({image.pixelColor(16, 12).name() for image in images}), 4)


class PcModeTests(unittest.TestCase):
    make_app = AppTests.make_app

    def test_pc_mode_starts_the_sensa_bridge(self):
        _, bridge, _, _ = self.make_app(mode="pc")
        self.assertEqual(bridge.started, 1)
        self.assertTrue(bridge.command[-1].endswith("pc_bridge.py"))

    def test_switching_controller_mode_restarts_the_matching_bridge(self):
        app, bridge, system, _ = self.make_app(mode="bridge")
        self.assertTrue(bridge.command[-1].endswith("gip_bridge.py"))
        system.service, system.instance = "usbccgp", "USB\\VID_1532&PID_0A4C\\TEST"
        app._probe()
        self.assertTrue(wait_for(lambda: bridge.started == 2, timeout=5))
        self.assertTrue(bridge.command[-1].endswith("pc_bridge.py"))

    def test_trigger_settings_are_unavailable_in_pc_mode(self):
        app, bridge, _, _ = self.make_app(mode="pc")
        bridge.status.emit({"type": "status", "state": "connected", "backend": "sensa"})
        page = app.window.vibration_page
        self.assertFalse(page.trigger_enabled.isEnabled())
        self.assertFalse(page.trigger_test.button.isEnabled())
        self.assertTrue(page.grip_test.button.isEnabled())
        self.assertIn("PC 模式", page.trigger_test.contentLabel.text())

    def test_driver_switch_is_not_offered_in_pc_mode(self):
        app, _, _, _ = self.make_app(mode="pc")
        self.assertTrue(app.window.device_page.driver_button.isHidden())
        self.assertIn("Sensa", app.window.device_page.driver.contentLabel.text())

    def test_hiding_the_physical_pad_runs_elevated_and_is_saved(self):
        app, _, system, path = self.make_app(mode="pc")
        app.window.device_page.hide_physical.switch.setChecked(True)
        self.assertTrue(wait_for(lambda: settings.load(path).hide_physical, timeout=5))
        self.assertIn("--dev-hide", system.elevated[-1])

    def test_declined_uac_reverts_the_hide_switch(self):
        app, _, system, path = self.make_app(mode="pc")
        system.elevated_code = None
        switch = app.window.device_page.hide_physical.switch
        switch.setChecked(True)
        self.assertTrue(wait_for(lambda: not switch.isChecked(), timeout=5))
        app.flush_save()
        self.assertFalse(settings.load(path).hide_physical)


class BridgeProcessTests(unittest.TestCase):
    def test_real_process_streams_status_takes_settings_and_quits_on_stdin_close(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        script = directory / "fake_bridge.py"
        script.write_text(
            "import json, sys\n"
            "print(json.dumps({'type': 'status', 'state': 'waiting'}), flush=True)\n"
            "print(json.dumps({'type': 'meter', 'motors': [0, 0, 0, 0]}), flush=True)\n"
            "for line in sys.stdin:\n"
            "    print('echo:' + line.strip(), flush=True)\n", encoding="utf-8")
        bridge = Bridge([sys.executable, "-u", str(script)], cwd=directory, log_dir=directory)
        statuses, meters, logs, running = [], [], [], []
        bridge.status.connect(statuses.append)
        bridge.meter.connect(meters.append)
        bridge.log.connect(logs.append)
        bridge.running.connect(running.append)
        bridge.start()
        self.assertTrue(wait_for(lambda: statuses))
        bridge.send('{"type": "settings", "settings": {}}')
        self.assertTrue(wait_for(lambda: any(text.startswith("echo:") for text in logs)))
        bridge.stop()
        self.assertTrue(wait_for(lambda: running and running[-1] is False))
        self.assertEqual(statuses[0]["state"], "waiting")
        self.assertEqual(len(meters), 1)
        log_text = "".join(path.read_text(encoding="utf-8") for path in directory.glob("bridge-*.log"))
        self.assertIn('"state": "waiting"', log_text)
        self.assertIn('echo:{"type": "settings"', log_text)
        self.assertNotIn('"meter"', log_text)


if __name__ == "__main__":
    unittest.main()
