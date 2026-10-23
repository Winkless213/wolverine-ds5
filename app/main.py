"""托盘程序入口：托管桥接子进程，把状态、设置和驱动切换接到窗口与托盘上。"""
import ctypes
import dataclasses
import getpass
import json
import os
import pathlib
import sys
import threading
import time
import traceback

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from qfluentwidgets import (Action, FluentIcon, InfoBar, InfoBarPosition, MessageBox, SystemTrayMenu, Theme,
                            setTheme, setThemeColor)

import settings
from app import core, native, synapse
from app.bridge import Bridge
from app.window import MODE_TEXT, Window, status_icon

NOTICES = {"connected": ("手柄已连接", "虚拟 DualSense 已就绪"),
           "lost": ("手柄已断开", "重新插上即可恢复，游戏无需重启"),
           "reconnected": ("手柄已重新连接", "震动与按键已恢复"),
           "new_port": ("手柄换了 USB 口", "游戏可能又能看到实体手柄；请在“设备与系统”页把“对游戏隐藏实体手柄”关闭再打开")}


class System:
    """真实的系统操作；测试里换成假对象。"""
    find_controller = staticmethod(core.find_controller)
    pc_instances = staticmethod(core.pc_instances)
    autostart_enabled = staticmethod(core.autostart_enabled)
    set_autostart = staticmethod(core.set_autostart)
    run_elevated = staticmethod(core.run_elevated)
    detach_virtual = staticmethod(native.detach_virtual)
    restore_native = staticmethod(native.restore_native)
    ensure_synapse = staticmethod(synapse.ensure_running)

    @staticmethod
    def configure_hiding(hidden, previous_app):
        return native.configure_hiding(hidden, core.bridge_command(pc=True)[0], previous_app)

    @staticmethod
    def usbip_attached():
        return core.usbip_attached(core.usbip_ports())

    @staticmethod
    def open_folder(path):
        os.startfile(path)


