import hashlib
import unittest

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import gip_host
from gip_host import Auth, GipHost, GipAuthError, ack, gip_endpoints, header, parse, prf


class FakeController:
    """设备侧 v1 握手：独立维护 transcript，校验主机 Finished 并回 Device Finished。"""

    def __init__(self, tamper_finish=False):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        der = self.key.public_key().public_bytes(Encoding.DER, PublicFormat.PKCS1)
        self.cert = b"\x11" * 100 + der + b"\x22" * 455
        self.random = bytes(range(32))
        self.transcript = hashlib.sha256()
        self.tamper_finish = tamper_finish
        self.host_random = self.master = None
        self.completed = False

    def message(self, cmd, body):
        data = bytes((cmd, 1)) + len(body).to_bytes(2, "big") + body
        self.transcript.update(data)
        return bytes((0, 0xC0, 0, cmd)) + len(data).to_bytes(2, "big") + data

    def handle(self, payload):
        if payload == b"\x01\x00":
            self.completed = True
            return []
        options, cmd = payload[1], payload[3]
        if options == 0x42:
            if cmd == 0x02:
                return [self.message(0x02, self.random + bytes(48))]
            if cmd == 0x03:
                return [self.message(0x03, self.cert)]
            if cmd == 0x08:
                finish = prf("Device Finished", self.master, self.transcript.copy().digest(), 32)
                if self.tamper_finish:
                    finish = bytes(32)
                return [self.message(0x08, finish + bytes(32))]
        size = int.from_bytes(payload[4:6], "big")
        data = payload[6:6 + size]
        body = data[4:]
        if cmd == 0x01:
            self.host_random = body[:32]
        elif cmd == 0x05:
            pms = self.key.decrypt(body, padding.PKCS1v15())
            self.master = prf("Master Secret", pms, self.host_random + self.random, 48)
        elif cmd == 0x07:
            expected = prf("Host Finished", self.master, self.transcript.copy().digest(), 32)
            if body != expected:
                return [bytes((0, 0xC1, 0, 0x07, 0, 0))]
        self.transcript.update(data)
        return [bytes((0, 0xC1, 0, 0x01, 0, 0))]


def run_handshake(device):
    outbox = []
    auth = Auth(lambda payload, need_ack: outbox.append(payload))
    auth.start()
    while outbox:
        for reply in device.handle(outbox.pop(0)):
            auth.process(reply)
    return auth


class FakeTransport:
    def __init__(self, packets=()):
        self.incoming, self.written = list(packets), []

    def read(self, timeout_ms):
        return self.incoming.pop(0) if self.incoming else None

    def write(self, data):
        self.written.append(bytes(data))

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Descriptor(list):
    """pyusb 描述符替身：可迭代出子描述符，字段按属性读取。"""

    def __init__(self, children=(), **fields):
        super().__init__(children)
        self.__dict__.update(fields)


def interface(number, alt, *endpoints, cls=(0xFF, 0x47, 0xD0)):
    return Descriptor([Descriptor(bEndpointAddress=address, bmAttributes=kind, wMaxPacketSize=size)
                       for address, kind, size in endpoints],
                      bInterfaceNumber=number, bAlternateSetting=alt,
                      bInterfaceClass=cls[0], bInterfaceSubClass=cls[1], bInterfaceProtocol=cls[2])


INTERRUPT, ISOCHRONOUS, BULK = 3, 1, 2
# 有线：research/gip-v3pro/NOTES.md:11；2.4G 接收器：2026-10-15 01:31 P1 探针在 WinUSB 下的描述符树。
WIRED = Descriptor([interface(0, 0, (0x81, INTERRUPT, 64), (0x01, INTERRUPT, 64)),
                    interface(1, 0),
                    interface(1, 1, (0x03, ISOCHRONOUS, 228), (0x83, ISOCHRONOUS, 64))])
