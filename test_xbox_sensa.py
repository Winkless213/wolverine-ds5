import collections
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from gip_host import GipHost, header
from pc_bridge import GripHaptics
from xbox_sensa import SensaStream, XboxEncoder, stream_packet, trigger_packet
from xbox_sensa_bridge import XboxHaptics
from test_gip_bridge import FULL_VIBRATION, trigger_report
from test_pc_bridge import FakeGrips, feed, rumble_report
from test_pcm_to_sensa import pcm_tones


class Transport:
    def __init__(self):
        self.writes = []
        self.reads = collections.deque()

    def write(self, data):
        self.writes.append(data)

    def read(self, timeout_ms):
        return self.reads.popleft() if self.reads else None


def reply(packet, status=2):
    data = bytearray(packet)
    data[0], data[4] = 0x10, status
    return bytes(data)


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.transport = Transport()
        self.host = GipHost(self.transport)
        self.host.phase = "ready"
        self.encoder = Mock()
        self.encoder.frame.return_value = bytes.fromhex("3c000000")
        self.now = 0
        self.stream = SensaStream(self.host, self.encoder, clock=lambda: self.now)

    def test_prefix_and_capacity_do_not_overwrite_checksum(self):
        packet = stream_packet(bytes(range(49)), 7)
        self.assertEqual(len(packet), 64)
        self.assertEqual(packet[:4], bytes((15, 0, 7, 60)))
        self.assertEqual(packet[8:13], bytes((0, 50, 22, 14, 1)))
        self.assertEqual(packet[13:62], bytes(range(49)))
        with self.assertRaises(ValueError):
            stream_packet(bytes(50), 8)

    def test_stream_replies_share_the_input_reader_without_losing_buttons(self):
        self.stream.set(0, .14, 180)
        self.stream.render()
        sent = self.transport.writes[-1]
        self.transport.reads.extend((reply(sent), header(0x20, 0, 99, 14) + bytes.fromhex("1000") + bytes(12)))
        self.host.poll()
        self.host.poll()
        self.assertEqual(self.host.reports, 1)
        self.assertEqual(self.host.report[:2], b"\x10\x00")
        self.assertEqual(self.stream.accepted, 1)
        self.assertFalse(self.stream.pending)

    def test_negative_reply_stops_the_session(self):
        self.stream.render()
        self.transport.reads.append(reply(self.transport.writes[-1], status=3))
        with self.assertRaises(ConnectionError):
            self.host.poll()

    def test_missing_reply_is_detected_even_while_silent(self):
        self.stream.render()
        self.now = .51
        with self.assertRaises(ConnectionError):
            self.stream.render()

    def test_frequency_is_retained_clamped_and_stop_bypasses_rate_limit(self):
        self.stream.set(0, .14, 60)
        self.stream.set(1, .14, 400)
        self.stream.render()
        self.assertEqual(self.encoder.frame.call_args.args[0], [(0.14, 60), (0.14, 300)])
        self.now = .004
        self.stream.set(0, 0, 80)
        self.stream.set(1, 0, 80)
        self.stream.render()
        self.assertEqual(len(self.transport.writes), 2)
        self.assertEqual(self.encoder.frame.call_args.args[0], [(0, 80), (0, 80)])

    def test_close_stops_private_output_and_restores_input_transport(self):
        self.stream.set(0, .14, 60)
        self.stream.render()
        self.stream.close()
        self.assertEqual(self.encoder.frame.call_args.args[0], [(0, 80), (0, 80)])
        self.encoder.close.assert_called_once()
        self.assertIs(self.host.transport, self.transport)

    def test_private_trigger_only_refreshes_and_stops_without_waiting_for_next_tick(self):
        self.stream.set_triggers(.14, 0)
        self.stream.render()
        self.now = .021
        self.stream.render()
        self.assertEqual(len(self.transport.writes), 2)
        self.now = .022
        self.stream.set_triggers(0, 0)
        self.stream.render()
        self.assertEqual(len(self.transport.writes), 3)
        self.assertEqual(self.encoder.frame.call_args.args[1], (0, 0))

    def test_wolverine_trigger_command_keeps_the_physically_verified_mask(self):
        data = trigger_packet(.15, .2)
        self.assertEqual(data[:6], bytes((0, 15, 15, 20, 0, 0)))
        self.assertEqual(trigger_packet(0, 0), bytes((0, 15, 0, 0, 0, 0, 0, 0, 0)))


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock(spec=GipHost)
        self.grips = FakeGrips()
        self.haptics = XboxHaptics()
        self.haptics.attach(self.host, grips=self.grips)

    def test_manual_grip_test_matches_pc_pressure_without_standard_rumble(self):
        pc_grips = FakeGrips()
        pc = GripHaptics(pc_grips)
        pc.test_target = self.haptics.test_target = "grip"
        for index, (left, right) in enumerate(((0, 0), (128, 0), (255, 0), (0, 128), (0, 255), (255, 255), (0, 0))):
            now = index * .004
            pc.step(left, right, now)
            self.haptics.step(left, right, now)
            self.assertEqual(self.grips.sides, pc_grips.sides)
        self.host.send_message.assert_not_called()

    def test_same_pcm_matches_pc_mapping_and_retains_frequency(self):
        feed(self.haptics, pcm_tones(((.4, 180),), frames=2400))
        self.haptics.step(0, 0, now=.001)
        self.assertGreater(self.grips.sides[0][0], 0)
        self.assertAlmostEqual(self.grips.sides[0][1], 180, delta=10)
        self.assertEqual(self.grips.sides[1][0], 0)
        self.assertEqual(self.haptics.bridge.stats["audio_frames"], 2400)

    def test_trigger_effect_does_not_use_legacy_grip_rumble(self):
        self.haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        self.haptics.accept(rumble_report(100, 100), now=0)
        self.haptics.step(0, 255, now=.001)
        self.host.set.assert_not_called()
        self.host.send_message.assert_called_with(0x09, 0, trigger_packet(0, 1))
        self.assertGreater(self.grips.sides[0][0], 0)

    def test_grip_changes_do_not_send_full_mask_zero_rumble(self):
        self.haptics.accept(rumble_report(100, 100), now=0)
        self.haptics.step(0, 0, now=.001)
        self.haptics.accept(rumble_report(200, 200), now=.01)
        self.haptics.step(0, 0, now=.03)
        self.host.send_message.assert_not_called()

    def test_stop_and_new_generation_cannot_revive_output(self):
        self.haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        self.haptics.accept(rumble_report(100, 100), now=0)
        self.haptics.step(0, 255, now=.001)
        self.haptics.accept({"type": "stopped"}, now=.002)
        self.haptics.accept({"type": "reset", "generation": 2}, now=.003)
        self.haptics.step(0, 255, now=.03)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])
        self.assertEqual(self.haptics.bridge.previous, (0, 0, 0, 0))


