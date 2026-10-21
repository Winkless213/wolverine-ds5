"""复用雷云安装器的启动入口；启动成功不代表 Sensa 已经可用。"""
import json
import os
from pathlib import Path

import psutil


def find_shortcut():
    for variable in ("PROGRAMDATA", "APPDATA"):
        directory = os.environ.get(variable)
        if directory:
            programs = Path(directory) / "Microsoft/Windows/Start Menu/Programs"
            for shortcut in programs.rglob("Razer Synapse*.lnk"):
                if shortcut.stem.lower() in ("razer synapse", "razer synapse 3", "razer synapse 4"):
                    return shortcut
    return None


def is_running():
    # App Engine 也承载 Chroma；只认 Synapse 进程或明确的 Synapse 启动参数。
    for process in psutil.process_iter(attrs=("name", "cmdline")):
        try:
            name = (process.info.get("name") or "").lower()
            command = " ".join(process.info.get("cmdline") or []).lower()
        except psutil.Error:
            continue
        if (name in ("razer synapse 3.exe", "razer synapse.exe")
                or "apps=synapse" in command or "--razer-page-name=win-synapse" in command):
            return True
    return False


def ensure_running():
    if is_running():
        return "running"
    shortcut = find_shortcut()
    if shortcut is None:
        return "missing"
    os.startfile(str(shortcut), show_cmd=0)
    return "started"
