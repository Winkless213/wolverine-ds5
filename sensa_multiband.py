"""有界 PCM 缓冲与多频游戏输出；编码和共享内存发送由独立线程调用。"""
from collections import deque
from dataclasses import dataclass, field, replace
import json
import math
import os
import pathlib
import threading
import time

import numpy as np

from pcm_encoder import CHUNK_BYTES, PcmEncoder
from sensa_frame import decode_frame
from sensa_mixer import Mixer, find_pc_device
from settings import DEFAULT_PROFILE, Settings


QUIET_FRAME = bytes.fromhex("51000000000000080000000000001000000000000080000000000000")
# 幅度码 6 位且全量程线性（离线探针实测 0–63 逐码可用）。这里限制的是「各频带峰值之和」，
# 所以 63 是能同时保证单个码不越界的最大取值；放到 126 时单带满幅叠加 1.5 增益会被算到 126，
# 写进 6 位字段会串位毁帧。旧的 32 是半量程：真实游戏录音里 14–15% 的帧被它钉死，
# 而「统一乘增益再按固定合计归一」会让 grip_gain 与 PROFILE_GAIN 在这些帧上完全失效。
MAX_AMPLITUDE = 63
MAX_PENDING = 1920 * 4
# 雷蛇“动态”预设把低频段音量压到 0.3、0/50Hz EQ 减半；同一段音频实测频带幅度只有“平衡”的 38%，
# 弱帧还会被 MIN_TOTAL 整段清零，实机听成“该震的地方没震”。这里补回电平，编码器预设保持原样。
PROFILE_GAIN = {"dynamic": 2.0}
# 只有“满配”试点档把雷蛇的冲击槽一起下发；其余档仍只走持续频带。
KEEP_TRANSIENTS = {"full"}
# 2026-10-29 实机：“打击”档节奏对了但断续不准，1–2 帧的孤立段占 20.6%（旧版 14.1%、动态 8.6%），
# 听成“该连成一片的断成点”。弱帧地板从 6 降到 4，孤立段降到 15.8%；再配合编码器窗口 0.03/0.08 降到 6.1%，
# 独立峰只从 1.13 降到 1.07 个/秒。地板 2 反而回升到 24.1%（零星噪声帧各自成段），所以停在 4。
# 只对“打击”档生效，其余档保持原观感。
PROFILE_FLOOR = {"full": 4}
# 冲击槽叠加在频带之上，而它 65% 落在 91Hz 以下、最大一档正好是 sensa-device.json 声明的
# FrequencyResonance=50。等幅叠加等于在共振点上双倍驱动：2026-11-03 实机在强度 1.0 下听成
# 「更猛烈浑厚、过了」，把全局强度拖到 0.65 后变成「挺好」。降电平就治好说明是过驱而不是选错频率
# （蜘蛛侠 2 的打击内容本身就低频主导），所以频率不动，只把槽压到那次实机认可的绝对幅度。
SLOT_GAIN = .65


@dataclass(frozen=True)
class MixState:
    settings: Settings = field(default_factory=Settings)
    rumble: tuple = (0.0, 0.0)
    test_target: str | None = None
    pressures: tuple = (0.0, 0.0)
    # 每次「全链路测试」加一；输出线程看到新值就用真编码器跑一遍合成 PCM。
    chain: int = 0


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
        # 冲击槽：最多两个，每个带幅度/频率/时间点；没有就写一个 0 结束位。
        transients = side.get("transients") or []
        for transient in transients[:2]:
            fields.append((1, 1))
            fields.extend(((transient["amplitude_code"], 6), (transient["frequency_code"], 7),
                           (transient["time_ms"], 7)))
        if len(transients) < 2:
            fields.append((0, 1))
    bits = "".join(f"{value:0{width}b}" for value, width in fields)
    bits += "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


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
                          "gain_left": state.settings.grip_gain_left,
                          "gain_right": state.settings.grip_gain_right,
                          "test": state.test_target,
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


