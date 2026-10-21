"""通过现有 HidHide CLI 和驱动恢复脚本收回桥接对系统的影响。"""
import ctypes
from ctypes import wintypes
import fnmatch
import os
import re
import subprocess
import time

from app import core


def command(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, errors="replace", timeout=15,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"命令失败：{result.returncode}")
    return result.stdout


def is_pc_pad(instance):
    return any(fnmatch.fnmatchcase(instance.upper(), pattern) for pattern in core.PC_GAMEPAD_PATTERNS)


def _hidhide_api():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = (
        ("CreateFileW", [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        ("DeviceIoControl", [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                             ctypes.c_void_p], wintypes.BOOL),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ("GetLogicalDrives", [], wintypes.DWORD),
        ("QueryDosDeviceW", [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD], wintypes.DWORD),
    )
    for name, arguments, result in signatures:
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


def _hidhide_read(api, handle, operation, size=0):
    # 只开放官方 GET；中文应用路径会截断 CLI 1.5.230 的文本输出。
    # ABI: https://github.com/nefarius/HidHide/blob/master/Shared/HidHideIoctlContract.h
    if operation not in (2048, 2050, 2052, 2054):
        raise ValueError("HidHide 状态查询只允许读取")
    code = (32769 << 16) | (1 << 14) | (operation << 2)
    returned = wintypes.DWORD(size)
    if not size and not api.DeviceIoControl(handle, code, None, 0, None, 0, ctypes.byref(returned), None):
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(returned.value)
    if not api.DeviceIoControl(handle, code, None, 0, buffer, len(buffer), ctypes.byref(returned), None):
        raise ctypes.WinError(ctypes.get_last_error())
    if returned.value > len(buffer) or (size and returned.value != size):
        raise RuntimeError("HidHide 状态数据不完整")
    return buffer.raw[:returned.value]


def _hidhide_app_paths(api, paths):
    drives = api.GetLogicalDrives()
    if not drives:
        raise ctypes.WinError(ctypes.get_last_error())
    prefixes = []
    for index in range(26):
        if drives & (1 << index):
            drive = chr(65 + index) + ":"
            target = ctypes.create_unicode_buffer(32768)
            if not api.QueryDosDeviceW(drive, target, len(target)):
                raise ctypes.WinError(ctypes.get_last_error())
            prefixes.append((target.value + "\\", drive + "\\"))
    # 离线卷的其他应用保留原路径，不能把无法映射误判成名单里不存在。
    return [next((drive + path[len(prefix):] for prefix, drive in prefixes
                  if path.casefold().startswith(prefix.casefold())), path) for path in paths]


def hiding_state():
    api = _hidhide_api()
    handle = api.CreateFileW(r"\\.\HidHide", 0x80000000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        apps = _hidhide_read(api, handle, 2048).decode("utf-16-le").strip("\0").split("\0")
        devices = _hidhide_read(api, handle, 2050).decode("utf-16-le").strip("\0").split("\0")
        active = bool(_hidhide_read(api, handle, 2052, 1)[0])
        inverse = bool(_hidhide_read(api, handle, 2054, 1)[0])
    finally:
        api.CloseHandle(handle)
    return {"devices": [device for device in devices if device],
            "apps": _hidhide_app_paths(api, [app for app in apps if app]),
            "active": active, "inverse": inverse}


def configure_hiding(hidden, bridge_exe, previous_app=""):
    before = hiding_state()
    arguments = []
    if hidden:
        if before["inverse"]:
            raise RuntimeError("HidHide 正在使用反向应用名单，未更改其他程序的配置")
        targets = {instance.upper() for kind in ("USB", "HID")
                   for instance in core.usb_instances(present=False, enumerator=kind) if is_pc_pad(instance)}
        arguments.extend(("--app-reg", bridge_exe))
        for instance in sorted(targets):
            arguments.extend(("--dev-hide", instance))
        arguments.append("--cloak-on")
    else:
        # 从实际隐藏名单撤销，实体已拔出或旧设备节点消失时仍能恢复。
        targets = {instance for instance in before["devices"] if is_pc_pad(instance)}
        for instance in sorted(targets):
            arguments.extend(("--dev-unhide", instance))
        owned_apps = {app.lower() for app in (bridge_exe, previous_app) if app}
        for app in before["apps"]:
            if app.lower() in owned_apps:
                arguments.extend(("--app-unreg", app))
        if before["active"] and not set(before["devices"]) - targets:
            arguments.append("--cloak-off")
    if arguments:
        command(core.HIDHIDE_CLI, *arguments)
    after = hiding_state()
    if hidden:
        if (not after["active"] or not targets.issubset({instance.upper() for instance in after["devices"]})
                or bridge_exe.lower() not in {app.lower() for app in after["apps"]}):
            raise RuntimeError("未能确认实体手柄隐藏和桥接放行已生效")
    elif any(is_pc_pad(instance) for instance in after["devices"]):
        raise RuntimeError("实体手柄仍被隐藏，恢复尚未完成")
    elif any(app.lower() in owned_apps for app in after["apps"]):
        raise RuntimeError("桥接的 HidHide 放行设置尚未移除")
    return 0


def detach_virtual():
    exe = os.environ.get("GIP_BRIDGE_USBIP_EXE", r"C:\Program Files\USBip\usbip.exe")
    ports = command(exe, "port")
    for match in re.finditer(r"(?ms)^Port\s+(\d+):(.*?)(?=^Port\s|\Z)", ports):
        if core.usbip_attached(match[2]):
            try:
                command(exe, "detach", "-p", match[1])
            except RuntimeError:
                if core.usbip_attached(command(exe, "port")):
                    raise
    if core.usbip_attached(command(exe, "port")):
        raise RuntimeError("虚拟 DualSense 仍在挂载，恢复尚未完成")


def restore_native(previous_app=""):
    detach_virtual()
    try:
        configure_hiding(False, core.bridge_command(pc=True)[0], previous_app)
    except FileNotFoundError:
        if previous_app:
            raise RuntimeError("HidHide CLI 缺失，无法解除实体手柄隐藏")
    instances = [instance for instance in core.usb_instances(present=False)
                 if instance.upper().startswith(r"USB\VID_1532&PID_0A3F" + "\\")
                 and core.device_service(instance).lower() == "winusb"
                 and not core.xbox_restore_pending(instance)]
    if not instances:
        return
    script = "".join(core.restore_xbox_script(instance) for instance in instances)
    if core.run_elevated(script) != 0:
        raise RuntimeError("Xbox 原厂驱动未恢复；如出现管理员提示，请允许后重试退出")
    for _ in range(30):
        if all(core.device_service(instance).lower() not in ("", "winusb")
               or core.xbox_restore_pending(instance) for instance in instances):
            return
        time.sleep(.1)
    raise RuntimeError("Xbox 驱动仍未恢复，程序保留以便重试")
