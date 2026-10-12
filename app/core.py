"""托盘程序的非界面逻辑：桥接命令行、状态解析、开机自启、日志轮转、驱动切换脚本。"""
import datetime
import json
import os
import pathlib
import subprocess
import sys

AUTOSTART_NAME = "WolverineDS5"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEVICE_PREFIX = r"USB\VID_1532&PID_0A3F"
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


def bridge_command(frozen=None, executable=None, root=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    if frozen:
        return [executable, "--bridge"]
    return [executable, "-u", str((root or root_dir()) / "gip_bridge.py")]


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


def find_controller():
    """返回 (实例 ID, 当前驱动服务)；没插时返回 (None, None)。"""
    script = (f"Get-PnpDevice -PresentOnly | Where-Object {{ $_.InstanceId -like '{DEVICE_PREFIX}\\*' }} | "
              "ForEach-Object { $_.InstanceId + '|' + $_.Service }")
    output = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    if not output:
        return None, None
    instance, _, service = output.splitlines()[0].partition("|")
    return instance, service


def restore_xbox_script(instance_id):
    # 删除设备节点后重新扫描，Windows 按原排名重新选中 Xbox 驱动；不删除驱动包本身。
    return (f'pnputil /remove-device "{instance_id}"\n'
            "Start-Sleep -Seconds 1\n"
            "pnputil /scan-devices\n")


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
