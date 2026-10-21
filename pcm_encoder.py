"""复用本机已核验的雷蛇 PCM 编码器；此模块不连接输出设备。"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path

import numpy as np


ENCODER_SHA256 = "433b2ee530babcb77d07e4efcc99320ba2509893a732d8b0046ab0c302e62801"
CHUNK_BYTES = 480 * 4


def game_profile():
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


class PcmEncoder:
    def __init__(self):
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
                self.pointer, json.dumps(game_profile()).encode()))
            self.checked(self.function(2, c.c_uint16, c.c_double, c.c_double, c.c_double)(
                self.pointer, 1, 0, .9))
            self._encode = self.function(15, c.c_uint16, c.POINTER(c.c_double), c.c_uint, c.c_uint,
                                         c.c_double, c.c_double)
            self._size = self.function(18, c.c_uint32)
            self._copy = self.function(19, c.c_uint16, c.c_void_p, c.c_int)
        except BaseException:
            self.close()
            raise

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