class TransientInjector:
    """按源 PCM 的上升沿自造冲击槽：频带承载持续感，冲击槽承载攻击。

    编码器的 30ms 幅度窗口比它要还原的攻击慢 3 倍——蜘蛛侠 2 实录里 59.4% 的攻击在 10ms 内
    到 90%，源有 3.81 个 onset/秒，而输出只做出 1.3–1.6 个/秒。冲击槽是格式里唯一能表达
    「瞬间」的字段，雷蛇编码器却在 4 段录音约 88000 帧里一次都没填过它。
    严格因果：只看已经到达的 10ms 块，没有前瞻，不增加任何延迟。
    """

    HISTORY = 4    # 参照窗 40ms，正好一个输出帧
    RISE = 1.6     # 相对参照窗峰值的上升倍数
    FLOOR = .02    # 满幅 2% 以下不算攻击，与档位检测阈值同量级
    COOLDOWN = 3   # 触发后 30ms 内不再触发：同一次攻击继续爬升不是新攻击

    def __init__(self):
        self.history = [deque(maxlen=self.HISTORY) for _ in range(2)]
        self.cooldown = [0, 0]
        self.pending = (False, False)

    def push(self, pcm):
        peaks = np.abs(np.frombuffer(pcm, dtype="<i2").reshape(-1, 2)).max(axis=0) / 32768
        fired = []
        for side, peak in enumerate(peaks):
            history = self.history[side]
            previous = max(history, default=0.0)
            history.append(float(peak))
            if self.cooldown[side]:
                self.cooldown[side] -= 1
                fired.append(False)
            elif peak >= self.FLOOR and peak >= previous * self.RISE:
                self.cooldown[side] = self.COOLDOWN
                fired.append(True)
            else:
                fired.append(False)
        # 一帧里可能编码多个 10ms 块；左右分别在不同块起振时不能互相顶掉。
        self.pending = tuple(before or now for before, now in zip(self.pending, fired))

    def take(self):
        pending, self.pending = self.pending, (False, False)
        return pending


MIN_TOTAL = 6


def compose_frame(raw, state, injector=None):
    fired = injector.take() if injector is not None else None
    gains = (state.settings.grip_gain_left, state.settings.grip_gain_right)
    if (state.test_target not in (None, "grip") or (state.test_target is None and not state.settings.grip_enabled)
            or not any(gains)):
        return QUIET_FRAME
    frame = decode_frame(raw)
    if frame["duration_ms"] != 40:
        raise ValueError("PCM 编码帧时长不符合候选 profile")
    profile = getattr(state.settings, "haptic_profile", DEFAULT_PROFILE)
    makeup = PROFILE_GAIN.get(profile, 1.0)
    floor = PROFILE_FLOOR.get(profile, MIN_TOTAL)
    # 冲击槽目前只有“满配”试点档下发；其余档丢弃（pack_frame 早先没有冲击通道）。
    keep_transients = profile in KEEP_TRANSIENTS
    for index, side in enumerate(frame["channels"]):
        gain = gains[index]
        if keep_transients:
            for transient in side["transients"]:
                transient["amplitude_code"] = min(63, round(transient["amplitude_code"] * gain * makeup))
        else:
            # 2026-10-29 实机：这里原本把冲击槽判为非法，一帧就让整条输出线程重启一秒。
            side["transients"] = []
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
                point["amplitude_code"] = round(point["amplitude_code"] * gain * makeup)
        total = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
        if 0 < total <= floor:
            # 实机 2026-10-20：6–12 级的持续中弱成分听成底噪；弱帧整段屏蔽。
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            total = sum(max(point["amplitude_code"] for point in band) for band in side["bands"])
        if total > MAX_AMPLITUDE:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = math.floor(point["amplitude_code"] * MAX_AMPLITUDE / total)
    if fired is not None and keep_transients:
        for index, side in enumerate(frame["channels"]):
            if not fired[index] or not side["bands"]:
                continue
            # 幅度沿用本帧主导频带已经过增益、地板和上限处理的峰值再乘 SLOT_GAIN：只加「锐度」，
            # 电平口径与频带一致，实机 A/B 才能把「变清晰」和「变响」分开。频率就是编码器刚测到的那个。
            band = max(side["bands"], key=lambda points: max(point["amplitude_code"] for point in points))
            amplitude = round(max(point["amplitude_code"] for point in band) * SLOT_GAIN)
            if amplitude:
                side["transients"].append({"amplitude_code": amplitude,
                                           "frequency_code": band[0]["frequency_code"], "time_ms": 0})
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


def chain_chunks(seconds=1.5, gap=.3):
    """全链路测试音：左 1.5s → 静音 0.3s → 右 1.5s。

    频率取 50Hz（马达谐振点）+ 150Hz（高频带），两条带都会被编码器看到；
    严格按 10ms 块输出，和游戏音频走同一个 `PcmEncoder.encode` 入口。
    """
    total, silence = int(seconds / .01), int(gap / .01)
    for index in range(total):
        yield tone_chunk(index, side=0)
    for _ in range(silence):
        yield bytes(CHUNK_BYTES)
    for index in range(total):
        yield tone_chunk(index, side=1)


def tone_chunk(index, side, frames=480, rate=48000):
    t = (np.arange(frames) + index * frames) / rate
    wave = (0.45 * np.sin(2 * np.pi * 50 * t) + 0.15 * np.sin(2 * np.pi * 150 * t)) * 32767
    samples = np.zeros((frames, 2), dtype="<i2")
    samples[:, side] = wave.astype("<i2")
    return samples.tobytes()


