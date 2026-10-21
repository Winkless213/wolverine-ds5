import ctypes
from ctypes import wintypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import core, native


PAD = r"HID\VID_1532&PID_0A4C&IG_00\UNPLUGGED"
OTHER = r"HID\VID_054C&PID_0CE6\OTHER"
APP = r"C:\Wolverine\WolverineDS5-bridge.exe"


def snapshot(devices=(), apps=(), active=True):
    return {"devices": list(devices), "apps": list(apps), "active": active, "inverse": False}


class HidingStateTests(unittest.TestCase):
    def setUp(self):
        self.chinese_app = r"C:\多频游戏候选\WolverineDS5-bridge.exe"
        apps = [r"\Device\HarddiskVolume3\多频游戏候选\WolverineDS5-bridge.exe",
                r"\Device\HarddiskVolume30\Other.exe", r"\Device\OfflineVolume\Keep.exe"]
        self.payloads = {0x80016000: ("\0".join(apps) + "\0\0").encode("utf-16-le"),
                         0x80016008: (PAD + "\0\0").encode("utf-16-le"),
                         0x80016010: b"\1", 0x80016018: b"\0"}
        self.api = SimpleNamespace(CreateFileW=Mock(return_value=64), CloseHandle=Mock(return_value=1),
                                   DeviceIoControl=Mock(side_effect=self.ioctl),
                                   GetLogicalDrives=Mock(return_value=12),
                                   QueryDosDeviceW=Mock(side_effect=self.dos_device))

    def ioctl(self, handle, code, data, count, buffer, size, returned, overlapped):
        # 只接受官方四个 GET，防止查询状态时意外写入驱动。
        self.assertIn(code, self.payloads)
        self.assertIsNone(data)
        self.assertEqual(count, 0)
        payload = self.payloads[code]
        ctypes.cast(returned, ctypes.POINTER(wintypes.DWORD)).contents.value = len(payload)
        if buffer is not None:
            self.assertGreaterEqual(size, len(payload))
            ctypes.memmove(buffer, payload, len(payload))
        return 1

    def dos_device(self, drive, buffer, size):
        buffer.value = {"C:": r"\Device\HarddiskVolume3", "D:": r"\Device\HarddiskVolume30"}[drive]
        return len(buffer.value) + 1

    def test_unicode_app_and_later_entries_are_read_without_cli_output(self):
        with patch.object(native, "_hidhide_api", return_value=self.api, create=True), \
                patch.object(native, "command", side_effect=RuntimeError("CLI output is truncated")):
            state = native.hiding_state()
        self.assertEqual(state, snapshot((PAD,), (self.chinese_app, r"D:\Other.exe",
                                                  r"\Device\OfflineVolume\Keep.exe")))
        self.api.CloseHandle.assert_called_once_with(64)

    def test_empty_lists_and_inverse_mode_are_preserved(self):
        self.payloads.update({0x80016000: b"\0\0\0\0", 0x80016008: b"\0\0\0\0",
                              0x80016010: b"\0", 0x80016018: b"\1"})
        with patch.object(native, "_hidhide_api", return_value=self.api, create=True), \
                patch.object(native, "command", side_effect=RuntimeError("CLI unavailable")):
            self.assertEqual(native.hiding_state(), {"devices": [], "apps": [], "active": False, "inverse": True})

    def test_driver_read_error_closes_handle_and_does_not_return_empty_state(self):
        self.api.DeviceIoControl.side_effect = OSError("driver unavailable")
        with patch.object(native, "_hidhide_api", return_value=self.api, create=True), \
                patch.object(native, "command", side_effect=RuntimeError("CLI unavailable")):
            with self.assertRaisesRegex(OSError, "driver unavailable"):
                native.hiding_state()
        self.api.CloseHandle.assert_called_once_with(64)

    def test_incomplete_flag_is_not_treated_as_cloak_off(self):
        self.payloads[0x80016010] = b""
        with patch.object(native, "_hidhide_api", return_value=self.api, create=True), \
                patch.object(native, "command", side_effect=RuntimeError("CLI unavailable")):
            with self.assertRaisesRegex(RuntimeError, "HidHide.*不完整"):
                native.hiding_state()
        self.api.CloseHandle.assert_called_once_with(64)


