"""按实体父链识别雷蛇手柄；显式创建输出对象后才可发送四路短震。"""
import ctypes as c
import time
import uuid

# 报文依据 X1nput 9653850（MIT），有限脉冲字段依据 xpadneo 3879ba0。
# https://github.com/araghon007/X1nput/blob/96538509155e887260f6caa797971eb680e4eae1/X1nput/X1nput.cpp
# https://github.com/atar-axis/xpadneo/blob/3879ba0f44e9bcfd500a5b92d02f83885f6b23c7/hid-xpadneo/src/xpadneo/rumble.c


def bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


class Guid(c.Structure):
    _fields_ = [("data1", c.c_uint32), ("data2", c.c_uint16),
                ("data3", c.c_uint16), ("data4", c.c_uint8 * 8)]


XUSB_GUID = "ec87f1e3-c13b-4100-b5f7-8b84d54260cb"


class PropertyKey(c.Structure):
    _fields_ = [("guid", Guid), ("pid", c.c_ulong)]


def decode_info(data):
    # 原始结构末尾有保留字节；本机 GIP 驱动实际返回 12 字节，VID/PID 已完整。
    if len(data) < 12:
        raise ValueError(f"Truncated XUSB device information: {len(data)} bytes, {data.hex()}")
    return {"xusb_version": int.from_bytes(data[:2], "little"),
            "device_index": data[2],
            "vendor": f"{int.from_bytes(data[8:10], 'little'):04X}",
            "product": f"{int.from_bytes(data[10:12], 'little'):04X}"}


class XusbApi:
    def __init__(self):
        cfg = c.WinDLL("cfgmgr32", use_last_error=True)
        kernel = c.WinDLL("kernel32", use_last_error=True)
        self.list_size = bind(cfg, "CM_Get_Device_Interface_List_SizeW", c.c_ulong,
                              c.POINTER(c.c_ulong), c.POINTER(Guid), c.c_wchar_p, c.c_ulong)
        self.list_paths = bind(cfg, "CM_Get_Device_Interface_ListW", c.c_ulong,
                               c.POINTER(Guid), c.c_wchar_p, c.c_wchar_p, c.c_ulong, c.c_ulong)
        self.create = bind(kernel, "CreateFileW", c.c_void_p, c.c_wchar_p,
                           c.c_ulong, c.c_ulong, c.c_void_p, c.c_ulong, c.c_ulong, c.c_void_p)
        self.ioctl = bind(kernel, "DeviceIoControl", c.c_int, c.c_void_p, c.c_ulong,
                          c.c_void_p, c.c_ulong, c.c_void_p, c.c_ulong,
                          c.POINTER(c.c_ulong), c.c_void_p)
        self.close = bind(kernel, "CloseHandle", c.c_int, c.c_void_p)
        self.interface_property = bind(cfg, "CM_Get_Device_Interface_PropertyW", c.c_ulong,
                                       c.c_wchar_p, c.POINTER(PropertyKey), c.POINTER(c.c_ulong),
                                       c.c_void_p, c.POINTER(c.c_ulong), c.c_ulong)
        self.locate = bind(cfg, "CM_Locate_DevNodeW", c.c_ulong,
                           c.POINTER(c.c_ulong), c.c_wchar_p, c.c_ulong)
        self.parent = bind(cfg, "CM_Get_Parent", c.c_ulong,
                           c.POINTER(c.c_ulong), c.c_ulong, c.c_ulong)
        self.device_id = bind(cfg, "CM_Get_Device_IDW", c.c_ulong,
                              c.c_ulong, c.c_wchar_p, c.c_ulong, c.c_ulong)

    def parents(self, path):
        # 按微软 DEVPKEY_Device_InstanceId 取得节点，不能把兼容 VID/PID 当实体身份。
        key = PropertyKey(Guid.from_buffer_copy(
            uuid.UUID("78c34fc8-104a-4aca-9ea4-524d52996e57").bytes_le), 256)
        buffer = c.create_unicode_buffer(512)
        size, kind = c.c_ulong(c.sizeof(buffer)), c.c_ulong()
        status = self.interface_property(path, c.byref(key), c.byref(kind),
                                         buffer, c.byref(size), 0)
        if status or kind.value != 0x12:
            raise RuntimeError(f"Cannot identify XUSB device node: {status}, type={kind.value}")
        node = c.c_ulong()
        status = self.locate(c.byref(node), buffer.value, 0)
        if status:
            raise RuntimeError(f"CM_Locate_DevNodeW: {status}")
        chain = []
        for _ in range(16):
            status = self.device_id(node.value, buffer, len(buffer), 0)
            if status:
                raise RuntimeError(f"CM_Get_Device_IDW: {status}")
            chain.append(buffer.value)
            parent = c.c_ulong()
            if self.parent(c.byref(parent), node.value, 0):
                return chain
            node = parent
        raise RuntimeError("Device parent chain exceeded 16 nodes")

    def paths(self):
        guid = Guid.from_buffer_copy(uuid.UUID(XUSB_GUID).bytes_le)
        for _ in range(2):
            size = c.c_ulong()
            status = self.list_size(c.byref(size), c.byref(guid), None, 0)
            if status:
                raise RuntimeError(f"CM_Get_Device_Interface_List_SizeW: {status}")
            buffer = c.create_unicode_buffer(size.value)
            status = self.list_paths(c.byref(guid), None, buffer, size.value, 0)
            if status == 0:
                return [path for path in c.wstring_at(buffer, size.value).split("\0") if path]
            if status != 0x1A:
                raise RuntimeError(f"CM_Get_Device_Interface_ListW: {status}")
        raise RuntimeError("XUSB interface list kept changing")

    def open(self, path, flags=0):
        handle = self.create(path, 0xC0000000, 3, None, 3, flags, None)
        if handle in (None, c.c_void_p(-1).value):
            raise c.WinError(c.get_last_error())
        return handle

    def info(self, handle):
        buffer = c.create_string_buffer(13)
        size = c.c_ulong()
        if not self.ioctl(handle, 0x80006000, None, 0, buffer, len(buffer), c.byref(size), None):
            raise c.WinError(c.get_last_error())
        raw = buffer.raw[:size.value]
        return {**decode_info(raw), "bytes_returned": size.value, "raw": raw.hex()}



