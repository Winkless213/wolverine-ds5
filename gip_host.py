"""在 WinUSB 下直接驱动 Xbox 模式手柄：GIP 启动、安全握手、输入解码与四路短震。"""
import hashlib
import hmac
import os
import struct
import time

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key

from sdl_input import input_state

# 协议与握手流程依据 Tinerou/wolverine-v3-pro-macos-wine（GPL-2.0，移植自 medusalix/xone auth）。
# https://github.com/Tinerou/wolverine-v3-pro-macos-wine

ACK, CHUNK_START, CHUNK, INTERNAL = 0x10, 0x40, 0x80, 0x20
PACKET_MAX = 58
GIP_BUTTONS = ((0x0004, 6), (0x0008, 4), (0x0010, 0), (0x0020, 1), (0x0040, 2), (0x0080, 3),
               (0x0100, 11), (0x0200, 12), (0x0400, 13), (0x0800, 14),
               (0x1000, 9), (0x2000, 10), (0x4000, 7), (0x8000, 8))


class GipAuthError(RuntimeError):
    pass


def _varint(value):
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return out


def _read_varint(data, pos):
    value = 0
    for i in range(4):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            break
    return value, pos


def header(cmd, opts, seq, length, offset=0):
    out = bytearray((cmd, opts, seq)) + _varint(length)
    chunk = _varint(offset) if opts & CHUNK else b""
    # 头部总长必须为偶数，奇数时把长度字段补成两字节。
    if (len(out) + len(chunk)) % 2:
        out[-1] |= 0x80
        out.append(0)
    return bytes(out + chunk)


def parse(packet):
    cmd, opts, seq = packet[:3]
    length, pos = _read_varint(packet, 3)
    offset = 0
    if opts & CHUNK:
        offset, pos = _read_varint(packet, pos)
    return cmd, opts, seq, offset, bytes(packet[pos:pos + length])


def ack(cmd, seq, received, remaining):
    return (bytes((0x01, INTERNAL, seq, 9, 0, cmd, INTERNAL)) + received.to_bytes(2, "little")
            + bytes(2) + remaining.to_bytes(2, "little"))


def rumble(left, right, lt, rt):
    # 字段顺序与 XUSB 相同（LT RT 左 右，0..100%）；GIP 路径按原生比例输出，允许满幅。
    values = (lt, rt, left, right)
    if any(not 0 <= value <= 1 for value in values):
        raise ValueError("Motor amplitudes must stay within 0..1")
    # 每次只发 100ms 短脉冲和 2 次循环，桥接持续刷新；断流时马达自行停止。
    timing = (10, 0, 2) if any(values) else (0, 0, 0)
    return bytes((0, 15, *(round(value * 100) for value in values), *timing))


