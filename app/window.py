"""设置窗口：状态 / 震动 / 设备与系统三页，以及托盘和窗口共用的状态图标。"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, FluentIcon, FluentWindow, IndicatorPosition,
                            NavigationItemPosition, PrimaryPushButton, PushButton, ScrollArea, SettingCard,
                            SettingCardGroup, SimpleCardWidget, Slider, StrongBodyLabel, SubtitleLabel,
                            SwitchButton, TitleLabel, isDarkTheme, setFont, themeColor)

from app import __version__

STATE_COLORS = {"connected": "#16A34A", "waiting": "#D97706", "error": "#DC2626", "stopped": "#6B7280"}
MODE_TEXT = {"bridge": "桥接模式（WinUSB）", "xbox": "Xbox 模式", "pc": "PC 模式（Sensa 握把）",
             "absent": "未检测到手柄", None: "正在检测"}


def draw_status_icon(state, size):
    """透明底上的手柄剪影，颜色表示状态；托盘在深浅任务栏上都能看清。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    s = size / 32
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(STATE_COLORS[state]))
    body = QPainterPath()
    body.addRoundedRect(QRectF(3 * s, 7 * s, 26 * s, 14 * s), 7 * s, 7 * s)
    body.addEllipse(QRectF(2 * s, 12 * s, 10 * s, 15 * s))
    body.addEllipse(QRectF(20 * s, 12 * s, 10 * s, 15 * s))
    painter.drawPath(body.simplified())
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setBrush(Qt.GlobalColor.black)
    painter.drawRect(QRectF(6 * s, 13 * s, 6 * s, 2 * s))
    painter.drawRect(QRectF(8 * s, 11 * s, 2 * s, 6 * s))
    for x, y in ((22, 12), (22, 16), (20, 14), (24, 14)):
        painter.drawEllipse(QPointF(x * s, y * s), 1.1 * s, 1.1 * s)
    painter.end()
    return pixmap


def status_icon(state):
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64):
        icon.addPixmap(draw_status_icon(state, size))
    return icon


def palette():
    """自绘控件的文字色与底色，跟随深浅主题。"""
    return (QColor(255, 255, 255, 200), QColor(255, 255, 255, 24)) if isDarkTheme() \
        else (QColor(0, 0, 0, 190), QColor(0, 0, 0, 18))


class Meter(QWidget):
    """四路马达电平条。"""

    LABELS = ("左握把", "右握把", "左扳机", "右扳机")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = [0, 0, 0, 0]
        self.setMinimumHeight(112)
        setFont(self, 13)

    def set_values(self, values):
        if values != self.values:
            self.values = list(values)
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text, track = palette()
        row = self.height() / 4
        for index, (label, value) in enumerate(zip(self.LABELS, self.values)):
            y = index * row
            painter.setPen(text)
            painter.drawText(QRectF(0, y, 64, row), Qt.AlignmentFlag.AlignVCenter, label)
            painter.drawText(QRectF(self.width() - 48, y, 48, row),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{round(value * 100)}%")
            bar = QRectF(72, y + row / 2 - 4, self.width() - 132, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, 4, 4)
            if value > 0:
                painter.setBrush(themeColor())
                painter.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * min(1, value), bar.height()), 4, 4)


