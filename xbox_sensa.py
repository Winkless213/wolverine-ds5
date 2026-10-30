"""有线 Xbox 的实验性私有触觉输出；HAR 只编码，不加载 Provider。"""
import ctypes as c
from functools import reduce
import hashlib
import math
import os
from pathlib import Path
import time

from gip_host import rumble
from sensa_multiband import PcmMailbox
from sensa_offline import HAR_PATH, HAR_SHA256, OfflineSensa, Target
from xbox_multiband import BandAnalyzer, QUIET_BANDS, compose_envelope

PARTS = (216, 116, 249, 149)
QUIET = [(0, 80), (0, 80)]
# 扳机执行器 0–300Hz、共振 20Hz（xbox-sensa-device.json）；无频率信息时停在共振。
TRIGGER_RESONANCE = 20
TRIGGER_QUIET = ((0, TRIGGER_RESONANCE), (0, TRIGGER_RESONANCE))


def available():
    """HAR 是本机专有二进制、不随包分发：只在 64 位且校验和匹配时启用私有四马达输出。"""
    return (c.sizeof(c.c_void_p) == 8 and HAR_PATH.is_file()
            and hashlib.sha256(HAR_PATH.read_bytes()).hexdigest() == HAR_SHA256)


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
        if not available():
            raise RuntimeError("Xbox Sensa requires the verified x64 HAR build")
        self.search = os.add_dll_directory(str(HAR_PATH.parent))
        self.active = False
        self.engine = OfflineSensa.__new__(OfflineSensa)
        self.effects = [None] * 6
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

    # 6 个固定效果槽：左右握把各 2 频带 + 左右扳机；首轮全建，帧布局从此稳定。
    GROUPS = (400, 400, 400, 400, 501, 501)
    HANDS = (2, 2, 1, 1, 2, 1)

    def frame(self, grips, triggers=TRIGGER_QUIET):
        sides = [tuple(side) if side and isinstance(side[0], tuple) else (side,) for side in grips]
        for side in sides:
            if not 0 < len(side) <= 2:
                raise ValueError("Xbox grips accept at most two bands per side")
        self.time += .02
        slots = [side + ((0, 80),) * (2 - len(side)) for side in sides]
        for slot, (amplitude, hz) in enumerate(sum(slots, ()) + tuple(triggers)):
            curve = (c.c_double * 6)(0, amplitude, 599.996, amplitude, 600, 0)
            pitch = (c.c_double * 4)(0, .5, 600, .5)
            args = (curve, 6, pitch, 4, hz, hz, None, 0, False)
            effect = self.effects[slot]
            if effect is None:
                effect = self.engine.add(*args)
                if effect < 0:
                    raise RuntimeError("HAR rejected Xbox grip effect")
                self.effects[slot] = effect
                # 官方 BodyMapping：Palm=400、Index=501，左右食指末节是 249/149。
                self.engine.target(effect, c.byref(Target(1, self.GROUPS[slot], self.HANDS[slot])), 1)
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
        self.triggers = self.previous_triggers = list(TRIGGER_QUIET)
        self.bands = [QUIET_BANDS, QUIET_BANDS]
        self.pcm = PcmMailbox()
        self.analyzer = BandAnalyzer()
        self.epoch = None
        self.previous_state = None
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

    def _render_bands(self, values, now):
        batch = self.pcm.take(now)
        if batch.epoch != self.epoch:
            if self.epoch is not None:
                self.analyzer = BandAnalyzer()
            self.epoch = batch.epoch
        if batch.pcm:
            self.analyzer.push(batch.pcm)
        if batch.last_audio is not None:
            sides = compose_envelope(values, self.analyzer.render(), batch.state)
        else:
            # 没有直播音频时只保留 PC 包络的低频，避免 FFT 历史残影。
            sides = compose_envelope(values, [QUIET_BANDS, QUIET_BANDS], batch.state)
        return sides

    def _send(self, values, now, track=True):
        self.bands = self._render_bands(values, now)
        frame = self.encoder.frame(self.bands, self.triggers)
        sequence = self.host._next_seq()
        self.transport.write(stream_packet(frame, sequence))
        self.sent += 1
        if track:
            self.pending[sequence] = self.clock()
        self.previous_state = (tuple(map(tuple, self.bands)), tuple(values), tuple(self.triggers))
        self.last_write = now
        self.previous_triggers = self.triggers

    def set_triggers(self, triggers):
        pairs = tuple(triggers)
        if len(pairs) != 2:
            raise ValueError("Expected exactly two Xbox private trigger parameters")
        for amplitude, frequency in pairs:
            if not math.isfinite(amplitude) or not 0 <= amplitude <= 1 or not math.isfinite(frequency):
                raise ValueError("Invalid Xbox private trigger parameters")
        self.triggers = [(amplitude, min(300, max(0, frequency))) if amplitude
                         else (0, TRIGGER_RESONANCE) for amplitude, frequency in pairs]

    def render(self):
        now = self.clock()
        if any(now - sent > .5 for sent in self.pending.values()):
            raise ConnectionError("Xbox Sensa stream reply timed out")
        quiet = (not any(value[0] for value in self.values)
                 and not any(pair[0] for pair in self.triggers))
        changed = self.previous_state != (tuple(map(tuple, self.bands)), tuple(self.values), tuple(self.triggers))
        if (self.previous_state is None or quiet and changed
                or not quiet and now - self.last_write >= .02):
            self._send(self.values, now)

    def stop(self):
        self.values = list(QUIET)
        self.triggers = list(TRIGGER_QUIET)
        self.bands = [QUIET_BANDS, QUIET_BANDS]
        self.pcm.pause()
        self._send(self.values, self.clock(), track=False)
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
