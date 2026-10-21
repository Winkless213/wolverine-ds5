import unittest
from unittest.mock import Mock

import sdl_input
from sdl_input import input_state


class InputTests(unittest.TestCase):
    def test_compatibility_id_requires_verified_physical_razer_parent(self):
        verify = Mock(return_value={"vendor": "1532", "product": "0A3F", "path": "physical-xusb"})
        ident, identity = sdl_input.select_device([(9, 0x045E, 0x02FF)], verify)
        self.assertEqual(ident, 9)
        self.assertEqual(identity["vendor"], "1532")
        self.assertEqual(identity["path"], "physical-xusb")
        verify.assert_called_once()

    def test_multiple_xinput_devices_cannot_be_associated_by_list_order(self):
        verify = Mock()
        with self.assertRaises(RuntimeError):
            sdl_input.select_device([(9, 0x045E, 0x02FF), (10, 0x045E, 0x028E)], verify)
        verify.assert_not_called()

    def test_failed_physical_verification_is_not_a_compatible_controller(self):
        verify = Mock(side_effect=RuntimeError("Not a physical Razer"))
        with self.assertRaisesRegex(RuntimeError, "Not a physical Razer"):
            sdl_input.select_device([(9, 0x045E, 0x02FF)], verify)

    def test_original_pc_mode_does_not_need_xusb_alias_verification(self):
        verify = Mock(side_effect=AssertionError("Unexpected alias check"))
        ident, identity = sdl_input.select_device([(5, 0x1532, 0x0A4C)], verify)
        self.assertEqual((ident, identity["product"]), (5, "0A4C"))

    def test_neutral_imu_matches_virtual_device_without_claiming_a_sensor(self):
        self.assertEqual(input_state([0]*6, set())["AccelZ"], -8192)

    def test_xbox_buttons_and_dpad_map_to_dualsense(self):
        result = input_state([0]*6, {0, 2, 4, 6, 11, 14})
        self.assertEqual(result["Buttons"], 0x22030)
        self.assertEqual(result["DPad"], 9)

    def test_view_clicks_touchpad_and_release_keeps_options(self):
        self.assertEqual(input_state([0]*6, {4})["Buttons"], 0x20000)
        self.assertEqual(input_state([0]*6, {4, 6})["Buttons"], 0x22000)
        self.assertEqual(input_state([0]*6, {6})["Buttons"], 0x2000)
        self.assertEqual(input_state([0]*6, set())["Buttons"], 0)

    def test_stick_extremes_and_trigger_press(self):
        result = input_state([-32768, 32767, 0, 256, 32767, 0], set())
        self.assertEqual([result[k] for k in ("LX", "LY", "RX", "RY", "L2", "R2")], [-128,127,0,1,255,0])
        self.assertEqual(result["Buttons"], 0x400)


if __name__ == "__main__":
    unittest.main()
