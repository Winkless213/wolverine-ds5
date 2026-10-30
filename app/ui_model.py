"""QML 界面的数据模型：把桥接状态、设置和用户操作暴露给 Qt Quick。

界面只读这里的属性和调用槽；所有真正的桥接/系统操作仍由 app.main.App 负责。
"""
from PySide6.QtCore import Property, QObject, Signal, Slot

from app import __version__
from settings import DEFAULT_PROFILE, PROFILES

STATUS_COLORS = {"connected": "#44D62C", "waiting": "#E8B454",
                 "stopped": "#8A8A8A", "error": "#F06A6A"}
HIDE_WARNINGS = {"port": "手柄接在开启隐藏后没用过的 USB 口，游戏可能又能看到它；请关闭再打开一次",
                 "app": "当前桥接程序还没被 HidHide 放行，读不到被隐藏的手柄；请关闭再打开一次"}
MODE_LABELS = {"pc": "PC 模式", "xbox": "Xbox 模式", "bridge": "Xbox 模式", "absent": "未检测", None: "未检测"}


class UiModel(QObject):
    statusChanged = Signal()
    modeChanged = Signal()
    connectedChanged = Signal()
    meterChanged = Signal()
    settingsChanged = Signal()
    testChanged = Signal()
    systemChanged = Signal()
    uptimeChanged = Signal()
    toastRequested = Signal(str, str, str)

    settingsEdited = Signal(dict)
    toggleRequested = Signal()
    testRequested = Signal(object)
    autostartRequested = Signal(bool)
    hideRequested = Signal(bool)
    openLogsRequested = Signal()
    exportLogsRequested = Signal()

    def __init__(self, settings, log_dir, parent=None):
        super().__init__(parent)
        self._status_key = "waiting"
        self._status_title = "正在检测手柄"
        self._status_detail = ""
        self._action_text = "启动桥接"
        self._action_enabled = False
        self._mode = None
        self._connected = False
        self._left = 0.0
        self._right = 0.0
        self._testable = False
        self._testing = None
        self._tray = False

        self._grip_enabled = settings.grip_enabled
        self._grip_gain = round(settings.grip_gain * 100)
        self._grip_gain_left = round(settings.grip_gain_left * 100)
        self._grip_gain_right = round(settings.grip_gain_right * 100)
        self._grip_soft = settings.grip_soft
        self._haptic_profile = getattr(settings, "haptic_profile", DEFAULT_PROFILE)
        self._reduce_motion = getattr(settings, "reduce_motion", False)
        self._audio_guard = settings.audio_guard
        self._hide_physical = settings.hide_physical
        self._autostart = False

        self._ds5_state = "检查中"
        self._ds5_detail = "usbip · 127.0.0.1:3240"
        self._sensa_state = "未检测"
        self._grip_ready = True
        self._hide_warning = ""
        self._uptime = ""
        self._log_dir = str(log_dir)
        self._version = __version__

    # ---- 只读状态 ----

    @Property(str, notify=statusChanged)
    def statusKey(self):
        return self._status_key

    @Property(str, notify=statusChanged)
    def statusTitle(self):
        return self._status_title

    @Property(str, notify=statusChanged)
    def statusDetail(self):
        return self._status_detail

    @Property(str, notify=statusChanged)
    def statusColor(self):
        return STATUS_COLORS.get(self._status_key, STATUS_COLORS["waiting"])

    @Property(str, notify=statusChanged)
    def actionText(self):
        return self._action_text

    @Property(bool, notify=statusChanged)
    def actionEnabled(self):
        return self._action_enabled

    @Property(str, notify=modeChanged)
    def modeLabel(self):
        return MODE_LABELS.get(self._mode, "未检测")

    @Property(bool, notify=connectedChanged)
    def connected(self):
        return self._connected

    @Property(float, notify=meterChanged)
    def leftLevel(self):
        return self._left

    @Property(float, notify=meterChanged)
    def rightLevel(self):
        return self._right

    @Property(bool, notify=testChanged)
    def testable(self):
        return self._testable

    @Property(str, notify=testChanged)
    def testing(self):
        return self._testing or ""

    @Property(bool, notify=systemChanged)
    def trayAvailable(self):
        return self._tray

    @Property(str, notify=systemChanged)
    def ds5State(self):
        return self._ds5_state

    @Property(str, notify=systemChanged)
    def ds5Detail(self):
        return self._ds5_detail

    @Property(str, notify=systemChanged)
    def sensaState(self):
        return self._sensa_state

    @Property(bool, notify=systemChanged)
    def gripReady(self):
        # 雷云/Sensa 还没认出握把时，震动测试按下去也不会有输出，界面要如实反映。
        return self._grip_ready

    @Property(str, notify=systemChanged)
    def hideWarning(self):
        return self._hide_warning

    @Property(str, notify=uptimeChanged)
    def uptime(self):
        return self._uptime

    @Property(str, notify=settingsChanged)
    def logDirectory(self):
        return self._log_dir

    @Property(str, constant=True)
    def version(self):
        return self._version

    # ---- 设置 ----

    @Property(bool, notify=settingsChanged)
    def gripEnabled(self):
        return self._grip_enabled

    @Property(int, notify=settingsChanged)
    def gripGainPercent(self):
        return self._grip_gain

    @Property(int, notify=settingsChanged)
    def gripGainLeftPercent(self):
        return self._grip_gain_left

    @Property(int, notify=settingsChanged)
    def gripGainRightPercent(self):
        return self._grip_gain_right

    @Property(bool, notify=settingsChanged)
    def gripSoft(self):
        return self._grip_soft

    @Property(str, notify=settingsChanged)
    def hapticProfile(self):
        return self._haptic_profile

    @Property(bool, notify=settingsChanged)
    def reduceMotion(self):
        return self._reduce_motion

    @Property(bool, notify=settingsChanged)
    def audioGuard(self):
        return self._audio_guard

    @Property(bool, notify=settingsChanged)
    def hidePhysical(self):
        return self._hide_physical

    @Property(bool, notify=settingsChanged)
    def autostart(self):
        return self._autostart

    # ---- App 调用 ----

    def apply_status(self, key, title, detail, action, enabled):
        self._status_key, self._status_title = key, title
        self._status_detail, self._action_text = detail, action
        self._action_enabled = enabled
        self.statusChanged.emit()

    def set_mode(self, mode):
        if mode != self._mode:
            self._mode = mode
            self.modeChanged.emit()

    def set_connected(self, connected):
        if connected != self._connected:
            self._connected = connected
            self.connectedChanged.emit()

    def set_meter(self, message):
        motors = message.get("motors", ())
        left = max(0.0, min(1.0, float(motors[0]))) if len(motors) > 0 else 0.0
        right = max(0.0, min(1.0, float(motors[1]))) if len(motors) > 1 else 0.0
        if abs(left - self._left) < 0.002 and abs(right - self._right) < 0.002:
            return  # 电平跳动很小，减少无意义的界面刷新。
        self._left, self._right = left, right
        self.meterChanged.emit()

    def set_testable(self, testable):
        if testable != self._testable:
            self._testable = testable
            if not testable:
                self._testing = None
            self.testChanged.emit()

    def set_testing(self, target):
        if target != self._testing:
            self._testing = target
            self.testChanged.emit()

    def set_ds5(self, state, detail=None):
        self._ds5_state = state
        if detail is not None:
            self._ds5_detail = detail
        self.systemChanged.emit()

    def set_sensa(self, state):
        self._sensa_state = state
        self.systemChanged.emit()

    def set_grip_ready(self, ready):
        if ready != self._grip_ready:
            self._grip_ready = ready
            self.systemChanged.emit()

    def set_hide_warning(self, warning):
        self._hide_warning = HIDE_WARNINGS.get(warning, "")
        self.systemChanged.emit()

    def set_uptime(self, uptime):
        if uptime != self._uptime:
            self._uptime = uptime
            self.uptimeChanged.emit()

    def set_tray_available(self, available):
        self._tray = available
        self.systemChanged.emit()

    def apply_settings(self, settings):
        values = (settings.grip_enabled, round(settings.grip_gain * 100),
                  round(settings.grip_gain_left * 100), round(settings.grip_gain_right * 100),
                  settings.grip_soft, getattr(settings, "haptic_profile", DEFAULT_PROFILE),
                  getattr(settings, "reduce_motion", False),
                  settings.audio_guard, settings.hide_physical)
        current = (self._grip_enabled, self._grip_gain, self._grip_gain_left, self._grip_gain_right,
                   self._grip_soft, self._haptic_profile, self._reduce_motion, self._audio_guard,
                   self._hide_physical)
        if values != current:
            (self._grip_enabled, self._grip_gain, self._grip_gain_left, self._grip_gain_right,
             self._grip_soft, self._haptic_profile, self._reduce_motion, self._audio_guard,
             self._hide_physical) = values
            self.settingsChanged.emit()

    def set_autostart(self, enabled):
        if enabled != self._autostart:
            self._autostart = enabled
            self.settingsChanged.emit()

    def set_hide_physical(self, enabled):
        if enabled != self._hide_physical:
            self._hide_physical = enabled
            self.settingsChanged.emit()

    def show_toast(self, kind, title, content):
        self.toastRequested.emit(kind, title, content)

    # ---- QML 调用 ----

    @Slot(bool)
    def setGripEnabled(self, value):
        self._grip_enabled = value
        self.settingsChanged.emit()
        self.settingsEdited.emit({"grip_enabled": value})

    @Slot(int)
    def setGripGain(self, percent):
        percent = max(0, min(150, int(percent)))
        # 界面只保留一个总强度；桥接仍按左右分路计算，这里同步两侧，避免旧值残留。
        self._grip_gain = percent
        self._grip_gain_left = percent
        self._grip_gain_right = percent
        self.settingsChanged.emit()
        self.settingsEdited.emit({"grip_gain": percent / 100,
                                  "grip_gain_left": percent / 100,
                                  "grip_gain_right": percent / 100})

    @Slot(int)
    def setGripGainLeft(self, percent):
        percent = max(0, min(150, int(percent)))
        self._grip_gain_left = percent
        self.settingsChanged.emit()
        self.settingsEdited.emit({"grip_gain_left": percent / 100})

    @Slot(int)
    def setGripGainRight(self, percent):
        percent = max(0, min(150, int(percent)))
        self._grip_gain_right = percent
        self.settingsChanged.emit()
        self.settingsEdited.emit({"grip_gain_right": percent / 100})

    @Slot(bool)
    def setGripSoft(self, value):
        self._grip_soft = value
        self.settingsChanged.emit()
        self.settingsEdited.emit({"grip_soft": value})

    @Slot(str)
    def setHapticProfile(self, value):
        if value not in PROFILES:
            return
        self._haptic_profile = value
        self.settingsChanged.emit()
        self.settingsEdited.emit({"haptic_profile": value})

    @Slot(bool)
    def setReduceMotion(self, value):
        self._reduce_motion = value
        self.settingsChanged.emit()
        self.settingsEdited.emit({"reduce_motion": value})

    @Slot(bool)
    def setAudioGuard(self, value):
        self._audio_guard = value
        self.settingsChanged.emit()
        self.settingsEdited.emit({"audio_guard": value})

    @Slot(bool)
    def setHidePhysical(self, value):
        self._hide_physical = value
        self.settingsChanged.emit()
        self.hideRequested.emit(value)

    @Slot(bool)
    def setAutostart(self, value):
        self._autostart = value
        self.settingsChanged.emit()
        self.autostartRequested.emit(value)

    @Slot()
    def toggleBridge(self):
        self.toggleRequested.emit()

    @Slot()
    def requestTest(self):
        if not self._testable:
            return
        self.testRequested.emit(None if self._testing == "grip" else "grip")

    @Slot()
    def openLogs(self):
        self.openLogsRequested.emit()

    @Slot()
    def exportLogs(self):
        self.exportLogsRequested.emit()
