"""有界 PCM 缓冲与多频游戏输出；编码和共享内存发送由独立线程调用。"""
from dataclasses import dataclass, field, replace
import json
import math
import os
import pathlib
import threading
import time

from pcm_encoder import CHUNK_BYTES, PcmEncoder
from sensa_frame import decode_frame
from sensa_mixer import Mixer, find_pc_device
from settings import Settings


QUIET_FRAME = bytes.fromhex("51000000000000080000000000001000000000000080000000000000")
MAX_AMPLITUDE = 32
MAX_PENDING = 1920 * 4
SUSTAIN_EQ = ((80, 1.0), (100, .5), (150, .3), (250, .15), (400, .1))


@dataclass(frozen=True)
class MixState:
    settings: Settings = field(default_factory=Settings)
    rumble: tuple = (0.0, 0.0)
    test_target: str | None = None
    pressures: tuple = (0.0, 0.0)


@dataclass(frozen=True)
class PcmBatch:
    pcm: bytes
    epoch: int
    last_audio: float | None
    state: MixState


def pack_frame(frame):
    fields = [(frame["duration_ms"], 7)]
    for side in frame["channels"]:
        for band in side["bands"]:
            fields.append((1, 1))
            for point in band:
                fields.extend(((point["amplitude_code"], 6), (point["frequency_code"], 7)))
        if len(side["bands"]) < 3:
            fields.append((0, 1))
        # 当前游戏候选只使用持续频带，冲击参数尚未实机验证。
        fields.append((0, 1))
    bits = "".join(f"{value:0{width}b}" for value, width in fields)
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def soft_gain(frequency, sustained=False):
    if not sustained:
        return max(.5, 1 - max(0, frequency - 80) / 400)
    if frequency <= SUSTAIN_EQ[0][0]:
        return SUSTAIN_EQ[0][1]
    for (low, start), (high, end) in zip(SUSTAIN_EQ, SUSTAIN_EQ[1:]):
        if frequency <= high:
            return start + (end - start) * (frequency - low) / (high - low)
    return SUSTAIN_EQ[-1][1]


class SustainSoftener:
    def __init__(self):
        self.reset()

    def reset(self):
        self.started = [None, None]
        self.levels = [0, 0]
        self.updated = None

    def apply(self, raw, enabled, now):
        if not enabled:
            self.reset()
            return raw
        if self.updated is not None and (now < self.updated or now - self.updated >= .05):
            self.reset()
        self.updated = now
        frame = decode_frame(raw)
        changed = False
        for index, side in enumerate(frame["channels"]):
            level = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
            high = any(point["amplitude_code"] and 30 + point["frequency_code"] * 370 / 127 > 80
                       for band in side["bands"] for point in band)
            attack = level - self.levels[index] >= 3 and level >= 1.6 * self.levels[index]
            self.levels[index] = level
            if not high:
                self.started[index] = None
                continue
            if self.started[index] is None or attack:
                self.started[index] = now
            # 保留前 120ms 和新冲击，之后用 200ms 渐入，只衰减持续高频。
            blend = min(1, max(0, (now - self.started[index] - .12) / .2))
            if not blend:
                continue
            for band in side["bands"]:
                for point in band:
                    frequency = 30 + point["frequency_code"] * 370 / 127
                    ratio = soft_gain(frequency, sustained=True) / soft_gain(frequency)
                    level = round(point["amplitude_code"] * (1 - blend + blend * ratio))
                    changed |= level != point["amplitude_code"]
                    point["amplitude_code"] = level
        return pack_frame(frame) if changed else raw


class FrameTrace:
    """诊断用：记录真正发出的帧，限量后停止；关闭时不创建实例。"""

    LIMIT = 30000

    def __init__(self, path=None):
        if path is None:
            log_dir = pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "WolverineDS5" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / time.strftime("grip-frames-%Y%m%d-%H%M%S.jsonl")
        self.path = pathlib.Path(path)
        self.rows = []
        self.count = 0
        self.started = time.monotonic()

    def record(self, now, frame, before, state):
        if self.count >= self.LIMIT:
            return
        self.count += 1
        self.rows.append({"t": round(now - self.started, 3), "gain": state.settings.grip_gain,
                          "soft": bool(state.settings.grip_soft), "test": state.test_target,
                          "changed": frame != before, "sent": frame.hex(), "raw": before.hex()})
        if len(self.rows) >= 250:
            self.flush()

    def flush(self):
        if not self.rows:
            return
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.writelines(json.dumps(row) + "\n" for row in self.rows)
        except OSError:
            pass
        self.rows.clear()


