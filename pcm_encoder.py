"""复用本机已核验的雷蛇 PCM 编码器；此模块不连接输出设备。"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path

import numpy as np


ENCODER_SHA256 = "433b2ee530babcb77d07e4efcc99320ba2509893a732d8b0046ab0c302e62801"
CHUNK_BYTES = 480 * 4
PROFILES = ("legacy", "controlled", "balanced", "balanced_plus", "dynamic", "full")


def game_profile(name="legacy"):
    """雷蛇 PCM 编码器 profile。

    controlled / balanced / dynamic 抄自本机 Synapse「音频到触觉」三档预设
    （RzAudioCapture.log 的 CA2HDevice::SetProfile 原文）；legacy 是本项目此前
    自调的双频带候选，保留用于 A/B 对照。
    """
    if name == "controlled":
        return {"volume": 1, "transients": {"volume": 0, "prominence": .4, "duration": .022},
                "underlying_bands": {"volume": 3, "bands": [
                    {"volume": .7, "amplitude_window_length": .04, "frequency_window_length": .125,
                     "minimal_amplitude_threshold": .03,
                     "frequency_range": {"min": 30, "max": 130},
                     "output_frequency_range": {"min": 30, "max": 80}}]},
                "haptic_EQ": {"is_before_compressor": True,
                              "keyframes": [{"frequency": 0, "volume": 1}, {"frequency": 50, "volume": 1},
                                            {"frequency": 100, "volume": .3},
                                            {"frequency": 150, "volume": .3}]},
                "compressor": {"amp_limit": 1, "amp_comp": .5, "amp_comp_ratio": .5, "gamma": 3}}
    if name == "balanced":
        return {"volume": 1, "transients": {"volume": 0, "prominence": .4, "duration": .022},
                "underlying_bands": {"volume": 7, "bands": [
                    {"volume": .7, "amplitude_window_length": .04, "frequency_window_length": .125,
                     "minimal_amplitude_threshold": .01,
                     "frequency_range": {"min": 30, "max": 150},
                     "output_frequency_range": {"min": 30, "max": 100}}]},
                "haptic_EQ": {"is_before_compressor": True,
                              "keyframes": [{"frequency": 0, "volume": 2}, {"frequency": 50, "volume": 2},
                                            {"frequency": 100, "volume": 1},
                                            {"frequency": 150, "volume": 0}]},
                "compressor": {"amp_limit": 1, "amp_comp": .25, "amp_comp_ratio": .3, "gamma": 5}}
    if name == "balanced_plus":
        # 平衡档原样，只把检测阈值从 0.01 降到 0.004：游戏触觉实测多在满幅 2–5%，
        # 0.01 时 2% 输入直接输出 0；降到 0.004 后 2% 起才出得来，响段行为不变。
        profile = game_profile("balanced")
        profile["underlying_bands"]["bands"][0]["minimal_amplitude_threshold"] = .004
        return profile
    if name == "full":
        # 试点档“打击”：不追覆盖，追一拳一拳分得开。
        # 实测（60s 真实游戏触觉录音）三带方案把帧填满、打击被抹平（peaks/s 1.00、响帧占 26.9%）；
        # 去掉 200–400 带、把幅度/频率窗口从 .04/.125 缩到 .02/.06、压缩器换成旧版那套松压缩，
        # 并把两带音量抬到 1.2/.9 补回电平后：peaks/s 1.35、响帧 13.2%、与源包络相关 0.72。
        # 2026-10-29 实机再反馈“断成点”：窗口 .02/.06 时 1–2 帧的孤立段占 20.6%，比旧版 14.1% 更碎；
        # 放到 .03/.08 后同场景降到 12.5%（叠加档位地板 4 后 6.1%），独立峰只从 1.13 掉到 1.07。
        return {"volume": 1, "transients": {"volume": 1, "prominence": 1.4, "duration": .022},
                "underlying_bands": {"volume": 7, "bands": [
                    {"volume": 1.2, "amplitude_window_length": .03, "frequency_window_length": .08,
                     "minimal_amplitude_threshold": .004,
                     "frequency_range": {"min": 30, "max": 100},
                     "output_frequency_range": {"min": 30, "max": 100}},
                    {"volume": .9, "amplitude_window_length": .03, "frequency_window_length": .08,
                     "minimal_amplitude_threshold": .004,
                     "frequency_range": {"min": 100, "max": 200},
                     "output_frequency_range": {"min": 100, "max": 200}}]},
                "haptic_EQ": {"is_before_compressor": True,
                              "keyframes": [{"frequency": 0, "volume": 1}, {"frequency": 50, "volume": 1},
                                            {"frequency": 100, "volume": 1}, {"frequency": 200, "volume": .8}]},
                "compressor": {"amp_limit": 1, "amp_comp": .5, "amp_comp_ratio": .5, "gamma": 3}}
    if name == "dynamic":
        return {"volume": 1, "transients": {"volume": 1, "prominence": 1.4, "duration": .022},
                "underlying_bands": {"volume": 6, "bands": [
                    {"volume": .3, "amplitude_window_length": .03, "frequency_window_length": .125,
                     "minimal_amplitude_threshold": .005,
                     "frequency_range": {"min": 30, "max": 100},
                     "output_frequency_range": {"min": 30, "max": 100}},
                    {"volume": .1, "amplitude_window_length": .03, "frequency_window_length": .125,
                     "minimal_amplitude_threshold": .005,
                     "frequency_range": {"min": 100, "max": 200},
                     "output_frequency_range": {"min": 100, "max": 200}}]},
                "haptic_EQ": {"is_before_compressor": True,
                              "keyframes": [{"frequency": 0, "volume": .5}, {"frequency": 50, "volume": .5},
                                            {"frequency": 100, "volume": 1}, {"frequency": 150, "volume": 1},
                                            {"frequency": 200, "volume": .5}]},
                "compressor": {"amp_limit": 1, "amp_comp": .25, "amp_comp_ratio": .3, "gamma": 5}}
    if name != "legacy":
        raise ValueError(f"未知触觉配置文件：{name}")
    # 低频映射到握把可达范围；降低门槛才能保留游戏里满幅 2–5% 的触觉。
    bands = [{"volume": .7, "amplitude_window_length": .04, "frequency_window_length": .125,
              "minimal_amplitude_threshold": .005,
              "frequency_range": {"min": low, "max": high},
              "output_frequency_range": {"min": max(30, low), "max": high}}
             for low, high in ((5, 80), (80, 400))]
    return {"volume": 1, "transients": {"volume": 0, "prominence": .4, "duration": .022},
            "underlying_bands": {"volume": .9, "bands": bands},
            "haptic_EQ": {"is_before_compressor": True,
                          "keyframes": [{"frequency": 0, "volume": 1}, {"frequency": 400, "volume": 1}]},
            "compressor": {"amp_limit": 1, "amp_comp": .5, "amp_comp_ratio": .5, "gamma": 3}}


# 桥接侧调音：雷蛇原档直接下发时，「受控」的阈值 0.03 加松压缩让游戏常见的
# 1–8% 触觉幅度输出恒为 0（实测 65Hz 8% 仍为 0），作为轻柔档太死。
# 保留它 30–130→30–80 的窄带，只把检测阈值降到 0.01、100Hz 以上 EQ 从 0.3 提到 0.5、
# 压缩器换成雷蛇另外两档用的 0.25/0.3/γ5：有事件、电平仍约为平衡的 55%。
TUNING = {"controlled": {"threshold": .01, "eq_high": .5,
                         "compressor": {"amp_limit": 1, "amp_comp": .25, "amp_comp_ratio": .3, "gamma": 5}}}


def tuned_profile(name):
    """雷蛇原文 + 桥接侧调音；没有调音项的档位与原文完全一致。"""
    profile = game_profile(name)
    tuning = TUNING.get(name)
    if not tuning:
        return profile
    band = profile["underlying_bands"]["bands"][0]
    band["minimal_amplitude_threshold"] = tuning["threshold"]
    for keyframe in profile["haptic_EQ"]["keyframes"]:
        if keyframe["frequency"] >= 100:
            keyframe["volume"] = tuning["eq_high"]
    profile["compressor"] = dict(tuning["compressor"])
    return profile


class PcmEncoder:
    def __init__(self, profile="legacy"):
        self.profile = profile
        path = (Path(os.environ["LOCALAPPDATA"]) / "Razer/RazerAppEngine/User Data/Apps/Common/"
                "RzInterhapticsHapticEncoder_v2.0.1.11.dll")
        if hashlib.sha256(path.read_bytes()).hexdigest() != ENCODER_SHA256:
            raise RuntimeError("雷蛇编码器版本不匹配；多频候选未启动")
        self.dll = c.WinDLL(str(path))
        self.dll.AcquireEncoderWithVirtualDevice.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
        self.dll.AcquireEncoderWithVirtualDevice.restype = c.c_uint16
        self.dll.ReleaseEncoder.argtypes = [c.c_void_p]
        self.dll.ReleaseEncoder.restype = c.c_uint16
        self.pointer = c.c_void_p()
        self.reset()

    def function(self, slot, result, *arguments):
        table = c.cast(c.cast(self.pointer, c.POINTER(c.c_void_p))[0], c.POINTER(c.c_void_p))
        return c.WINFUNCTYPE(result, c.c_void_p, *arguments)(table[slot])

    @staticmethod
    def checked(code):
        if code:
            raise RuntimeError(f"雷蛇 PCM 编码失败：{code}")

    def reset(self):
        self.close()
        metadata = json.dumps(json.loads(Path(__file__).with_name("sensa-device.json")
                                        .read_text(encoding="utf-8")), separators=(",", ":")).encode()
        if not 16 <= len(metadata) < 0xFFF:
            raise ValueError("设备描述长度不符合已核验的 ABI")
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.GetProcessHeap.restype = c.c_void_p
        kernel.HeapAlloc.argtypes = [c.c_void_p, c.c_uint32, c.c_size_t]
        kernel.HeapAlloc.restype = c.c_void_p
        allocation = kernel.HeapAlloc(kernel.GetProcessHeap(), 0, len(metadata) + 1)
        if not allocation:
            raise MemoryError("无法分配编码器元数据")
        c.memmove(allocation, metadata + b"\0", len(metadata) + 1)
        # 工厂按值接收 MSVC string 并负责释放，必须使用同一 Windows process heap。
        string = (c.c_uint64 * 4)(allocation, 0, len(metadata), len(metadata))
        try:
            self.checked(self.dll.AcquireEncoderWithVirtualDevice(c.addressof(string), c.byref(self.pointer)))
            if not self.pointer:
                raise RuntimeError("编码器未返回实例")
            self.checked(self.function(0, c.c_uint16, c.c_uint8)(self.pointer, 1))
            self.checked(self.function(1, c.c_uint16, c.c_char_p)(
                self.pointer, json.dumps(tuned_profile(self.profile)).encode()))
            self.checked(self.function(2, c.c_uint16, c.c_double, c.c_double, c.c_double)(
                self.pointer, 1, 0, .9))
            self._encode = self.function(15, c.c_uint16, c.POINTER(c.c_double), c.c_uint, c.c_uint,
                                         c.c_double, c.c_double)
            self._size = self.function(18, c.c_uint32)
            self._copy = self.function(19, c.c_uint16, c.c_void_p, c.c_int)
        except BaseException:
            self.close()
            raise

    def set_profile(self, name):
        """运行中切换编码器 profile；失败时保持旧档位并抛错。"""
        if name == self.profile:
            return
        self.checked(self.function(1, c.c_uint16, c.c_char_p)(
            self.pointer, json.dumps(tuned_profile(name)).encode()))
        self.profile = name

    def encode(self, pcm):
        if len(pcm) != CHUNK_BYTES:
            raise ValueError("编码器只接受 10ms、48kHz 的双声道 S16LE")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768
        self.checked(self._encode(self.pointer, samples.ctypes.data_as(c.POINTER(c.c_double)),
                                  samples.size, 2, 48000, 1))
        size = self._size(self.pointer)
        if not 0 < size <= 52:
            raise RuntimeError(f"编码帧长度无效：{size}")
        output = c.create_string_buffer(size)
        self.checked(self._copy(self.pointer, output, size))
        return output.raw

    def close(self):
        if self.pointer:
            self.dll.ReleaseEncoder(self.pointer)
            self.pointer = c.c_void_p()