def dualsense_state(payload, guide=False):
    buttons, lt, rt, lx, ly, rx, ry = struct.unpack_from("<HHHhhhh", payload)
    pressed = {index for mask, index in GIP_BUTTONS if buttons & mask}
    if guide:
        pressed.add(5)
    # GIP 的 Y 轴向上为正，SDL/DS5 映射按向下为正。
    axes = (lx, min(32767, -ly), rx, min(32767, -ry),
            (lt & 0x3FF) * 32767 // 1023, (rt & 0x3FF) * 32767 // 1023)
    return input_state(axes, pressed)


def prf(label, key, seed, size):
    seed = label.encode() + seed
    a, out = seed, b""
    while len(out) < size:
        a = hmac.digest(key, a, "sha256")
        out += hmac.digest(key, a + seed, "sha256")
    return out[:size]


class Auth:
    """v1 RSA 握手；transcript 为去掉 6 字节握手头后的全部消息。"""

    def __init__(self, send, random=os.urandom):
        self.send, self.random = send, random
        self.transcript = hashlib.sha256()
        self.last_sent = self.host_random = self.client_random = self.master = None
        self.complete = False

    def start(self):
        self.host_random = self.random(32)
        self._send(0x01, self.host_random + bytes(8))

    def _send(self, cmd, body):
        data = bytes((cmd, 1)) + len(body).to_bytes(2, "big") + body
        self.transcript.update(data)
        self.last_sent = cmd
        self.send(bytes((0, 0x41, 0, cmd)) + len(data).to_bytes(2, "big") + data + bytes(8), True)

    def _request(self, cmd, length):
        self.send(bytes((0, 0x42, 0, cmd)) + (length + 4).to_bytes(2, "big") + bytes(8), True)

    def _digest(self):
        return self.transcript.copy().digest()

    def process(self, payload):
        if len(payload) < 6:
            raise GipAuthError("Truncated handshake packet")
        options, error, cmd = payload[1:4]
        if error:
            raise GipAuthError(f"Device reported error 0x{error:02x} for 0x{cmd:02x}")
        if options & 1:
            if cmd != 1:
                raise GipAuthError(f"Device rejected handshake step 0x{cmd:02x}")
            if self.last_sent == 0x01:
                self._request(0x02, 32 + 48)
            elif self.last_sent == 0x05:
                self._send(0x07, prf("Host Finished", self.master, self._digest(), 32))
            elif self.last_sent == 0x07:
                self._request(0x08, 32 + 32)
            else:
                raise GipAuthError(f"Unexpected handshake ack after 0x{self.last_sent}")
            return
        if len(payload) < 10:
            raise GipAuthError("Truncated handshake message")
        if payload[6] != cmd:
            raise GipAuthError("Security handshake v2 is not implemented")
        data, body = payload[6:], payload[10:]
        if cmd == 0x08:
            if body[:32] != prf("Device Finished", self.master, self._digest(), 32):
                raise GipAuthError("Device Finished mismatch")
            self.transcript.update(data)
            self.complete = True
            self.send(b"\x01\x00", False)
            return
        self.transcript.update(data)
        if cmd == 0x02 and len(body) >= 80:
            self.client_random = body[:32]
            self._request(0x03, 1024)
        elif cmd == 0x03:
            start = body.find(b"\x30\x82\x01\x0a")
            if start < 0 or start + 270 > len(body):
                raise GipAuthError("RSA public key not found in certificate")
            key = load_der_public_key(body[start:start + 270])
            secret = self.random(48)
            self.master = prf("Master Secret", secret, self.host_random + self.client_random, 48)
            self._send(0x05, key.encrypt(secret, padding.PKCS1v15()))
        else:
            raise GipAuthError(f"Unexpected handshake message 0x{cmd:02x}")


class GipHost:
    def __init__(self, transport, clock=time.monotonic, random=os.urandom):
        self.transport, self.clock, self.random = transport, clock, random
        self.seq, self.phase = 1, "hello"
        self.opened = self.requested = clock()
        self.meta_retries = 0
        self.rx = self.tx = self.auth = None
        self.report, self.guide, self.closed = bytes(32), False, False
        self.reports = 0

    def _next_seq(self):
        seq, self.seq = self.seq, self.seq % 255 + 1
        return seq

    def send_message(self, cmd, opts, data):
        seq = self._next_seq()
        if len(data) <= PACKET_MAX:
            self.transport.write(header(cmd, opts, seq, len(data)) + data)
            return
        self.tx = (cmd, opts & ~(ACK | CHUNK_START), seq, bytes(data))
        self.transport.write(header(cmd, opts | ACK | CHUNK_START | CHUNK, seq, PACKET_MAX, len(data))
                             + data[:PACKET_MAX])

    def _on_ack(self, payload):
        if not self.tx or len(payload) < 9 or payload[1] != self.tx[0]:
            return
        cmd, opts, seq, data = self.tx
        if int.from_bytes(payload[3:5], "little") < len(data):
            for start in range(PACKET_MAX, len(data), PACKET_MAX):
                chunk = data[start:start + PACKET_MAX]
                last = ACK if start + PACKET_MAX >= len(data) else 0
                self.transport.write(header(cmd, opts | CHUNK | last, seq, len(chunk), start) + chunk)
        else:
            self.transport.write(header(cmd, opts | CHUNK, seq, 0, len(data)))
            self.tx = None

    def _request_metadata(self, now):
        self.send_message(0x04, INTERNAL, b"")
        self.phase, self.requested = "metadata", now

    def _start_auth(self):
        self.phase = "auth"
        self.auth = Auth(lambda payload, need_ack: self.send_message(
            0x06, INTERNAL | (ACK if need_ack else 0), payload), self.random)
        self.auth.start()

    def _on_auth(self, payload):
        self.auth.process(payload)
        if self.auth.complete and self.phase == "auth":
            self.phase = "ready"
            self.send_message(0x05, INTERNAL, b"\x00")
            self.send_message(0x0A, INTERNAL, b"\x00\x01\x14")
            self.send_message(0x09, 0x00, bytes.fromhex("000f00000000ff00eb"))

    def _on_message(self, cmd, data):
        if cmd == 0x04 and self.phase == "metadata":
            self._start_auth()
        elif cmd == 0x06 and self.auth:
            self._on_auth(data)

    def _on_chunk(self, cmd, opts, seq, offset, payload):
        if opts & CHUNK_START:
            self.rx, offset = [cmd, offset, bytearray(offset), 0], 0
        if not self.rx or self.rx[0] != cmd:
            return
        _, total, buffer, received = self.rx
        if payload:
            if offset + len(payload) > total:
                raise ValueError("GIP chunk exceeds declared length")
            buffer[offset:offset + len(payload)] = payload
            received = self.rx[3] = offset + len(payload)
        if opts & ACK:
            self.transport.write(ack(cmd, seq, received, total - received))
        if not payload:
            self.rx = None
            self._on_message(cmd, bytes(buffer[:received]))

    def poll(self, timeout_ms=4):
        now = self.clock()
        if self.phase == "hello" and now - self.opened > .6:
            self._request_metadata(now)
        elif self.phase == "metadata" and self.rx is None and now - self.requested > .5:
            self.meta_retries += 1
            if self.meta_retries >= 4:
                self._start_auth()
            else:
                self._request_metadata(now)
        packet = self.transport.read(timeout_ms)
        if not packet:
            return
        cmd, opts, seq, offset, payload = parse(packet)
        if opts & CHUNK:
            self._on_chunk(cmd, opts, seq, offset, payload)
            return
        if cmd == 0x01:
            self._on_ack(payload)
            return
        if opts & ACK:
            self.transport.write(ack(cmd, seq, len(payload), 0))
        if cmd == 0x02 and self.phase == "hello":
            self._request_metadata(self.clock())
        elif cmd == 0x20 and len(payload) >= 14:
            self.report = payload
            self.reports += 1
        elif cmd == 0x07 and payload:
            self.guide = bool(payload[0] & 0x03)
        else:
            self._on_message(cmd, payload)

    def state(self):
        return dualsense_state(self.report, self.guide)

    def set(self, left, right, lt, rt):
        if self.closed:
            raise RuntimeError("GIP host is closed")
        self.send_message(0x09, 0x00, rumble(left, right, lt, rt))

    def close(self):
        if self.closed:
            return
        try:
            self.set(0, 0, 0, 0)
        finally:
            self.closed = True
            self.transport.close()


class UsbTransport:
    """WinUSB/libusb 端点 0x81/0x01；需先把 1532:0A3F 的驱动换为 WinUSB。"""

    def __init__(self, vid=0x1532, pid=0x0A3F):
        import libusb_package
        import usb.core
        import usb.util
        self.usb = usb
        self.device = libusb_package.find(idVendor=vid, idProduct=pid)
        if self.device is None:
            raise RuntimeError(f"USB device {vid:04X}:{pid:04X} not found via libusb (driver must be WinUSB)")
        usb.util.claim_interface(self.device, 0)
        try:
            self.device.set_interface_altsetting(1, 0)
        except usb.core.USBError:
            pass

    def read(self, timeout_ms):
        try:
            return bytes(self.device.read(0x81, 64, max(1, timeout_ms)))
        except self.usb.core.USBTimeoutError:
            return None

    def write(self, data):
        if self.device.write(0x01, data, 250) != len(data):
            raise OSError("Short GIP write")

    def close(self):
        self.usb.util.dispose_resources(self.device)
