import base64
import json
import unittest
from unittest.mock import Mock, patch

import gip_bridge
import pc_bridge
from gip_bridge import Status
from pc_bridge import LIMIT, RUMBLE_HZ, GripHaptics
from settings import Settings
from test_capture_recorder import block
from test_pcm_to_sensa import pcm_tones


class FakeGrips:
    def __init__(self):
        self.sides = [(0.0, 80.0), (0.0, 80.0)]
        self.sets = []
        self.renders = 0

    def set(self, side, amplitude, frequency):
        self.sides[side] = (amplitude, frequency)
        self.sets.append((side, amplitude, frequency))

    def render(self):
        self.renders += 1


def rumble_report(left, right):
    report = bytearray(48)
    report[0], report[1], report[3], report[4] = 2, 1, right, left
    return {"type": "output", "report": base64.b64encode(bytes(report)).decode("ascii")}


def feed(haptics, pcm, now=0, first=0, generation=1):
    for offset in range(0, len(pcm), 192):
        haptics.accept(block(generation, first + offset // 4, pcm[offset:offset + 192], "usb-host"), now=now)


class GripHapticsTests(unittest.TestCase):
    def setUp(self):
        self.grips = FakeGrips()
        self.haptics = GripHaptics(self.grips)

    def test_sub_30hz_game_haptics_vibrate_the_same_side_only(self):
        feed(self.haptics, pcm_tones(((.4, 18),), frames=2400))
        self.haptics.step(0, 0, now=.001)
        (left, frequency), (right, _) = self.grips.sides
        self.assertGreater(left, .05)
        self.assertEqual(frequency, 30)
        self.assertEqual(right, 0)

    def test_classic_rumble_drives_both_grips_at_the_resonance(self):
        self.haptics.accept(rumble_report(left=255, right=51), now=0)
        self.haptics.step(0, 0, now=0)
        (left, left_hz), (right, right_hz) = self.grips.sides
        self.assertEqual((left, left_hz, right_hz), (LIMIT, RUMBLE_HZ, RUMBLE_HZ))
        self.assertAlmostEqual(right, LIMIT * .2)

    def test_audio_timeout_clears_haptics_but_keeps_classic_rumble(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400))
        self.haptics.accept(rumble_report(left=0, right=128), now=0)
        self.haptics.step(0, 0, now=.01)
        self.assertGreater(self.grips.sides[0][0], 0)
        self.haptics.step(0, 0, now=.06)
        self.assertEqual(self.grips.sides[0][0], 0)
        self.assertGreater(self.grips.sides[1][0], 0)

    def test_host_stop_silences_everything(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400))
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.accept({"type": "stopped"}, now=0)
        self.haptics.step(0, 0, now=.001)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_grip_switch_and_gain(self):
        self.haptics.accept(rumble_report(left=255, right=128), now=0)
        self.haptics.settings = Settings(grip_gain=1.5)
        self.haptics.step(0, 0, now=0)
        self.assertAlmostEqual(self.grips.sides[0][0], min(1, LIMIT * 1.5))
        self.haptics.settings = Settings(grip_enabled=False)
        self.haptics.step(0, 0, now=.004)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_grip_test_follows_lt_rt_and_mutes_the_game(self):
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.test_target = "grip"
        self.haptics.step(255, 0, now=0)
        self.assertEqual(self.grips.sides, [(LIMIT, RUMBLE_HZ), (0, 80.0)])

    def test_trigger_test_is_silent_because_pc_mode_has_no_trigger_motors(self):
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.test_target = "trigger"
        self.haptics.step(255, 255, now=0)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_restarted_haptic_stream_resyncs_instead_of_failing(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=960))
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400), first=50000)
        self.haptics.step(0, 0, now=.001)
        self.assertGreater(self.grips.sides[0][0], 0)
        self.assertEqual(self.haptics.stats["audio_resyncs"], 1)

    def test_unchanged_output_is_rendered_but_not_resent(self):
        self.haptics.accept(rumble_report(left=255, right=0), now=0)
        for step in range(5):
            self.haptics.step(0, 0, now=step * .004)
        self.assertEqual(len(self.grips.sets), 1)
        self.assertEqual(self.grips.renders, 5)

    def test_reattached_output_receives_the_current_state(self):
        self.haptics.accept(rumble_report(left=255, right=0), now=0)
        self.haptics.step(0, 0, now=0)
        fresh = FakeGrips()
        self.haptics.attach(fresh)
        self.haptics.step(0, 0, now=.004)
        self.assertEqual(fresh.sides[0], (LIMIT, RUMBLE_HZ))

    def test_settings_and_test_commands_reach_the_pc_haptics(self):
        gip_bridge.handle_command(self.haptics, {"type": "settings", "settings": {"grip_gain": .3}})
        gip_bridge.handle_command(self.haptics, {"type": "test", "target": "grip"})
        self.assertEqual((self.haptics.settings.grip_gain, self.haptics.test_target), (.3, "grip"))


class OpenTests(unittest.TestCase):
    def test_missing_sensa_is_reported_with_its_reason(self):
        lines = []
        with patch.object(gip_bridge, "STATUS", Status(lines.append)), \
                patch.object(pc_bridge, "RazerInput"), \
                patch.object(pc_bridge, "SensaGrips", side_effect=ConnectionError("Sensa unavailable")):
            with self.assertRaises(ConnectionError):
                pc_bridge.open_devices()
        self.assertEqual(json.loads(lines[-1])["reason"], "sensa")

    def test_input_is_closed_when_sensa_fails(self):
        pad = Mock()
        with patch.object(gip_bridge, "STATUS", Status(Mock())), \
                patch.object(pc_bridge, "RazerInput", return_value=pad), \
                patch.object(pc_bridge, "SensaGrips", side_effect=ConnectionError("Sensa unavailable")):
            with self.assertRaises(ConnectionError):
                pc_bridge.open_devices()
        pad.close.assert_called_once()


class StatusDetailTests(unittest.TestCase):
    def test_changed_waiting_reason_is_reported_again(self):
        lines = []
        status = Status(lines.append)
        status.set("waiting", reason="input")
        status.set("waiting", reason="input")
        status.set("waiting", reason="sensa")
        self.assertEqual([json.loads(line)["reason"] for line in lines], ["input", "sensa"])


if __name__ == "__main__":
    unittest.main()