RECEIVER = Descriptor([interface(0, 0, (0x05, INTERRUPT, 64), (0x84, INTERRUPT, 64)),
                       interface(1, 0),
                       interface(1, 1, (0x06, ISOCHRONOUS, 228), (0x87, ISOCHRONOUS, 64))])


class EndpointDiscoveryTests(unittest.TestCase):
    def test_wired_controller_uses_its_interrupt_pipe(self):
        self.assertEqual(gip_endpoints(WIRED), (0, 0x81, 0x01, 64))

    def test_receiver_uses_its_own_endpoint_addresses(self):
        self.assertEqual(gip_endpoints(RECEIVER), (0, 0x84, 0x05, 64))

    def test_audio_alt_setting_is_never_picked(self):
        audio_only = Descriptor([interface(1, 1, (0x06, ISOCHRONOUS, 228), (0x87, ISOCHRONOUS, 64))])
        with self.assertRaises(RuntimeError):
            gip_endpoints(audio_only)

    def test_missing_gip_pipe_reports_what_was_found(self):
        vendor = Descriptor([interface(0, 0, (0x81, BULK, 64), (0x02, BULK, 64), cls=(0xFF, 0x5D, 0x01))])
        with self.assertRaisesRegex(RuntimeError, r"if0 alt0 FF/5D/01 \[0x81 bulk, 0x02 bulk\]"):
            gip_endpoints(vendor)


