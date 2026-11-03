"""在接收线程之外保存原始左右触觉，显式记录缺样和连接代次。"""
import base64
import json
import math
import os
import pathlib
import struct
import time
import wave


def decode_audio_block(message):
    generation, first, frames = (message[key] for key in ("generation", "first_frame", "frames"))
    source = message["source"]
    pcm = base64.b64decode(message["pcm"], validate=True)
    if (any(type(value) is not int for value in (generation, first, frames))
            or source not in ("synthetic", "usb-host") or message["sample_rate"] != 48000
            or not 0 < frames <= 48 or len(pcm) != frames * 4 or first < 0 or generation < 1):
        raise ValueError("Invalid raw haptics block")
    return generation, first, frames, source, pcm


def make_recorder():
    """WOLVERINE_PLAY_RECORD=1 时把游戏触觉音频录成 WAV，供离线分析频带覆盖。

    PC 与 Xbox 两条路径共用这一个工厂；开关曾经只在 Xbox 路径生效，PC 模式设了也没反应，
    所以开着时必须留一行目录，让人一眼看出到底有没有录上。
    """
    if os.environ.get("WOLVERINE_PLAY_RECORD") != "1":
        return None
    directory = (pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "WolverineDS5"
                 / "captures" / time.strftime("%Y%m%d-%H%M%S"))
    print(f"Recording haptic audio to {directory}", flush=True)
    return CaptureRecorder(directory)


def record(recorder, message):
    """旁路录像：缺样或写盘失败只关掉录像，绝不影响震动输出。返回仍然可用的 recorder。"""
    if recorder is None or message["type"] not in ("audio", "reset", "stopped"):
        return recorder
    try:
        recorder.accept(message)
    except (ValueError, FileExistsError, OSError) as error:
        print(f"capture recorder: {type(error).__name__}: {error}", flush=True)
        return None
    return recorder


class CaptureRecorder:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.generation = 0
        self.source = None
        self.next_frame = 0
        self.segment = 0
        self.audio = None
        self.stats = {"frames": 0, "missing_frames": 0, "stale_blocks": 0,
                      "duplicate_blocks": 0, "resyncs": 0, "files": [], "peak": [0, 0],
                      "sum_squares": [0, 0]}

    def reset(self, generation):
        if self.audio:
            self.audio.close()
        self.audio = None
        self.generation = generation
        self.next_frame = 0
        self.source = None
        self.segment = 0

    def _restart(self, first, source):
        """游戏重开触觉流后帧号会跳回 0；另起一个文件，不能把整段当重复丢掉。"""
        if self.audio:
            self.audio.close()
        self.audio = None
        self.next_frame = first
        self.source = source
        self.segment += 1

    def accept(self, message):
        if message["type"] == "reset":
            if message["generation"] > self.generation:
                self.reset(message["generation"])
            return
        if message["type"] != "audio":
            return
        generation, first, frames, source, pcm = decode_audio_block(message)
        if generation < self.generation:
            self.stats["stale_blocks"] += 1
            return
        if generation > self.generation:
            self.reset(generation)
        if first < self.next_frame:
            # 小于 1 秒的重叠是真实重复块；整段跳回 0 是新开的触觉流。
            if self.next_frame - (first + frames) <= 48000:
                self.stats["duplicate_blocks"] += 1
                return
            self._restart(first, source)
            self.stats["resyncs"] += 1
        gap = first - self.next_frame
        if gap > 48000:
            # 游戏重开或 capture 断流超过 1 秒：不伪装成连续录音，另起一段。
            self._restart(first, source)
            self.stats["resyncs"] += 1
            gap = 0
        if self.audio is None:
            name = f"{source}-{generation:04d}" + (f"-r{self.segment}" if self.segment else "")
            path = self.directory / f"{name}.wav"
            while path.exists():
                self.segment += 1
                path = self.directory / f"{source}-{generation:04d}-r{self.segment}.wav"
            self.audio = wave.open(str(path), "wb")
            self.audio.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
            self.source = source
            self.stats["files"].append(path.name)
        if source != self.source:
            raise ValueError("Synthetic and USB input cannot share a recording")
        self.audio.writeframesraw(b"\0" * gap * 4 + pcm)
        self.next_frame = first + frames
        self.stats["frames"] += frames
        self.stats["missing_frames"] += gap
        for left, right in struct.iter_unpack("<hh", pcm):
            for channel, value in enumerate((left / 32768, right / 32768)):
                self.stats["peak"][channel] = max(self.stats["peak"][channel], abs(value))
                self.stats["sum_squares"][channel] += value * value

    def close(self):
        if self.audio:
            self.audio.close()
            self.audio = None
        self.stats["rms"] = [math.sqrt(value / max(1, self.stats["frames"])) for value in self.stats["sum_squares"]]
        (self.directory / "capture.json").write_text(json.dumps(self.stats, indent=2), encoding="utf-8")
