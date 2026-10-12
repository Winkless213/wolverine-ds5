import time

import hid

info = next(d for d in hid.enumerate(0x054C, 0x0CE6) if d["usage_page"] == 1 and d["usage"] == 5)
dev = hid.device()
dev.open_path(info["path"])
last = None
start = time.monotonic()
while time.monotonic() - start < 20:
    data = dev.read(64, 100)
    if not data:
        continue
    view = (data[1], data[2], data[3], data[4], data[5], data[6], data[8], data[9], data[10])
    if view != last:
        print("t=%5.2f lx=%3d ly=%3d rx=%3d ry=%3d l2=%3d r2=%3d btn=%02x %02x %02x" % ((time.monotonic() - start,) + view), flush=True)
        last = view
