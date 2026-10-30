"""复用雷云安装器的启动入口；启动成功不代表 Sensa 已经可用，握把能不能震以雷蛇自己的日志为准。"""
import datetime
import json
import os
import re
from pathlib import Path

import psutil

# HapticService 用 "2636-{ContainerId}" 标识 PC 模式手柄（PID 0x0A4C）；共享内存服务开机就在跑，
# 能打开它不代表雷云已经把手柄交给它，只有 DeviceAdded 才算数。
ADDED, REMOVED = 'DeviceAdded "2636-{', 'DeviceRemoved "2636-{'
# 新的服务进程或与雷云失联后，之前登记的设备都作废，要等雷云重新 DeviceAdded。
RESETS = ("Establishing connection", "RpcPing failed")
# 雷云断网启动时只在 dashboard 日志里记这一行，界面上不提示，也不会加载手柄。
OFFLINE = "No internet connection found"
LISTED = "devices shown in dashboard [{"
DASHBOARD_TIME = re.compile(r"\[(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d)")
TAIL_BYTES = 1 << 20


def find_shortcut():
    for variable in ("PROGRAMDATA", "APPDATA"):
        directory = os.environ.get(variable)
        if directory:
            programs = Path(directory) / "Microsoft/Windows/Start Menu/Programs"
            for shortcut in programs.rglob("Razer Synapse*.lnk"):
                if shortcut.stem.lower() in ("razer synapse", "razer synapse 3", "razer synapse 4"):
                    return shortcut
    return None


def synapse_processes():
    # App Engine 也承载 Chroma；只认 Synapse 进程或明确的 Synapse 启动参数。
    for process in psutil.process_iter(attrs=("name", "cmdline", "create_time")):
        try:
            name = (process.info.get("name") or "").lower()
            command = " ".join(process.info.get("cmdline") or []).lower()
        except psutil.Error:
            continue
        if (name in ("razer synapse 3.exe", "razer synapse.exe")
                or "apps=synapse" in command or "--razer-page-name=win-synapse" in command):
            yield process.info


def is_running():
    return any(True for _ in synapse_processes())


def started_at():
    """这次雷云的启动时间（最早的 Synapse 进程）；没在运行时返回 None。"""
    times = [info.get("create_time") for info in synapse_processes()]
    times = [value for value in times if value]
    return datetime.datetime.fromtimestamp(min(times)) if times else None


def device_registered(lines):
    """HapticService 日志里手柄的最新登记状态；日志里没有任何依据时返回 None。"""
    registered = None
    for line in lines:
        if any(reset in line for reset in RESETS):
            registered = False
        elif ADDED in line:
            registered = True
        elif REMOVED in line:
            registered = False
    return registered


def offline_since(lines, started):
    """雷云这次启动后是否进了离线模式；之后又列出了设备就算已经恢复。"""
    started = started.replace(microsecond=0)
    offline = False
    for line in lines:
        match = DASHBOARD_TIME.match(line)
        if not match or datetime.datetime.strptime(match[1], "%Y/%m/%d %H:%M:%S") < started:
            continue
        if OFFLINE in line:
            offline = True
        elif LISTED in line:
            offline = False
    return offline


def tail_lines(path, size=TAIL_BYTES):
    with open(path, "rb") as file:
        file.seek(0, os.SEEK_END)
        file.seek(max(0, file.tell() - size))
        return file.read().decode("utf-8", "replace").splitlines()


def dashboard_offline(directory, started):
    try:
        latest = max(Path(directory).glob("dashboard*.log"), key=lambda path: path.stat().st_mtime)
        return offline_since(tail_lines(latest), started)
    except (OSError, ValueError):
        return False


def diagnose(haptic_log=None, dashboard_dir=None):
    """握把为什么还不能震：ready / stopped（雷云没运行）/ offline（雷云离线，没加载手柄）/
    unregistered（雷云在线但还没认出手柄）；读不到雷蛇日志时返回 unknown，交回桥接自己的判断。"""
    if haptic_log is None:
        haptic_log = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                          "Razer/RazerAppEngine/Logs/RzInterHaptics-HapticService.log")
    if dashboard_dir is None:
        dashboard_dir = Path(os.environ.get("LOCALAPPDATA", ""), "Razer/RazerAppEngine/User Data/Logs")
    try:
        registered = device_registered(tail_lines(haptic_log))
    except OSError:
        return "unknown"
    if registered is None:
        return "unknown"
    if registered:
        return "ready"
    started = started_at()
    if started is None:
        return "stopped"
    return "offline" if dashboard_offline(dashboard_dir, started) else "unregistered"


def ensure_running():
    if is_running():
        return "running"
    shortcut = find_shortcut()
    if shortcut is None:
        return "missing"
    os.startfile(str(shortcut), show_cmd=0)
    return "started"