class InputView(QWidget):
    """手柄实时输入示意图：按实体 Xbox 键位摆放，按下的键高亮。"""

    WIDTH, HEIGHT = 560, 175
    # (键名, 位掩码, 中心 x, 中心 y, 半径)，位掩码与 sdl_input.input_state 一致
    BUTTONS = (("Y", 0x80, 450, 78, 11), ("A", 0x20, 450, 122, 11), ("X", 0x10, 428, 100, 11),
               ("B", 0x40, 472, 100, 11), ("", 0x20000, 240, 70, 6), ("", 0x10000, 280, 62, 10),
               ("", 0x2000, 320, 70, 6))
    DPAD = ((1, 0, -1), (2, 0, 1), (4, -1, 0), (8, 1, 0))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = {"l2": 0, "r2": 0, "buttons": 0, "dpad": 0, "sticks": [0, 0, 0, 0]}
        self.setMinimumHeight(self.HEIGHT)
        setFont(self, 12)

    def set_state(self, message):
        state = {key: message.get(key, self.state[key]) for key in self.state}
        if state != self.state:
            self.state = state
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / self.WIDTH, self.height() / self.HEIGHT)
        painter.translate((self.width() - self.WIDTH * scale) / 2, (self.height() - self.HEIGHT * scale) / 2)
        painter.scale(scale, scale)
        text, track = palette()
        accent = themeColor()
        # 深色主题的主题色偏亮，高亮处配深色字；浅色主题反之。
        on_accent = QColor("black") if isDarkTheme() else QColor("white")
        buttons, sticks = self.state["buttons"], self.state["sticks"]

        def fill(on):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent if on else track)

        for x, label, value, bumper in ((40, "LT", self.state["l2"], 0x100), (410, "RT", self.state["r2"], 0x200)):
            fill(False)
            painter.drawRoundedRect(QRectF(x, 8, 110, 14), 7, 7)
            if value:
                fill(True)
                painter.drawRoundedRect(QRectF(x, 8, 110 * value / 255, 14), 7, 7)
            fill(buttons & bumper)
            painter.drawRoundedRect(QRectF(x, 30, 110, 14), 7, 7)
            painter.setPen(on_accent if value >= 128 else text)
            painter.drawText(QRectF(x, 8, 110, 14), Qt.AlignmentFlag.AlignCenter, f"{label} {value}")
            painter.setPen(on_accent if buttons & bumper else text)
            painter.drawText(QRectF(x, 30, 110, 14), Qt.AlignmentFlag.AlignCenter, "LB" if x < 280 else "RB")

        for cx, cy, radius, sx, sy, click in ((110, 100, 34, sticks[0], sticks[1], 0x4000),
                                              (360, 135, 28, sticks[2], sticks[3], 0x8000)):
            fill(buttons & click)
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
            painter.setBrush(text)
            reach = radius - 8
            painter.drawEllipse(QPointF(cx + sx / 128 * reach, cy + sy / 128 * reach), 6, 6)

        for mask, dx, dy in self.DPAD:
            fill(self.state["dpad"] & mask)
            painter.drawRoundedRect(QRectF(200 + dx * 14 - 7, 135 + dy * 14 - 7, 14, 14), 3, 3)

        for label, mask, x, y, radius in self.BUTTONS:
            fill(buttons & mask)
            painter.drawEllipse(QPointF(x, y), radius, radius)
            if label:
                painter.setPen(on_accent if buttons & mask else text)
                painter.drawText(QRectF(x - radius, y - radius, 2 * radius, 2 * radius),
                                 Qt.AlignmentFlag.AlignCenter, label)


