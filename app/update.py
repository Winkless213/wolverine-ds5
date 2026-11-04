"""检查有没有新版本：启动时最多每天问一次 GitHub，失败就当没有新版。

这里只读一次发布信息、不下载、不安装；更新仍然由用户自己运行安装包完成。
原因：本程序会装驱动、改设备可见性，静默自更新一旦半途失败，用户很难自己恢复。
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.request

from app import __version__

REPO = "Winkless213/wolverine-ds5"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL = 24 * 3600
TIMEOUT = 6.0


def _numbers(text):
    return tuple(int(part) for part in re.findall(r"\d+", text or "")[:3])


def is_newer(tag, current=__version__):
    remote, local = _numbers(tag), _numbers(current)
    return bool(remote) and bool(local) and remote > local


def fetch_latest(timeout=TIMEOUT):
    request = urllib.request.Request(
        API, headers={"User-Agent": f"WolverineDS5/{__version__}",
                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return str(data.get("tag_name") or "")


def due(marker, now=None, interval=CHECK_INTERVAL):
    """距上次成功检查是否已经超过间隔；文件读不出来时按"该查了"处理。"""
    try:
        last = float(pathlib.Path(marker).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now or time.time()) - last >= interval


def mark_checked(marker, now=None):
    try:
        pathlib.Path(marker).write_text(str(now or time.time()), encoding="utf-8")
    except OSError:
        pass  # 记不下时间只会让下次多查一次，不值得报错。


def check(marker, now=None, fetch=fetch_latest):
    """返回比当前版本新的 tag；不该查、没网、没新版都返回空串。"""
    if not due(marker, now):
        return ""
    try:
        tag = fetch()
    except Exception:
        return ""  # 离线、限流、发布还没建：都不该出现在界面上。
    mark_checked(marker, now)
    return tag if is_newer(tag) else ""


def release_url(tag):
    return f"https://github.com/{REPO}/releases/tag/{tag}"
