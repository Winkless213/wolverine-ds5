import unittest
from unittest.mock import Mock, patch

from gip_bridge import Haptics, handle_command
from settings import Settings
from test_gip_bridge import trigger_report
from test_trigger_mapper import OFF, report
from trigger_mapper import TriggerPair


CONTACT = bytes.fromhex("21c0030000000000000000")
DEEP_CONTACT = bytes.fromhex("2100020000000000000000")
GAME_PULSE = bytes.fromhex("26ff03499224090000b400")


class ResistanceEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.pair = TriggerPair(gain=1, feedback_envelope=True)
        self.pair.update_report(report(left=CONTACT, right=CONTACT))
        self.assertEqual(self.pair.sample(0, 0, 0), (0, 0))

    def test_contact_has_attack_decay_and_silent_hold(self):
        self.assertEqual(self.pair.sample(.59, 0, .01), (0, 0))
        self.assertEqual(self.pair.sample(.7, 0, .02), (.125, 0))
        self.assertEqual(self.pair.sample(.7, 0, .06), (.125, 0))
        decayed, _ = self.pair.sample(.7, 0, .16)
        self.assertGreater(decayed, 0)
        self.assertLess(decayed, .125)
        self.assertEqual(self.pair.sample(.7, 0, .3), (0, 0))
        self.assertEqual(self.pair.sample(.7, 0, 2), (0, 0))

    def test_duplicate_and_threshold_updates_do_not_restart_held_feedback(self):
        self.pair.sample(1, 0, .01)
        self.pair.update_report(report(left=CONTACT))
        self.assertEqual(self.pair.sample(1, 0, .3), (0, 0))
        self.pair.update_report(report(left=DEEP_CONTACT))
        self.assertEqual(self.pair.sample(1, 0, .4), (0, 0))
        self.pair.update_report(report(left=CONTACT))
        self.assertEqual(self.pair.sample(1, 0, .5), (0, 0))

    def test_boundary_jitter_does_not_rearm_but_deliberate_release_does(self):
        self.pair.sample(.7, 0, .01)
        self.assertEqual(self.pair.sample(.599, 0, .02), (0, 0))
        self.assertEqual(self.pair.sample(.601, 0, .03), (0, 0))
        self.assertEqual(self.pair.sample(.5, 0, .04), (0, 0))
        self.assertEqual(self.pair.sample(.7, 0, .05), (.125, 0))

    def test_left_and_right_contacts_are_independent(self):
        self.assertEqual(self.pair.sample(.7, 0, .01), (.125, 0))
        self.assertEqual(self.pair.sample(.7, .7, .3), (0, .125))
        self.assertEqual(self.pair.sample(.7, 0, .31), (0, 0))

    def test_initial_held_position_and_reset_do_not_invent_contact(self):
        self.pair.reset()
        self.pair.update_report(report(left=CONTACT))
        self.assertEqual(self.pair.sample(1, 0, 1), (0, 0))
        self.pair.sample(0, 0, 1.01)
        self.assertEqual(self.pair.sample(1, 0, 1.02), (.125, 0))
        self.assertEqual(self.pair.sample(1, 0, 1.4), (0, 0))

    def test_game_vibration_interrupts_feedback_without_extra_contact_on_return(self):
        self.pair.sample(1, 0, .01)
        self.pair.update_report(report(left=GAME_PULSE))
        self.assertEqual(self.pair.sample(1, 0, .1), (.25, 0))
        self.pair.update_report(report(left=GAME_PULSE))
        self.assertEqual(self.pair.sample(1, 0, .15), (.25, 0))
        self.pair.update_report(report(left=CONTACT))
        self.assertEqual(self.pair.sample(1, 0, .16), (0, 0))

    def test_off_stops_feedback_and_all_zone_effect_is_silent_at_rest(self):
        self.pair.sample(1, 0, .01)
        self.pair.update_report(report(left=OFF))
        self.assertEqual(self.pair.sample(1, 0, .02), (0, 0))
        self.pair.update_report(report(left=bytes.fromhex("21ff030000000000000000")))
        self.assertEqual(self.pair.sample(0, 0, .03), (0, 0))
        self.assertEqual(self.pair.sample(.5, 0, .04), (.125, 0))
        self.assertEqual(self.pair.sample(0, 0, .05), (0, 0))

    def test_invalid_position_clears_feedback_and_retains_envelope_mode(self):
        self.pair.sample(.7, 0, .01)
        self.assertEqual(self.pair.sample(float("nan"), 0, .02), (0, 0))
        self.pair.update_report(report(left=CONTACT))
        self.pair.sample(0, 0, .03)
        self.assertEqual(self.pair.sample(1, 0, .04), (.125, 0))
        self.assertEqual(self.pair.sample(1, 0, .4), (0, 0))


class EnvelopeBridgeTests(unittest.TestCase):
    def test_experimental_flag_uses_envelope_with_saved_gain_and_switch(self):
        output = Mock()
        with patch.dict("os.environ", {"WOLVERINE_TRIGGER_ENVELOPE": "1"}):
            haptics = Haptics(output, Settings(trigger_resistance=True, trigger_gain=.15))
        haptics.accept(trigger_report(right_effect=CONTACT), now=0)
        haptics.step(0, 0, now=0)
        haptics.step(0, 255, now=.01)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, .01875))
        for now in (.04, .07, .1, .13, .16, .19, .22, .25, .28):
            haptics.step(0, 255, now=now)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))
        self.assertEqual(haptics.stalls, 0)
        handle_command(haptics, {"type": "settings", "settings": {"trigger_resistance": False}})
        haptics.step(0, 0, now=.3)
        haptics.step(0, 255, now=.32)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_without_flag_retains_existing_resistance_mapping(self):
        output = Mock()
        with patch.dict("os.environ", {"WOLVERINE_TRIGGER_ENVELOPE": "0"}):
            haptics = Haptics(output, Settings(trigger_resistance=True, trigger_gain=.15))
        haptics.accept(trigger_report(right_effect=CONTACT), now=0)
        haptics.step(0, 0, now=0)
        for index in range(1, 16):
            haptics.step(0, 255, now=index * .02)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, .01875))


if __name__ == "__main__":
    unittest.main()
