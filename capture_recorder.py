"""在接收线程之外保存原始左右触觉，显式记录缺样和连接代次。"""
import base64
import json
import math
import struct
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


class CaptureRecorder:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.generation = 0
        self.source = None
        self.next_frame = 0
        self.audio = None
        self.stats = {"frames": 0, "missing_frames": 0, "stale_blocks": 0,
                      "duplicate_blocks": 0, "files": [], "peak": [0, 0], "sum_squares": [0, 0]}

    def reset(self, generation):
        if self.audio:
            self.audio.close()
        self.audio = None
        self.generation = generation
        self.next_frame = 0
        self.source = None

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
            self.stats["duplicate_blocks"] += 1
            return
        gap = first - self.next_frame
        if gap > 48000:
            raise ValueError("Capture gap exceeds one second; refusing to conceal a failed capture")
        if self.audio is None:
            path = self.directory / f"{source}-{generation:04d}.wav"
            if path.exists():
                raise FileExistsError(path)
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
