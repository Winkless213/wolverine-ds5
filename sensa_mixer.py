"""复用本机 Mixer 的原生多设备帧命令；只在创建 Mixer 后打开输出。"""
import ctypes as c
import os
import struct
import time
import uuid

from app.core import usb_instances
from sensa_frame import decode_frame
from xusb_output import Guid, PropertyKey, bind


MAPPING = r"Global\SharedMemory_InterhapticsMixerCommand-{fc3bf7a7-5224-48d6-8c5d-d5173ca09737}"
EVENT = r"Global\Event_InterhapticsMixerCommand-{ee4d3efa-297b-40f1-81c9-ecaff6295f02}"
PROGRAM = "Wolverine DS5 Multiband"
PC_ROOT = "USB\\VID_1532&PID_0A4C\\"


def select_pc_device(containers):
    targets = {"2636-{" + str(uuid.UUID(container.strip("{}"))) + "}"
               for instance, container in containers.items() if instance.upper().startswith(PC_ROOT)}
    if len(targets) != 1:
        raise ConnectionError("多频候选需要连接一只 PC 模式 Wolverine V3 Pro")
    return targets.pop()


def find_pc_device():
    cfg = c.WinDLL("cfgmgr32", use_last_error=True)
    locate = bind(cfg, "CM_Locate_DevNodeW", c.c_ulong, c.POINTER(c.c_ulong), c.c_wchar_p, c.c_ulong)
    get = bind(cfg, "CM_Get_DevNode_PropertyW", c.c_ulong, c.c_ulong, c.POINTER(PropertyKey),
               c.POINTER(c.c_ulong), c.c_void_p, c.POINTER(c.c_ulong), c.c_ulong)
    key = PropertyKey(Guid.from_buffer_copy(uuid.UUID("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c").bytes_le), 2)
    containers = {}
    for instance in usb_instances():
        if not instance.upper().startswith(PC_ROOT):
            continue
        node, kind = c.c_ulong(), c.c_ulong()
        value = (c.c_ubyte * 16)()
        size = c.c_ulong(16)
        if locate(c.byref(node), instance, 0) or get(node, c.byref(key), c.byref(kind), value, c.byref(size), 0):
            raise ConnectionError("无法读取当前手柄 ContainerId")
        if kind.value != 0x0D or size.value != 16:
            raise ConnectionError("当前手柄 ContainerId 格式无效")
        containers[instance] = str(uuid.UUID(bytes_le=bytes(value)))
    return select_pc_device(containers)


def mixer_command(program, opcode, payload=b""):
    name = program.encode("utf-8")
    if not 0 < len(name) <= 127:
        raise ValueError("Mixer 程序名长度无效")
    header = bytearray(144)
    header[:len(name)] = name
    header[128] = opcode
    struct.pack_into("<Q", header, 136, len(payload))
    return bytes(header) + payload


def play_command(program, device, frame):
    if not device.startswith("2636-{") or not device.endswith("}"):
        raise ValueError("目标不是 PC 模式 Wolverine")
    uuid.UUID(device[6:-1])
    if not decode_frame(frame)["duration_ms"]:
        raise ValueError("Sage T1 帧缺少有效时长")
    name = device.encode("utf-8")
    payload = b"\x01" + struct.pack("<H", len(name)) + name + struct.pack("<BI", 1, len(frame)) + frame
    return mixer_command(program, 12, payload)


class Mixer:
    def __init__(self):
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        for name, result, args in (
            ("OpenFileMappingW", c.c_void_p, [c.c_uint32, c.c_int, c.c_wchar_p]),
            ("MapViewOfFile", c.c_void_p, [c.c_void_p, c.c_uint32, c.c_uint32, c.c_uint32, c.c_size_t]),
            ("OpenEventW", c.c_void_p, [c.c_uint32, c.c_int, c.c_wchar_p]),
            ("SetEvent", c.c_int, [c.c_void_p]),
            ("UnmapViewOfFile", c.c_int, [c.c_void_p]),
            ("CloseHandle", c.c_int, [c.c_void_p]),
        ):
            bind(self.kernel, name, result, *args)
        self.mapping = self.address = self.event = None
        try:
            self.mapping = self.kernel.OpenFileMappingW(2, False, MAPPING)
            if not self.mapping:
                raise c.WinError(c.get_last_error())
            self.address = self.kernel.MapViewOfFile(self.mapping, 2, 0, 0, 512)
            if not self.address:
                raise c.WinError(c.get_last_error())
            self.event = self.kernel.OpenEventW(2, False, EVENT)
            if not self.event:
                raise c.WinError(c.get_last_error())
        except BaseException:
            self.close()
            raise

    def send(self, packet):
        if len(packet) > 512:
            raise ValueError("Mixer 命令超出映射窗口")
        c.memmove(self.address, packet, len(packet))
        if not self.kernel.SetEvent(self.event):
            raise c.WinError(c.get_last_error())

    def start(self):
        self.send(mixer_command(PROGRAM, 1, struct.pack("<Q", os.getpid())))
        time.sleep(.025)

    def play(self, target, frame):
        self.send(play_command(PROGRAM, target, frame))

    def stop(self):
        self.send(mixer_command(PROGRAM, 2))
        time.sleep(.025)

    def close(self):
        if self.address:
            self.kernel.UnmapViewOfFile(self.address)
        for handle in (self.event, self.mapping):
            if handle:
                self.kernel.CloseHandle(handle)
        self.mapping = self.address = self.event = None