def trace_enabled():
    return pathlib.Path(__file__).with_name("frame-trace.enabled").is_file()


HIGH_RATIO = .8
FREQ_HOLD = 6.0
MIN_TOTAL = 6
FAINT_FLOOR = 16
FAINT_HIGH = 3
LEVEL_HOLD = 2
RAMP_JUMP = 6


class FrequencyHold:
    """实机记录：摆荡时低频主频每次跳 8.7Hz、33% 的帧都在跳；战斗只跳 2.9Hz。
    小幅逐帧跳变沿用上一个频率，避免音高抖动听成尖锐嗡嗡；大跳变照实跟踪。"""

    def __init__(self):
        self.held = [None, None]

    def reset(self):
        self.held = [None, None]

    def apply(self, frame):
        decoded = decode_frame(frame)
        changed = False
        for index, side in enumerate(decoded["channels"]):
            points = [(point, 30 + point["frequency_code"] * 370 / 127)
                      for band in side["bands"] for point in band if point["amplitude_code"]]
            low = [item for item in points if item[1] <= 80]
            if not low:
                self.held[index] = None
                continue
            frequency = max(low, key=lambda item: item[0]["amplitude_code"])[1]
            previous = self.held[index]
            if previous is None or abs(frequency - previous) > FREQ_HOLD:
                self.held[index] = frequency
                continue
            if abs(frequency - previous) > 1:
                code = round((previous - 30) * 127 / 370)
                for point, point_hz in low:
                    if point_hz != previous:
                        point["frequency_code"] = code
                        changed = True
        return pack_frame(decoded) if changed else frame


def shape_high_band(side):
    """实机记录：摆荡时高频压过低频（中位 1.38），战斗时低频主导（中位 0.77）。
    按高/低比值连续压高频，比值不超门槛的帧（战斗多数）完全不动。"""
    low, top = 0, 0
    for band in side["bands"]:
        for point in band:
            amplitude = point["amplitude_code"]
            if 30 + point["frequency_code"] * 370 / 127 <= 80:
                low = max(low, amplitude)
            else:
                top = max(top, amplitude)
    if not low or not top or top <= HIGH_RATIO * low:
        return
    factor = max(.25, 1 / (1 + top / low - HIGH_RATIO))
    for band in side["bands"]:
        for point in band:
            if 30 + point["frequency_code"] * 370 / 127 > 80:
                point["amplitude_code"] = round(point["amplitude_code"] * factor)


class LevelHold:
    """实机：残留之外的 6–12 级内容仍带 ±1 级逐帧闪烁，听感是若有若无。
    幅度变化小于 2 级时沿用上一帧比例，让中弱震动稳住而不是忽大忽小；强冲击照常跳变。"""

    def __init__(self):
        self.held = [None, None]

    def reset(self):
        self.held = [None, None]

    def apply(self, frame):
        decoded = decode_frame(frame)
        changed = False
        for index, side in enumerate(decoded["channels"]):
            points = [point for band in side["bands"] for point in band if point["amplitude_code"]]
            if not points:
                self.held[index] = None
                continue
            top = max(point["amplitude_code"] for point in points)
            previous = self.held[index]
            if previous is None or abs(top - previous) >= LEVEL_HOLD:
                self.held[index] = top
                continue
            if top != previous:
                ratio = previous / top
                for point in points:
                    point["amplitude_code"] = max(1, round(point["amplitude_code"] * ratio))
                changed = True
        return pack_frame(decoded) if changed else frame


