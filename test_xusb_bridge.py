import unittest
from unittest.mock import Mock

from test_capture_recorder import block
from test_pcm_to_sensa import pcm_tones
from xusb_bridge import XusbBridge


class BridgeTests(unittest.TestCase):
    def feed(self, bridge):
        pcm = pcm_tones(((.6, 80),), ((.3, 160),), frames=2400)
        for offset in range(0, len(pcm), 192):
            bridge.accept(block(1, offset // 4, pcm[offset:offset + 192], "usb-host"), now=0)

    def test_stereo_amplitudes_and_trigger_values_keep_four_independent_channels(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        self.feed(bridge)
        bridge.poll((.11, .055), now=.01)
        left, right, lt, rt = output.set.call_args.args
        self.assertAlmostEqual(left, .132, delta=.008)
        self.assertAlmostEqual(right, .066, delta=.008)
        self.assertEqual((lt, rt), (.11, .055))

    def test_audio_timeout_stops_grips_without_erasing_live_trigger_effect(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        self.feed(bridge)
        bridge.poll((.11, 0), now=.01)
        bridge.poll((.11, 0), now=.04)
        bridge.poll((.11, 0), now=.061)
        self.assertEqual(output.set.call_args.args, (0, 0, .11, 0))

    def test_audio_timeout_keeps_classic_rumble(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        self.feed(bridge)
        bridge.rumble = (.05, .1)
        bridge.poll((0, 0), now=.01)
        bridge.poll((0, 0), now=.04)
        bridge.poll((0, 0), now=.061)
        self.assertEqual(output.set.call_args.args, (.05, .1, 0, 0))

    def test_missing_audio_fails_closed_instead_of_playing_old_values(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        self.feed(bridge)
        bridge.poll((.11, 0), now=.01)
        with self.assertRaisesRegex(ValueError, "sequence"):
            bridge.accept(block(1, 2448, bytes(192), "usb-host"), now=.02)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_synthetic_messages_cannot_reach_the_live_output(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        with self.assertRaisesRegex(ValueError, "USB"):
            bridge.accept(block(1, 0, bytes(192)), now=0)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_main_loop_stall_clears_every_motor_and_requires_restart(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        bridge.poll((.11, 0), now=0)
        with self.assertRaisesRegex(TimeoutError, "50 ms"):
            bridge.poll((.11, 0), now=.051)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_rate_limit_keeps_latest_values_and_does_not_delay_full_stop(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        bridge.poll((.1, 0), now=0)
        bridge.poll((.2, 0), now=.005)
        self.assertEqual(output.set.call_count, 1)
        bridge.poll((.15, 0), now=.021)
        self.assertEqual(output.set.call_args.args, (0, 0, .15, 0))
        bridge.poll((0, 0), now=.022)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_close_releases_the_output_even_after_an_error(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        output.close.side_effect = OSError("removed")
        with self.assertRaises(OSError):
            bridge.close()
        output.close.assert_called_once()
        with self.assertRaises(RuntimeError):
            bridge.poll((.1, 0), now=0)

    def test_host_stop_cannot_restart_persistent_trigger_effects(self):
        output = Mock(calls=[])
        bridge = XusbBridge(output)
        bridge.poll((.1, 0), now=0)
        bridge.accept({"type": "stopped"}, now=.005)
        bridge.poll((.1, 0), now=.025)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
