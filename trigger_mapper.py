"""DS5 效果到扳机震动的近似映射；不模拟机械阻力。"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Effect:
    mode: int = 5
    strengths: tuple = (0.0,) * 10
    start: float = 0
    end: float = 1
    strength: float = 0
    frequency: int = 0


def decode_effect(data):
    if len(data) != 11:
        return Effect()
    mode = data[0]
    mask = int.from_bytes(data[1:3], "little")
    if mask & ~0x3ff:
        return Effect()
    if mode in (0x21, 0x26):
        packed = int.from_bytes(data[3:7], "little")
        strengths = tuple((((packed >> (3 * zone)) & 7) + 1) / 8
                          if mask & (1 << zone) else 0.0 for zone in range(10))
        return Effect(mode, strengths, frequency=data[9])
    if mode == 0x25:
        zones = [zone for zone in range(10) if mask & (1 << zone)]
        if len(zones) == 2 and 2 <= zones[0] <= 7 and zones[0] < zones[1] <= 8 and data[3] <= 7:
            return Effect(mode, start=zones[0] / 10, end=zones[1] / 10,
                          strength=(data[3] + 1) / 8)
    return Effect()


class Trigger:
    def __init__(self, gain=0.22):
        self.gain = gain
        self.effect = Effect()
        self.previous = None
        self.armed = False
        self.pulse_until = -1.0
        self.rhythm_started = None

    def set_effect(self, effect):
        # 游戏常重发相同效果；重发不能重新装填或重置脉冲时钟。
        if effect == self.effect:
            return
        self.effect = effect
        self.pulse_until = -1.0
        self.armed = self.previous is not None and self.previous < effect.start
        self.rhythm_started = None

    def sample(self, position, now):
        if not math.isfinite(position) or not 0 <= position <= 1 or not math.isfinite(now):
            self.__init__(self.gain)
            return 0.0
        effect = self.effect
        amplitude = 0.0
        zone = min(9, int(position * 10))
        if effect.mode == 0x21:
            amplitude = effect.strengths[zone]
        elif effect.mode == 0x25:
            if position <= effect.start - 0.02:
                self.armed = True
            if self.armed and self.previous is not None and self.previous < effect.end <= position:
                self.pulse_until = now + 0.035
                self.armed = False
            if now < self.pulse_until:
                amplitude = effect.strength
        elif effect.mode == 0x26 and effect.frequency:
            amplitude = effect.strengths[zone]
            if amplitude == 0:
                self.rhythm_started = None
            else:
                if self.rhythm_started is None:
                    self.rhythm_started = now
                # 高频载波不能靠纽扣马达幅度指令还原；首版显式降级为持续震动。
                if effect.frequency <= 20 and ((now - self.rhythm_started) * effect.frequency) % 1 >= 0.5:
                    amplitude = 0.0
        self.previous = position
        return amplitude * self.gain


class TriggerPair:
    def __init__(self, gain=0.22):
        self.gain = gain
        self.left = Trigger(gain)
        self.right = Trigger(gain)
        self.unsupported_modes = set()
        self.malformed_reports = 0

    def update_report(self, report):
        if len(report) < 2 or report[0] != 2:
            self.malformed_reports += 1
            return
        for trigger, flag, offset in ((self.right, 4, 11), (self.left, 8, 22)):
            if not report[1] & flag:
                continue
            if len(report) < offset + 11:
                self.malformed_reports += 1
                continue
            data = report[offset:offset + 11]
            if data[0] not in (0, 5, 0x21, 0x25, 0x26):
                self.unsupported_modes.add(data[0])
            trigger.set_effect(decode_effect(data))

    def sample(self, left_position, right_position, monotonic_seconds):
        return (self.left.sample(left_position, monotonic_seconds),
                self.right.sample(right_position, monotonic_seconds))

    def reset(self):
        self.left = Trigger(self.gain)
        self.right = Trigger(self.gain)
