import unittest

from api_check import ROOT, inspect_host


@unittest.skipUnless((ROOT / "wolverine-capture.exe").exists(), "needs a locally built wolverine-capture.exe")
class HostApiTests(unittest.TestCase):
    def test_real_local_socket_carries_input_audio_triggers_and_shutdown(self):
        result = inspect_host()
        self.assertTrue(result["usbip_rear_pcm_exact"])
        self.assertTrue(result["trigger_report_exact"])
        self.assertTrue(result["input_roundtrip"])
        self.assertTrue(result["input_watchdog_neutral"])
        self.assertTrue(result["audio_reopen_generation"])
        self.assertFalse(result["physical_output"])


if __name__ == "__main__":
    unittest.main()
