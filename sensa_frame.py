"""解析本次 HAR 构建的 Sage T1 压缩帧，仅用于离线取证。"""


def decode_frame(data):
    if not data:
        return {"duration_ms": 0, "channels": []}
    if len(data) > 52:
        raise ValueError("Frame exceeds recorded Sage T1 capacity")
    position = 0

    def read(count):
        nonlocal position
        if position + count > len(data) * 8:
            raise ValueError("Truncated Sensa frame")
        value = 0
        for _ in range(count):
            value = value << 1 | (data[position // 8] >> (7 - position % 8) & 1)
            position += 1
        return value

    result = {"duration_ms": read(7), "channels": []}
    for bodypart in (216, 116):
        channel = {"bodypart": bodypart, "bands": [], "transients": []}
        for _ in range(3):
            if read(1) != 1:
                raise ValueError("Unverified optional-band encoding")
            channel["bands"].append([{"amplitude_code":read(6), "frequency_code":read(7)} for _ in range(4)])
        for _ in range(2):
            if not read(1):
                break
            channel["transients"].append({"amplitude_code":read(6), "frequency_code":read(7), "time_ms":read(7)})
        result["channels"].append(channel)
    remaining = len(data) * 8 - position
    if remaining >= 8 or read(remaining):
        raise ValueError("Unexpected data after Sensa frame")
    return result
