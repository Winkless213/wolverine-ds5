"""只生成进程内 Sensa 帧；不加载 Provider、不连接手柄。"""
import ctypes as c
import hashlib
import math
import os
from pathlib import Path


HAR_PATH = Path(r"C:\Program Files (x86)\Interhaptics\HapticService\HAR.dll")
HAR_SHA256 = "ed774be3b3fac9d3dad0d75c8ad2e95d019fec1c4720b77957ce434e468c807e"


class Target(c.Structure):
    _fields_ = [("sign", c.c_int), ("group", c.c_int), ("side", c.c_int)]


class OfflineSensa:
    def __init__(self):
        if c.sizeof(c.c_void_p) != 8 or hashlib.sha256(HAR_PATH.read_bytes()).hexdigest() != HAR_SHA256:
            raise RuntimeError("This offline probe requires the verified x64 HAR build")
        self.search = os.add_dll_directory(str(HAR_PATH.parent))
        self.dll = c.CDLL(str(HAR_PATH))
        self.active = False
        self.time = 0.0
        self.effects = [None, None]
        try:
            self._bind()
            if not self.init():
                raise RuntimeError("HAR.Init failed")
            self.active = True
            metadata = Path(__file__).with_name("sensa-device.json").read_bytes()
            self.device = self.add_device(metadata)
            if self.device < 0:
                raise RuntimeError("HAR rejected the recorded device metadata")
            self.parts = (c.c_int * 2)(216, 116)
            self.connection = self.connect(self.device, self.parts, 2)
            self.max_frame_bytes = self.get_size(self.device, self.parts, 2)
            if not 0 < self.max_frame_bytes <= 4096:
                raise RuntimeError("Invalid Sensa frame capacity")
            layout = (c.c_int * 256)()
            if self.decode(self.device, 2, self.parts, layout) != 0:
                raise RuntimeError("HAR could not describe the frame")
            self.layout = list(layout)[:10]
            self.compute(0)
        except Exception:
            self.close()
            raise

    def _bind(self):
        def bind(name, result, *args):
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, args
            return function
        pointer = c.POINTER(c.c_double)
        curve_args = (pointer, c.c_int, pointer, c.c_int, c.c_double, c.c_double, pointer, c.c_int, c.c_bool)
        self.init = bind("Init", c.c_bool)
        self.quit = bind("Quit", None)
        self.stop = bind("StopAllEvents", None)
        self.compute = bind("ComputeAllEvents", None, c.c_double)
        self.add_device = bind("AddDevice", c.c_int, c.c_char_p)
        self.connect = bind("AddConnectedDevice", c.c_uint64, c.c_int, c.POINTER(c.c_int), c.c_int)
        self.get_size = bind("GetFrameSize", c.c_int, c.c_int, c.POINTER(c.c_int), c.c_int)
        self.get_frame = bind("GetInterhapticsHapticFrame", c.c_int, c.c_int, c.POINTER(c.c_int), c.c_int, c.c_void_p)
        self.decode = bind("GetInterhapticsFrameDecodingData", c.c_int, c.c_int, c.c_int, c.POINTER(c.c_int), c.POINTER(c.c_int))
        self.add = bind("AddParametricEffect", c.c_int, *curve_args)
        self.update = bind("UpdateParametricEffect", c.c_bool, c.c_int, *curve_args)
        self.target_type = Target
        self.target = bind("AddTargetToEventMarshal", None, c.c_int, c.POINTER(Target), c.c_int)
        self.play = bind("PlayEvent", None, c.c_int, c.c_double, c.c_double, c.c_double)

    def set_tone(self, side, amplitude, frequency):
        if (side not in (0, 1) or not math.isfinite(amplitude) or not 0 <= amplitude <= .22
                or not math.isfinite(frequency) or not 30 <= frequency <= 400):
            raise ValueError("Tone must have a valid side, amplitude 0..0.22 and frequency 30..400 Hz")
        amplitude_curve = (c.c_double * 4)(0, amplitude, 1, amplitude)
        pitch_curve = (c.c_double * 4)(0, .5, 1, .5)
        args = (amplitude_curve, 4, pitch_curve, 4, frequency, frequency, None, 0, True)
        effect = self.effects[side]
        if effect is None:
            effect = self.add(*args)
            if effect < 0:
                raise RuntimeError("HAR rejected the tone")
            self.effects[side] = effect
            self.target(effect, c.byref(Target(1, 400, 2 if side == 0 else 1)), 1)
            self.play(effect, -self.time, 0, 0)
        elif not self.update(effect, *args):
            raise RuntimeError("HAR rejected a tone update")

    def frame(self, seconds):
        if not math.isfinite(seconds) or seconds < self.time:
            raise ValueError("HAR frame time must be finite and monotonic")
        self.time = seconds
        self.compute(seconds)
        data = (c.c_ubyte * self.max_frame_bytes)()
        size = self.get_frame(self.device, self.parts, 2, data)
        if size == -1:
            return b""
        if not 0 <= size <= self.max_frame_bytes:
            raise RuntimeError(f"Invalid Sensa frame size: {size}")
        return bytes(data[:size])

    def close(self):
        if self.active:
            self.stop()
            self.quit()
            self.active = False
        self.search.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
