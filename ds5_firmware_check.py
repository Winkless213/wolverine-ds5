import hid

info = next(d for d in hid.enumerate(0x054C, 0x0CE6) if d["usage_page"] == 1 and d["usage"] == 5)
dev = hid.device()
dev.open_path(info["path"])
report = bytes(dev.get_feature_report(0x20, 64))
print("build", report[1:12].decode(errors="replace"), report[12:20].decode(errors="replace"))
print("hardware_type=%02x hw_info=%08x firmware=%04x" % (
    report[20], int.from_bytes(report[24:28], "little"), int.from_bytes(report[44:46], "little")))
