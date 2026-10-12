import time

import hid

info = next(d for d in hid.enumerate(0x054C, 0x0CE6) if d["usage_page"] == 1 and d["usage"] == 5)
dev = hid.device()
dev.open_path(info["path"])
dev.set_nonblocking(False)
start, count, first = time.monotonic(), 0, None
while time.monotonic() - start < 3:
    data = dev.read(64, 100)
    if data:
        count += 1
        first = first or data
print(f"reports={count} hz={count / 3:.0f}")
if first:
    print("report_id=%02x lx=%d ly=%d rx=%d ry=%d buttons=%02x %02x %02x" % (
        first[0], first[1], first[2], first[3], first[4], first[8], first[9], first[10]))