class App(QObject):
    usbip_checked = Signal(bool)
    driver_done = Signal(object, str, str)
    hide_done = Signal(object, bool)
    virtual_detached = Signal(object)
    native_done = Signal(object)
    synapse_done = Signal(str)

    def __init__(self, bridge, system, settings_path, log_dir):
        super().__init__()
        setTheme(Theme.AUTO)
        setThemeColor("#16A34A")
        self.bridge, self.system = bridge, system
        self.settings_path, self.log_dir = settings_path, log_dir
        self.settings = settings.load(settings_path)
        self.events = core.BridgeEvents(lambda event: self.notify(event))
        self.status, self.mode, self.instance = {}, None, None
        self.wanted = self.paused = self.busy = self.closing = self.checking = self.hinted = False
        self.pending_driver = None
        self.hiding = self.hide_failed = self.exiting = self.quit_pending = False
        self.cloak_at = None
        self.connected_at = None
        self.icon_key = self.state_title = None
        self.tray = None
        self.synapse_checking = False
        self.synapse_next_check = 0
        self.synapse_result = None

        self.window = Window(self.settings, system.autostart_enabled(), log_dir)
        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.flush_save)
        self.restart_timer = QTimer(self, singleShot=True, interval=3000, timeout=self._restart)
        self.probe_timer = QTimer(self, interval=2000, timeout=self._probe)
        self.usbip_timer = QTimer(self, interval=5000, timeout=self._check_usbip)
        self.tick_timer = QTimer(self, interval=1000, timeout=self._tick)

        bridge.status.connect(self._on_status)
        bridge.meter.connect(self.window.status_page.meter)
        bridge.running.connect(self._on_running)
        self.usbip_checked.connect(self._on_usbip)
        self.driver_done.connect(self._driver_done)
        self.hide_done.connect(self._hide_done)
        self.virtual_detached.connect(self._virtual_detached)
        self.native_done.connect(self._native_done)
        self.synapse_done.connect(self._synapse_done)
        pages = self.window
        pages.status_page.toggle_requested.connect(self._toggle)
        pages.vibration_page.changed.connect(self.update_settings)
        pages.vibration_page.test_requested.connect(self._test)
        pages.device_page.changed.connect(self.update_settings)
        pages.device_page.autostart_changed.connect(self._set_autostart)
        pages.device_page.hide_changed.connect(self._set_hidden)
        pages.device_page.driver_action.connect(self.switch_driver)
        pages.device_page.open_logs.connect(lambda: system.open_folder(str(log_dir)))
        pages.shown.connect(self._check_usbip)
        pages.hidden.connect(self._hidden)
        pages.quit_requested.connect(self.quit)

    def start(self, show=True):
        if self.settings.hide_physical and not self.settings.hidden_devices:
            # 旧版本没有登记端口；当时的脚本隐藏了已有的全部实例。放行程序无从得知，留空让界面提示重新开关。
            self.update_settings({"hidden_devices": tuple(self.system.pc_instances())})
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._make_tray()
        if self.settings.hide_physical:
            self._set_hidden(True)
        self._probe()
        for timer in (self.probe_timer, self.usbip_timer, self.tick_timer):
            timer.start()
        if show:
            self.show_window()

    # ---- 桥接进程 ----

    def _probe(self):
        instance, service = self.system.find_controller()
        mode = core.driver_mode(service, instance)
        changed = mode != self.mode or (instance or self.instance) != self.instance
        self.instance = instance or self.instance
        if mode != self.mode:
            self.mode = mode
            if not self.busy:
                self._apply_mode()
        if changed:
            if self._hide_warning() == "port":
                self.notify("new_port")
            self._refresh()
        if self.mode == "pc" and self.status.get("grips_ready") is False:
            self._ensure_synapse()

    def _hide_warning(self):
        """HidHide 按设备实例隐藏、按程序路径放行；两者任一和当前不符，隐藏就不完整。"""
        if self.mode != "pc" or not self.settings.hide_physical:
            return None
        known = {device.upper() for device in self.settings.hidden_devices}
        if self.instance and self.instance.upper() not in known:
            return "port"
        if self.settings.hidden_app.lower() != core.bridge_command(pc=True)[0].lower():
            return "app"
        return None

    def _apply_mode(self):
        # 拔线（变为 absent）时桥接继续跑，虚拟 DS5 不掉，游戏无需重启；Xbox 驱动下桥接用不了，停掉。
        self.wanted = self.mode != "xbox" and not self.paused
        if self.wanted and self.mode in ("pc", "bridge") and self.bridge.pc != (self.mode == "pc"):
            # 手柄换了模式：先停当前桥接，退出后由重启计时器按新模式拉起（虚拟 DS5 会短暂断开）。
            self.bridge.set_pc(self.mode == "pc")
            if self.bridge.is_running:
                self.bridge.stop()
                return
        if self.wanted:
            self._start_bridge()
        elif self.bridge.is_running:
            self.bridge.stop()

    def _start_bridge(self):
        if self.bridge.is_running or self.closing or self.hiding or self.hide_failed or self.quit_pending or self.exiting:
            return
        self.restart_timer.stop()
        # 桥接启动时读设置文件，未落盘的改动先写进去。
        if self.save_timer.isActive():
            self.flush_save()
        if self.bridge.pc:
            self._ensure_synapse()
        self.bridge.start()

    def _ensure_synapse(self):
        if (self.synapse_checking or self.closing or self.exiting or self.quit_pending or self.paused
                or not self.wanted or self.mode != "pc" or time.monotonic() < self.synapse_next_check):
            return
        self.synapse_checking = True
        self.synapse_next_check = time.monotonic() + 60
        self._log_synapse("Synapse check started")

        def work():
            self._log_synapse("Synapse check worker started")
            try:
                result = self.system.ensure_synapse()
            except Exception as error:
                result = f"error: {error}"
            self._log_synapse(f"Synapse check worker finished: {result}")
            self.synapse_done.emit(result)

        # 雷云启动慢也不阻塞输入；握把由桥接现有的重连逻辑原地恢复。
        threading.Thread(target=work, daemon=True).start()

    def _synapse_done(self, result):
        self.synapse_checking = False
        self._log_synapse(f"Synapse check finished: {result}")
        if self.closing or self.exiting or self.quit_pending:
            return
        previous, self.synapse_result = self.synapse_result, result
        if result == previous:
            return
        self._log_synapse(f"Synapse: {result}")
        if result == "started":
            self.toast("success", "已启动雷云", "握把服务就绪后自动恢复震动")
        elif result == "missing":
            self.toast("warning", "未找到雷云启动入口", "请安装或手动打开 Razer Synapse；手柄输入可继续使用")
        elif result.startswith("error:"):
            self.toast("warning", "雷云自动启动未完成", "请手动打开 Razer Synapse；检查详情已记录到 startup.log")

    def _log_synapse(self, result):
        try:
            with (self.log_dir / "startup.log").open("a", encoding="utf-8") as file:
                file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + result + "\n")
        except OSError:
            pass

    def _restart(self):
        if self.wanted and not self.closing:
            self._start_bridge()

    def _toggle(self):
        if self.bridge.is_running or self.wanted:
            self.paused = True
        elif self.mode == "xbox":
            self.switch_driver("bridge")
            return
        else:
            self.paused = False
        self._apply_mode()
        self._refresh()

    def _on_running(self, running):
        if not running:
            if self.wanted and not self.closing:
                self.events.status("lost")
                self.restart_timer.start()
            else:
                self.events.connected = False
            self.status = {}
            if self.pending_driver:
                target, self.pending_driver = self.pending_driver, None
                self._launch_driver(target)
        self._refresh()

    def _on_status(self, message):
        self.status = message
        self.events.status(message.get("state"))
        self._refresh()

    def _refresh(self):
        running = self.bridge.is_running
        connected = running and self.status.get("state") == "connected"
        key, title, detail = core.describe(running, self.wanted, self.status, self.mode)
        if self.busy:
            key, title, detail = "waiting", "正在切换驱动", "请在弹出的窗口中允许管理员权限"
        if self.exiting:
            key, title, detail = "waiting", "正在恢复原生手柄", "完成后自动退出"
        if running or self.wanted:
            action = "停止桥接"
        elif self.mode == "xbox":
            action = "切换到桥接模式"
        else:
            action = "启动桥接"
        page = self.window.status_page
        page.show_state(key, title, detail, action, not (self.busy or self.exiting) and self.mode is not None)
        page.mode_card.setContent(MODE_TEXT[self.mode])
        self.window.device_page.show_mode(self.mode, self.busy)
        self.window.device_page.show_hide_warning(self._hide_warning())
        self.window.vibration_page.set_pc_mode(self.mode == "pc")
        self.window.vibration_page.set_testable(connected)
        if not connected and self.window.vibration_page.testing:
            self._test(None)
        if connected and self.connected_at is None:
            self.connected_at = time.monotonic()
        elif not connected:
            self.connected_at = None
            page.clear()
        self.state_title = title
        if self.tray and key != self.icon_key:
            self.tray.setIcon(status_icon(key))
        self.icon_key = key
        if self.tray:
            self.toggle_action.setText(action)
            self.toggle_action.setEnabled(not (self.busy or self.exiting) and self.mode is not None)
        self._tick()

    def _tick(self):
        uptime = core.format_duration(time.monotonic() - self.connected_at) if self.connected_at else ""
        self.window.status_page.uptime.setText(uptime)
        if self.tray:
            self.tray.setToolTip(f"Wolverine DS5 · {self.state_title}" + (f" {uptime}" if uptime else ""))

    def _check_usbip(self):
        if self.checking or not self.window.isVisible():
            return
        self.checking = True

        def check():
            self.usbip_checked.emit(self.system.usbip_attached())

        threading.Thread(target=check, daemon=True).start()

    def _on_usbip(self, attached):
        self.checking = False
        self.window.status_page.ds5_card.setContent("已挂载（usbip 127.0.0.1:3240）" if attached
                                                    else "未挂载，桥接启动后自动挂载")

    # ---- 设置与测试 ----

    def update_settings(self, changes):
        self.settings = settings.Settings.from_dict({**dataclasses.asdict(self.settings), **changes})
        self.bridge.send(json.dumps({"type": "settings", "settings": dataclasses.asdict(self.settings)}))
        self.save_timer.start()

    def flush_save(self):
        self.save_timer.stop()
        settings.save(self.settings, self.settings_path)

    def _set_autostart(self, enabled):
        try:
            self.system.set_autostart(enabled)
        except OSError as error:
            self.toast("error", "开机自启设置失败", str(error))
        actual = self.system.autostart_enabled()
        if actual != enabled:
            self.window.device_page.autostart.switch.setChecked(actual)

    def _test(self, target):
        self.bridge.send(json.dumps({"type": "test", "target": target}))
        self.window.vibration_page.set_test(target)

    # ---- 对游戏隐藏实体手柄（HidHide） ----

    def _set_hidden(self, hidden):
        if self.hiding or self.exiting or self.closing:
            return
        self.hiding = True
        self.window.device_page.hide_physical.setEnabled(False)

        def work():
            try:
                result = self.system.configure_hiding(hidden, self.settings.hidden_app)
            except Exception as error:
                result = str(error)
            self.hide_done.emit(result, hidden)

        threading.Thread(target=work, daemon=True).start()

    def _warn_conflicts(self):
        """遮挡只对启动之后的程序生效：接管前就在跑的游戏仍能看到实体手柄，会和虚拟手柄抢信号。"""
        try:
            stale = [item["name"] for item in core.stale_windowed_processes(self.cloak_at)] if self.cloak_at else []
            tools = core.conflict_tools()
            audio = core.audio_to_haptics_active()
        except Exception as error:  # 枚举失败不影响主流程
            self._log_synapse(f"conflict check failed: {error!r}")
            return
        lines = []
        if stale:
            lines.append("接管前已在运行：" + "、".join(stale[:3]) + "；若其中含游戏请重启它")
        if tools:
            lines.append("还在运行：" + "、".join(tools) + "；它会再挂一个虚拟手柄")
        if audio:
            lines.append("雷云正在把音频转成震动；请在设备页取消勾选“音频到触感（此设备）”")
        if not lines:
            return
        for line in lines:
            self._log_synapse("conflict: " + line)
        self.toast("warning", "可能和虚拟手柄抢信号", "；".join(lines))

    def _hide_done(self, code, hidden):
        self.hiding = False
        if self.closing:
            return
        self.window.device_page.hide_physical.setEnabled(True)
        self.hide_failed = hidden and code != 0
        if code == 0:
            self.update_settings({"hide_physical": hidden,
                                  "hidden_devices": tuple(self.system.pc_instances()) if hidden else (),
                                  "hidden_app": core.bridge_command(pc=True)[0] if hidden else ""})
            if self.quit_pending:
                self.quit()
                return
            self._apply_mode()
            self._refresh()
            self.toast("success", "已隐藏实体手柄" if hidden else "已恢复实体手柄",
                       "若已运行的 Steam 或游戏仍识别到 Xbox，请完全退出后重开" if hidden else "游戏可以再次直接读取实体手柄")
            if hidden:
                self.cloak_at = time.time()
                self._warn_conflicts()
            return
        switch = self.window.device_page.hide_physical.switch
        switch.blockSignals(True)
        switch.setChecked(self.settings.hide_physical)
        switch.blockSignals(False)
        if self.quit_pending:
            self.quit()
            return
        self.toast("error", "HidHide 设置失败", f"{code}；请确认 HidHide 可用后重试")

    # ---- 驱动切换 ----

    def switch_driver(self, target):
        if self.busy or not self.instance:
            return
        if target == "xbox":
            title, content = "还原 Xbox 模式", "将停止桥接并卸载 WinUSB 驱动，手柄回到普通 Xbox 手柄，游戏里的虚拟 DualSense 会消失。"
        else:
            title, content = "切换到桥接模式", "将为手柄安装 WinUSB 驱动并启动桥接，手柄会以虚拟 DualSense 出现在游戏里。"
        self.show_window()
        box = MessageBox(title, content + "\n\n需要管理员权限，接下来会弹出 UAC 确认。", self.window)
        box.yesButton.setText("继续")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self.busy = True
        self.wanted = False
        self.restart_timer.stop()
        if self.bridge.is_running:
            # 桥接占着 WinUSB 句柄，等它真正退出再改驱动。
            self.pending_driver = target
            self.bridge.stop()
        else:
            self._launch_driver(target)
        self._refresh()

    def _launch_driver(self, target):
        script = core.restore_xbox_script(self.instance) if target == "xbox" else core.winusb_script(self.instance)

        def work():
            code = self.system.run_elevated(script)
            mode = "absent"
            for _ in range(30):
                mode = core.driver_mode(*reversed(self.system.find_controller()))
                if mode == target or code is None:
                    break
                time.sleep(.5)
            self.driver_done.emit(code, target, mode)

        threading.Thread(target=work, daemon=True).start()

    def _driver_done(self, code, target, mode):
        self.busy = False
        self.mode = mode
        if mode == target:
            self.paused = False
            self.toast("success", "驱动已切换", f"当前：{MODE_TEXT[mode]}")
        elif code is None:
            self.toast("warning", "未切换", "没有获得管理员权限")
        else:
            self.toast("error", "驱动切换未生效", f"退出码 {code}，当前：{MODE_TEXT[mode]}。"
                       "可在设备管理器卸载该设备并勾选“尝试删除此设备的驱动程序”，再重新插线。")
        if self.quit_pending:
            self.quit()
            return
        self._apply_mode()
        self._refresh()

    # ---- 窗口、托盘与通知 ----

    def _make_tray(self):
        self.tray = QSystemTrayIcon(status_icon("waiting"), self)
        self.menu = SystemTrayMenu(parent=self.window)
        self.toggle_action = Action(FluentIcon.SYNC, "停止桥接", triggered=self._toggle)
        self.menu.addActions([Action(FluentIcon.HOME, "打开主界面", triggered=self.show_window),
                              self.toggle_action,
                              Action(FluentIcon.CLOSE, "退出", triggered=self.quit)])
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.window.tray_available = True

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _hidden(self):
        if not self.hinted and self.tray:
            self.hinted = True
            self.tray.showMessage("Wolverine DS5 仍在运行", "桥接在后台继续工作，可从托盘图标打开或退出",
                                  self.tray.icon(), 3000)

    def notify(self, event):
        if self.tray and not self.closing:
            title, content = NOTICES[event]
            self.tray.showMessage(title, content, self.tray.icon(), 4000)

    def toast(self, kind, title, content):
        getattr(InfoBar, kind)(title, content, duration=6000, position=InfoBarPosition.TOP_RIGHT, parent=self.window)

    def quit(self):
        if self.closing or self.exiting:
            return
        self.quit_pending = True
        if self.hiding or self.busy:
            return
        self.exiting = self.paused = True
        self.wanted = False
        for timer in (self.restart_timer, self.probe_timer, self.usbip_timer, self.tick_timer):
            timer.stop()
        self.flush_save()
        self.window.device_page.setEnabled(False)
        self._refresh()

        def detach():
            try:
                self.system.detach_virtual()
                error = None
            except Exception as caught:
                error = str(caught)
            self.virtual_detached.emit(error)

        threading.Thread(target=detach, daemon=True).start()

    def _virtual_detached(self, error):
        # 先卸载客户端再停止服务器，避免 USB/IP 将正常退出当成断线并排队重连。
        self.bridge.shutdown()
        if error is not None:
            self._native_done(error)
            return

        def restore():
            try:
                self.system.restore_native(self.settings.hidden_app)
                error = None
            except Exception as caught:
                error = str(caught)
            self.native_done.emit(error)

        threading.Thread(target=restore, daemon=True).start()

    def _native_done(self, error):
        try:
            with (self.log_dir / "native-exit.log").open("a", encoding="utf-8") as file:
                file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + (error or "原生恢复完成") + "\n")
        except OSError:
            pass  # 日志不可写时仍完成恢复或显示失败，不能再次卡住退出。
        if error is not None:
            self.exiting = self.quit_pending = False
            self.hide_failed = self.settings.hide_physical
            self.window.quitting = False
            self.window.device_page.setEnabled(True)
            for timer in (self.probe_timer, self.usbip_timer, self.tick_timer):
                timer.start()
            self._refresh()
            self.show_window()
            self.toast("error", "原生恢复未完成，暂未退出", f"{error}。请再次点击托盘“退出”重试。")
            return
        # 保存桥接偏好，但清除已撤销的隐藏登记；下次启动会重新申请。
        self.settings = dataclasses.replace(self.settings, hidden_devices=(), hidden_app="")
        self.close()
        QApplication.quit()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.wanted = False
        for timer in (self.save_timer, self.restart_timer, self.probe_timer, self.usbip_timer, self.tick_timer):
            timer.stop()
        settings.save(self.settings, self.settings_path)
        self.window.hide()
        if self.tray:
            self.tray.hide()
        self.bridge.shutdown()
        self.window.quitting = True
        self.window.close()


