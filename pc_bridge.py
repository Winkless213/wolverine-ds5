"""PC 模式（1532:0A4C）桥接：XInput 输入 → 虚拟 DS5；DS5 触觉与传统震动 → 雷蛇 Sensa 左右握把。

PC 模式的 xusb22 只接受左右两路强度，扳机马达不可达（WinError 87），这里没有扳机输出。
HAR / Provider 是雷蛇专有库，只从本机 Synapse 安装目录加载，不随程序分发。
"""
import base64
import ctypes as c
import hashlib
import json
import os
import pathlib
import sys
import time

import gip_bridge
from capture_recorder import decode_audio_block
from pcm_to_sensa import ENVELOPE_LIMIT, EnvelopeToSensa
from sdl_input import RazerInput
from settings import Settings

SENSA_DIR = pathlib.Path(r"C:\Program Files (x86)\Interhaptics\HapticService")
VERIFIED = {"HAR.dll": "ed774be3b3fac9d3dad0d75c8ad2e95d019fec1c4720b77957ce434e468c807e",
            "Interhaptics.RazerProvider.dll": "62465547a378d65b03e5ba2b68b1d17ed0bcfd16bdf84c9f4e179ab545b1c06b"}
LIMIT = ENVELOPE_LIMIT
RUMBLE_HZ = 50.0  # Sage T1 握把的谐振频率；传统震动只有强度，放在最有力的频点上
QUIET = (0.0, 80.0)
EFFECT_SECONDS = 600.0
HAR_SIDES = (2, 1)  # HAR 目标的 side：2 = 左握把（bodypart 216），1 = 右握把（116）


class Target(c.Structure):
    _fields_ = [("sign", c.c_int), ("group", c.c_int), ("side", c.c_int)]


class SensaGrips:
    """左右各一个常驻参数效果，每 4ms 只更新强度与频率；效果时间轴每 5 分钟从头播放，长时间运行不会到期。"""

    def __init__(self):
        for name, expected in VERIFIED.items():
            if hashlib.sha256((SENSA_DIR / name).read_bytes()).hexdigest() != expected:
                print(f"WARNING: {name} differs from the verified Synapse build", file=sys.stderr, flush=True)
        self.search = os.add_dll_directory(str(SENSA_DIR))
        self.initialized = self.up = False
        self.effects = [None, None]
        try:
            har = c.CDLL(str(SENSA_DIR / "HAR.dll"))
            provider = c.CDLL(str(SENSA_DIR / "Interhaptics.RazerProvider.dll"))

            def bind(dll, name, result, *arguments):
                function = getattr(dll, name)
                function.restype, function.argtypes = result, arguments
                return function

            pointer = c.POINTER(c.c_double)
            curve = (pointer, c.c_int, pointer, c.c_int, c.c_double, c.c_double, pointer, c.c_int, c.c_bool)
            self.stop = bind(har, "StopAllEvents", None)
            self.quit = bind(har, "Quit", None)
            self.compute = bind(har, "ComputeAllEvents", None, c.c_double)
            self.play = bind(har, "PlayEvent", None, c.c_int, c.c_double, c.c_double, c.c_double)
            self.target = bind(har, "AddTargetToEventMarshal", None, c.c_int, c.POINTER(Target), c.c_int)
            self.add = bind(har, "AddParametricEffect", c.c_int, *curve)
            self.update = bind(har, "UpdateParametricEffect", c.c_bool, c.c_int, *curve)
            self.present = bind(provider, "ProviderIsPresent", c.c_bool)
            self.clean = bind(provider, "ProviderClean", c.c_bool)
            self.render_haptics = bind(provider, "ProviderRenderHaptics", None)
            if not bind(har, "Init", c.c_bool)():
                raise ConnectionError("HAR.Init failed")
            self.initialized = True
            self.started = time.perf_counter()
            self.played = 0.0
            self.up = bool(bind(provider, "ProviderInit", c.c_bool)())
            if not self.up or not self.present():
                raise ConnectionError("No Sensa device; Razer Synapse must be running")
        except BaseException:
            self.close()
            raise

    def now(self):
        return time.perf_counter() - self.started

    def set(self, side, amplitude, frequency):
        amplitude = min(1.0, amplitude)
        curve = (c.c_double * 6)(0, amplitude, EFFECT_SECONDS - .004, amplitude, EFFECT_SECONDS, 0)
        pitch = (c.c_double * 4)(0, .5, EFFECT_SECONDS, .5)
        args = (curve, 6, pitch, 4, frequency, frequency, None, 0, False)
        if self.effects[side] is None:
            effect = self.add(*args)
            if effect < 0:
                raise RuntimeError("HAR rejected the grip effect")
            self.target(effect, c.byref(Target(1, 400, HAR_SIDES[side])), 1)
            self.play(effect, -self.now(), 0, 0)
            self.effects[side] = effect
        elif not self.update(self.effects[side], *args):
            raise RuntimeError("HAR rejected a grip update")

    def render(self):
        now = self.now()
        if now - self.played >= EFFECT_SECONDS / 2:
            for effect in self.effects:
                if effect is not None:
                    self.play(effect, -now, 0, 0)
            self.played = now
        self.compute(now)
        if not self.present():
            raise ConnectionError("Sensa device lost")
        self.render_haptics()

    def close(self):
        try:
            if self.initialized:
                self.stop()
                if self.up and self.present():
                    for _ in range(10):
                        self.compute(self.now())
                        self.render_haptics()
                        time.sleep(.005)
        finally:
            try:
                if self.up:
                    self.clean()
            finally:
                if self.initialized:
                    self.quit()
                self.initialized = self.up = False
                self.search.close()


