"""四个马达同走一条私有 Sensa 帧：握把沿用 PC 模式映射，扳机带自己的载波频率。"""
import json
import time

import gip_bridge
from pc_bridge import GripHaptics, NullGrips
from xbox_sensa import SensaStream, trigger_packet


class Triggers:
    """私有流在场时扳机与握把同帧下发；没有私有流才回退到实机验证过的 GIP 0x0F 指令。"""

    def __init__(self, host, stream=None, tones=None):
        self.host, self.stream, self.tones = host, stream, tones
        self.previous = (0, 0)

    def set(self, left, right, lt, rt):
        if (lt, rt) == self.previous == (0, 0):
            return
        self.previous = (lt, rt)
        if self.stream is None:
            self.host.send_message(0x09, 0, trigger_packet(lt, rt))
            return
        left_hz, right_hz = self.tones()
        self.stream.set_triggers(((lt, left_hz), (rt, right_hz)))

    def stop_now(self):
        """关掉扳机震动要当拍就停，不能等 20ms 限频窗口或下一次值变化。"""
        self.set(0, 0, 0, 0)


class XboxHaptics(gip_bridge.Haptics):
    def __init__(self, settings=None, private=True):
        self.private = private
        super().__init__(gip_bridge.NullOutput(), settings, trigger_tone=private)
        self.grips = GripHaptics(NullGrips(), self.settings)
        self.stream = None
        self.last_stats = time.monotonic()
        self.bridge.stats.update(backend="xbox-sensa-private" if private else "gip-rumble-fallback",
                                 frequency_preserved=private)

    def trigger_tones(self):
        return (self.mapper.left.tone_hz, self.mapper.right.tone_hz)

    def trace_state(self, l2, r2):
        state = super().trace_state(l2, r2)
        state.update(grips=[list(value) for value in self.grips.previous],
                     tones=[self.mapper.left.tone_hz, self.mapper.right.tone_hz])
        if self.stream is not None:
            state.update(bands=[[list(band) for band in side] for side in self.stream.bands],
                         stream_triggers=[list(pair) for pair in self.stream.triggers],
                         stream_sent=self.stream.sent, stream_accepted=self.stream.accepted)
        return state

    def attach(self, output, grips=None):
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError as error:
                print(f"Xbox Sensa cleanup: {error!r}", flush=True)
            finally:
                self.stream = None
        if isinstance(output, gip_bridge.NullOutput):
            self.grips.attach(NullGrips())
            super().attach(output)
        else:
            self.stream = SensaStream(output) if grips is None else None
            self.grips.attach(self.stream if grips is None else grips)
            super().attach(Triggers(output, self.stream, self.trigger_tones))
            print("Haptic backend: xbox-sensa-private; grips=216/116, triggers=249/149, "
                  "all four in one 16/0E frame", flush=True)

    def mix(self, values, now):
        _, _, lt, rt = super().mix((0, 0, values[2], values[3]), now)
        left, right = (pair[0] for pair in self.grips.previous)
        if self.settings.trigger_follow and self.settings.trigger_enabled and self.test_target is None:
            lt, rt = max(lt, left * self.settings.follow_ratio), max(rt, right * self.settings.follow_ratio)
        return left, right, lt, rt

    def accept(self, message, now):
        kind = message["type"]
        if kind == "audio":
            self.record(message)
            if self.bridge.ended or message.get("generation", 0) < self.grips.generation:
                return
            if message.get("host_queue_us", 0) > 50000:
                self.grips.clear_audio()
                self.audio_errors += 1
                return
            self.grips.accept(message, now)
            self.bridge.stats["audio_frames"] = self.grips.stats["audio_frames"]
            self.audio_errors = self.grips.stats["audio_errors"]
            return
        try:
            super().accept(message, now)
        except (ValueError, TypeError):
            self.grips.clear_audio()
            self.grips.rumble = (0, 0)
            if self.stream is not None:
                self.stream.stop()
            raise
        self.grips.accept(message, now)
        if kind in ("reset", "stopped"):
            self.mapper.reset()
            self.grips.rumble = (0, 0)
            if self.stream is not None:
                self.stream.stop()

    def step(self, l2, r2, now):
        self.grips.settings, self.grips.test_target = self.settings, self.test_target
        if self.bridge.ended or self.bridge.last_poll is not None and now - self.bridge.last_poll > .05:
            self.grips.clear_audio()
            self.grips.rumble = (0, 0)
            if self.stream is not None:
                self.stream.stop()
        # 先算扳机再渲染握把：四路进同一帧，扳机不会落后一个渲染周期。
        super().step(l2, r2, now)
        triggers_on = self.test_target == "trigger" or (self.test_target is None
                                                        and self.settings.trigger_enabled)
        if self.stream is not None and not triggers_on:
            self.bridge.output.stop_now()
        self.grips.step(l2, r2, now)
        if self.stream is not None and time.monotonic() - self.last_stats >= 5:
            print(json.dumps({"haptic_backend": "xbox-sensa-private", "grips": self.grips.previous,
                              "bands": self.stream.bands, "triggers": self.stream.triggers,
                              "stream_sent": self.stream.sent, "stream_accepted": self.stream.accepted,
                              "stream_pending": len(self.stream.pending)}), flush=True)
            self.last_stats = time.monotonic()


def serve(capture_proc):
    return gip_bridge.serve(capture_proc, make_haptics=XboxHaptics)