class SwitchCard(SettingCard):
    def __init__(self, icon, title, content, checked, parent=None):
        super().__init__(icon, title, content, parent)
        self.switch = SwitchButton(self, IndicatorPosition.RIGHT)
        self.switch.setOnText("开")
        self.switch.setOffText("关")
        self.switch.setChecked(checked)
        self.hBoxLayout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class SliderCard(SettingCard):
    """滑块按百分比整数显示；数值本身是 0–1.5 的小数。"""

    def __init__(self, icon, title, content, value, maximum, parent=None):
        super().__init__(icon, title, content, parent)
        self.slider = Slider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, maximum)
        self.slider.setMinimumWidth(240)
        self.value_label = BodyLabel(self)
        self.value_label.setMinimumWidth(44)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(lambda percent: self.value_label.setText(f"{percent}%"))
        self.slider.setValue(round(value * 100))
        self.value_label.setText(f"{self.slider.value()}%")
        self.hBoxLayout.addWidget(self.value_label, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self.slider, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class TestCard(SettingCard):
    """进入测试后由 LT / RT 的按压深度驱动这一组马达，再点一次结束。"""

    def __init__(self, title, idle, active, parent=None):
        super().__init__(FluentIcon.PLAY, title, idle, parent)
        self.idle, self.active = idle, active
        self.button = PushButton("开始测试", self)
        self.button.setEnabled(False)
        self.hBoxLayout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def set_active(self, active):
        self.button.setText("结束测试" if active else "开始测试")
        self.setContent(self.active if active else self.idle)


class Page(ScrollArea):
    def __init__(self, name, title, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.view = QWidget(self)
        self.column = QVBoxLayout(self.view)
        self.column.setContentsMargins(36, 20, 36, 36)
        self.column.setSpacing(20)
        self.column.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.column.addWidget(TitleLabel(title, self.view))
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

    def card(self, title, widget):
        card = SimpleCardWidget(self.view)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(StrongBodyLabel(title, card))
        layout.addWidget(widget)
        self.column.addWidget(card)
        return card


class StatusPage(Page):
    toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("status", "状态", parent)
        header = SimpleCardWidget(self.view)
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        self.icon = QLabel(header)
        self.icon.setFixedSize(48, 48)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = SubtitleLabel("正在检测手柄", header)
        self.detail = CaptionLabel("", header)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        self.uptime = BodyLabel("", header)
        self.toggle = PushButton("停止桥接", header)
        self.toggle.clicked.connect(self.toggle_requested)
        row.addWidget(self.icon)
        row.addLayout(text, 1)
        row.addWidget(self.uptime)
        row.addWidget(self.toggle)
        self.column.addWidget(header)

        self.motors = Meter(self.view)
        self.card("马达输出", self.motors)
        self.inputs = InputView(self.view)
        self.card("手柄输入", self.inputs)

        group = SettingCardGroup("设备", self.view)
        self.ds5_card = SettingCard(FluentIcon.GAME, "虚拟 DualSense", "正在检查", group)
        self.mode_card = SettingCard(FluentIcon.CONNECT, "手柄驱动", "正在检测", group)
        group.addSettingCard(self.ds5_card)
        group.addSettingCard(self.mode_card)
        self.column.addWidget(group)
        self.column.addStretch(1)

    def show_state(self, key, title, detail, action, action_enabled):
        self.icon.setPixmap(status_icon(key).pixmap(48, 48))
        self.title.setText(title)
        self.detail.setText(detail)
        self.toggle.setText(action)
        self.toggle.setEnabled(action_enabled)

    def meter(self, message):
        self.motors.set_values(message.get("motors", self.motors.values))
        self.inputs.set_state(message)

    def clear(self):
        self.meter({"motors": [0, 0, 0, 0], "l2": 0, "r2": 0, "buttons": 0, "dpad": 0, "sticks": [0, 0, 0, 0]})


class VibrationPage(Page):
    changed = Signal(dict)
    test_requested = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__("vibration", "震动", parent)
        grip = SettingCardGroup("握把马达", self.view)
        self.grip_enabled = SwitchCard(FluentIcon.GAME, "握把震动", "左右握把的大马达", settings.grip_enabled, grip)
        self.grip_gain = SliderCard(FluentIcon.SPEED_HIGH, "握把强度", "100% 为默认强度",
                                    settings.grip_gain, 150, grip)
        self.grip_soft = SwitchCard(FluentIcon.MIX_VOLUMES, "柔和握把", "按雷蛇自带的音频震动参数压低高频，仅 PC 模式",
                                    settings.grip_soft, grip)
        for card in (self.grip_enabled, self.grip_gain, self.grip_soft):
            grip.addSettingCard(card)
        self.grip_test = TestCard("测试握把", "按 LT / RT 分别震左 / 右握把，按得越深越强",
                                  "测试中：按 LT 震左握把、RT 震右握把；游戏震动与扳机马达已暂停", grip)
        grip.addSettingCard(self.grip_test)

        trigger = SettingCardGroup("扳机马达", self.view)
        self.trigger_enabled = SwitchCard(FluentIcon.GAME, "扳机震动", "LT / RT 里的小马达",
                                          settings.trigger_enabled, trigger)
        self.trigger_gain = SliderCard(FluentIcon.SPEED_HIGH, "扳机强度", "100% 为游戏原始强度",
                                       settings.trigger_gain, 150, trigger)
        self.trigger_resistance = SwitchCard(FluentIcon.SYNC, "扳机阻力转震动",
                                             "DualSense 的扳机阻力效果改用马达模拟；马达只能硬震，默认关闭",
                                             settings.trigger_resistance, trigger)
        self.trigger_follow = SwitchCard(FluentIcon.LINK, "扳机跟随握把", "扳机马达同时跟随同侧握把震动，取两者较大值",
                                         settings.trigger_follow, trigger)
        self.follow_ratio = SliderCard(FluentIcon.MIX_VOLUMES, "跟随比例", "相对同侧握把的强度",
                                       settings.follow_ratio, 100, trigger)
        for card in (self.trigger_enabled, self.trigger_gain, self.trigger_resistance, self.trigger_follow,
                     self.follow_ratio):
            trigger.addSettingCard(card)
        self.trigger_test = TestCard("测试扳机", "按 LT / RT 分别震左 / 右扳机，按得越深越强",
                                     "测试中：按 LT 震左扳机、RT 震右扳机；游戏震动与握把马达已暂停", trigger)
        trigger.addSettingCard(self.trigger_test)
        self.pc_mode = False
        for group in (grip, trigger):
            self.column.addWidget(group)
        self.column.addStretch(1)

        self.testing = None
        for target, card in (("grip", self.grip_test), ("trigger", self.trigger_test)):
            # 同一时间只测一组：点另一组直接切过去，再点当前组结束测试。
            card.button.clicked.connect(
                lambda _=False, target=target: self.test_requested.emit(None if self.testing == target else target))

        for key in ("grip_enabled", "grip_soft", "trigger_enabled", "trigger_resistance", "trigger_follow"):
            getattr(self, key).switch.checkedChanged.connect(lambda checked, key=key: self._emit(key, checked))
        for key in ("grip_gain", "trigger_gain", "follow_ratio"):
            getattr(self, key).slider.valueChanged.connect(lambda percent, key=key: self._emit(key, percent / 100))
        self._sync()

    def _emit(self, key, value):
        self._sync()
        self.changed.emit({key: value})

    def _sync(self):
        grip, trigger = self.grip_enabled.switch.isChecked(), self.trigger_enabled.switch.isChecked()
        self.grip_gain.setEnabled(grip)
        self.grip_soft.setEnabled(grip)
        self.trigger_enabled.setEnabled(not self.pc_mode)
        trigger = trigger and not self.pc_mode
        for card in (self.trigger_gain, self.trigger_resistance, self.trigger_follow):
            card.setEnabled(trigger)
        self.follow_ratio.setEnabled(trigger and self.trigger_follow.switch.isChecked())

    def set_pc_mode(self, pc_mode):
        # PC 模式的 XInput 只接受左右两路强度，扳机马达物理上收不到指令；设置保留，回到 Xbox 模式时照常生效。
        self.pc_mode = pc_mode
        self.trigger_test.idle = ("PC 模式下扳机马达不可用，切到 Xbox 模式才能使用" if pc_mode
                                  else "按 LT / RT 分别震左 / 右扳机，按得越深越强")
        self.trigger_test.set_active(self.testing == "trigger")
        self._sync()

    def set_testable(self, enabled):
        self.grip_test.button.setEnabled(enabled)
        self.trigger_test.button.setEnabled(enabled and not self.pc_mode)

    def set_test(self, target):
        self.testing = target
        self.grip_test.set_active(target == "grip")
        self.trigger_test.set_active(target == "trigger")


HIDE_TEXT = "运行时对游戏隐藏战狼，退出时自动恢复；下次启动自动重新隐藏。需要 HidHide"
HIDE_WARNINGS = {"port": "手柄接在开启隐藏后没用过的 USB 口，游戏可能又能看到它；请关闭再打开一次",
                 "app": "当前桥接程序还没被 HidHide 放行，读不到被隐藏的手柄；请关闭再打开一次"}


class DevicePage(Page):
    changed = Signal(dict)
    autostart_changed = Signal(bool)
    hide_changed = Signal(bool)
    driver_action = Signal(str)
    open_logs = Signal()

    def __init__(self, settings, autostart, log_dir, parent=None):
        super().__init__("device", "设备与系统", parent)
        self.mode = None
        driver = SettingCardGroup("手柄驱动", self.view)
        self.driver = SettingCard(FluentIcon.CONNECT, "驱动模式", "正在检测", driver)
        self.driver_button = PrimaryPushButton("切换", self.driver)
        self.driver_button.clicked.connect(
            lambda: self.driver_action.emit("xbox" if self.mode == "bridge" else "bridge"))
        self.driver.hBoxLayout.addWidget(self.driver_button, 0, Qt.AlignmentFlag.AlignRight)
        self.driver.hBoxLayout.addSpacing(16)
        driver.addSettingCard(self.driver)

        system = SettingCardGroup("系统", self.view)
        self.autostart = SwitchCard(FluentIcon.POWER_BUTTON, "开机自启", "登录后在托盘静默启动", autostart, system)
        self.audio_guard = SwitchCard(FluentIcon.SPEAKERS, "默认音频自动切回",
                                      "虚拟 DualSense 抢成默认音频设备时切回原设备，避免游戏声音让握把一直震",
                                      settings.audio_guard, system)
        self.hide_physical = SwitchCard(FluentIcon.HIDE, "对游戏隐藏实体手柄", HIDE_TEXT,
                                        settings.hide_physical, system)
        self.logs = SettingCard(FluentIcon.FOLDER, "日志", str(log_dir), system)
        logs_button = PushButton("打开目录", self.logs)
        logs_button.clicked.connect(self.open_logs)
        self.logs.hBoxLayout.addWidget(logs_button, 0, Qt.AlignmentFlag.AlignRight)
        self.logs.hBoxLayout.addSpacing(16)
        for card in (self.autostart, self.audio_guard, self.hide_physical, self.logs):
            system.addSettingCard(card)

        about = SettingCardGroup("关于", self.view)
        about.addSettingCard(SettingCard(FluentIcon.INFO, f"Wolverine DS5 {__version__}",
                                         "把 Razer Wolverine V3 Pro 呈现为 DualSense：PC 模式左右对称震动，Xbox 模式四马达",
                                         about))
        for group in (driver, system, about):
            self.column.addWidget(group)
        self.column.addStretch(1)

        self.autostart.switch.checkedChanged.connect(self.autostart_changed)
        self.audio_guard.switch.checkedChanged.connect(lambda checked: self.changed.emit({"audio_guard": checked}))
        self.hide_physical.switch.checkedChanged.connect(self.hide_changed)

    def show_mode(self, mode, busy):
        self.mode = mode
        if busy:
            self.driver.setContent("正在切换驱动，请在弹出的窗口中允许管理员权限")
        elif mode == "pc":
            self.driver.setContent("当前：PC 模式，震动经雷蛇 Sensa 输出到左右握把（需 Synapse 运行）；扳机马达仅 Xbox 模式可用")
        elif mode == "bridge":
            self.driver.setContent("当前：桥接模式（WinUSB），游戏里是虚拟 DualSense")
        elif mode == "xbox":
            self.driver.setContent("当前：Xbox 模式，手柄作为普通 Xbox 手柄使用")
        else:
            self.driver.setContent("未检测到手柄，请用数据线连接")
        self.driver_button.setText("还原 Xbox 模式" if mode == "bridge" else "切换到桥接模式")
        self.driver_button.setEnabled(not busy and mode in ("bridge", "xbox"))
        self.driver_button.setHidden(mode == "pc")

    def show_hide_warning(self, warning):
        self.hide_physical.setContent(HIDE_WARNINGS.get(warning, HIDE_TEXT))


class Window(FluentWindow):
    shown = Signal()
    hidden = Signal()
    quit_requested = Signal()

    def __init__(self, settings, autostart, log_dir):
        super().__init__()
        self.quitting = False
        self.tray_available = False
        self.status_page = StatusPage(self)
        self.vibration_page = VibrationPage(settings, self)
        self.device_page = DevicePage(settings, autostart, log_dir, self)
        self.addSubInterface(self.status_page, FluentIcon.HOME, "状态")
        self.addSubInterface(self.vibration_page, FluentIcon.GAME, "震动")
        self.addSubInterface(self.device_page, FluentIcon.SETTING, "设备与系统", NavigationItemPosition.BOTTOM)
        self.setWindowTitle("Wolverine DS5")
        self.setWindowIcon(status_icon("connected"))
        self.resize(960, 720)
        self.setMinimumSize(760, 560)
        screen = self.screen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def showEvent(self, event):
        super().showEvent(event)
        self.shown.emit()

    def closeEvent(self, event):
        # 有托盘时关闭窗口只是隐藏，桥接继续运行；从托盘菜单“退出”才真正结束。
        if self.tray_available and not self.quitting:
            event.ignore()
            self.hide()
            self.hidden.emit()
            return
        if not self.quitting:
            self.quitting = True
            self.quit_requested.emit()
        super().closeEvent(event)
