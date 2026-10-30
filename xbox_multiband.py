"""Xbox 私有通道的多频握把管线：双频带分析 + compose + 实机教训整形。

与 PC 模式同一套手感规则（sensa_multiband 的移植），但分析器用本模块自己的
FFT，输出直接写成每侧两个 (幅度, 频率) 频带，交给 HAR 按 2 频带 × 2 点编码。
"""
import math
from collections import deque

import numpy as np

from settings import Settings
from sensa_multiband import MixState

QUIET_BANDS = ((0, 80), (0, 80))
SAMPLE_RATE = 48000
WINDOW = 4096
FFT_SIZE = WINDOW * 2
LOW_MAX = 80
# 60Hz 主瓣在 4096 窗下延伸到 ~83Hz；高频带从 84 起算，避免低频泄漏压过高频内容。
HIGH_MIN = 84
HIGH_MAX = 400
MIN_TOTAL = 6 / 63
FAINT_FLOOR = 16 / 63
FAINT_HIGH = 3 / 63
MAX_TOTAL = 32 / 63
LEVEL_HOLD = 2 / 63
FREQ_HOLD = 6.0
HIGH_RATIO = .8
RUMBLE_HZ = 50
# 低频走 PC 包络后的总幅度上限；旧 FFT 路径的 32/63 会把强震压掉一半。
ENVELOPE_MAX_TOTAL = 48 / 63
# PC soft profile 的高频权重：100–150Hz 只留 0.3，200Hz 以上为 0。
HIGH_EQ = ((0, 1.0), (50, 1.0), (100, .3), (130, .3), (200, 0.0))


MIN_AMPLITUDE = 2 / 63


def soft_gain(frequency):
    return max(.5, 1 - max(0, frequency - 80) / 400)


def soft_high_gain(frequency):
    if frequency <= HIGH_EQ[0][0]:
        return HIGH_EQ[0][1]
    for (low, start), (high, end) in zip(HIGH_EQ, HIGH_EQ[1:]):
        if frequency <= high:
            return start + (end - start) * (frequency - low) / (high - low)
    return HIGH_EQ[-1][1]


class BandAnalyzer:
    """滑窗 Hann FFT：每侧输出（低频带，高频带）两个 (幅度, 主频)。"""

    def __init__(self):
        self.samples = [deque(maxlen=WINDOW), deque(maxlen=WINDOW)]
        self.window = np.hanning(WINDOW)
        self.scale = 2 / self.window.sum()

    def push(self, pcm):
        if len(pcm) % 4:
            raise ValueError("PCM 必须为完整双声道 S16LE 帧")
        block = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768
        for side in (0, 1):
            self.samples[side].extend(block[:, side])

    def _band(self, samples, low, high):
        windowed = np.asarray(samples, dtype=np.float64) * self.window
        spectrum = np.abs(np.fft.rfft(windowed, FFT_SIZE))
        frequencies = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
        span = (frequencies >= low) & (frequencies < high)
        if not span.any() or spectrum[span].max() < 1e-4:
            return (0, 80)
        index = np.argmax(spectrum[span])
        base = np.flatnonzero(span)[index]
        peak = spectrum[base]
        if 0 < base < len(spectrum) - 1:
            left, right = spectrum[base - 1], spectrum[base + 1]
            offset = .5 * (left - right) / (left - 2 * peak + right + 1e-12)
            frequency = (base + offset) * SAMPLE_RATE / FFT_SIZE
        else:
            frequency = frequencies[base]
        amplitude = min(1, peak * self.scale)
        if amplitude < MIN_AMPLITUDE:
            return (0, 80)
        return (amplitude, float(min(high, max(low, frequency))))

    def render(self):
        result = []
        for side in (0, 1):
            samples = self.samples[side]
            if len(samples) < WINDOW:
                samples = [0.0] * (WINDOW - len(samples)) + list(samples)
            low = self._band(samples, 5, LOW_MAX)
            high = self._band(samples, HIGH_MIN, HIGH_MAX)
            result.append((low, high))
        return result


def shape_high_band(bands):
    """实机记录：摆荡时高频压过低频（中位 1.38），战斗时低频主导（中位 0.77）。"""
    low = bands[0][0]
    top = max(band[0] for band in bands[1:])
    if not low or not top or top <= HIGH_RATIO * low:
        return bands
    factor = max(.25, 1 / (1 + top / low - HIGH_RATIO))
    return (bands[0],) + tuple((round6(band[0] * factor), band[1]) for band in bands[1:])


def round6(value):
    return round(value * 63) / 63