class NullGrips:
    def set(self, side, amplitude, frequency):
        pass

    def render(self):
        pass


class GripHaptics:
    """DS5 左右触觉（包络映射）与传统震动（byte3/4）取较强者，送到 Sensa 两个握把。"""

    def __init__(self, output, settings=None):
        self.output = output
        self.settings = settings or Settings()
        self.converter = EnvelopeToSensa()
        self.test_target = None
        self.audio = [QUIET, QUIET]
        self.rumble = (0.0, 0.0)
        self.generation = self.next_frame = 0
        self.last_audio = None
        self.previous = [QUIET, QUIET]
        self.stats = {"audio_frames": 0, "audio_resyncs": 0, "audio_errors": 0, "timeouts": 0}

    def attach(self, output):
        # 新输出是静止的；记录清零后下一步把当前状态完整发一次。
        self.output = output
        self.previous = [QUIET, QUIET]

    def clear_audio(self):
        self.converter.reset()
        self.audio = [QUIET, QUIET]
        self.last_audio = None

    def accept(self, message, now):
        kind = message["type"]
        if kind == "output":
            report = base64.b64decode(message["report"], validate=True)
            # hid-playstation：flag0 bit0 或 flag2 bit2 表示 byte3（右）/byte4（左）有效。
            if len(report) > 4 and report[0] == 2 and (report[1] & 0x01 or len(report) > 39 and report[39] & 0x04):
                self.rumble = (report[4] / 255, report[3] / 255)
        elif kind == "reset":
            if message["generation"] > self.generation:
                self.clear_audio()
                self.generation, self.next_frame = message["generation"], 0
        elif kind == "stopped":
            self.clear_audio()
            self.rumble = (0.0, 0.0)
        elif kind == "audio":
            try:
                generation, first, count, source, pcm = decode_audio_block(message)
            except (ValueError, KeyError, TypeError):
                self.stats["audio_errors"] += 1
                self.clear_audio()
                return
            if source != "usb-host":
                return
            if (generation, first) != (self.generation, self.next_frame):
                # 游戏重开触觉流会让帧号跳变；从新位置重新分析，不拖垮输入链路。
                self.stats["audio_resyncs"] += generation == self.generation
                self.converter.reset()
                self.generation = generation
            parameters = self.converter.push(pcm)
            if parameters:
                self.audio = [(side["amplitude"], side["frequency_hz"]) for side in parameters[-1]["channels"]]
            self.next_frame = first + count
            self.stats["audio_frames"] += count
            self.last_audio = now

    def mix(self, l2, r2):
        gain = self.settings.grip_gain
        if self.test_target == "grip":
            pairs = [(min(1, LIMIT * gain * pressure / 255), RUMBLE_HZ) for pressure in (l2, r2)]
        elif self.test_target is not None or not self.settings.grip_enabled:
            pairs = [QUIET, QUIET]
        else:
            pairs = []
            for (amplitude, frequency), rumble in zip(self.audio, self.rumble):
                if rumble * LIMIT > amplitude:
                    amplitude, frequency = rumble * LIMIT, RUMBLE_HZ
                pairs.append((min(1, amplitude * gain), frequency))
        return [pair if pair[0] > 0 else QUIET for pair in pairs]

    def step(self, l2, r2, now):
        if self.last_audio is not None and now - self.last_audio >= .05:
            self.clear_audio()
            self.stats["timeouts"] += 1
        for side, value in enumerate(self.mix(l2, r2)):
            if value != self.previous[side]:
                self.output.set(side, *value)
                self.previous[side] = value
        self.output.render()


