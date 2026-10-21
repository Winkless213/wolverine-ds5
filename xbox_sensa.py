"""有线 Xbox 的实验性私有触觉输出；HAR 只编码，不加载 Provider。"""
import ctypes as c
from functools import reduce
import hashlib
import math
import os
from pathlib import Path
import time

from gip_host import rumble
from sensa_offline import HAR_PATH, HAR_SHA256, OfflineSensa, Target

PARTS = (216, 116, 249, 149)
QUIET = [(0, 80), (0, 80)]


def stream_packet(frame, sequence):
    if not 0 < len(frame) <= 49:
        raise ValueError("Xbox HAR frame must fit in 49 bytes")
    packet = bytearray(64)
    packet[:4] = bytes((0x0F, 0, sequence, 60))
    packet[5] = 0x1F
    # Synapse sendHapticData 的单段流带一个 remaining-fragments 字节。
    packet[9:13] = bytes((len(frame) + 1, 0x16, 0x0E, 1))
    packet[13:13 + len(frame)] = frame
    packet[62] = reduce(int.__xor__, packet[6:62], 0)
    return bytes(packet)


def trigger_packet(lt, rt):
    # xone 的 0x0C 掩码在本机没有扳机响应；实机 A/B 只确认原 0x0F 指令有效。
    return rumble(0, 0, lt, rt)


class XboxEncoder:
    def __init__(self):
        if c.sizeof(c.c_void_p) != 8 or hashlib.sha256(HAR_PATH.read_bytes()).hexdigest() != HAR_SHA256:
            raise RuntimeError("Xbox Sensa requires the verified x64 HAR build")
        self.search = os.add_dll_directory(str(HAR_PATH.parent))
        self.active = False
        self.engine = OfflineSensa.__new__(OfflineSensa)
        self.effects = [None] * 4
        self.time = self.played = 0.0
        try:
            self.engine.dll = c.CDLL(str(HAR_PATH))
            self.engine._bind()
            if not self.engine.init():
                raise RuntimeError("HAR.Init failed")
            self.active = True
            self.device = self.engine.add_device(Path(__file__).with_name("xbox-sensa-device.json").read_bytes())
            if self.device < 0:
                raise RuntimeError("HAR rejected Xbox metadata")
            self.parts = (c.c_int * 4)(*PARTS)
            self.engine.connect(self.device, self.parts, 4)
            self.size = self.engine.get_size(self.device, self.parts, 4)
            if self.size != 49:
                raise RuntimeError("Unexpected Xbox HAR frame capacity")
            self.engine.compute(0)
        except BaseException:
            self.close()
            raise

    def frame(self, grips, triggers=(0, 0), trigger_hz=20):
        self.time += .02
        for side, (amplitude, hz) in enumerate(list(grips) + [(value, trigger_hz) for value in triggers]):
            curve = (c.c_double * 6)(0, amplitude, 599.996, amplitude, 600, 0)
            pitch = (c.c_double * 4)(0, .5, 600, .5)
            args = (curve, 6, pitch, 4, hz, hz, None, 0, False)
            effect = self.effects[side]
            if effect is None:
                effect = self.engine.add(*args)
                if effect < 0:
                    raise RuntimeError("HAR rejected Xbox grip effect")
                self.effects[side] = effect
                # 官方 BodyMapping：Palm=400、Index=501，左右食指末节是 249/149。
                self.engine.target(effect, c.byref(Target(1, 400 if side < 2 else 501, 2 if side % 2 == 0 else 1)), 1)
                self.engine.play(effect, -self.time, 0, 0)
            elif not self.engine.update(effect, *args):
                raise RuntimeError("HAR rejected Xbox grip update")
        if self.time - self.played >= 300:
            for effect in self.effects:
                self.engine.play(effect, -self.time, 0, 0)
            self.played = self.time
        self.engine.compute(self.time)
        data = (c.c_ubyte * self.size)()
        size = self.engine.get_frame(self.device, self.parts, 4, data)
        if not 0 < size <= self.size:
            raise RuntimeError(f"Invalid Xbox HAR frame size: {size}")
        frame = bytes(data[:size])
        if not 0 < frame[0] >> 1 <= 60:
            raise RuntimeError("Xbox frame must have a bounded duration")
        return frame

    def close(self):
        if self.active:
            self.engine.stop()
            self.engine.quit()
            self.active = False
        self.search.close()


class SensaStream:
    """旁听同一个 USB 读取循环的厂商回复，不另开线程抢输入；每帧都是有限短帧。"""

    def __init__(self, host, encoder=None, clock=time.monotonic):
        self.host, self.clock = host, clock
        self.encoder = encoder if encoder is not None else XboxEncoder()
        self.transport = host.transport
        self.values = list(QUIET)
        self.triggers = self.previous_triggers = (0, 0)
        self.previous = None
        self.last_write = None
        self.pending = {}
        self.accepted = self.sent = 0
        self.closed = False
        host.transport = self

    def write(self, data):
        self.transport.write(data)

    def read(self, timeout_ms):
        data = self.transport.read(timeout_ms)
        if data and len(data) >= 4 and data[0] == 0x10 and data[2] in self.pending:
            if (len(data) != 64 or data[1] != 0 or data[3:6] != bytes((60, 2, 0x1F))
                    or data[10:12] != b"\x16\x0e"
                    or data[62] != reduce(int.__xor__, data[6:62], 0)):
                raise ConnectionError("Xbox Sensa stream reply rejected or corrupt")
            del self.pending[data[2]]
            self.accepted += 1
            return None
        return data

    def set(self, side, amplitude, frequency):
        if side not in (0, 1) or not math.isfinite(amplitude) or not 0 <= amplitude <= 1 or not math.isfinite(frequency):
            raise ValueError("Invalid Xbox grip parameters")
        self.values[side] = (amplitude, min(300, max(20, frequency))) if amplitude else (0, 80)

    def _send(self, values, track=True):
        frame = self.encoder.frame(values, self.triggers)
        sequence = self.host._next_seq()
        self.transport.write(stream_packet(frame, sequence))
        self.sent += 1
        if track:
            self.pending[sequence] = self.clock()
        self.previous, self.last_write = list(values), self.clock()
        self.previous_triggers = self.triggers

    def set_triggers(self, lt, rt):
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (lt, rt)):
            raise ValueError("Invalid Xbox private trigger parameters")
        self.triggers = (lt, rt)

    def render(self):
        now = self.clock()
        if any(now - sent > .5 for sent in self.pending.values()):
            raise ConnectionError("Xbox Sensa stream reply timed out")
        quiet = not any(value[0] for value in self.values) and not any(self.triggers)
        if (self.previous is None or quiet and (self.values != self.previous or self.triggers != self.previous_triggers)
                or not quiet and now - self.last_write >= .02):
            self._send(self.values)

    def stop(self):
        self.values = list(QUIET)
        self.triggers = (0, 0)
        self._send(self.values, track=False)
        self.pending.clear()

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.stop()
        finally:
            self.host.transport = self.transport
            self.encoder.close()