def build_report(left, right, lt, rt):
    values = (lt, rt, left, right)
    if any(not 0 <= value <= .25 for value in values):
        raise ValueError("Bench amplitudes must stay within 0..0.25")
    # 避免现成持续报文中的 FF/EB 长循环；每次只发 100ms 短脉冲和 2 次循环。
    timing = (10, 0, 2) if any(values) else (0, 0, 0)
    return bytes((3, 15, *(round(value * 100) for value in values), *timing))


class XusbTransport(XusbApi):
    def __init__(self):
        super().__init__()
        kernel = c.WinDLL("kernel32", use_last_error=True)
        self.write_file = bind(kernel, "WriteFile", c.c_int, c.c_void_p,
                               c.c_void_p, c.c_ulong, c.POINTER(c.c_ulong), c.c_void_p)

    def write(self, handle, report):
        buffer = c.create_string_buffer(report, len(report))
        written = c.c_ulong()
        if not self.write_file(handle, buffer, len(report), c.byref(written), None):
            raise c.WinError(c.get_last_error())
        return written.value


def find_razer_interface(api, *, only_interface=False):
    paths = api.paths()
    if only_interface and len(paths) != 1:
        raise RuntimeError("XInput alias matching requires exactly one XUSB interface")
    candidates = []
    for path in paths:
        chain = api.parents(path)
        if any(node.upper().startswith("USB\\VID_1532&PID_0A3F\\") for node in chain):
            candidates.append((path, chain))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one physical Xbox-mode Razer interface, got {len(candidates)}")
    return candidates[0]


class XusbOutput:
    def __init__(self, api=None):
        self.api = api if api is not None else XusbTransport()
        self.calls, self.handle = [], None
        path, chain = find_razer_interface(self.api)
        handle = self.api.open(path)
        try:
            compatibility = self.api.info(handle)
        except BaseException:
            self.api.close(handle)
            raise
        self.handle = handle
        self.identity = {"backend": "xusb", "vendor": "1532", "product": "0A3F",
                         "path": path, "parents": chain, "compatibility": compatibility}

    def set(self, left, right, lt, rt):
        report = build_report(left, right, lt, rt)
        if self.handle is None:
            raise RuntimeError("XUSB output is closed")
        before = time.perf_counter_ns()
        call = {"at_ns": before, "values": [left, right, lt, rt],
                "report_hex": report.hex(), "ok": False}
        try:
            written = self.api.write(self.handle, report)
            call["bytes_written"] = written
            if written != len(report):
                raise OSError(f"Short XUSB write: {written}/{len(report)}")
            call["ok"] = True
        except Exception as error:
            call["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            call["call_us"] = (time.perf_counter_ns() - before) / 1000
            self.calls.append(call)

    def wait(self, seconds):
        time.sleep(seconds)

    def close(self):
        if self.handle is not None:
            try:
                self.set(0, 0, 0, 0)
            finally:
                handle, self.handle = self.handle, None
                if not self.api.close(handle):
                    raise OSError("CloseHandle failed for XUSB output")
