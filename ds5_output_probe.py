"""向虚拟 DS5 写输出报告，模拟游戏：先经典握把震动，再右扳机 0x21 反馈效果。"""
import sys
import time

import hid

info = next(d for d in hid.enumerate(0x054C, 0x0CE6) if d["usage_page"] == 1 and d["usage"] == 5)
dev = hid.device()
dev.open_path(info["path"])


def report(flag0, rumble=(0, 0), right_trigger=None):
    data = bytearray(48)
    data[0] = 0x02
    data[1] = flag0
    data[3], data[4] = rumble
    if right_trigger:
        data[11:22] = right_trigger
    return bytes(data)


mode = sys.argv[1]
if mode == "rumble":
    # flag0 bit0|bit1：经典 rumble 兼容模式，byte3 右（高频）、byte4 左（低频）。
    dev.write(report(0x03, rumble=(128, 255)))
    time.sleep(6)
    dev.write(report(0x03, rumble=(0, 0)))
elif mode in ("left", "right"):
    print(f"{mode} grip only", flush=True)
    dev.write(report(0x03, rumble=(0, 255) if mode == "left" else (255, 0)))
    time.sleep(5)
    dev.write(report(0x03, rumble=(0, 0)))
elif mode == "trigger":
    dev.write(report(0x04, right_trigger=bytes((0x21, 0xFF, 0x03, 0xFF, 0xFF, 0xFF, 0x3F, 0, 0, 0, 0))))
    print("right trigger effect set; press RT now", flush=True)
    time.sleep(8)
    dev.write(report(0x04, right_trigger=bytes(11)))
print("done", flush=True)