class MultibandGrips:
    def __init__(self, encoder_factory=PcmEncoder, mixer_factory=Mixer, target_finder=find_pc_device):
        self.encoder = self.mixer = None
        self.profile = None
        self.target_finder = target_finder
        self.target = target_finder()
        self.epoch = None
        self.pending = bytearray()
        self.raw = QUIET_FRAME
        self.last_sent = self.last_checked = None
        self.last_frame = None
        self.transient_slots = 0
        self.rejected_frames = 0
        self.trace = FrameTrace() if trace_enabled() else None
        self.injector = TransientInjector()
        self.transient_on = None
        self.chain_token = 0
        self.chain_frames = []
        self.chain_next = 0.0
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
        profile = getattr(batch.state.settings, "haptic_profile", DEFAULT_PROFILE)
        if profile != self.profile and hasattr(self.encoder, "set_profile"):
            self.encoder.set_profile(profile)
            # 档位在日志里原本看不见，出问题只能靠猜：启动和每次实际切换都留一行。
            previous, self.profile = self.profile, profile
            print(f"PCM 档位：{profile}" + (f"（从 {previous} 切换）" if previous else ""), flush=True)
        inject = getattr(batch.state.settings, "haptic_transient", False)
        if inject != self.transient_on:
            # 必须是 ASCII：托盘把桥接 stdout 写进日志时编码是坏的，中文一律变成 U+FFFD 且不可恢复。
            # 开和关都留一行，否则无法区分「用户关了」和「开关根本没生效」。
            self.transient_on = inject
            print(f"haptic transient: {'on' if inject else 'off'}", flush=True)
        if batch.epoch != self.epoch:
            if self.epoch is not None:
                self.encoder.reset()
            self.epoch = batch.epoch
            self.pending.clear()
            self.raw = QUIET_FRAME
        if batch.state.chain != self.chain_token:
            # 新一次全链路测试：清掉游戏音频，用真编码器把合成 PCM 编成帧，再按 10ms 节奏下发。
            self.chain_token = batch.state.chain
            self.pending.clear()
            self.raw = QUIET_FRAME
            self.chain_frames = self._chain_frames() if self.chain_token else []
            self.chain_next = now
            if self.chain_frames:
                print(f"chain test: {len(self.chain_frames)} frames", flush=True)
        if self.chain_frames:
            if now >= self.chain_next:
                raw = self.chain_frames.pop(0)
                try:
                    frame = compose_frame(raw, replace(batch.state, test_target=None), None)
                except ValueError as error:
                    self.rejected_frames += 1
                    if self.rejected_frames == 1:
                        print(f"PCM 帧被跳过：{error}", flush=True)
                else:
                    self.mixer.play(self.target, frame)
                    self.last_sent, self.last_frame = now, frame
                self.chain_next = now + .01
            return
        self.pending.extend(batch.pcm)
        while len(self.pending) >= CHUNK_BYTES:
            chunk = bytes(self.pending[:CHUNK_BYTES])
            del self.pending[:CHUNK_BYTES]
            if inject:
                self.injector.push(chunk)
            raw = self.encoder.encode(chunk)
            if any(side["transients"] for side in decode_frame(raw)["channels"]):
                self.transient_slots += 1
                if self.transient_slots == 1:
                    kept = profile in KEEP_TRANSIENTS
                    print(f"PCM 帧带冲击槽：{'已随帧下发' if kept else '槽位已丢弃'}", flush=True)
            self.raw = raw
        if batch.last_audio is None or now - batch.last_audio >= .05:
            self.raw = QUIET_FRAME
            self.pending.clear()
        try:
            raw_frame = compose_frame(self.raw, batch.state, self.injector if inject else None)
        except ValueError as error:
            self.rejected_frames += 1
            if self.rejected_frames == 1:
                print(f"PCM 帧被跳过：{error}", flush=True)
            return
        if raw_frame != self.last_frame or self.last_sent is None or now - self.last_sent >= .1:
            self.mixer.play(self.target, raw_frame)
            self.last_sent, self.last_frame = now, raw_frame
            if self.trace is not None:
                # raw 必须是编码器交出来的帧，不是 compose_frame 的返回值：
                # 两者同值时 changed 恒为 False，钳位和地板做了什么在日志里完全看不见。
                self.trace.record(now, raw_frame, self.raw, batch.state)

    def _chain_frames(self):
        frames = []
        for chunk in chain_chunks():
            frames.append(self.encoder.encode(chunk))
        return frames

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
