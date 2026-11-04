"""把诊断日志合并成一个 UTF-8 文本文件，方便出问题时直接发给开发者。"""
import datetime
import json
from pathlib import Path

MAX_BRIDGE_LINES = 5000
MAX_SECTION_BYTES = 512 * 1024


def _tail(path, lines):
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - MAX_SECTION_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError as error:
        return f"<无法读取 {path.name}: {error}>"
    content = text.splitlines()
    if len(content) > lines:
        content = [f"<仅显示最后 {lines} 行，原文件 {size} 字节>"] + content[-lines:]
    return "\n".join(content)


def build_diagnostic(log_dir, version, mode, settings, now=None, status=None, readiness=None):
    """返回可直接写盘的诊断文本。"""
    moment = now or datetime.datetime.now()
    log_dir = Path(log_dir)
    lines = [
        "Wolverine DS5 diagnostics",
        f"generated: {moment:%Y-%m-%d %H:%M:%S}",
        f"version: {version}",
        f"mode: {mode}",
        f"log_dir: {log_dir}",
        "",
        "--- settings ---",
        json.dumps(settings, ensure_ascii=False, indent=2, default=str),
    ]
    # 桥接当前状态决定“测试按下去有没有输出”，反馈里必须带上，否则只能从日志里翻。
    lines += ["", "--- bridge status ---",
              json.dumps(status or {}, ensure_ascii=False, indent=2, default=str)]
    # 自检结果把“哪一层断了”写清楚：环境、桥接、握把、游戏触觉各一条。
    lines += ["", "--- readiness ---",
              json.dumps(readiness or {}, ensure_ascii=False, indent=2, default=str)]

    for name in ("ui-errors.log", "native-exit.log", "startup.log"):
        path = log_dir / name
        lines += ["", f"--- {name} ---"]
        lines.append(_tail(path, MAX_BRIDGE_LINES) if path.exists() else "<不存在>")

    bridges = sorted(log_dir.glob("bridge-*.log"))
    if bridges:
        path = bridges[-1]
        lines += ["", f"--- {path.name}（最后 {MAX_BRIDGE_LINES} 行） ---", _tail(path, MAX_BRIDGE_LINES)]
    else:
        lines += ["", "--- bridge log ---", "<没有 bridge-*.log>"]

    traces = sorted(log_dir.glob("trigger-trace-*.jsonl"))
    if traces:
        path = traces[-1]
        lines += ["", f"--- {path.name}（最后 500 行） ---", _tail(path, 500)]

    frames = sorted(log_dir.glob("grip-frames-*.jsonl"))
    if frames:
        path = frames[-1]
        lines += ["", f"--- {path.name}（最后 300 行） ---", _tail(path, 300)]

    return "\n".join(lines) + "\n"


def default_export_path(log_dir, now=None):
    moment = now or datetime.datetime.now()
    return Path(log_dir) / f"WolverineDS5-diagnostics-{moment:%Y%m%d-%H%M%S}.txt"