class PairedStreamTests(unittest.TestCase):
    def setUp(self):
        self.transport = Transport()
        self.host = GipHost(self.transport)
        self.host.phase = "ready"
        self.now = 0
        encoder = Mock()
        encoder.frame.return_value = bytes.fromhex("3c000000")
        self.stream = SensaStream(self.host, encoder, clock=lambda: self.now)
        self.haptics = XboxHaptics()
        with patch("xbox_sensa_bridge.SensaStream", return_value=self.stream):
            self.haptics.attach(self.host)
        self.haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        self.haptics.accept(rumble_report(100, 100), now=0)

    def step(self, now):
        self.now = now
        self.haptics.step(0, 255, now)

    def test_sustained_trigger_is_restored_after_each_private_refresh(self):
        self.step(0)
        self.assertEqual([packet[0] for packet in self.transport.writes], [15, 9])
        self.transport.writes.clear()
        self.step(.021)
        self.assertEqual([packet[0] for packet in self.transport.writes], [15, 9])
        self.assertEqual(self.transport.writes[-1][4:], trigger_packet(0, 1))
        self.transport.writes.clear()
        self.step(.025)
        self.assertEqual(self.transport.writes, [])

    def test_disabling_triggers_stops_immediately_and_prevents_replay(self):
        self.step(0)
        self.transport.writes.clear()
        self.haptics.settings = replace(self.haptics.settings, trigger_enabled=False)
        self.step(.004)
        self.assertEqual([packet[4:] for packet in self.transport.writes], [trigger_packet(0, 0)])
        self.transport.writes.clear()
        self.step(.021)
        self.assertEqual([packet[0] for packet in self.transport.writes], [15])

    def test_grip_only_stream_does_not_emit_standard_rumble(self):
        self.haptics.settings = replace(self.haptics.settings, trigger_enabled=False)
        self.step(0)
        self.step(.021)
        self.step(.042)
        self.assertEqual([packet[0] for packet in self.transport.writes], [15, 15, 15])

    def test_stopped_capture_cannot_replay_the_old_trigger(self):
        self.step(0)
        self.haptics.accept({"type": "stopped"}, now=.002)
        self.transport.writes.clear()
        self.step(.021)
        self.assertTrue(self.transport.writes)
        self.assertTrue(all(packet[0] == 15 for packet in self.transport.writes))


class NativeEncoderTests(unittest.TestCase):
    def test_private_index_frequency_can_be_varied_without_activating_palms(self):
        encoder = XboxEncoder()
        try:
            frames = [encoder.frame([(0, 80), (0, 80)], (.14, .14), trigger_hz=hz) for hz in (80, 180)]
            codes = []
            for frame in frames:
                bits = "".join(f"{byte:08b}" for byte in frame)
                self.assertEqual([int(bits[8 + side * 55:14 + side * 55], 2) for side in range(4)], [0, 0, 8, 8])
                codes.append(int(bits[124:131], 2))
            self.assertNotEqual(*codes)
        finally:
            encoder.close()

    def test_index_targets_are_isolated_from_palms_and_stop_in_one_frame(self):
        encoder = XboxEncoder()
        try:
            for triggers, expected in (((.14, 0), [0, 0, 8, 0]), ((0, .14), [0, 0, 0, 8]),
                                       ((0, 0), [0, 0, 0, 0])):
                frame = encoder.frame([(0, 80), (0, 80)], triggers)
                bits = "".join(f"{byte:08b}" for byte in frame)
                self.assertLessEqual(int(bits[:7], 2), 60)
                peaks = [max(int(bits[8 + side * 55 + offset:14 + side * 55 + offset], 2)
                             for offset in (0, 13, 27, 40)) for side in range(4)]
                self.assertEqual(peaks, expected)
        finally:
            encoder.close()


if __name__ == "__main__":
    unittest.main()
