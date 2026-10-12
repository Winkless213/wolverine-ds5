import unittest

from trigger_mapper import TriggerPair


FEEDBACK = bytes.fromhex("21 ff 03 ff ff ff 3f 00 00 00 00")
WEAPON = bytes.fromhex("25 84 00 07 00 00 00 00 00 00 00")
VIBRATION = bytes.fromhex("26 ff 03 00 00 00 00 00 00 0a 00")
OFF = bytes.fromhex("05 00 00 00 00 00 00 00 00 00 00")


def report(left=None, right=None):
    data = bytearray(48)
    data[0] = 2
    if left is not None:
        data[1] |= 8
        data[22:33] = left
    if right is not None:
        data[1] |= 4
        data[11:22] = right
    return bytes(data)


class TriggerTests(unittest.TestCase):
    def test_weapon_crossing_fires_once_even_with_duplicate_reports(self):
        pair = TriggerPair()
        pair.update_report(report(right=WEAPON))
        self.assertEqual(pair.sample(0, 0.1, 0), (0, 0))
        self.assertEqual(pair.sample(0, 0.8, 0.001), (0, 0.22))
        pair.update_report(report(right=WEAPON))
        self.assertEqual(pair.sample(0, 0.8, 0.1), (0, 0))
        self.assertEqual(pair.sample(0, 0.1, 0.2), (0, 0))
        self.assertEqual(pair.sample(0, 0.8, 0.201), (0, 0.22))

    def test_first_observation_while_held_does_not_invent_shot(self):
        pair = TriggerPair()
        pair.update_report(report(left=WEAPON))
        self.assertEqual(pair.sample(1, 0, 0), (0, 0))

    def test_partial_update_retains_other_trigger_and_off_clears_pulse(self):
        pair = TriggerPair()
        pair.update_report(report(left=FEEDBACK, right=WEAPON))
        pair.sample(0.4, 0, 0)
        self.assertEqual(pair.sample(0.4, 0.9, 0.01), (0.22, 0.22))
        pair.update_report(report(right=OFF))
        self.assertEqual(pair.sample(0.4, 0.9, 0.011), (0.22, 0))

    def test_feedback_selects_position_zone_and_strength(self):
        pair = TriggerPair()
        pair.update_report(report(left=bytes.fromhex("21 02 00 18 00 00 00 00 00 00 00")))
        self.assertEqual(pair.sample(0, 0, 0), (0, 0))
        self.assertEqual(pair.sample(0.15, 0, 0.01), (0.11, 0))
        self.assertEqual(pair.sample(0.8, 0, 0.02), (0, 0))

    def test_vibration_retains_low_frequency_rhythm(self):
        pair = TriggerPair()
        pair.update_report(report(right=VIBRATION))
        self.assertEqual(pair.sample(0, 0.5, 0), (0, 0.22 / 8))
        self.assertEqual(pair.sample(0, 0.5, 0.075), (0, 0))
        self.assertEqual(pair.sample(0, 0.5, 0.101), (0, 0.22 / 8))

    def test_unknown_and_malformed_effects_cannot_leave_old_rumble(self):
        pair = TriggerPair()
        pair.update_report(report(left=FEEDBACK))
        pair.update_report(report(left=bytes.fromhex("fc 00 00 00 00 00 00 00 00 00 00")))
        self.assertEqual(pair.sample(1, 0, 0), (0, 0))
        self.assertEqual(pair.unsupported_modes, {0xfc})
        pair.update_report(report(right=bytes.fromhex("25 04 00 07 00 00 00 00 00 00 00")))
        self.assertEqual(pair.sample(0, 1, 0.1), (0, 0))

    def test_unflagged_and_truncated_reports_do_not_replace_state(self):
        pair = TriggerPair()
        pair.update_report(report(left=FEEDBACK))
        pair.update_report(bytes.fromhex("02 08 00"))
        pair.update_report(report())
        self.assertEqual(pair.sample(1, 0, 0), (0.22, 0))
        pair.reset()
        self.assertEqual(pair.sample(1, 1, 0.1), (0, 0))


if __name__ == "__main__":
    unittest.main()