class PointRamp:
    """实机与历史记录：编码器把同一个幅度复制到频带内全部四点（66000 帧无一例外），
    所以幅度变化永远是 10ms 硬台阶，微震时的台阶感就是听出来的颗粒/底噪。
    这里用上一帧到本帧的过渡点补出斜坡；达到 RAMP_JUMP 级的冲击保持硬边，别削打击力度。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = [None, None]

    def apply(self, frame):
        decoded = decode_frame(frame)
        changed = False
        for index, side in enumerate(decoded["channels"]):
            previous = self.previous[index]
            levels = []
            for order, band in enumerate(side["bands"]):
                top = max(point["amplitude_code"] for point in band)
                levels.append(top)
                start = previous[order] if previous is not None and order < len(previous) else None
                if not top or start is None or abs(top - start) >= RAMP_JUMP or top == start:
                    continue
                span = max(1, len(band) - 2)
                for place, point in enumerate(band):
                    level = round(start + (top - start) * min(1, place / span))
                    changed |= point["amplitude_code"] != level
                    point["amplitude_code"] = level
            self.previous[index] = levels
        return pack_frame(decoded) if changed else frame


def side_levels(side):
    """返回（低频段最大幅度、其余频段最大幅度）。"""
    low = high = 0
    for band in side["bands"]:
        for point in band:
            if 30 + point["frequency_code"] * 370 / 127 <= 80:
                low = max(low, point["amplitude_code"])
            else:
                high = max(high, point["amplitude_code"])
    return low, high


def compose_frame(raw, state):
    if (state.test_target not in (None, "grip") or (state.test_target is None and not state.settings.grip_enabled)
            or state.settings.grip_gain == 0):
        return QUIET_FRAME
    frame = decode_frame(raw)
    if frame["duration_ms"] != 40 or any(side["transients"] for side in frame["channels"]):
        raise ValueError("PCM 编码帧不符合当前候选 profile")
    for index, side in enumerate(frame["channels"]):
        rumble = state.pressures[index] if state.test_target == "grip" else state.rumble[index]
        # 真实单频样本会向高频带泄漏少量低频，先排除它，再与经典震动比较力度。
        if len(side["bands"]) > 1:
            for point in side["bands"][1]:
                if 30 + point["frequency_code"] * 370 / 127 < 78:
                    point["amplitude_code"] = 0
        strength = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
        use_rumble = state.test_target == "grip" or rumble * 63 > strength
        if use_rumble:
            side["bands"] = [[{"amplitude_code": round(rumble * 63), "frequency_code": 7}
                              for _ in range(4)]]
        for band in side["bands"]:
            for point in band:
                frequency = 30 + point["frequency_code"] * 370 / 127
                # 短促冲击沿用已实机认可的柔和力度，持续高频由独立状态处理。
                soft = soft_gain(frequency) if state.settings.grip_soft else 1
                point["amplitude_code"] = round(point["amplitude_code"] * state.settings.grip_gain * soft)
        if state.settings.grip_soft:
            shape_high_band(side)
        total = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
        if 0 < total <= MIN_TOTAL:
            # 实机 2026-10-20：6–12 级的持续中弱成分听成底噪，先整段屏蔽；
            # 实机 2026-10-21：屏蔽后仍剩“忽隐忽现”的弱低频，改成按比例抬成稳定的一层；
            # 只有几乎全是低频的才抬，带高频的弱帧仍静音。
            low, high = side_levels(side)
            if state.settings.grip_soft and state.test_target is None and low and high <= FAINT_HIGH:
                for band in side["bands"]:
                    for point in band:
                        if 30 + point["frequency_code"] * 370 / 127 <= 80:
                            point["amplitude_code"] = min(MAX_AMPLITUDE,
                                                          round(point["amplitude_code"] * FAINT_FLOOR / low))
            else:
                for band in side["bands"]:
                    for point in band:
                        point["amplitude_code"] = 0
            total = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
        if total > MAX_AMPLITUDE:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = math.floor(point["amplitude_code"] * MAX_AMPLITUDE / total)
    return pack_frame(frame)


class PcmMailbox:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = bytearray()
        self.epoch = 0
        self.last_audio = self.heartbeat = None
        self.state = MixState(settings=Settings(grip_enabled=False))

    def push(self, pcm, now):
        if not pcm or len(pcm) % 4:
            raise ValueError("PCM 必须为完整双声道 S16LE 帧")
        with self.lock:
            if self.last_audio is not None and now - self.last_audio >= .05:
                self.pending.clear()
                self.epoch += 1
            self.pending.extend(pcm)
            if len(self.pending) > MAX_PENDING:
                del self.pending[:-MAX_PENDING]
                self.epoch += 1
            self.last_audio = now

    def configure(self, state, now):
        with self.lock:
            self.state, self.heartbeat = state, now

    def clear(self):
        with self.lock:
            self.pending.clear()
            self.last_audio = None
            self.epoch += 1

    def pause(self):
        self.clear()
        with self.lock:
            self.heartbeat = None

    def take(self, now):
        with self.lock:
            if self.last_audio is not None and now - self.last_audio >= .05:
                self.pending.clear()
                self.last_audio = None
                self.epoch += 1
            state = self.state
            if self.heartbeat is None or now - self.heartbeat >= .1:
                state = replace(state, settings=replace(state.settings, grip_enabled=False),
                                test_target=None, rumble=(0.0, 0.0))
                self.pending.clear()
            batch = PcmBatch(bytes(self.pending), self.epoch, self.last_audio, state)
            self.pending.clear()
            return batch


class MultibandGrips:
    def __init__(self, encoder_factory=PcmEncoder, mixer_factory=Mixer, target_finder=find_pc_device):
        self.encoder = self.mixer = None
        self.target_finder = target_finder
        self.target = target_finder()
        self.epoch = None
        self.pending = bytearray()
        self.raw = QUIET_FRAME
        self.last_sent = self.last_checked = None
        self.last_frame = None
        self.softener = SustainSoftener()
        self.hold = FrequencyHold()
        self.level = LevelHold()
        self.ramp = PointRamp()
        self.trace = FrameTrace() if trace_enabled() else None
        try:
            self.encoder = encoder_factory()
            self.mixer = mixer_factory()
            self.mixer.start()
        except BaseException:
            self.close()
            raise

    def render_pcm(self, batch, now):
        if self.last_checked is None or now - self.last_checked >= 1:
            if self.target_finder() != self.target:
                raise ConnectionError("手柄连接已改变，正在重新定位 Sensa 输出")
            self.last_checked = now
        if batch.epoch != self.epoch:
            if self.epoch is not None:
                self.encoder.reset()
            self.epoch = batch.epoch
            self.pending.clear()
            self.raw = QUIET_FRAME
            self.softener.reset()
            self.hold.reset()
            self.level.reset()
            self.ramp.reset()
        self.pending.extend(batch.pcm)
        while len(self.pending) >= CHUNK_BYTES:
            self.raw = self.encoder.encode(bytes(self.pending[:CHUNK_BYTES]))
            del self.pending[:CHUNK_BYTES]
        if batch.last_audio is None or now - batch.last_audio >= .05:
            self.raw = QUIET_FRAME
            self.pending.clear()
        raw_frame = compose_frame(self.raw, batch.state)
        frame = self.hold.apply(raw_frame) if batch.state.settings.grip_soft else raw_frame
        if batch.state.settings.grip_soft:
            frame = self.level.apply(frame)
        frame = self.softener.apply(frame, batch.state.settings.grip_soft and batch.state.test_target is None, now)
        if batch.state.settings.grip_soft and batch.state.test_target is None:
            frame = self.ramp.apply(frame)
        if frame != self.last_frame or self.last_sent is None or now - self.last_sent >= .1:
            self.mixer.play(self.target, frame)
            self.last_sent, self.last_frame = now, frame
            if self.trace is not None:
                self.trace.record(now, frame, raw_frame, batch.state)

    def close(self):
        try:
            if self.mixer is not None:
                try:
                    self.mixer.play(self.target, QUIET_FRAME)
                    time.sleep(.05)
                finally:
                    try:
                        self.mixer.stop()
                    finally:
                        self.mixer.close()
        finally:
            self.mixer = None
            if self.encoder is not None:
                self.encoder.close()
                self.encoder = None
