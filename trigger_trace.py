"""按需记录游戏扳机报文与实体开度，写入托盘日志目录，不参与震动映射。"""
import json
import os
from pathlib import Path
import time


def log_path():
    directory = Path(os.environ.get("LOCALAPPDATA", ".")) / "WolverineDS5" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / time.strftime("trigger-trace-%Y%m%d-%H%M%S.jsonl")


class TriggerTrace:
    def __init__(self, flag=None, write=None, seconds=None):
        self.flag = Path(flag) if flag else None
        self.seconds = seconds if seconds is not None else float(
            os.environ.get("WOLVERINE_TRIGGER_TRACE_SECONDS", 60))
        self.path = None
        self.write = write or self._write_file
        self.present = self.flag.is_file() if self.flag else False
        self.next_check = 0
        self.until = None
        self.effects = {"left": None, "right": None}
        self.previous = None
        self.last_sample = 0
        self.reports_seen = self.reports_changed = self.samples = 0

    def _write_file(self, event):
        # 桥接由托盘的隐藏窗口启动，stdout 收不到；录制一律落盘。
        if self.path is None:
            self.path = log_path()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def emit(self, event, now, **values):
        self.write({"type": "trigger-trace", "event": event, "monotonic_s": now, **values})

    def close(self, now, reason="device-detached"):
        if self.until is not None:
            self.emit("stop", now, reason=reason, reports_seen=self.reports_seen,
                      reports_changed=self.reports_changed, samples=self.samples,
                      path=str(self.path) if self.path else None)
            self.until = None

    def active(self, now):
        if self.until is not None and now >= self.until:
            self.close(now, "duration")
        return self.until is not None

    def sample(self, state, now):
        if self.flag is None:
            return
        if now >= self.next_check:
            present = self.flag.is_file()
            if present and not self.present:
                self.until = now + self.seconds
                self.previous = None
                self.reports_seen = self.reports_changed = self.samples = 0
                self.emit("start", now, max_seconds=self.seconds, effects=dict(self.effects))
            elif not present:
                self.close(now, "requested")
            self.present, self.next_check = present, now + .2
        if self.active(now) and (state != self.previous or now - self.last_sample >= .1):
            self.emit("sample", now, state=state)
            self.previous, self.last_sample = state, now
            self.samples += 1

    def output(self, report, now):
        if self.flag is None:
            return
        changed = False
        has_trigger = False
        for side, flag, offset in (("right", 4, 11), ("left", 8, 22)):
            if report[1] & flag:
                has_trigger = True
                data = report[offset:offset + 11].hex()
                changed |= self.effects[side] != data
                self.effects[side] = data
        if self.active(now) and has_trigger:
            self.reports_seen += 1
            if changed:
                self.emit("output", now, report_hex=report.hex())
                self.reports_changed += 1

    def reset(self, now):
        self.effects = {"left": None, "right": None}
        if self.active(now):
            self.emit("reset", now)
            self.previous = None
