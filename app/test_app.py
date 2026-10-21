import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

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
        self.hiding_calls = []
        self.hiding_code = 0
        self.synapse_calls = 0

    def ensure_synapse(self):
        self.synapse_calls += 1
        return "running"

    def find_controller(self):
        return (self.instance, self.service) if self.service else (None, None)

    def pc_instances(self):
        return [self.instance] if self.service else []

    def run_elevated(self, script):
        self.elevated.append(script)
        return self.elevated_code

    def configure_hiding(self, hidden, previous_app):
        self.hiding_calls.append((hidden, previous_app))
        return self.hiding_code

    def usbip_attached(self):
        return True

    def autostart_enabled(self):
        return self.autostart

    def set_autostart(self, enabled):
        self.autostart = enabled

    def open_folder(self, path):
        self.opened.append(path)

    def detach_virtual(self):
        pass


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

    def test_soft_grip_switch_reaches_the_bridge_and_is_saved(self):
        app, bridge, _, path = self.make_app()
        app.window.vibration_page.grip_soft.switch.setChecked(True)
        self.assertTrue(json.loads(bridge.sent[-1])["settings"]["grip_soft"])
        app.flush_save()
        self.assertTrue(settings.load(path).grip_soft)

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

    def test_pc_start_checks_synapse_without_blocking_the_bridge(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1, timeout=1))
        self.assertTrue(bridge.is_running)
        self.assertTrue(wait_for(lambda: not app.synapse_checking, timeout=1))

    def test_synapse_check_writes_start_and_result_to_startup_log(self):
        app, _, system, path = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        log = path.parent / "startup.log"
        self.assertTrue(log.exists())
        contents = log.read_text(encoding="utf-8")
        self.assertIn("Synapse check started", contents)
        self.assertIn("Synapse check worker finished: running", contents)
        self.assertIn("Synapse check finished: running", contents)
        self.assertIn("Synapse: running", contents)

    def test_xbox_bridge_does_not_start_synapse(self):
        _, _, system, _ = self.make_app(mode="bridge")
        self.assertEqual(system.synapse_calls, 0)

    def test_sensa_retry_is_throttled_and_does_not_restart_the_virtual_controller(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": False})
        for _ in range(3):
            app._probe()
        self.assertEqual(system.synapse_calls, 1)
        app.synapse_next_check = 0
        app._probe()
        self.assertTrue(wait_for(lambda: system.synapse_calls == 2 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": True})
        app.synapse_next_check = 0
        app._probe()
        self.assertEqual(system.synapse_calls, 2)
        self.assertEqual(bridge.started, 1)

    def test_missing_synapse_does_not_stop_input_and_warns_once(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        app.toast = Mock()
        app._synapse_done("missing")
        app._synapse_done("missing")
        self.assertTrue(bridge.is_running)
        app.toast.assert_called_once()
        self.assertIn("雷云", app.toast.call_args.args[1])

    def test_paused_or_exiting_app_does_not_relaunch_synapse(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": False})
        app.synapse_next_check = 0
        app.paused = True
        app._probe()
        app.paused, app.exiting = False, True
        app._probe()
        self.assertEqual(system.synapse_calls, 1)

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

    def test_pc_cable_receiver_switch_keeps_the_virtual_controller_process(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        for instance in (None, "USB\\VID_1532&PID_0A4C\\RECEIVER",
                         "USB\\VID_1532&PID_0A4C\\CABLE", None,
                         "USB\\VID_1532&PID_0A4C\\RECEIVER"):
            system.instance = instance
            system.service = "usbccgp" if instance else None
            app._probe()
            self.assertTrue(bridge.is_running)
            self.assertEqual(bridge.started, 1)
            self.assertTrue(bridge.pc)

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

    def test_hiding_the_physical_pad_is_applied_and_saved(self):
        app, _, system, path = self.make_app(mode="pc")
        app.window.device_page.hide_physical.switch.setChecked(True)
        self.assertTrue(wait_for(lambda: settings.load(path).hide_physical, timeout=5))
        self.assertEqual(system.hiding_calls[-1][0], True)
        self.assertEqual(system.elevated, [])
        self.assertEqual(settings.load(path).hidden_devices, (system.instance,))

    def test_controller_on_a_port_unknown_at_hide_time_is_flagged(self):
        # HidHide 只隐藏开启时已存在的端口实例；换到新 USB 口后游戏又能看到实体手柄。
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\OLD",)))
        self.assertIn("USB 口", app.window.device_page.hide_physical.contentLabel.text())

    def test_rehiding_clears_the_new_port_warning(self):
        app, _, system, path = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\OLD",)))
        card = app.window.device_page.hide_physical
        self.assertIn("USB 口", card.contentLabel.text())
        app._hide_done(0, True)
        self.assertNotIn("USB 口", card.contentLabel.text())
        app._probe()
        self.assertNotIn("USB 口", card.contentLabel.text())

    def test_hide_saved_by_an_older_version_registers_existing_ports(self):
        app, _, system, path = self.make_app(mode="pc", saved=settings.Settings(hide_physical=True))
        self.assertNotIn("USB 口", app.window.device_page.hide_physical.contentLabel.text())
        app.flush_save()
        self.assertEqual(settings.load(path).hidden_devices, (system.instance,))

    def test_known_port_is_not_flagged(self):
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\TEST",),
            hidden_app=core.bridge_command(pc=True)[0]))
        self.assertNotIn("USB 口", app.window.device_page.hide_physical.contentLabel.text())
        self.assertNotIn("放行", app.window.device_page.hide_physical.contentLabel.text())

    def test_hiding_records_the_whitelisted_bridge(self):
        app, _, _, path = self.make_app(mode="pc")
        app._hide_done(0, True)
        app.flush_save()
        self.assertEqual(settings.load(path).hidden_app, core.bridge_command(pc=True)[0])

    def test_bridge_not_whitelisted_by_hidhide_is_flagged(self):
        # 换成打包版或挪了目录后，新桥接不在 HidHide 放行名单里，自己也读不到手柄。
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\TEST",), hidden_app="C:/old/python.exe"))
        self.assertIn("放行", app.window.device_page.hide_physical.contentLabel.text())

    def test_failed_hiding_reverts_the_hide_switch(self):
        app, _, system, path = self.make_app(mode="pc")
        system.hiding_code = "HidHide unavailable"
        switch = app.window.device_page.hide_physical.switch
        switch.setChecked(True)
        self.assertTrue(wait_for(lambda: not switch.isChecked(), timeout=5))
        app.flush_save()
        self.assertFalse(settings.load(path).hide_physical)


class NativeExitTests(unittest.TestCase):
    make_app = AppTests.make_app

    def test_exit_detaches_virtual_device_before_stopping_its_server(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        calls = []
        system.detach_virtual = lambda: calls.append(("detach", bridge.is_running))
        system.restore_native = lambda saved: calls.append(("restore", bridge.is_running))
        with patch("app.main.QApplication.quit") as quit_app:
            app.quit()
            self.assertTrue(wait_for(lambda: quit_app.called))
        self.assertEqual(calls, [("detach", True), ("restore", False)])

    def test_tray_exit_restores_native_access_after_stopping_the_bridge(self):
        app, bridge, system, path = self.make_app(mode="pc")
        app.update_settings({"hide_physical": True, "hidden_devices": (system.instance,),
                             "hidden_app": "C:/bridge.exe", "grip_gain": 1.1})
        calls = []
        system.restore_native = lambda saved_app: calls.append((bridge.is_running, saved_app))
        with patch("app.main.QApplication.quit") as quit_app:
            app.quit()
            self.assertTrue(wait_for(lambda: quit_app.called))
        self.assertEqual(calls, [(False, "C:/bridge.exe")])
        saved = settings.load(path)
        self.assertTrue(saved.hide_physical)
        self.assertEqual(saved.grip_gain, 1.1)
        self.assertEqual(saved.hidden_devices, ())
        self.assertEqual(saved.hidden_app, "")

    def test_failed_restore_keeps_the_app_available_for_retry(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        system.restore_native = Mock(side_effect=RuntimeError("HidHide unavailable"))
        app.toast = Mock()
        with patch("app.main.QApplication.quit") as quit_app:
            app.quit()
            self.assertTrue(wait_for(lambda: app.toast.called))
            quit_app.assert_not_called()
        self.assertFalse(app.closing)
        self.assertFalse(bridge.is_running)
        self.assertFalse(app.wanted)
        self.assertIn("HidHide unavailable", app.toast.call_args.args[2])
        self.assertIn("HidHide unavailable", (app.log_dir / "native-exit.log").read_text(encoding="utf-8"))

    def test_exit_waits_for_inflight_hide_before_restoring(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        system.restore_native = Mock()
        app.hiding = True
        with patch("app.main.QApplication.quit") as quit_app:
            app.quit()
            system.restore_native.assert_not_called()
            app._hide_done(0, True)
            self.assertTrue(wait_for(lambda: quit_app.called))
        system.restore_native.assert_called_once()
        self.assertFalse(bridge.is_running)

    def test_relaunch_reapplies_saved_hiding_before_starting_the_bridge(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "settings.json"
        settings.save(settings.Settings(hide_physical=True), path)
        bridge, system = FakeBridge(), FakeSystem("pc")
        observed = []
        system.configure_hiding = lambda hidden, previous: observed.append((hidden, bridge.started)) or 0
        app = App(bridge, system, path, directory)
        self.addCleanup(app.close)
        app.start(show=False)
        self.assertTrue(wait_for(lambda: observed and bridge.started == 1))
        self.assertEqual(observed, [(True, 0)])

    def test_failed_startup_hiding_does_not_expose_a_duplicate_virtual_controller(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "settings.json"
        settings.save(settings.Settings(hide_physical=True), path)
        bridge, system = FakeBridge(), FakeSystem("pc")
        system.hiding_code = "driver unavailable"
        app = App(bridge, system, path, directory)
        self.addCleanup(app.close)
        app.toast = Mock()
        app.start(show=False)
        self.assertTrue(wait_for(lambda: app.toast.called))
        app._probe()
        app._restart()
        self.assertEqual(bridge.started, 0)

    def test_repeated_exit_clicks_do_not_run_cleanup_twice(self):
        app, _, system, _ = self.make_app(mode="pc")
        system.restore_native = Mock()
        with patch("app.main.QApplication.quit") as quit_app:
            app.quit()
            app.quit()
            self.assertTrue(wait_for(lambda: quit_app.called))
        system.restore_native.assert_called_once()


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
