"""输入和触觉各自保持节奏，超时后只处理最新状态。"""


class InputCadence:
    def __init__(self, hz):
        if hz not in (250, 1000):
            raise ValueError("Input polling must be 250 or 1000 Hz")
        self.period, self.next_read = 1 / hz, 0

    def due(self, now):
        if now < self.next_read:
            return False
        # 正常唤醒保留原定节奏，避免每次 sleep 的误差累积成降速。
        # 错过整轮时重新起算，不连续补发已经过时的输入。
        self.next_read = (now + self.period if now >= self.next_read + self.period
                          else self.next_read + self.period)
        return True
