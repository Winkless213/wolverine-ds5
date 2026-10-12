"""把现有左右 PCM 参数与扳机映射接到限幅 XUSB 输出，不还原频率或机械阻力。"""
import time

from capture_recorder import decode_audio_block
from pcm_to_sensa import PcmToSensa
from xusb_output import XusbOutput


class XusbBridge:
    def __init__(self, output=None, limit=.22):
        self.converter = PcmToSensa(limit)
        self.output = output if output is not None else XusbOutput()
        self.closed = False
        self.ended = False
        self.grips = (0, 0)
        self.rumble = (0, 0)
        # 可选的 (values, now) -> values；在限频与去重之前生效，去重比较的是实际下发值。
        self.mix = None
        self.generation = self.next_frame = 0
        self.last_audio = self.last_poll = self.last_write = None
        self.previous = (0, 0, 0, 0)
        self.stats = {"backend": "xusb", "mapping": "stereo dominant-tone amplitude only",
                      "frequency_preserved": False, "amplitude_limit": limit,
                      "max_update_hz": 50, "refresh_ms": 100, "watchdog_ms": 50,
                      "audio_frames": 0, "timeouts": 0, "resets": 0,
                      "hardware_output_attempted": False, "physical_latency_measured": False}

    def stop(self):
        self.converter.reset()
        self.grips = (0, 0)
        self.rumble = (0, 0)
        self.last_audio = None
        self.output.set(0, 0, 0, 0)
        self.previous = (0, 0, 0, 0)

    def accept(self, message, now=None):
        if self.closed:
            raise RuntimeError("XUSB bridge is closed")
        now = time.monotonic() if now is None else now
        try:
            if message["type"] == "reset":
                generation = message["generation"]
                if type(generation) is not int or generation < 1:
                    raise ValueError("Invalid capture generation")
                if generation > self.generation:
                    self.stop()
                    self.ended = False
                    self.generation, self.next_frame = generation, 0
                    self.stats["resets"] += 1
                return
            if message["type"] == "stopped":
                self.stop()
                self.ended = True
                return
            if message["type"] != "audio":
                return
            generation, first, count, source, pcm = decode_audio_block(message)
            if source != "usb-host":
                raise ValueError("Live XUSB output requires USB-host capture")
            if message.get("host_queue_us", 0) > 50000:
                raise TimeoutError("Host audio queue exceeded 50 ms")
            if generation > self.generation:
                self.converter.reset()
                self.grips = (0, 0)
                self.generation, self.next_frame = generation, 0
            if generation != self.generation or first != self.next_frame:
                raise ValueError("Audio sequence discontinuity; output stopped")
            parameters = self.converter.push(pcm)
            if parameters:
                self.grips = tuple(channel["amplitude"] for channel in parameters[-1]["channels"])
            self.next_frame += count
            self.stats["audio_frames"] += count
            self.last_audio = now
        except Exception:
            self.stop()
            raise

    def poll(self, triggers, now=None):
        if self.closed:
            raise RuntimeError("XUSB bridge is closed")
        if self.ended:
            return
        now = time.monotonic() if now is None else now
        if self.last_poll is not None and now - self.last_poll > .05:
            self.stop()
            raise TimeoutError("Output loop exceeded 50 ms; restart required")
        self.last_poll = now
        if self.last_audio is not None and now - self.last_audio >= .05:
            self.converter.reset()
            self.grips = (0, 0)
            self.last_audio = None
            self.stats["timeouts"] += 1
        # 传统震动（DS5 byte3/4）与音频触觉取较大者；音频超时只清音频，不清传统震动。
        values = (*(max(pair) for pair in zip(self.grips, self.rumble)), *triggers)
        if self.mix:
            values = self.mix(values, now)
        changed = values != self.previous
        ready = self.last_write is None or now - self.last_write >= .02
        refresh = any(values) and self.last_write is not None and now - self.last_write >= .1
        # 全部归零绕过限频；每轮只发送最新状态，不补发旧的马达指令。
        if (changed and (ready or not any(values))) or refresh:
            self.stats["hardware_output_attempted"] |= any(values)
            self.output.set(*values)
            self.previous, self.last_write = values, now

    def close(self):
        if not self.closed:
            self.closed = True
            self.output.close()
