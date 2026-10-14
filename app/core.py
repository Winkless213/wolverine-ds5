"""托盘程序的非界面逻辑：桥接命令行、状态解析、开机自启、日志轮转、驱动切换脚本。"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

AUTOSTART_NAME = "WolverineDS5"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEVICE_PREFIXES = (r"USB\VID_1532&PID_0A3F", r"USB\VID_1532&PID_0A4C")
PC_PRODUCT = "PID_0A4C"
HIDHIDE_CLI = r"C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe"
# PC 模式下游戏能直接看到的两个接口：XInput（xusb22）与 HID 游戏手柄；其余雷蛇接口（Sensa 私有协议等）不动。
PC_GAMEPAD_PATTERNS = (r"USB\VID_1532&PID_0A4C&MI_00\*", r"HID\VID_1532&PID_0A4C&IG_*")
WINUSB_CLASS = "{88BAE032-5A81-49f0-BC3D-A4FF138216D6}"
XBOX_CLASS = "{05f5cfe2-4733-4950-a6bb-07aad01a3a84}"


def root_dir():
    # 打包后资源在 exe 旁边（onedir 的 _internal 由 PyInstaller 处理）；源码运行时是仓库根目录。
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys._MEIPASS)
    return pathlib.Path(__file__).resolve().parents[1]


def data_dir():
    path = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) / "WolverineDS5"
    (path / "logs").mkdir(parents=True, exist_ok=True)
    return path


def bridge_command(frozen=None, executable=None, root=None, pc=False):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        return [executable, "--bridge"] + (["--pc"] if pc else [])
    # pythonw 没有标准输出句柄，桥接子进程必须用控制台版 python（由 QProcess 隐藏窗口）。
    console = re.sub(r"pythonw\.exe$", "python.exe", executable, flags=re.IGNORECASE)
    return [console, "-u", str((root or root_dir()) / ("pc_bridge.py" if pc else "gip_bridge.py"))]


def parse_line(line):
    text = line.rstrip("\r\n")
    if text.startswith("{"):
        try:
            message = json.loads(text)
        except ValueError:
            message = None
        if isinstance(message, dict) and message.get("type") in ("status", "meter"):
            return message
    return {"type": "log", "text": text}


class BridgeEvents:
    """把桥接的状态序列变成用户关心的通知：首次连接、掉线、重连，不随握手超时反复弹。"""

    def __init__(self, notify):
        self.notify = notify
        self.ever_connected = False
        self.connected = False

    def status(self, state):
        if state == "connected" and not self.connected:
            self.notify("reconnected" if self.ever_connected else "connected")
            self.connected = self.ever_connected = True
        elif state == "lost" and self.connected:
            self.connected = False
            self.notify("lost")


def autostart_command(argv=None):
    argv = argv or ([sys.executable] if getattr(sys, "frozen", False)
                    else [sys.executable.replace("python.exe", "pythonw.exe"), str(root_dir() / "app" / "main.py")])
    return " ".join(f'"{part}"' for part in argv) + " --tray"


def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


def daily_log_path(directory, now=None):
    return pathlib.Path(directory) / f"bridge-{(now or datetime.date.today()).isoformat()}.log"


def prune_logs(directory, keep=7):
    logs = sorted(pathlib.Path(directory).glob("bridge-*.log"))
    for path in logs[:-keep]:
        path.unlink(missing_ok=True)


def usbip_attached(port_output, address="127.0.0.1:3240", busid="1-1"):
    return f"usbip://{address}/{busid}" in port_output


def usbip_ports():
    exe = os.environ.get("GIP_BRIDGE_USBIP_EXE", r"C:\Program Files\USBip\usbip.exe")
    try:
        return subprocess.run([exe, "port"], capture_output=True, text=True, timeout=5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def driver_mode(service, instance=None):
    if not service:
        return "absent"
    if instance and PC_PRODUCT in instance.upper():
        return "pc"
    return "bridge" if service.lower() == "winusb" else "xbox"


def format_duration(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def describe(running, wanted, status, mode):
    """托盘图标和状态页共用：(图标状态, 标题, 说明)。"""
    if not wanted:
        if mode is None:
            return "waiting", "正在检测手柄", ""
        detail = "手柄当前是 Xbox 模式，可直接当 Xbox 手柄用" if mode == "xbox" else "已手动停止，可在托盘菜单启动"
        return "stopped", "桥接已停止", detail
    if not running:
        return "error", "桥接异常退出", "正在自动重启，详情见日志"
    state = status.get("state")
    if state == "connected" and status.get("backend") == "sensa":
        return "connected", "已连接", "PC 模式：震动经雷蛇 Sensa 输出到左右握把，扳机马达不可用"
    if state == "connected":
        return "connected", "已连接", f"握手 {status.get('handshake_s', 0)} 秒"
    if status.get("reason") == "sensa":
        return "waiting", "等待 Sensa", "请确认雷蛇 Synapse 正在运行，且已识别到手柄"
    if state == "handshake":
        return "waiting", "正在握手", "通常 2 秒内完成"
    if "handshake timeout" in status.get("error", ""):
        return "waiting", "等待手柄", "握手超时，多次出现请拔插一次数据线"
    if state == "lost":
        return "waiting", "手柄已断开", "重新插上即可恢复，游戏无需重启"
    if mode == "absent":
        return "waiting", "等待手柄", "请用数据线连接手柄（PC 模式或 Xbox 模式均可）"
    if mode == "xbox":
        return "waiting", "等待手柄", "手柄仍是 Xbox 驱动，请在“设备”页切换到桥接模式"
    return "waiting", "等待手柄", "正在连接"


def usb_instances(present=True):
    """cfgmgr32 列出 USB 设备实例 ID，单次约 1ms；present=False 时包含已拔出的历史实例。"""
    import ctypes
    from ctypes import wintypes

    cfg = ctypes.WinDLL("cfgmgr32")
    flags = 0x101 if present else 0x1  # CM_GETIDLIST_FILTER_ENUMERATOR (| CM_GETIDLIST_FILTER_PRESENT)
    size = wintypes.ULONG()
    if cfg.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), "USB", flags) or not size.value:
        return []
    buffer = ctypes.create_unicode_buffer(size.value)
    if cfg.CM_Get_Device_ID_ListW("USB", buffer, size, flags):
        return []
    return [instance for instance in buffer[:size.value].split("\0") if instance]


def pc_instances():
    """PC 模式手柄在各 USB 口留下的设备实例（含已拔出的），与 hidhide_script 隐藏的范围一致。"""
    prefix = rf"USB\VID_1532&{PC_PRODUCT}" + "\\"
    return [instance for instance in usb_instances(present=False) if instance.upper().startswith(prefix)]


def find_controller():
    """返回 (实例 ID, 当前驱动服务)；没插时返回 (None, None)。可以放在界面定时器里轮询（Get-PnpDevice 每次要 1 秒以上）。"""
    import ctypes
    from ctypes import wintypes

    cfg = ctypes.WinDLL("cfgmgr32")
    for instance in usb_instances():
        if instance.upper().startswith(tuple(prefix.upper() + "\\" for prefix in DEVICE_PREFIXES)):
            devinst = wintypes.DWORD()
            service = ctypes.create_unicode_buffer(256)
            length = wintypes.ULONG(ctypes.sizeof(service))
            if not cfg.CM_Locate_DevNodeW(ctypes.byref(devinst), instance, 0):
                cfg.CM_Get_DevNode_Registry_PropertyW(devinst, 0x5, None, service, ctypes.byref(length), 0)  # SERVICE
            return instance, service.value or None
    return None, None


def restore_xbox_script(instance_id):
    # 删除设备节点后重新扫描，Windows 按原排名重新选中 Xbox 驱动；不删除驱动包本身。
    return (f'pnputil /remove-device "{instance_id}"\n'
            "Start-Sleep -Seconds 1\n"
            "pnputil /scan-devices\n")


def hidhide_script(bridge_exe, hide):
    """隐藏后只有放行的桥接程序能读到实体手柄，游戏里只剩虚拟 DualSense；恢复时只撤销对手柄的隐藏。

    包括已拔出的历史实例，换 USB 口后仍然生效。全局隐藏开关和其他程序（DSX 等）的放行名单在恢复时保持不动。
    """
    patterns = " -or ".join(f"$_.InstanceId -like '{pattern}'" for pattern in PC_GAMEPAD_PATTERNS)
    flag = "--dev-hide" if hide else "--dev-unhide"
    register = "'--app-reg', '{}'".format(bridge_exe.replace("'", "''")) if hide else ""
    return (f"$ids = @(Get-PnpDevice | Where-Object {{ {patterns} }} | ForEach-Object InstanceId)\n"
            "if (-not $ids) { throw 'PC-mode controller interfaces not found' }\n"
            f"$arguments = @({register}) + @($ids | ForEach-Object {{ '{flag}', $_ }})"
            + (" + @('--cloak-on')\n" if hide else "\n")
            + f"& '{HIDHIDE_CLI}' @arguments\n"
            "exit $LASTEXITCODE\n")


def winusb_script(instance_id):
    tools = root_dir() / "tools"
    return f"& '{tools / 'swap_winusb.ps1'}' -InstanceId '{instance_id}' -Install\n"


def run_elevated(script):
    """经 UAC 运行一段 PowerShell，等它结束；返回退出码，用户拒绝 UAC 时返回 None。"""
    import ctypes
    from ctypes import wintypes

    path = data_dir() / "elevated.ps1"
    path.write_text("$ErrorActionPreference = 'Stop'\n" + script, encoding="utf-8-sig")

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    info = ShellExecuteInfo(cbSize=ctypes.sizeof(ShellExecuteInfo), fMask=0x40, lpVerb="runas",
                            lpFile="powershell.exe", nShow=0,
                            lpParameters=f'-NoProfile -ExecutionPolicy Bypass -File "{path}"')
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return None
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 120000)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return code.value
