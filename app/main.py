"""托盘程序入口：托管桥接子进程，把状态、设置和驱动切换接到窗口与托盘上。"""
import ctypes
import dataclasses
import faulthandler
import getpass
import json
import os
import pathlib
import platform
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _early_log_dir():
    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home())
    return pathlib.Path(base) / "WolverineDS5" / "logs"


def _install_early_logging():
    """PySide6 导入失败时不会有任何界面；先把 faulthandler 挂到固定文件上。"""
    try:
        directory = _early_log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stream = (directory / "startup-crash.log").open("a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=stream, all_threads=True)
        return stream
    except OSError:
        return None


_CRASH_STREAM = _install_early_logging()


def _report_startup_failure(detail):
    """导入失败时给中文提示：最常见原因是杀毒软件删了包里的 pyd/dll。

    这时 Qt 可能根本没加载，只能用 Win32 MessageBox；日志已经写进 startup-crash.log。
    """
    try:
        last = detail.strip().splitlines()[-1][:300] if detail.strip() else ""
        message = ("程序文件缺失或被杀毒软件拦截，启动不了。\n\n"
                   "1）把这个程序加入杀毒软件白名单；\n"
                   "2）重新运行安装包修复（会重新自检）；\n"
                   f"3）详细日志：{_early_log_dir() / 'startup-crash.log'}\n\n"
                   f"{last}")
        ctypes.windll.user32.MessageBoxW(None, message, "Wolverine DS5 启动失败", 0x10)
    except Exception:
        pass


try:
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from qfluentwidgets import Action, FluentIcon, MessageBox, SystemTrayMenu, Theme, setTheme, setThemeColor

    import settings
    from app import __version__, core, log_export, native, readiness, synapse, update
    from app.bridge import Bridge
    from app.qml_window import QmlWindow
    from app.ui_model import UiModel
    from app.window import MODE_TEXT, status_icon
except BaseException:
    _detail = traceback.format_exc()
    if _CRASH_STREAM is not None:
        _CRASH_STREAM.write("import failure:\n" + _detail)
        _CRASH_STREAM.flush()
    _report_startup_failure(_detail)
    sys.exit(3)

NOTICES = {"connected": ("手柄已连接", "虚拟 DualSense 已就绪"),
           "lost": ("手柄已断开", "重新插上即可恢复，游戏无需重启"),
           "reconnected": ("手柄已重新连接", "震动与按键已恢复"),
           "xbox": ("手柄处于 Xbox 模式", "握把震动只支持 PC 模式；拨到 PC 模式后会自动连接"),
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
    diagnose_synapse = staticmethod(synapse.diagnose)

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
    grips_checked = Signal(str)
    readiness_checked = Signal(object)
    update_checked = Signal(str)

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
        self.xbox_hinted = False
        self.pending_driver = None
        self.hiding = self.hide_failed = self.exiting = self.quit_pending = False
        self.hiding_active = self.hide_transient = False
        self.connected_at = None
        self.icon_key = self.state_title = None
        self.tray = None
        self.synapse_action = None
        self.synapse_checking = False
        self.synapse_tried = False
        self.synapse_result = None
        self.grips_state = None
        self.grips_were_ready = False
        self.grips_checking = False
        self.grips_next_check = 0
        self.bridge_running = False
        self.bridge_started_at = None
        self.usbip_state = None
        self.audio_frames = 0
        self.audio_seen_at = None
        self.audio_color = "#8A8A8A"
        self.readiness_report = None
        self.readiness_checking = False
        self.update_tag = ""
        self.update_marker = log_dir.parent / "update-check.txt"
        # 安装器在需要重启时留下这个文件：重启后第一次自检要把结果主动告诉用户。
        self.first_run_marker = pathlib.Path(core.root_dir()) / "first-run.pending"
        self.first_run = self.first_run_marker.exists()

        self.model = UiModel(self.settings, log_dir)
        self.model.apply_settings(self.settings)
        self.model.set_autostart(system.autostart_enabled())
        self.window = QmlWindow(self.model)
        self.save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.flush_save)
        self.restart_timer = QTimer(self, singleShot=True, interval=3000, timeout=self._restart)
        self.probe_timer = QTimer(self, interval=2000, timeout=self._probe)
        self.usbip_timer = QTimer(self, interval=5000, timeout=self._check_usbip)
        self.tick_timer = QTimer(self, interval=1000, timeout=self._tick)
        self.readiness_timer = QTimer(self, interval=15000, timeout=self._run_readiness)

        bridge.status.connect(self._on_status)
        bridge.meter.connect(self.model.set_meter)
        bridge.stats.connect(self._on_stats)
        bridge.running.connect(self._on_running)
        self.usbip_checked.connect(self._on_usbip)
        self.driver_done.connect(self._driver_done)
        self.hide_done.connect(self._hide_done)
        self.virtual_detached.connect(self._virtual_detached)
        self.native_done.connect(self._native_done)
        self.synapse_done.connect(self._synapse_done)
        self.grips_checked.connect(self._grips_checked)
        self.readiness_checked.connect(self._on_readiness)
        self.update_checked.connect(self._on_update)
        self.model.toggleRequested.connect(self._toggle)
        self.model.settingsEdited.connect(self.update_settings)
        self.model.testRequested.connect(self._test)
        self.model.chainTestRequested.connect(self._chain_test)
        self.model.autostartRequested.connect(self._set_autostart)
        self.model.hideRequested.connect(self._set_hidden)
        self.model.synapseRequested.connect(self._start_synapse)
        self.model.readinessRequested.connect(self._run_readiness)
        self.model.fixRequested.connect(self.apply_fix)
        self.model.openUpdateRequested.connect(self._open_update)
        self.model.openLogsRequested.connect(lambda: system.open_folder(str(log_dir)))
        self.model.exportLogsRequested.connect(self.export_logs)
        self.window.shown.connect(self._check_usbip)
        self.window.hidden.connect(self._hidden)
        self.window.quit_requested.connect(self.quit)

    def start(self, show=True):
        if self.settings.hide_physical and not self.settings.hidden_devices:
            # 旧版本没有登记端口；当时的脚本隐藏了已有的全部实例。放行程序无从得知，留空让界面提示重新开关。
            self.update_settings({"hidden_devices": tuple(self.system.pc_instances())})
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._make_tray()
        if self.settings.hide_physical:
            self._set_hidden(True)
        self._probe()
        for timer in (self.probe_timer, self.usbip_timer, self.tick_timer, self.readiness_timer):
            timer.start()
        self._run_readiness()
        threading.Thread(target=self._check_update, daemon=True).start()
        if show:
            self.show_window()

    # ---- 桥接进程 ----

    def _probe(self):
        instance, service = self.system.find_controller()
        mode = core.driver_mode(service, instance)
        changed = mode != self.mode or (instance or self.instance) != self.instance
        self.instance = instance or self.instance
        if mode != self.mode:
            previous, self.mode = self.mode, mode
            # 用户拨模式开关后，诊断导出要能看出程序在什么时刻认出了哪一种模式。
            self._log_synapse(f"Mode: {previous} -> {mode} ({instance or 'no device'})")
            if not self.busy:
                self._apply_mode()
        if mode in ("xbox", "bridge"):
            self._remind_pc_mode()
        else:
            self.xbox_hinted = False
        if changed:
            if self._hide_warning() == "port":
                self.notify("new_port")
            self._refresh()
        if self.mode == "pc" and self.status.get("backend") == "sensa":
            self._check_grips()
        if self.mode == "pc" and self._grips_ready() is False and not self.synapse_tried:
            self._ensure_synapse()

    def _remind_pc_mode(self):
        # Xbox 模式不是故障：每次切到该模式只提醒一次，拨回 PC 模式后桥接会自己起来。
        if not self.xbox_hinted:
            self.xbox_hinted = True
            self.notify("xbox")

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
        # PC-only 产品：PC 模式（以及拔线后的 absent）保持虚拟 DS5；Xbox 模式保留为实验性代码，不自动接管。
        self.wanted = self.mode in ("pc", "absent") and not self.paused
        if self.wanted and self.settings.hide_physical and not self.hiding_active \
                and not self.hiding and not self.hide_failed:
            # 隐藏是给桥接用的：桥接重新起来之前先把实体手柄藏回去，成功后再由 _hide_done 拉起桥接。
            self._set_hidden(True, transient=True)
            return
        if self.wanted and not self.bridge.pc:
            # 从旧模式切到 PC：先停当前桥接，退出后由重启计时器拉起（虚拟 DS5 会短暂断开）。
            self.bridge.set_pc(True)
            if self.bridge.is_running:
                self.bridge.stop()
                return
        if self.wanted:
            self._start_bridge()
            return
        if self.bridge.is_running:
            self.bridge.stop()
        if self.hiding_active and self.settings.hide_physical and not self.hiding:
            # 桥接停了就别再藏着实体手柄：否则虚拟 DS5 没了、手柄也看不见，游戏里一只都没有。
            self._set_hidden(False, transient=True)

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

    def _ensure_synapse(self, manual=False):
        # 自动拉起只做一次（桥接启动时）；中途退出雷云不追着重启，改成界面上的「启动雷云」按钮。
        if (self.synapse_checking or self.closing or self.exiting or self.quit_pending or self.paused
                or not self.wanted or self.mode != "pc"):
            return
        if not manual and self.synapse_tried:
            return
        if not manual:
            self.synapse_tried = True
        self.synapse_checking = True
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

    def _start_synapse(self):
        self._ensure_synapse(manual=True)

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
        elif result == "failed":
            self.toast("warning", "雷云没有启动成功", "请从开始菜单手动打开 Razer Synapse；手柄输入可继续使用")
        elif result == "missing":
            self.toast("warning", "未找到雷云启动入口", "请安装或手动打开 Razer Synapse；手柄输入可继续使用")
        elif result.startswith("error:"):
            self.toast("warning", "雷云自动启动未完成", "请手动打开 Razer Synapse；检查详情已记录到 startup.log")

    def _check_grips(self):
        # 桥接只知道震动服务的共享内存能不能打开；手柄有没有被雷云登记、雷云是不是离线，要看雷蛇自己的日志。
        if (self.grips_checking or self.closing or self.exiting or self.quit_pending
                or time.monotonic() < self.grips_next_check):
            return
        self.grips_checking = True
        self.grips_next_check = time.monotonic() + 5

        def work():
            try:
                result = self.system.diagnose_synapse()
            except Exception as error:
                self._log_synapse(f"Grips check failed: {error}")
                result = "unknown"
            self.grips_checked.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _grips_checked(self, result):
        self.grips_checking = False
        if self.closing or self.exiting or self.quit_pending:
            return
        previous, self.grips_state = self.grips_state, result
        if result == previous:
            return
        self._log_synapse(f"Grips: {result}")
        if result == "ready":
            self.grips_were_ready = True
        elif result == "offline":
            self.toast("warning", "雷云处于离线模式", "雷云没联网时不会加载手柄，握把不会震。恢复网络后点「启动雷云」重开")
        elif result == "stopped" and self.grips_were_ready:
            # 中途退出雷云：不追着重启，只提示一次，给一个可点的入口。
            self.toast("warning", "雷云已退出", "握把暂时不可用；点状态页或托盘菜单的「启动雷云」恢复，按键输入不受影响")
        self._refresh()

    def _grips_ready(self):
        ready = self.status.get("grips_ready")
        if ready and self.grips_state in ("offline", "unregistered", "stopped"):
            return False
        return ready

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
        elif self.mode != "pc":
            self.toast("warning", "请切换到 PC 模式", "握把震动只支持 PC 模式；把手柄拨到 PC 模式后会自动连接")
            return
        else:
            self.paused = False
        self._apply_mode()
        self._refresh()

    def _on_running(self, running):
        self.bridge_running = running
        if not running:
            self.bridge_started_at = None
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
        if message.get("state") == "connected" and self.bridge_started_at is None:
            # 标记虚拟手柄挂载时刻：比它更早启动的游戏拿不到触觉流，要提示重开。
            self.bridge_started_at = time.time()
        if message.get("state") == "lost":
            self.bridge_started_at = None
        self.events.status(message.get("state"))
        self._refresh()

    def _on_stats(self, message):
        frames = int(message.get("audio_frames") or 0)
        if frames > self.audio_frames:
            self.audio_seen_at = time.monotonic()
        self.audio_frames = frames
        self._update_audio()
        self._refresh()

    def _audio_age(self):
        return None if self.audio_seen_at is None else time.monotonic() - self.audio_seen_at

    def _update_audio(self):
        if not self.bridge_running:
            text, color = "未启动", "#8A8A8A"
        elif self.audio_frames <= 0:
            text, color = "还没收到", "#E8B454"
        else:
            age = self._audio_age() or 0.0
            text = f"已收到（最近 {age:.0f} 秒）" if age < 30 else "最近 30 秒没收到"
            color = "#44D62C" if age < 30 else "#E8B454"
        self.audio_color = color
        self.model.set_audio_state(text, color)

    def _run_readiness(self):
        if self.readiness_checking or self.closing:
            return
        self.readiness_checking = True

        def work():
            try:
                stale = ()
                if self.bridge_started_at and self.mode == "pc":
                    try:
                        stale = tuple(core.stale_windowed_processes(self.bridge_started_at))
                    except Exception:
                        stale = ()
                facts = readiness.gather_facts(
                    root=core.root_dir(), settings=self.settings, mode=self.mode, instance=self.instance,
                    bridge_running=self.bridge_running, bridge_state=self.status,
                    audio_frames=self.audio_frames, audio_age=self._audio_age(), stale=stale)
                data = readiness.build_report(facts).to_dict()
            except Exception as error:
                data = {"ready": False, "summary": "自检失败", "error": str(error), "checks": []}
            self.readiness_checked.emit(data)

        threading.Thread(target=work, daemon=True).start()

    def _on_readiness(self, data):
        self.readiness_checking = False
        if self.closing:
            return
        self.readiness_report = data
        self.model.set_readiness(data)
        if self.first_run:
            self._first_run_result(data)

    def _first_run_result(self, data):
        """安装/重启后第一次跑完自检：把结论直接推给用户，别让他在检查项里自己找。"""
        self.first_run = False
        try:
            self.first_run_marker.unlink()
        except OSError:
            pass
        summary = data.get("summary", "")
        if data.get("state") == "ready":
            self.toast("info", "安装完成", "自检通过，进游戏就能用")
        elif data.get("core_ready"):
            self.toast("warning", "按键已可用，握把还差一步", summary)
        else:
            self.toast("warning", "还差几步才能用", f"{summary}；按状态页的按钮逐项处理")

    def _check_update(self):
        try:
            tag = update.check(self.update_marker)
        except Exception:
            tag = ""
        self.update_checked.emit(tag)

    def _on_update(self, tag):
        if not tag or self.closing:
            return
        self.update_tag = tag
        self.model.set_update(tag.lstrip("vV"))

    def _open_update(self):
        if self.update_tag:
            webbrowser.open(update.release_url(self.update_tag))

    def _report_issue(self):
        """带版本和自检结果打开新 issue：用户不用会写复现步骤，也不会漏带关键信息。"""
        report = self.readiness_report or {}
        lines = [f"版本：{__version__}", f"系统：{platform.platform()}",
                 f"自检：{report.get('summary', '')}", ""]
        for item in report.get("checks", []):
            if item.get("state") in ("fail", "warn"):
                lines.append(f"- {item.get('title', '')}：{item.get('detail', '')}")
        query = urllib.parse.urlencode({"title": f"[自动] {report.get('summary', '问题反馈')}",
                                        "body": "\n".join(lines)})
        webbrowser.open(f"https://github.com/Winkless213/wolverine-ds5/issues/new?{query}")

    def apply_fix(self, action):
        """自检横幅上的修复动作；只做用户本来就能在界面上做的事。"""
        if action == "recheck":
            self._run_readiness()
            return
        if action == "start_synapse":
            self._start_synapse()
        elif action == "restart_bridge":
            self.paused = False
            if self.bridge.is_running:
                self.bridge.stop()
            else:
                self._apply_mode()
        elif action in ("enable_hide", "rehide"):
            if action == "enable_hide":
                self.update_settings({"hide_physical": True})
            self.hide_failed = False
            self._set_hidden(True)
        elif action == "switch_pc":
            self.switch_driver("pc")
        elif action == "open_synapse":
            webbrowser.open("https://www.razer.com/synapse-4")
        elif action == "open_usbip":
            webbrowser.open("https://github.com/vadimgrn/usbip-win2/releases")
        elif action == "open_hidhide":
            webbrowser.open("https://github.com/nefarius/HidHide/releases")
        elif action == "report_issue":
            self._report_issue()
        elif action == "enable_grip":
            self.update_settings({"grip_enabled": True})
        elif action == "set_gain":
            self.update_settings({"grip_gain": 1.0, "grip_gain_left": 1.0, "grip_gain_right": 1.0})
        self._refresh()
        # 隐藏、拉雷云、重启桥接都是异步的：立刻重查还是旧状态，等它们落地后再查一次。
        self._run_readiness()
        if action in ("start_synapse", "restart_bridge", "enable_hide", "rehide", "switch_pc"):
            QTimer.singleShot(2500, self._run_readiness)

    def _refresh(self):
        running = self.bridge.is_running
        self.bridge_running = running
        connected = running and self.status.get("state") == "connected"
        ready = self._grips_ready()
        status = dict(self.status, grips_ready=ready, synapse=self.grips_state,
                      hide_released=bool(self.settings.hide_physical and not self.hiding_active),
                      hide_failed=bool(self.settings.hide_physical and self.hide_failed))
        key, title, detail = core.describe(running, self.wanted, status, self.mode)
        if self.busy:
            key, title, detail = "waiting", "正在切换驱动", "请在弹出的窗口中允许管理员权限"
        if self.exiting:
            key, title, detail = "waiting", "正在恢复原生手柄", "完成后自动退出"
        if running or self.wanted:
            action = "停止桥接"
        elif self.mode in ("xbox", "bridge"):
            action = "请切换到 PC 模式"
        else:
            action = "启动桥接"
        enabled = (running or self.wanted or self.mode == "pc") and not (self.busy or self.exiting)
        self.model.apply_status(key, title, detail, action, enabled)
        self.model.set_mode(self.mode)
        self.model.set_connected(connected)
        if self.mode is None:
            self.model.set_ds5("检查中")
        self.model.set_hide_warning(self._hide_warning())
        if self.status.get("backend") == "sensa":
            offline = not ready and self.grips_state == "offline"
            self.model.set_sensa("就绪" if ready else "雷云离线" if offline else "等待")
            self.model.set_grip_ready(bool(ready))
        else:
            self.model.set_sensa("未检测")
            self.model.set_grip_ready(True)
        error_title, error_detail = readiness.grip_error_text(self.status.get("grip_error"))
        self.model.set_grip_error(error_title, error_detail)
        if not self.settings.hide_physical:
            hide_text, hide_color = "关闭", "#8A8A8A"
        elif self.hide_failed:
            hide_text, hide_color = "失败", "#F06A6A"
        elif self.hiding_active:
            hide_text, hide_color = "开启", "#44D62C"
        else:
            hide_text, hide_color = "未生效", "#E8B454"
        self.model.set_hide_state(hide_text, hide_color)
        self._update_audio()
        ds5_color = "#44D62C" if self.usbip_state else ("#E8B454" if running else "#8A8A8A")
        sensa_color = ("#44D62C" if ready else
                       "#F06A6A" if self.status.get("grip_error") else "#E8B454")
        self.model.set_dots(ds5_color, sensa_color, self.audio_color, hide_color)
        # 雷云没在跑（或离线）才给「启动雷云」入口；程序不会自己去反复拉起。
        self.model.set_synapse_startable(
            bool(self.mode == "pc" and self.wanted and not self.synapse_checking
                 and self.status.get("backend") == "sensa"
                 and self.grips_state in ("stopped", "offline")))
        was_testing = self.model.testing
        self.model.set_testable(connected)
        if not connected and was_testing:
            self._test(None)
        if connected and self.connected_at is None:
            self.connected_at = time.monotonic()
        elif not connected:
            self.connected_at = None
            self.model.set_meter({"motors": [0, 0]})
        self.state_title = title
        if self.tray and key != self.icon_key:
            self.tray.setIcon(status_icon(key))
        self.icon_key = key
        if self.tray:
            self.toggle_action.setText(action)
            self.toggle_action.setEnabled(not (self.busy or self.exiting) and self.mode is not None)
            if self.synapse_action is not None:
                self.synapse_action.setEnabled(self.model.synapseStartable)
        self._tick()

    def _tick(self):
        uptime = core.format_duration(time.monotonic() - self.connected_at) if self.connected_at else ""
        self.model.set_uptime(uptime)
        if self.tray:
            self.tray.setToolTip(f"Wolverine to DS5 · {self.state_title}" + (f" {uptime}" if uptime else ""))

    def _check_usbip(self):
        if self.checking or not self.window.isVisible():
            return
        self.checking = True

        def check():
            self.usbip_checked.emit(self.system.usbip_attached())

        threading.Thread(target=check, daemon=True).start()

    def _on_usbip(self, attached):
        self.checking = False
        self.usbip_state = attached
        self.model.set_ds5("已挂载" if attached else "未挂载",
                           "usbip · 127.0.0.1:3240" if attached else "桥接启动后自动挂载")
        self._refresh()

    # ---- 设置与测试 ----

    def update_settings(self, changes):
        self.settings = settings.Settings.from_dict({**dataclasses.asdict(self.settings), **changes})
        self.model.apply_settings(self.settings)
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
        self.model.set_autostart(actual)

    def export_logs(self):
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QFileDialog
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        folder = pathlib.Path(desktop) if desktop else pathlib.Path.home()
        default = log_export.default_export_path(folder)
        path, _ = QFileDialog.getSaveFileName(None, "导出诊断日志", str(default), "文本日志 (*.txt)")
        if not path:
            return
        try:
            text = log_export.build_diagnostic(self.log_dir, __version__, self.mode,
                                               dataclasses.asdict(self.settings), status=self.status,
                                               readiness=self.readiness_report)
            pathlib.Path(path).write_text(text, encoding="utf-8")
        except OSError as error:
            self.toast("error", "日志导出失败", str(error))
            return
        self.toast("success", "日志已导出", path)

    def _test(self, target):
        self.bridge.send(json.dumps({"type": "test", "target": target}))
        self.model.set_testing(target)

    def _chain_test(self):
        # 先关掉 LT/RT 测试，再让输出线程用真编码器跑合成 PCM（左 1.5s → 右 1.5s）。
        self._test(None)
        self.bridge.send(json.dumps({"type": "test", "target": "chain"}))
        self.toast("success", "全链路测试",
                   "先左握把、再右握把各 1.5 秒；只震一边或都没震，请到系统页导出日志")

    # ---- 对游戏隐藏实体手柄（HidHide） ----

    def _set_hidden(self, hidden, transient=False):
        if self.hiding or self.exiting or self.closing:
            return
        self.hiding = True
        self.hide_transient = transient

        def work():
            try:
                result = self.system.configure_hiding(hidden, self.settings.hidden_app)
            except Exception as error:
                result = str(error)
            self.hide_done.emit(result, hidden)

        threading.Thread(target=work, daemon=True).start()

    def _hide_done(self, code, hidden):
        self.hiding = False
        transient, self.hide_transient = self.hide_transient, False
        if self.closing:
            return
        self.hide_failed = hidden and code != 0
        if code == 0:
            self.hiding_active = hidden
            # 临时解除隐藏只为把实体手柄让回去，界面上的开关仍反映保存的偏好。
            self.model.set_hide_physical(self.settings.hide_physical if transient else hidden)
            if transient:
                if hidden:
                    self.update_settings({"hidden_devices": tuple(self.system.pc_instances()),
                                          "hidden_app": core.bridge_command(pc=True)[0]})
            else:
                self.update_settings({"hide_physical": hidden,
                                      "hidden_devices": tuple(self.system.pc_instances()) if hidden else (),
                                      "hidden_app": core.bridge_command(pc=True)[0] if hidden else ""})
            if self.quit_pending:
                self.quit()
                return
            self._apply_mode()
            self._refresh()
            if transient:
                if not hidden:
                    self.toast("success", "实体手柄已恢复", "桥接停止期间游戏可以看到原生手柄；启动桥接会自动重新隐藏")
                return
            self.toast("success", "已隐藏实体手柄" if hidden else "已恢复实体手柄", "设置已保存")
            return
        self.model.set_hide_physical(self.settings.hide_physical)
        if self.quit_pending:
            self.quit()
            return
        # 隐藏失败不能把原因吞掉：桥接按旧规则不启动（实体手柄还看得见，不能让游戏出现两只），
        # 但状态标题和自检都会写明真实原因，并给「重新隐藏」的入口。
        self.toast("error", "HidHide 设置失败", f"{code}；请确认 HidHide 可用后重试")
        self._refresh()
        self._run_readiness()

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
        self.menu = SystemTrayMenu()
        self.toggle_action = Action(FluentIcon.SYNC, "停止桥接", triggered=self._toggle)
        self.synapse_action = Action(FluentIcon.PLAY, "启动雷云", triggered=self._start_synapse)
        self.synapse_action.setEnabled(False)
        self.menu.addActions([Action(FluentIcon.HOME, "打开主界面", triggered=self.show_window),
                              self.toggle_action,
                              self.synapse_action,
                              Action(FluentIcon.CLOSE, "退出", triggered=self.quit)])
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.window.tray_available = True
        self.model.set_tray_available(True)

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
            self.tray.showMessage("Wolverine to DS5 仍在运行", "桥接在后台继续工作，可从托盘图标打开或退出",
                                  self.tray.icon(), 3000)

    def notify(self, event):
        if self.tray and not self.closing:
            title, content = NOTICES[event]
            self.tray.showMessage(title, content, self.tray.icon(), 4000)

    def toast(self, kind, title, content):
        self.model.show_toast(kind, title, content)

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


def diagnose():
    """无界面诊断：安装器和故障机直接跑 `WolverineDS5.exe --diagnose`，不启动桥接。"""
    import tempfile

    report = readiness.diagnose(root=core.root_dir(), settings=settings.load())
    paths = readiness.write_files(report, pathlib.Path(tempfile.gettempdir()))
    print(report.text())
    print(f"报告：{paths[1]}")
    # 只看核心链路：没有雷云时按键照样能用，不该让环境诊断返回失败。
    return 0 if report.core_ready else 3


def uninstall_cleanup():
    """卸载前收尾：放开实体手柄、卸掉虚拟手柄、删掉最高权限任务。

    卸载器可能已经删掉部分文件，所以每一步失败都只记录，最后的退出码表示是否全部完成。
    结果同时写进 %TEMP%\\WolverineDS5-uninstall-result.txt：窗口版 exe 没有控制台，卸载器只认这个文件。
    """
    import tempfile

    done = True
    lines = []
    before = readiness.usbip_services()
    try:
        native.restore_native(settings.load().hidden_app)
        lines.append("restore_native=ok")
    except Exception as error:
        lines.append(f"restore_native=failed {error}")
        done = False
    try:
        if synapse.delete_task():
            lines.append("delete_task=ok")
        else:
            lines.append("delete_task=failed")
            done = False
    except Exception as error:
        lines.append(f"delete_task=failed {error}")
        done = False
    try:
        core.set_autostart(False)
        lines.append("autostart=removed")
    except Exception as error:
        lines.append(f"autostart=skipped {error}")
    # 卸载只解除挂载和隐藏，绝不删 USBIP 驱动/服务：删了就可能在 USB 层留烂摊子。
    after = readiness.usbip_services()
    lines.append("usbip_services_before=" + ",".join(before))
    lines.append("usbip_services_after=" + ",".join(after))
    lines.append("usbip_untouched=" + ("ok" if before == after else "changed"))
    if before != after:
        done = False
    lines.append("result=" + ("ok" if done else "failed"))
    try:
        (pathlib.Path(tempfile.gettempdir()) / "WolverineDS5-uninstall-result.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if done else 1


def request_quit(name, timeout_ms=30000):
    """安装器、卸载器用：请正在运行的实例自己退出。

    绝对不能直接结束进程：那会跳过"放开实体手柄、卸掉虚拟手柄"，
    用户看到的是手柄时隐时现或者两只手柄并存，只能重启电脑。
    """
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return 0  # 没在运行，正是想要的结果
    socket.write(b"quit")
    if not socket.waitForBytesWritten(1000):
        return 1
    # 服务端完成原生恢复、桥接退出后进程结束，这条连接随之断开。
    return 0 if socket.waitForDisconnected(timeout_ms) else 1


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
    if "--quit" in argv:
        return request_quit(name)
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
        if client.waitForReadyRead(1000):
            message = bytes(client.readAll())
            if message == b"show":
                app.show_window()
            elif message == b"quit":
                app.quit()
        client.disconnectFromServer()

    server.newConnection.connect(activate)
    server.listen(name)
    app.start(show="--tray" not in argv)
    return qt.exec()


def self_test():
    """安装后自检：只验证依赖和随包文件，不启动桥接、不碰驱动与手柄。"""
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    report, ok = [], True
    try:
        from PySide6.QtWidgets import QApplication
        import numpy
        import psutil
        import qfluentwidgets
        qt = QApplication([])
        report.append(f"qt_platform={qt.platformName()}")
        root = core.root_dir()
        from app.qml_window import QmlWindow
        from app.ui_model import UiModel
        window = QmlWindow(UiModel(settings.Settings(), pathlib.Path(tempfile.gettempdir())))
        qml_ok = window.root is not None and (root / "ui" / "main.qml").exists()
        report.append(f"qml={qml_ok}")
        ok = ok and qml_ok
        window.close()
        for name in ("wolverine-capture.exe", "SDL3.dll", "xbox-sensa-device.json", "sensa-device.json",
                     "psutil/_psutil_windows.pyd", "_socket.pyd"):
            present = (root / name).exists()
            ok = ok and present
            report.append(f"{name}={present}")
        # 桥接链路的第三方依赖（如 cryptography）必须随包，缺了 Xbox/GIP 路线会在运行时才炸。
        import pc_bridge  # noqa: F401
        import gip_bridge  # noqa: F401
        import libusb_package
        libusb_dll = libusb_package.get_library_path()
        libusb_ok = libusb_dll is not None and pathlib.Path(libusb_dll).exists()
        report.append(f"bridge_import=ok libusb_package_dll={libusb_ok}")
        ok = ok and libusb_ok
        report.append(f"python={sys.version.split()[0]} numpy={numpy.__version__}")
    except Exception:
        ok = False
        report.append(traceback.format_exc())
    log = pathlib.Path(tempfile.gettempdir()) / "WolverineDS5-self-test.log"
    log.write_text("\n".join(report + (["OK"] if ok else ["FAILED"])) + "\n", encoding="utf-8")
    return 0 if ok else 3


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        sys.exit(diagnose())
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--uninstall" in sys.argv:
        sys.exit(uninstall_cleanup())
    sys.exit(main())
