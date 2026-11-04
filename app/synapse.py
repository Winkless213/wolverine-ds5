"""复用雷云安装器的启动入口；启动成功不代表 Sensa 已经可用，握把能不能震以雷蛇自己的日志为准。"""
import datetime
import json
import os
import re
import subprocess
import time
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
# 拉起雷云后的观察窗口：startfile 成功不代表引擎站住，实测见过它 6 秒后自己退出。
START_TIMEOUT = 8.0
START_STABLE = 2.0
START_POLL = .5
# 雷云 4 在部分机器上只认管理员启动：普通权限拉起的引擎一秒内就退出（退出码 9，不写日志）。
# 安装时注册的同名计划任务以最高权限代跑，触发它本身不需要 UAC。
TASK_NAME = "WolverineDS5-RazerSynapse"
TASK_TIMEOUT = 15.0
TASK_REGISTER_TIMEOUT = 10.0
CREATE_NO_WINDOW = 0x08000000


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


def launcher_path():
    """雷云启动器（版本无关的入口，任务里存的就是这个路径）。"""
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if not base:
            continue
        path = Path(base) / "Razer/RazerAppEngine/RazerAppEngine.exe"
        if path.exists():
            return path
    return None


def task_registered(run=None):
    run = run or subprocess.run
    try:
        done = run(["schtasks.exe", "/query", "/tn", TASK_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=TASK_TIMEOUT, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


def _run_as_admin(executable, arguments):
    """走一次 UAC 拉起可执行文件；用户点取消时返回 False（ShellExecuteW 返回 <=32）。"""
    import ctypes

    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, arguments, None, 0)
    return code > 32


def register_task(run=None, elevate=None, wait=None):
    """建一个最高权限的登录任务，让雷云以后不用 UAC 也能被唤醒。

    只在「普通快捷方式拉不起来」时才建；用户点取消就返回 False，交回原来的失败提示。
    """
    run = run or subprocess.run
    elevate = elevate or _run_as_admin
    wait = wait or time.sleep
    if task_registered(run):
        return True
    launcher = launcher_path()
    if launcher is None:
        return False
    arguments = (f'/create /tn "{TASK_NAME}" /tr "\\"{launcher}\\" --url-params=apps=synapse" '
                 f'/sc onlogon /rl HIGHEST /f')
    if not elevate("schtasks.exe", arguments):
        return False
    for _ in range(int(TASK_REGISTER_TIMEOUT / START_POLL)):
        wait(START_POLL)
        if task_registered(run):
            return True
    return task_registered(run)


def delete_task(run=None):
    """卸载时删掉最高权限任务；任务不存在也算成功。"""
    run = run or subprocess.run
    try:
        done = run(["schtasks.exe", "/delete", "/tn", TASK_NAME, "/f"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=TASK_TIMEOUT, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0 or not task_registered(run)


def trigger_task(run=None):
    """用计划任务拉起雷云；没注册任务或调用失败时返回 False，交回普通快捷方式。

    不接管道：任务拉起的雷云会继承句柄，管道永远等不到 EOF，实测能把整个检查线程卡死。
    超时只说明没等到 schtasks 退出，任务可能已经提交，能不能站住交给 settled 判断。
    """
    run = run or subprocess.run
    try:
        done = run(["schtasks.exe", "/run", "/tn", TASK_NAME],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=TASK_TIMEOUT, creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


def settled(probe, wait, clock):
    """引擎出现后要连续站住 START_STABLE 秒才算数；闪一下就退出的不报启动成功。"""
    seen = None
    deadline = clock() + START_TIMEOUT
    while clock() < deadline:
        wait(START_POLL)
        now = clock()
        if not probe():
            seen = None  # 起来了又退出，继续等到期限再下结论
            continue
        seen = now if seen is None else seen
        if now - seen >= START_STABLE:
            return True
    return bool(probe())


def ensure_running(wait=None, clock=None, probe=None, trigger=None, register=None):
    """启动雷云并确认它真的站住：startfile 成功只代表拉起了入口，引擎可能几秒后自己退出。

    顺序：计划任务（免 UAC）→ 开始菜单快捷方式 → 建计划任务后重试（会弹一次 UAC）。
    返回 running（本来就在跑）/ started（拉起并稳定住）/ failed（拉起了又退出）/ missing（没装）。
    """
    wait = wait or time.sleep
    clock = clock or time.monotonic
    probe = probe or is_running
    trigger = trigger or trigger_task
    register = register or register_task
    if probe():
        return "running"
    if trigger() and settled(probe, wait, clock):
        return "started"
    shortcut = find_shortcut()
    if shortcut is None:
        return "missing"
    os.startfile(str(shortcut), show_cmd=0)
    if settled(probe, wait, clock):
        return "started"
    # 实测：雷云 4 在部分机器上普通权限拉起后一秒内自杀（退出码 9）。这时补一个最高权限任务，
    # 之后每次唤醒都走任务、不再弹 UAC；用户取消授权就当普通失败处理。
    if register() and trigger() and settled(probe, wait, clock):
        return "started"
    return "failed"
