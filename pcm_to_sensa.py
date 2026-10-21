"""48kHz 左右触觉到两个独立主频参数；不是任意 PCM 透传。"""
import numpy as np


SAMPLE_RATE = 48000
HOP_FRAMES = 192
WINDOW_FRAMES = 1920
FFT_SIZE = 8192
AMPLITUDE_LIMIT = .22
LOW_FREQUENCIES = np.arange(20, 70.5, .5)
LOW_PHASE = 2 * np.pi * LOW_FREQUENCIES[:, None] * np.arange(WINDOW_FRAMES) / SAMPLE_RATE
LOW_BASIS = np.stack((np.sin(LOW_PHASE), np.cos(LOW_PHASE), np.ones_like(LOW_PHASE)), axis=1)
LOW_INVERSE = np.linalg.pinv(LOW_BASIS.transpose(0, 2, 1))


def quiet_channels():
    return [{"bodypart": part, "amplitude": 0.0, "frequency_hz": 80.0} for part in (216, 116)]


def low_tone(samples):
    coefficients = LOW_INVERSE @ samples
    residual = samples @ samples - np.sum(coefficients * (LOW_BASIS @ samples), axis=1)
    index = int(np.argmin(residual))
    centered = samples - samples.mean()
    if residual[index] > .01 * (centered @ centered):
        return None
    return float(LOW_FREQUENCIES[index]), float(np.hypot(*coefficients[index, :2]))


def recent_amplitude(recent, frequency, fallback):
    phase = 2 * np.pi * frequency * np.arange(len(recent)) / SAMPLE_RATE
    basis = np.column_stack((np.sin(phase), np.cos(phase), np.ones(len(recent))))
    coefficients, residual, _, _ = np.linalg.lstsq(basis, recent, rcond=None)
    centered = recent - recent.mean()
    # 已跟踪的单频可在当前 4ms 内更新强度；复杂波形仍退回频谱幅度，避免盲目外推。
    if residual.size and residual[0] <= .01 * (centered @ centered):
        return float(np.hypot(*coefficients[:2]))
    return fallback


def dominant_tone(samples, recent, bodypart, limit=AMPLITUDE_LIMIT):
    tone = {"bodypart": bodypart, "amplitude": 0.0, "frequency_hz": 80.0}
    if np.max(np.abs(recent)) < 1 / 32768 or np.ptp(recent) < 1 / 32768:
        return tone
    window = np.hanning(len(samples))
    spectrum = np.abs(np.fft.rfft((samples - samples.mean()) * window, n=FFT_SIZE))
    lower = int(30 * FFT_SIZE / SAMPLE_RATE)
    upper = int(np.ceil(400 * FFT_SIZE / SAMPLE_RATE))
    index = lower + int(np.argmax(spectrum[lower:upper + 1]))
    # 40ms 仅含约一个 30Hz 周期；窄带低频用含直流项的最小二乘消除相位偏差。
    fitted = low_tone(samples) if len(samples) == WINDOW_FRAMES and index * SAMPLE_RATE / FFT_SIZE <= 70 else None
    if fitted is not None:
        frequency, amplitude = fitted
        if 30 <= frequency <= 400:
            amplitude = recent_amplitude(recent, frequency, amplitude)
            tone.update(amplitude=min(limit, amplitude * limit), frequency_hz=frequency)
        return tone
    if (spectrum[index] < spectrum.max() * .05 or spectrum[index] <= spectrum[index - 1]
            or spectrum[index] <= spectrum[index + 1]):
        return tone
    # 对数峰值插值降低栅格误差；补零本身不增加实际频率分辨率。
    left, center, right = np.log(np.maximum(spectrum[index - 1:index + 2], 1e-20))
    offset = float(.5 * (left - right) / (left - 2 * center + right))
    frequency = (index + offset) * SAMPLE_RATE / FFT_SIZE
    amplitude = float(2 * np.exp(center - .25 * (left - right) * offset) / window.sum())
    if not 28 <= frequency <= 402 or amplitude < .002:
        return tone
    amplitude = recent_amplitude(recent, frequency, amplitude)
    tone.update(amplitude=min(limit, amplitude * limit),
                frequency_hz=float(np.clip(frequency, 30, 400)))
    return tone