class HidingTests(unittest.TestCase):
    def test_exit_unhides_disconnected_wolverine_without_changing_other_devices(self):
        with patch.object(native, "hiding_state", side_effect=[snapshot((PAD, OTHER), (APP,)),
                                                              snapshot((OTHER,))]), \
                patch.object(native, "command", return_value="") as command:
            native.configure_hiding(False, APP)
        mutation = command.call_args.args
        self.assertIn("--dev-unhide", mutation)
        self.assertIn(PAD, mutation)
        self.assertNotIn(OTHER, mutation)
        self.assertNotIn("--cloak-off", mutation)
        self.assertIn("--app-unreg", mutation)

    def test_exit_disables_empty_cloak_after_removing_our_last_device(self):
        with patch.object(native, "hiding_state", side_effect=[snapshot((PAD,), (APP,)),
                                                              snapshot(active=False)]), \
                patch.object(native, "command", return_value="") as command:
            native.configure_hiding(False, APP)
        self.assertIn("--cloak-off", command.call_args.args)

    def test_zero_exit_code_with_device_still_hidden_is_a_failure(self):
        with patch.object(native, "hiding_state", side_effect=[snapshot((PAD,), (APP,)), snapshot((PAD,))]), \
                patch.object(native, "command", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "隐藏"):
                native.configure_hiding(False, APP)

    def test_start_hides_both_connected_and_disconnected_pc_interfaces(self):
        cable = r"USB\VID_1532&PID_0A4C&MI_00\CABLE"
        with patch.object(native, "hiding_state", side_effect=[snapshot(active=False),
                                                              snapshot((PAD, cable), (APP,))]), \
                patch.object(native, "command", return_value="") as command, \
                patch.object(core, "usb_instances", side_effect=[[cable.lower()], [PAD.lower(), OTHER]]):
            native.configure_hiding(True, APP)
        mutation = command.call_args.args
        self.assertIn(PAD, mutation)
        self.assertIn(cable, mutation)
        self.assertNotIn(OTHER, mutation)
        self.assertIn("--cloak-on", mutation)


class RestoreTests(unittest.TestCase):
    def test_detach_only_removes_the_bridge_virtual_controller(self):
        ports = ("Port 01: device in use\n -> usbip://127.0.0.1:3240/1-1\n"
                 "Port 02: device in use\n -> usbip://192.0.2.1:3240/1-1\n")
        other = "Port 02: device in use\n -> usbip://192.0.2.1:3240/1-1\n"
        with patch.object(native, "command", side_effect=[ports, "", other]) as command:
            native.detach_virtual()
        self.assertEqual(command.call_args_list[1].args[1:], ("detach", "-p", "01"))

    def test_pc_mode_restore_does_not_request_driver_changes(self):
        instance = r"USB\VID_1532&PID_0A4C\TEST"
        with patch.object(native, "configure_hiding") as unhide, patch.object(native, "detach_virtual"), \
                patch.object(core, "usb_instances", return_value=[instance]), \
                patch.object(core, "run_elevated") as elevated:
            native.restore_native(APP)
        unhide.assert_called_once()
        elevated.assert_not_called()

    def test_restore_reads_back_driver_and_does_not_claim_success_when_still_winusb(self):
        instance = r"USB\VID_1532&PID_0A3F\TEST"
        with patch.object(native, "configure_hiding"), patch.object(native, "detach_virtual"), \
                patch.object(core, "usb_instances", return_value=[instance]), \
                patch.object(core, "device_service", return_value="WinUSB"), \
                patch.object(core, "xbox_restore_pending", return_value=False), \
                patch.object(core, "run_elevated", return_value=0), patch.object(native.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "驱动"):
                native.restore_native(APP)

    def test_exit_accepts_verified_reinstall_for_disconnected_xbox_instance(self):
        instance = r"USB\VID_1532&PID_0A3F\TEST"
        with patch.object(native, "configure_hiding"), patch.object(native, "detach_virtual"), \
                patch.object(core, "usb_instances", return_value=[instance]), \
                patch.object(core, "device_service", return_value="WinUSB"), \
                patch.object(core, "xbox_restore_pending", side_effect=[False, True], create=True), \
                patch.object(core, "run_elevated", return_value=0), patch.object(native.time, "sleep"):
            native.restore_native(APP)

    def test_exit_does_not_request_uac_again_for_verified_pending_restore(self):
        instance = r"USB\VID_1532&PID_0A3F\TEST"
        with patch.object(native, "configure_hiding"), patch.object(native, "detach_virtual"), \
                patch.object(core, "usb_instances", return_value=[instance]), \
                patch.object(core, "device_service", return_value="WinUSB"), \
                patch.object(core, "xbox_restore_pending", return_value=True, create=True), \
                patch.object(core, "run_elevated") as elevated:
            native.restore_native(APP)
        elevated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
