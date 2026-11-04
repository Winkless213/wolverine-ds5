import dataclasses
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import settings
from app import __version__, core
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
    stats = Signal(dict)
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
        self.grips = "ready"
        self.grip_checks = 0

    def ensure_synapse(self):
        self.synapse_calls += 1
        return "running"

    def diagnose_synapse(self):
        self.grip_checks += 1
        return self.grips

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
    def make_app(self, mode="pc", saved=None, hide_physical=False):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "settings.json"
        if saved:
            settings.save(saved, path)
        else:
            # 多数用例只想验证桥接/状态逻辑：显式写死隐藏开关，别让默认值把流程改成“先隐藏再启动”。
            settings.save(dataclasses.replace(settings.Settings(), hide_physical=hide_physical), path)
        bridge, system = FakeBridge(), FakeSystem(mode)
        app = App(bridge, system, settings_path=path, log_dir=directory)
        app.start(show=False)
        self.addCleanup(app.close)
        return app, bridge, system, path

    def test_qml_window_loads_and_has_the_model(self):
        app, _, _, _ = self.make_app()
        self.assertIsNotNone(app.window.root)
        from app import __version__
        self.assertEqual(app.model.version, __version__)

    def test_default_font_keeps_the_chinese_fallback(self):
        # 内置 Roboto 没有汉字字形；回退链丢了中文就会落到宋体，界面又细又糊。
        self.make_app()
        from PySide6.QtGui import QGuiApplication
        families = QGuiApplication.font().families()
        self.assertEqual(families[0], "Roboto")
        self.assertIn("Microsoft YaHei UI", families)

    def test_qml_files_do_not_override_the_font_family(self):
        # QML 的 font 值类型没有 families 属性，任何 font.family 都会把回退链换成单一字体。
        for path in (core.root_dir() / "ui").glob("*.qml"):
            self.assertNotIn("font.family", path.read_text(encoding="utf-8"), path.name)

    def test_slider_change_reaches_the_bridge_and_is_saved(self):
        app, bridge, _, path = self.make_app()
        app.model.setGripGain(40)
        self.assertEqual(json.loads(bridge.sent[-1])["settings"]["grip_gain"], .4)
        app.flush_save()
        self.assertEqual(settings.load(path).grip_gain, .4)

    def test_one_grip_slider_drives_both_sides(self):
        # 界面只保留一个总强度；左右分路仍由桥接计算，两者必须同步。
        app, bridge, _, path = self.make_app()
        app.model.setGripGainLeft(100)
        app.model.setGripGainRight(100)
        app.model.setGripGain(40)
        sent = json.loads(bridge.sent[-1])["settings"]
        self.assertEqual((sent["grip_gain"], sent["grip_gain_left"], sent["grip_gain_right"]), (.4, .4, .4))
        app.flush_save()
        saved = settings.load(path)
        self.assertEqual((saved.grip_gain_left, saved.grip_gain_right), (.4, .4))

    def test_per_side_sliders_reach_the_bridge_and_are_saved(self):
        app, bridge, _, path = self.make_app()
        app.model.setGripGainLeft(40)
        app.model.setGripGainRight(120)
        sent = json.loads(bridge.sent[-1])["settings"]
        self.assertEqual((sent["grip_gain_left"], sent["grip_gain_right"]), (.4, 1.2))
        app.flush_save()
        saved = settings.load(path)
        self.assertEqual((saved.grip_gain_left, saved.grip_gain_right), (.4, 1.2))

    def test_xbox_mode_at_startup_does_not_start_the_bridge(self):
        app, bridge, _, _ = self.make_app(mode="xbox")
        self.assertEqual(bridge.started, 0)
        self.assertEqual(app.model.statusTitle, "请切换到 PC 模式")
        self.assertIn("PC 模式", app.model.statusDetail)
        self.assertIn("自动连接", app.model.statusDetail)

    def test_xbox_bridge_mode_at_startup_does_not_start_the_bridge(self):
        app, bridge, _, _ = self.make_app(mode="bridge")
        self.assertEqual(bridge.started, 0)
        self.assertEqual(app.model.statusTitle, "请切换到 PC 模式")
        self.assertIn("PC 模式", app.model.statusDetail)

    def test_mode_changes_are_written_to_the_startup_log(self):
        app, _, system, path = self.make_app(mode="xbox")
        system.service, system.instance = "usbccgp", "USB\\VID_1532&PID_0A4C\\TEST"
        app._probe()
        contents = (path.parent / "startup.log").read_text(encoding="utf-8")
        self.assertIn("Mode: xbox -> pc", contents)

    def test_xbox_mode_reminds_once_and_again_after_switching_back(self):
        app, bridge, system, _ = self.make_app(mode="xbox")
        notes = []
        app.notify, app.xbox_hinted = notes.append, False
        app._probe()
        app._probe()
        self.assertEqual(notes, ["xbox"])
        system.service, system.instance = "usbccgp", "USB\\VID_1532&PID_0A4C\\TEST"
        app._probe()
        self.assertTrue(wait_for(lambda: bridge.started == 1, timeout=5))
        system.service, system.instance = "dc1-controller", "USB\\VID_1532&PID_0A3F\\TEST"
        app._probe()
        self.assertEqual(notes, ["xbox", "xbox"])

    def test_disconnect_and_reconnect_notify_once_each(self):
        app, bridge, _, _ = self.make_app()
        notes = []
        app.notify = notes.append
        for state in ("waiting", "handshake", "connected", "lost", "waiting", "connected"):
            bridge.status.emit({"type": "status", "state": state})
        self.assertEqual(notes, ["connected", "lost", "reconnected"])
        self.assertEqual(app.model.statusTitle, "已连接")

    def test_bridge_exit_while_connected_counts_as_lost_and_restarts(self):
        app, bridge, _, _ = self.make_app()
        notes = []
        app.notify = notes.append
        bridge.status.emit({"type": "status", "state": "connected"})
        bridge.stop()
        self.assertEqual(notes, ["connected", "lost"])
        self.assertTrue(wait_for(lambda: bridge.started == 2, timeout=5))

    def test_grip_test_toggles(self):
        app, bridge, _, _ = self.make_app()
        bridge.status.emit({"type": "status", "state": "connected"})
        app.model.requestTest()
        app.model.requestTest()
        self.assertEqual([json.loads(line)["target"] for line in bridge.sent], ["grip", None])
        self.assertEqual(app.model.testing, "")

    def test_test_needs_a_connection_and_ends_on_disconnect(self):
        app, bridge, _, _ = self.make_app()
        self.assertFalse(app.model.testable)
        app.model.requestTest()
        self.assertEqual(bridge.sent, [])
        bridge.status.emit({"type": "status", "state": "connected"})
        app.model.requestTest()
        bridge.status.emit({"type": "status", "state": "lost"})
        self.assertEqual(json.loads(bridge.sent[-1]), {"type": "test", "target": None})
        self.assertFalse(app.model.testable)

    def test_meter_updates_the_motor_bars(self):
        app, bridge, _, _ = self.make_app()
        bridge.status.emit({"type": "status", "state": "connected"})
        bridge.meter.emit({"type": "meter", "motors": [.5, 0, 1, 0], "l2": 0, "r2": 255, "buttons": 0, "dpad": 0,
                           "sticks": [0, 0, 0, 0]})
        self.assertAlmostEqual(app.model.leftLevel, .5)
        self.assertAlmostEqual(app.model.rightLevel, 0)

    def test_window_shows_saved_settings(self):
        saved = settings.Settings(grip_enabled=False, trigger_gain=1.2, trigger_follow=True, follow_ratio=.3,
                                  audio_guard=False, reduce_motion=True)
        app, _, _, _ = self.make_app(saved=saved)
        self.assertFalse(app.model.gripEnabled)
        self.assertEqual(app.model.gripGainPercent, 100)
        self.assertFalse(app.model.audioGuard)
        self.assertTrue(app.model.reduceMotion)

    def test_autostart_switch_is_read_back_from_the_system(self):
        app, _, system, _ = self.make_app()
        app.model.setAutostart(True)
        self.assertTrue(system.autostart)
        self.assertTrue(app.model.autostart)

    def test_export_logs_writes_a_single_text_file(self):
        app, _, _, _ = self.make_app()
        target = pathlib.Path(tempfile.mkdtemp()) / "diagnostics.txt"
        with patch("PySide6.QtWidgets.QFileDialog.getSaveFileName",
                   return_value=(str(target), "文本日志 (*.txt)")):
            app.export_logs()
        self.assertTrue(target.exists())
        text = target.read_text(encoding="utf-8")
        self.assertIn("Wolverine DS5 diagnostics", text)
        self.assertIn(f"version: {__version__}", text)

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

    def test_synapse_is_started_once_and_never_retried_automatically(self):
        # 用户主动退出雷云时程序不追着重启；要拉起只能点「启动雷云」。
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": False})
        app._grips_checked("stopped")
        for _ in range(3):
            app._ensure_synapse()
        self.assertEqual(system.synapse_calls, 1)
        self.assertTrue(app.model.synapseStartable)
        app.model.requestSynapse()
        self.assertTrue(wait_for(lambda: system.synapse_calls == 2 and not app.synapse_checking, timeout=1))
        self.assertEqual(bridge.started, 1)

    def test_synapse_button_only_shows_once_synapse_is_reported_missing(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": False})
        app._grips_checked("ready")
        self.assertFalse(app.model.synapseStartable)
        app._grips_checked("stopped")
        self.assertTrue(app.model.synapseStartable)
        app._grips_checked("ready")
        self.assertFalse(app.model.synapseStartable)

    def test_synapse_exiting_mid_session_warns_once_without_restarting_it(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": False})
        app._grips_checked("ready")
        app.toast = Mock()
        app._grips_checked("stopped")
        app.toast.assert_called_once()
        self.assertIn("雷云", app.toast.call_args.args[1])
        self.assertIn("启动雷云", app.toast.call_args.args[2])
        self.assertEqual(system.synapse_calls, 1)

    def test_failed_synapse_start_warns_instead_of_claiming_success(self):
        app, bridge, _, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: not app.synapse_checking, timeout=1))
        app.toast = Mock()
        app._synapse_done("failed")
        self.assertTrue(bridge.is_running)
        self.assertIn("雷云", app.toast.call_args.args[1])
        self.assertIn("手动", app.toast.call_args.args[2])

    def test_missing_synapse_does_not_stop_input_and_warns_once(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        self.assertTrue(wait_for(lambda: system.synapse_calls == 1 and not app.synapse_checking, timeout=1))
        app.toast = Mock()
        app._synapse_done("missing")
        app._synapse_done("missing")
        self.assertTrue(bridge.is_running)
        app.toast.assert_called_once()
        self.assertIn("雷云", app.toast.call_args.args[1])

    def check_grips(self, app, system, checks):
        app.grips_next_check = 0
        app._probe()
        self.assertTrue(wait_for(lambda: system.grip_checks == checks and not app.grips_checking, timeout=1))

    def test_offline_synapse_overrides_the_bridges_ready_and_warns_once(self):
        # 2026-10-30 早上：雷云离线没加载手柄，桥接只因共享内存能打开就报了就绪。
        app, bridge, system, _ = self.make_app(mode="pc")
        app.toast = Mock()
        system.grips = "offline"
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": True})
        self.check_grips(app, system, 1)
        self.assertEqual(app.model.sensaState, "雷云离线")
        self.assertFalse(app.model.gripReady)
        self.assertIn("离线", app.state_title)
        self.check_grips(app, system, 2)
        app.toast.assert_called_once()
        self.assertIn("离线", app.toast.call_args.args[1])
        self.assertIn("网络", app.toast.call_args.args[2])
        self.assertIn("Grips: offline", (app.log_dir / "startup.log").read_text(encoding="utf-8"))
        system.grips = "ready"
        self.check_grips(app, system, 3)
        self.assertEqual(app.model.sensaState, "就绪")
        self.assertTrue(app.model.gripReady)
        self.assertEqual(app.state_title, "已连接")

    def test_pad_not_yet_registered_by_synapse_is_waiting_without_a_warning(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        app.toast = Mock()
        system.grips = "unregistered"
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": True})
        self.check_grips(app, system, 1)
        self.assertEqual(app.model.sensaState, "等待")
        self.assertEqual(app.state_title, "等待握把震动服务")
        app.toast.assert_not_called()

    def test_dead_synapse_shows_the_real_reason_without_a_warning(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        app.toast = Mock()
        system.grips = "stopped"
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": True})
        self.check_grips(app, system, 1)
        self.assertEqual(app.state_title, "雷云未运行，握把不可用")
        app.toast.assert_not_called()

    def test_unreadable_razer_logs_keep_the_bridges_own_verdict(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        system.grips = "unknown"
        bridge.status.emit({"state": "connected", "backend": "sensa", "grips_ready": True})
        self.check_grips(app, system, 1)
        self.assertEqual(app.model.sensaState, "就绪")

    def test_grips_are_not_diagnosed_before_the_sensa_bridge_connects(self):
        app, _, system, _ = self.make_app(mode="pc")
        app.grips_next_check = 0
        app._probe()
        self.assertEqual(system.grip_checks, 0)

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

    def test_switching_controller_to_pc_mode_starts_the_sensa_bridge(self):
        app, bridge, system, _ = self.make_app(mode="xbox")
        self.assertEqual(bridge.started, 0)
        system.service, system.instance = "usbccgp", "USB\\VID_1532&PID_0A4C\\TEST"
        app._probe()
        self.assertTrue(wait_for(lambda: bridge.started == 1, timeout=5))
        self.assertTrue(bridge.command[-1].endswith("pc_bridge.py"))
        self.assertEqual(app.model.modeLabel, "PC 模式")

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

    def test_hiding_the_physical_pad_is_applied_and_saved(self):
        app, _, system, path = self.make_app(mode="pc")
        app.model.setHidePhysical(True)
        self.assertTrue(wait_for(lambda: settings.load(path).hide_physical, timeout=5))
        self.assertEqual(system.hiding_calls[-1][0], True)
        self.assertTrue(app.model.hidePhysical)
        self.assertEqual(settings.load(path).hidden_devices, (system.instance,))

    def test_controller_on_a_port_unknown_at_hide_time_is_flagged(self):
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\OLD",)))
        self.assertIn("USB 口", app.model.hideWarning)

    def test_rehiding_clears_the_new_port_warning(self):
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\OLD",)))
        self.assertIn("USB 口", app.model.hideWarning)
        app._hide_done(0, True)
        self.assertNotIn("USB 口", app.model.hideWarning)
        app._probe()
        self.assertNotIn("USB 口", app.model.hideWarning)

    def test_hide_saved_by_an_older_version_registers_existing_ports(self):
        app, _, system, path = self.make_app(mode="pc", saved=settings.Settings(hide_physical=True))
        self.assertNotIn("USB 口", app.model.hideWarning)
        app.flush_save()
        self.assertEqual(settings.load(path).hidden_devices, (system.instance,))

    def test_known_port_is_not_flagged(self):
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\TEST",),
            hidden_app=core.bridge_command(pc=True)[0]))
        self.assertNotIn("USB 口", app.model.hideWarning)
        self.assertNotIn("放行", app.model.hideWarning)

    def test_hiding_records_the_whitelisted_bridge(self):
        app, _, _, path = self.make_app(mode="pc")
        app._hide_done(0, True)
        app.flush_save()
        self.assertEqual(settings.load(path).hidden_app, core.bridge_command(pc=True)[0])

    def test_bridge_not_whitelisted_by_hidhide_is_flagged(self):
        app, _, _, _ = self.make_app(mode="pc", saved=settings.Settings(
            hide_physical=True, hidden_devices=("USB\\VID_1532&PID_0A4C\\TEST",), hidden_app="C:/old/python.exe"))
        self.assertIn("放行", app.model.hideWarning)

    def test_failed_hiding_reverts_the_hide_switch(self):
        app, _, system, path = self.make_app(mode="pc")
        system.hiding_code = "HidHide unavailable"
        app.model.setHidePhysical(True)
        self.assertTrue(wait_for(lambda: not app.model.hidePhysical, timeout=5))
        app.flush_save()
        self.assertFalse(settings.load(path).hide_physical)

    def test_stopping_the_bridge_gives_the_physical_pad_back(self):
        # 虚拟 DS5 卸载后手柄还藏着，游戏里就一只都看不到；停止桥接要把实体手柄让回去。
        app, bridge, system, path = self.make_app(mode="pc", saved=settings.Settings(hide_physical=True))
        self.assertTrue(wait_for(lambda: app.hiding_active, timeout=5))
        app.model.toggleBridge()
        self.assertTrue(wait_for(lambda: system.hiding_calls[-1][0] is False, timeout=5))
        self.assertFalse(bridge.is_running)
        app.flush_save()
        self.assertTrue(settings.load(path).hide_physical)  # 偏好保留，下次桥接仍然隐藏

    def test_restarting_the_bridge_hides_the_pad_again(self):
        app, bridge, system, _ = self.make_app(mode="pc", saved=settings.Settings(hide_physical=True))
        self.assertTrue(wait_for(lambda: app.hiding_active, timeout=5))
        app.model.toggleBridge()
        self.assertTrue(wait_for(lambda: system.hiding_calls[-1][0] is False, timeout=5))
        app.model.toggleBridge()
        self.assertTrue(wait_for(lambda: system.hiding_calls[-1][0] is True, timeout=5))
        self.assertTrue(wait_for(lambda: bridge.started == 2, timeout=5))

    def test_stopping_without_the_hide_preference_leaves_hidhide_alone(self):
        app, bridge, system, _ = self.make_app(mode="pc")
        before = len(system.hiding_calls)
        app.model.toggleBridge()
        self.assertTrue(wait_for(lambda: not bridge.is_running, timeout=5))
        self.assertEqual(len(system.hiding_calls), before)


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


class QuitProtocolTests(unittest.TestCase):
    """安装器、卸载器靠这条协议请旧实例自己退出；没在运行必须当成已经退出。

    真正的收发由安装包实测覆盖（两个 QLocalSocket 在没有事件循环的测试线程里不可靠）。
    """

    def test_no_running_instance_counts_as_quit(self):
        from app.main import request_quit

        self.assertEqual(request_quit(f"WolverineDS5-absent-{os.getpid()}", timeout_ms=300), 0)


if __name__ == "__main__":
    unittest.main()