class Devices:
    def __init__(self, pad, grips):
        self.pad, self.grips = pad, grips

    def close(self):
        try:
            self.grips.close()
        finally:
            self.pad.close()


def open_devices():
    """手柄输入或 Sensa 任一不可用都按“等待”处理，reconnect_loop 每秒重试；原因写进状态给界面显示。"""
    try:
        pad = RazerInput()
    except RuntimeError as error:
        gip_bridge.STATUS.set("waiting", reason="input", error=str(error))
        raise ConnectionError(str(error)) from error
    try:
        grips = SensaGrips()
    except (OSError, RuntimeError) as error:
        pad.close()
        gip_bridge.STATUS.set("waiting", reason="sensa", error=str(error))
        raise ConnectionError(str(error)) from error
    return Devices(pad, grips)


def session(devices, capture_proc, events, haptics, counts):
    haptics.attach(devices.grips)
    gip_bridge.STATUS.set("connected", backend="sensa")
    print("PC-mode bridge ready: Sensa grips, no trigger motors", flush=True)
    start = last_stats = last_meter = time.monotonic()
    last_state, last_sent, input_updates = None, 0, 0
    try:
        while True:
            tick = time.monotonic()
            try:
                state = devices.pad.read()
            except RuntimeError as error:
                raise ConnectionError(str(error)) from error
            if gip_bridge.input_due(last_state, state, tick, last_sent):
                try:
                    capture_proc.stdin.write(json.dumps({"type": "input", "state": state}) + "\n")
                    capture_proc.stdin.flush()
                except BrokenPipeError:
                    print("ERROR: wolverine-capture stdin broken", file=sys.stderr, flush=True)
                    return 1
                last_state, last_sent = state, time.monotonic()
                input_updates += 1

            gip_bridge.drain(events, haptics, counts)
            haptics.step(state["L2"], state["R2"], time.monotonic())

            now = time.monotonic()
            motors = [round(side[0], 3) for side in haptics.previous] + [0, 0]
            if os.environ.get("WOLVERINE_MANAGED") and now - last_meter >= .05:
                print(json.dumps({"type": "meter", "motors": motors, "l2": state["L2"], "r2": state["R2"],
                                  "buttons": state["Buttons"], "dpad": state["DPad"],
                                  "sticks": [state[axis] for axis in ("LX", "LY", "RX", "RY")]}), flush=True)
                last_meter = now
            if now - last_stats >= 5.0:
                print(json.dumps({"elapsed_s": round(now - start, 1), "input_updates": input_updates,
                                  "grips": haptics.previous, **haptics.stats,
                                  "capture_messages": dict(counts)}), flush=True)
                last_stats = now
            if capture_proc.poll() is not None:
                print("ERROR: wolverine-capture exited", file=sys.stderr, flush=True)
                return 1
            time.sleep(max(0, .004 - (time.monotonic() - tick)))
    finally:
        haptics.attach(NullGrips())


def main():
    return gip_bridge.main(lambda capture_proc: gip_bridge.serve(
        capture_proc, make_haptics=lambda saved: GripHaptics(NullGrips(), saved),
        opener=open_devices, run_session=session))


if __name__ == "__main__":
    sys.exit(gip_bridge.run(main))
