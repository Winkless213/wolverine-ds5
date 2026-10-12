import unittest

from sensa_offline import OfflineSensa
from sensa_frame import decode_frame
from sensa_api_check import inspect_engine


class SensaOfflineTests(unittest.TestCase):
    def test_timing_check_covers_both_targets_at_each_compute_interval(self):
        report = inspect_engine()
        self.assertEqual([case["compute_interval_ms"] for case in report["stereo_intervals"]],
                         [1, 2, 4, 8, 16])
        self.assertEqual([case["encoded_duration_ms"] for case in report["stereo_intervals"]],
                         [[60, 60, 60]] * 5)
        self.assertTrue(all(case["stop_returned_empty"] for case in report["stereo_intervals"]))

    def test_native_left_right_updates_and_stop_without_provider(self):
        with OfflineSensa() as engine:
            self.assertEqual(engine.layout, [216, 1, 3, 4, 2, 116, 1, 3, 4, 2])
            self.assertEqual(engine.max_frame_bytes, 52)
            engine.set_tone(0, .22, 80)
            left = engine.frame(.01)
            engine.set_tone(0, 0, 80)
            engine.set_tone(1, .22, 160)
            right = engine.frame(.02)
            self.assertTrue(left)
            self.assertTrue(right)
            self.assertNotEqual(left, right)
            left_channels = decode_frame(left)["channels"]
            right_channels = decode_frame(right)["channels"]
            self.assertEqual(left_channels[0]["bands"][0][0]["amplitude_code"], 13)
            self.assertEqual(right_channels[1]["bands"][0][0]["amplitude_code"], 13)
            self.assertTrue(all(point["amplitude_code"] == 0 for band in left_channels[1]["bands"] for point in band))
            self.assertTrue(all(point["amplitude_code"] == 0 for band in right_channels[0]["bands"] for point in band))
            engine.stop()
            self.assertEqual(engine.frame(.03), b"")


if __name__ == "__main__":
    unittest.main()