class FramingTests(unittest.TestCase):
    def test_short_header_matches_known_start_packet(self):
        self.assertEqual(header(0x05, 0x20, 7, 1), bytes.fromhex("05200701"))

    def test_odd_chunk_header_pads_length_to_even_size(self):
        packet = header(0x06, 0xA0, 3, 58, 58)
        self.assertEqual(packet, bytes.fromhex("06a003ba003a"))
        self.assertEqual(parse(packet + bytes(58))[3:], (58, bytes(58)))

    def test_chunk_start_carries_total_length(self):
        packet = header(0x06, 0xF0, 3, 58, 825) + bytes(range(58))
        cmd, opts, seq, offset, payload = parse(packet)
        self.assertEqual((cmd, seq, offset, payload), (0x06, 3, 825, bytes(range(58))))

    def test_ack_layout_matches_metadata_capture(self):
        self.assertEqual(ack(0x04, 0x11, 116, 144), bytes.fromhex("012011090004207400000090 00".replace(" ", "")))

    def test_rumble_payload_uses_full_percent_range_and_short_pulse(self):
        self.assertEqual(gip_host.rumble(.1, .2, .22, 1), bytes((0, 15, 22, 100, 10, 20, 10, 0, 2)))
        for value in (-.1, 1.01, float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gip_host.rumble(0, 0, value, 0)


class InputTests(unittest.TestCase):
    def test_gip_report_maps_to_dualsense_state(self):
        payload = bytes.fromhex("1201" "ff03" "0000" "0000" "ff7f" "0080" "0000") + bytes(18)
        state = gip_host.dualsense_state(payload, guide=True)
        self.assertEqual((state["L2"], state["R2"]), (255, 0))
        self.assertEqual((state["LY"], state["RY"]), (-128, 0))
        self.assertEqual(state["RX"], -128)
        self.assertEqual(state["Buttons"], 0x20 | 0x400 | 0x10000)
        self.assertEqual(state["DPad"], 1)

    def test_keepalive_bit_is_not_a_button(self):
        state = gip_host.dualsense_state(bytes.fromhex("0200") + bytes(30))
        self.assertEqual((state["Buttons"], state["DPad"]), (0, 0))


class AuthTests(unittest.TestCase):
    def test_tls12_sha256_prf_vector(self):
        secret = bytes.fromhex("9bbe436ba940f017b17652849a71db35")
        seed = bytes.fromhex("a0ba9f936cda311827a6f796ffd5198c")
        self.assertEqual(prf("test label", secret, seed, 16), bytes.fromhex("e3f229ba727be17b8d122620557cd453"))

    def test_v1_handshake_completes_against_independent_device(self):
        device = FakeController()
        auth = run_handshake(device)
        self.assertTrue(auth.complete)
        self.assertTrue(device.completed)

    def test_wrong_device_finished_aborts(self):
        with self.assertRaisesRegex(GipAuthError, "Device Finished"):
            run_handshake(FakeController(tamper_finish=True))

    def test_device_error_aborts(self):
        auth = Auth(lambda payload, need_ack: None)
        with self.assertRaisesRegex(GipAuthError, "error 0x05"):
            auth.process(bytes((0, 0xC0, 5, 0x02, 0, 0)))


class HostTests(unittest.TestCase):
    def test_hello_triggers_metadata_request(self):
        transport = FakeTransport([bytes.fromhex("02200120") + bytes(32)])
        GipHost(transport, clock=Clock()).poll()
        self.assertEqual(transport.written, [bytes.fromhex("04200100")])

    def test_late_hello_does_not_restart_startup(self):
        hello = bytes.fromhex("02200120") + bytes(32)
        transport = FakeTransport([hello, hello])
        host = GipHost(transport, clock=Clock())
        host.poll()
        host.poll()
        self.assertEqual(len(transport.written), 1)

    def test_chunked_metadata_is_acked_and_starts_auth(self):
        transport = FakeTransport([
            header(0x04, 0xF0, 9, 58, 70) + bytes(58),
            header(0x04, 0xA0, 9, 12, 58) + bytes(12),
            header(0x04, 0xA0, 9, 0, 70),
        ])
        host = GipHost(transport, clock=Clock(), random=lambda size: bytes(size))
        host.phase = "metadata"
        for _ in range(3):
            host.poll()
        self.assertEqual(transport.written[0], ack(0x04, 9, 58, 12))
        self.assertEqual(host.phase, "auth")
        cmd, opts, _, _, payload = parse(transport.written[-1])
        self.assertEqual((cmd, opts & 0x30, payload[3]), (0x06, 0x30, 0x01))

    def test_large_message_is_chunked_and_finished_after_acks(self):
        transport = FakeTransport()
        host = GipHost(transport, clock=Clock())
        data = bytes(range(256)) + bytes(18)
        host.send_message(0x06, 0x20, data)
        first = parse(transport.written[0])
        self.assertEqual((first[1], first[3], first[4]), (0xF0, 274, data[:58]))
        transport.incoming.append(ack(0x06, 1, 58, 216))
        host.poll()
        chunks = [parse(packet) for packet in transport.written[1:]]
        self.assertEqual([(c[1], c[3]) for c in chunks], [(0xA0, 58), (0xA0, 116), (0xA0, 174), (0xB0, 232)])
        self.assertEqual(b"".join(c[4] for c in chunks), data[58:])
        transport.incoming.append(ack(0x06, 1, 274, 0))
        host.poll()
        self.assertEqual(parse(transport.written[-1])[1:5], (0xA0, 1, 274, b""))

    def test_input_with_ack_flag_is_acked_and_decoded(self):
        report = header(0x20, 0x10, 5, 32) + bytes.fromhex("1000") + bytes(30)
        transport = FakeTransport([report])
        host = GipHost(transport, clock=Clock())
        host.phase = "ready"
        host.poll()
        self.assertEqual(transport.written, [ack(0x20, 5, 32, 0)])
        self.assertEqual((host.state()["Buttons"], host.reports), (0x20, 1))

    def test_set_sends_rumble_and_zero_on_close(self):
        transport = FakeTransport()
        host = GipHost(transport, clock=Clock())
        host.set(0, 0, .2, 0)
        host.close()
        self.assertEqual([parse(p)[4] for p in transport.written],
                         [bytes((0, 15, 20, 0, 0, 0, 10, 0, 2)), bytes((0, 15, 0, 0, 0, 0, 0, 0, 0))])


if __name__ == "__main__":
    unittest.main()
