"""复用 PC 握把映射与 Xbox 扳机映射，只有私有握把输出为实验路径。"""
import json
import time

import gip_bridge
from pc_bridge import GripHaptics, NullGrips
from xbox_sensa import SensaStream, trigger_packet


class Triggers:
    def __init__(self, host, stream=None):
        self.host, self.stream = host, stream
        self.previous = (0, 0)
        self.last_private_sent = 0
        self.paired_refreshes = 0

    def set(self, left, right, lt, rt):
        # 只有握把变化时不能附带全马达停止指令，否则会覆盖私有握把流。
        if (lt, rt) == self.previous == (0, 0):
            return
        self.host.send_message(0x09, 0, trigger_packet(lt, rt))
        self.previous = (lt, rt)
        self.last_private_sent = self.stream.sent if self.stream is not None else 0

    def refresh(self, enabled):
        if not enabled:
            self.set(0, 0, 0, 0)
        elif self.stream is not None and self.stream.sent != self.last_private_sent and any(self.previous):
            # 私有帧可能覆盖标准扳机；同轮已发送最新扳机时不重复补发。
            self.set(0, 0, *self.previous)
            self.paired_refreshes += 1


class XboxHaptics(gip_bridge.Haptics):
    def __init__(self, settings=None):
        super().__init__(gip_bridge.NullOutput(), settings)
        self.grips = GripHaptics(NullGrips(), self.settings)
        self.stream = None
        self.last_stats = time.monotonic()
        self.bridge.stats.update(backend="xbox-sensa-experimental", frequency_preserved=True)

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
            super().attach(Triggers(output, self.stream))
            print("Haptic backend: xbox-sensa-experimental; grips=private 16/0E; triggers=GIP mask 0x0F; "
                  "trigger_refresh=after-private-frame", flush=True)

    def mix(self, values, now):
        _, _, lt, rt = super().mix((0, 0, values[2], values[3]), now)
        left, right = (pair[0] for pair in self.grips.previous)
        if self.settings.trigger_follow and self.settings.trigger_enabled and self.test_target is None:
            lt, rt = max(lt, left * self.settings.follow_ratio), max(rt, right * self.settings.follow_ratio)
        return left, right, lt, rt

    def accept(self, message, now):
        kind = message["type"]
        if kind == "audio":
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
        self.grips.step(l2, r2, now)
        super().step(l2, r2, now)
        if self.stream is not None:
            self.bridge.output.refresh(self.test_target == "trigger" or
                                       self.test_target is None and self.settings.trigger_enabled)
        if self.stream is not None and time.monotonic() - self.last_stats >= 5:
            print(json.dumps({"haptic_backend": "xbox-sensa-experimental", "grips": self.grips.previous,
                              "stream_sent": self.stream.sent, "stream_accepted": self.stream.accepted,
                              "stream_pending": len(self.stream.pending),
                              "trigger_paired_refreshes": self.bridge.output.paired_refreshes}), flush=True)
            self.last_stats = time.monotonic()


def serve(capture_proc):
    return gip_bridge.serve(capture_proc, make_haptics=XboxHaptics)