class PcmToSensa:
    def __init__(self, limit=AMPLITUDE_LIMIT):
        self.limit = limit
        self.reset()

    def reset(self):
        self.pending = np.empty((0, 2))
        self.history = np.empty((0, 2))
        self.frames = 0

    @property
    def buffered_frames(self):
        return len(self.pending)

    def push(self, pcm):
        if not pcm or len(pcm) % 4:
            raise ValueError("Expected complete, nonempty stereo S16LE frames")
        samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768
        self.pending = np.concatenate((self.pending, samples))
        result = []
        while len(self.pending) >= HOP_FRAMES:
            recent = self.pending[:HOP_FRAMES]
            self.pending = self.pending[HOP_FRAMES:]
            self.history = np.concatenate((self.history, recent))[-WINDOW_FRAMES:]
            self.frames += HOP_FRAMES
            channels = [dominant_tone(self.history[:, side], recent[:, side], part, self.limit)
                        for side, part in enumerate((216, 116))]
            result.append({"end_frame": self.frames, "warmup": len(self.history) < WINDOW_FRAMES,
                           "channels": channels})
        return result


ENVELOPE_FRAMES = 480
ENVELOPE_GAIN = 1.2
ENVELOPE_LIMIT = 1.0
ENVELOPE_EXPONENT = .75
SPECTRUM_FREQUENCIES = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
ENVELOPE_BAND = (SPECTRUM_FREQUENCIES >= 5) & (SPECTRUM_FREQUENCIES <= 400)
ENVELOPE_FREQUENCIES = SPECTRUM_FREQUENCIES[ENVELOPE_BAND]
# 雷蛇本机给战狼的音频转震动 profile：haptic_EQ 50Hz 以下 1、100–150Hz 0.3，输入 30–130Hz 线性压到 30–80Hz；
# 130Hz 以上在其带通外，这里到 200Hz 衰减为 0。
SOFT_WEIGHTS = np.interp(SPECTRUM_FREQUENCIES, (0, 50, 100, 130, 200), (1, 1, .3, .3, 0))


def envelope_tone(samples, bodypart, soft=False):
    """10ms 峰值包络 ×1.2 后取 0.75 次方作强度：游戏多数触觉只有满幅的 2–5%，线性映射在握把上几乎摸不到；
    开平方又把强弱压得太平，实机整体偏强。主频含 30Hz 以下（DS5 触觉常在 12–23Hz），夹到 Sensa 的 30–400Hz。
    soft 按雷蛇 profile 先做频率加权再取强度和主频，并把主频往低处压。"""
    quiet = {"bodypart": bodypart, "amplitude": 0.0, "frequency_hz": 80.0}
    recent = samples[-ENVELOPE_FRAMES:]
    level = ENVELOPE_GAIN * float(np.sqrt(np.mean(recent ** 2))) * np.sqrt(2)
    if level <= .01:
        return quiet
    spectrum = np.abs(np.fft.rfft((samples - samples.mean()) * np.hanning(len(samples)), n=FFT_SIZE))
    if soft:
        weighted = spectrum * SOFT_WEIGHTS
        level *= float(np.sqrt(np.sum(weighted ** 2) / max(np.sum(spectrum ** 2), 1e-20)))
        spectrum = weighted
        if level <= .01:
            return quiet
    amplitude = min(ENVELOPE_LIMIT, level ** ENVELOPE_EXPONENT)
    peak = float(ENVELOPE_FREQUENCIES[np.argmax(spectrum[ENVELOPE_BAND])])
    if soft:
        peak = 30 + (peak - 30) / 2
    return {"bodypart": bodypart, "amplitude": amplitude, "frequency_hz": float(np.clip(peak, 30, 400))}


class EnvelopeToSensa(PcmToSensa):
    """PC 模式 Sensa 用的映射（实机对比后选定）：不丢 30Hz 以下的能量，强度跟随包络。"""

    soft = False

    def push(self, pcm):
        if not pcm or len(pcm) % 4:
            raise ValueError("Expected complete, nonempty stereo S16LE frames")
        samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768
        self.pending = np.concatenate((self.pending, samples))
        result = []
        while len(self.pending) >= HOP_FRAMES:
            self.history = np.concatenate((self.history, self.pending[:HOP_FRAMES]))[-WINDOW_FRAMES:]
            self.pending = self.pending[HOP_FRAMES:]
            self.frames += HOP_FRAMES
            result.append({"end_frame": self.frames, "warmup": len(self.history) < WINDOW_FRAMES,
                           "channels": [envelope_tone(self.history[:, side], part, self.soft)
                                        for side, part in enumerate((216, 116))]})
        return result
