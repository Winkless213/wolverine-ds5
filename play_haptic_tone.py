"""往 DualSense 扬声器端点播 3 秒 4 声道 80Hz 正弦，验证 Windows → 虚拟 DS5 等时 OUT 链路。"""
import sys

import numpy as np
import sounddevice as sd

device = next(i for i, d in enumerate(sd.query_devices())
              if "DualSense" in d["name"] and d["max_output_channels"] >= 4
              and sd.query_hostapis(d["hostapi"])["name"] == "Windows WASAPI")
info = sd.query_devices(device)
print("device", device, info["name"], info["max_output_channels"], info["default_samplerate"], flush=True)
rate, channels = int(info["default_samplerate"]), info["max_output_channels"]
t = np.arange(rate * 3) / rate
tone = (0.5 * np.sin(2 * np.pi * 80 * t)).astype(np.float32)
data = np.zeros((len(t), channels), dtype=np.float32)
data[:, 2:4] = tone[:, None]  # DS5 触觉在第 3/4 声道
sd.play(data, rate, device=device, blocking=True)
print("played", flush=True)
