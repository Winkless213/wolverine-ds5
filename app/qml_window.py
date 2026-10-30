"""Qt Quick 主窗口：加载 ui/main.qml，并把窗口生命周期信号转给 App。"""
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal  # noqa: F401
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from app import core

# 内置 Roboto 只有拉丁字形；不显式给中文回退，Qt 会落到宋体（细、带衬线）。
# QML 的 font 值类型（6.12）没有 families 属性，回退链只能挂在应用默认字体上，
# 因此 QML 侧不再逐项设置 font.family，否则会把回退链覆盖成单一 Roboto。
FONT_FILES = ("Roboto-Regular.ttf", "Roboto-Medium.ttf", "Roboto-Bold.ttf")
FONT_STACK = ["Roboto", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"]
_fonts_ready = False


def install_ui_fonts(root=None):
    """注册内置字体并设置带中文回退的应用默认字体。"""
    global _fonts_ready
    if _fonts_ready:
        return
    root = Path(root) if root is not None else core.root_dir()
    font_dir = root / "ui" / "assets" / "fonts"
    for name in FONT_FILES:
        QFontDatabase.addApplicationFont(str(font_dir / name))
    font = QGuiApplication.font()
    font.setFamilies(FONT_STACK)
    QGuiApplication.setFont(font)
    _fonts_ready = True


class QmlWindow(QObject):
    shown = Signal()
    hidden = Signal()
    quit_requested = Signal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.quitting = False
        self.tray_available = False
        self.model = model
        QQuickWindow.setTextRenderType(QQuickWindow.TextRenderType.NativeTextRendering)
        install_ui_fonts()
        self.engine = QQmlApplicationEngine()
        self.engine.setInitialProperties({"appModel": model})
        path = core.root_dir() / "ui" / "main.qml"
        self.engine.load(QUrl.fromLocalFile(str(path)))
        roots = self.engine.rootObjects()
        if not roots:
            raise RuntimeError(f"无法加载 QML 界面：{path}")
        self.root = roots[0]
        for name in ("navBar", "statusPage", "systemPage"):
            child = self.root.findChild(QObject, name)
            if child is not None:
                child.setProperty("appModel", model)
        self.root.visibleChanged.connect(self._visible_changed)
        self.root.hideRequested.connect(lambda: self.hidden.emit())
        self.root.quitRequested.connect(lambda: self.quit_requested.emit())

    def _visible_changed(self):
        if self.root.isVisible():
            self.shown.emit()
        else:
            self.hidden.emit()

    def show(self):
        self.root.showNormal()
        self.root.requestActivate()

    def showNormal(self):
        self.show()

    def raise_(self):
        self.root.raise_()

    def activateWindow(self):
        self.root.requestActivate()

    def isVisible(self):
        return self.root.isVisible()

    def hide(self):
        self.root.hide()

    def close(self):
        self.quitting = True
        self.root.setProperty("quitting", True)
        self.root.close()
