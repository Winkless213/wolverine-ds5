import unittest
from unittest.mock import Mock

from xusb_output import XusbOutput, build_report


class ReportTests(unittest.TestCase):
    def test_four_channels_use_independent_protocol_positions(self):
        self.assertEqual(build_report(.22, 0, 0, 0).hex(), "030f000016000a0002")
        self.assertEqual(build_report(0, .22, 0, 0).hex(), "030f000000160a0002")
        self.assertEqual(build_report(0, 0, .22, 0).hex(), "030f160000000a0002")
        self.assertEqual(build_report(0, 0, 0, .22).hex(), "030f001600000a0002")

    def test_stop_clears_every_motor_and_pulse_field(self):
        self.assertEqual(build_report(0, 0, 0, 0), bytes.fromhex("030f00000000000000"))

    def test_invalid_amplitude_never_becomes_a_packet(self):
        for value in (-.1, .251, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_report(value, 0, 0, 0)


class OutputTests(unittest.TestCase):
    def api(self):
        api = Mock()
        api.paths.return_value = ["xusb-interface"]
        api.parents.return_value = ["HID\\VID_045E&PID_02FF&IG_00\\compat",
                                    "USB\\VID_1532&PID_0A3F\\physical"]
        api.open.return_value = 7
        api.info.return_value = {"vendor": "045E", "product": "02FF"}
        api.write.return_value = 9
        api.close.return_value = True
        return api

    def test_open_requires_the_real_razer_parent_and_sends_nothing(self):
        api = self.api()
        output = XusbOutput(api=api)
        self.assertEqual(output.identity["vendor"], "1532")
        self.assertEqual(output.identity["product"], "0A3F")
        api.write.assert_not_called()

    def test_microsoft_compatibility_ids_alone_are_not_a_target(self):
        api = self.api()
        api.parents.return_value = ["USB\\VID_045E&PID_02FF\\physical"]
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            XusbOutput(api=api)
        api.open.assert_not_called()
        api.write.assert_not_called()

    def test_multiple_razer_interfaces_are_not_selected_by_slot_order(self):
        api = self.api()
        api.paths.return_value = ["first", "second"]
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            XusbOutput(api=api)
        api.open.assert_not_called()

    def test_short_write_is_a_failure_and_is_recorded(self):
        api = self.api()
        output = XusbOutput(api=api)
        api.write.return_value = 4
        with self.assertRaisesRegex(OSError, "Short"):
            output.set(.22, 0, 0, 0)
        self.assertFalse(output.calls[-1]["ok"])

    def test_close_attempts_stop_and_releases_handle_even_when_stop_fails(self):
        api = self.api()
        output = XusbOutput(api=api)
        api.write.side_effect = OSError("device removed")
        with self.assertRaises(OSError):
            output.close()
        api.write.assert_called_once_with(7, bytes.fromhex("030f00000000000000"))
        api.close.assert_called_once_with(7)
        output.close()
        api.close.assert_called_once()

    def test_identity_query_failure_releases_the_open_handle(self):
        api = self.api()
        api.info.side_effect = OSError("device removed")
        with self.assertRaises(OSError):
            XusbOutput(api=api)
        api.close.assert_called_once_with(7)
        api.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