def compose_side(bands, state, rumble, gain):
    low, high = bands
    strength = low[0] + high[0]
    if state.test_target == "grip" or rumble > strength:
        return ((rumble, RUMBLE_HZ), (0, 80))
    if state.settings.grip_soft:
        low = (low[0] * soft_gain(low[1]), low[1]) if low[0] else low
        high = (high[0] * soft_gain(high[1]), high[1]) if high[0] else high
        bands = shape_high_band((low, high))
        low, high = bands
    low = (round6(low[0] * gain), low[1]) if low[0] else low
    high = (round6(high[0] * gain), high[1]) if high[0] else high
    total = low[0] + high[0]
    if 0 < total <= MIN_TOTAL:
        if state.settings.grip_soft and state.test_target is None and low[0] and high[0] <= FAINT_HIGH:
            low = (round6(low[0] * FAINT_FLOOR / low[0]) if low[0] else low[0], low[1])
        else:
            low = high = (0, low[1] if low[0] else 80)
    total = low[0] + high[0]
    if total > MAX_TOTAL:
        floor = MAX_TOTAL / total
        low = (round6(low[0] * floor), low[1]) if low[0] else low
        high = (round6(high[0] * floor), high[1]) if high[0] else high
    return (low, high)


def compose_bands(sides, state):
    gains = (state.settings.grip_gain_left, state.settings.grip_gain_right)
    if (state.test_target not in (None, "grip")
            or state.test_target is None and not state.settings.grip_enabled
            or not any(gains)):
        return [QUIET_BANDS, QUIET_BANDS]
    return [compose_side(bands, state, state.rumble[index], gains[index])
            for index, bands in enumerate(sides)]


def compose_envelope(values, sides, state):
    """低频直接复用 PC 包络值，高频只留很轻的纹理。

    values 来自 GripHaptics 的 EnvelopeToSensa（已含 0.75 次方、增益和传统震动），
    不再经过 FFT 低频的 2/63 门限和 16/63 固定平台；高频按 PC soft 权重压到 200Hz 以上为 0。
    """
    gains = (state.settings.grip_gain_left, state.settings.grip_gain_right)
    if (state.test_target not in (None, "grip")
            or state.test_target is None and not state.settings.grip_enabled
            or not any(gains)):
        return [QUIET_BANDS, QUIET_BANDS]
    result = []
    for index, value in enumerate(values):
        low = (float(value[0]), float(value[1])) if value[0] else (0, 80)
        side = sides[index] if index < len(sides) else ()
        high = side[1] if len(side) > 1 else (0, 80)
        if state.settings.grip_soft and high[0]:
            high = (high[0] * soft_high_gain(high[1]), high[1])
        high = (round6(high[0] * gains[index]), high[1]) if high[0] else (0, 80)
        low = (round6(low[0]), low[1]) if low[0] else (0, 80)
        if state.settings.grip_soft:
            low, high = shape_high_band((low, high))
        total = low[0] + high[0]
        if total > ENVELOPE_MAX_TOTAL:
            scale = ENVELOPE_MAX_TOTAL / total
            low = (round6(low[0] * scale), low[1]) if low[0] else low
            high = (round6(high[0] * scale), high[1]) if high[0] else high
        result.append((low, high))
    return result


class FrequencyHold:
    """实机记录：小幅逐帧跳变沿用上一个频率，避免音高抖动；大跳变照实跟踪。"""

    def __init__(self):
        self.held = [None, None]

    def reset(self):
        self.held = [None, None]

    def apply(self, sides):
        output = []
        for index, bands in enumerate(sides):
            low = bands[0]
            if not low[0]:
                self.held[index] = None
                output.append(bands)
                continue
            previous = self.held[index]
            if previous is None or abs(low[1] - previous) > FREQ_HOLD:
                self.held[index] = low[1]
                output.append(bands)
                continue
            if abs(low[1] - previous) > 1:
                output.append(((low[0], previous),) + bands[1:])
            else:
                output.append(bands)
        return output


class LevelHold:
    """实机：中弱震动的 ±1 级逐帧闪烁听成若有若无；小变化沿用上一帧比例。"""

    def __init__(self):
        self.held = [None, None]

    def reset(self):
        self.held = [None, None]

    def apply(self, sides):
        output = []
        for index, bands in enumerate(sides):
            live = [band for band in bands if band[0]]
            if not live:
                self.held[index] = None
                output.append(bands)
                continue
            top = max(band[0] for band in live)
            previous = self.held[index]
            if previous is None or abs(top - previous) >= LEVEL_HOLD:
                self.held[index] = top
                output.append(bands)
                continue
            if top != previous:
                ratio = previous / top
                output.append(tuple((round6(band[0] * ratio) if band[0] else 0, band[1]) for band in bands))
            else:
                output.append(bands)
        return output