def log_crashes(directory):
    # pythonw 没有 stderr，界面里的未捕获异常写进日志目录，不然会无声丢失。
    def hook(kind, error, trace):
        with open(pathlib.Path(directory) / "ui-errors.log", "a", encoding="utf-8") as file:
            file.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "".join(traceback.format_exception(kind, error, trace)))
    sys.excepthook = hook


def main(argv=None):
    argv = sys.argv if argv is None else argv
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WolverineDS5.App")
    log_dir = core.data_dir() / "logs"
    log_crashes(log_dir)
    qt = QApplication(argv)
    qt.setQuitOnLastWindowClosed(False)
    qt.setWindowIcon(status_icon("connected"))

    # 单实例：已有实例时让它显示窗口（开机自启的 --tray 不打扰），自己退出。
    name = f"WolverineDS5-{getpass.getuser()}"
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(300):
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        socket.write(b"tray" if "--tray" in argv else b"show")
        socket.waitForBytesWritten(1000)
        return 0

    app = App(Bridge(core.bridge_command(), core.root_dir(), log_dir,
                     make_command=lambda pc: core.bridge_command(pc=pc)),
              System(), settings.default_path(), log_dir)
    server = QLocalServer(app)

    def activate():
        client = server.nextPendingConnection()
        if client.waitForReadyRead(1000) and bytes(client.readAll()) == b"show":
            app.show_window()
        client.disconnectFromServer()

    server.newConnection.connect(activate)
    server.listen(name)
    app.start(show="--tray" not in argv)
    return qt.exec()


def self_test():
    """安装后自检：只验证依赖和随包文件，不启动桥接、不碰驱动与手柄。"""
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report, ok = [], True
    try:
        from PySide6.QtWidgets import QApplication
        import numpy
        import psutil
        import qfluentwidgets
        qt = QApplication([])
        report.append(f"qt_platform={qt.platformName()}")
        root = core.root_dir()
        for name in ("wolverine-capture.exe", "SDL3.dll", "xbox-sensa-device.json", "sensa-device.json"):
            present = (root / name).exists()
            ok = ok and present
            report.append(f"{name}={present}")
        report.append(f"python={sys.version.split()[0]} numpy={numpy.__version__}")
    except Exception:
        ok = False
        report.append(traceback.format_exc())
    log = pathlib.Path(tempfile.gettempdir()) / "WolverineDS5-self-test.log"
    log.write_text("\n".join(report + (["OK"] if ok else ["FAILED"])) + "\n", encoding="utf-8")
    return 0 if ok else 3


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
