import unittest

from sensa_frame import decode_frame


class FrameTests(unittest.TestCase):
    def test_decodes_native_har_left_80hz_fixture(self):
        frame = bytes.fromhex("1f3489a44d226918000000000000400000000000010000000000000800000000000040000000000000")
        result = decode_frame(frame)
        self.assertEqual(result["duration_ms"], 15)
        self.assertEqual(result["channels"][0]["bodypart"], 216)
        self.assertEqual(result["channels"][0]["bands"][0], [{"amplitude_code":13, "frequency_code":17}] * 4)
        self.assertTrue(all(point["amplitude_code"] == 0 for band in result["channels"][1]["bands"] for point in band))

    def test_rejects_truncated_or_extended_frame(self):
        with self.assertRaises(ValueError):
            decode_frame(b"\xff")
        frame = bytes.fromhex("1f3489a44d226918000000000000400000000000010000000000000800000000000040000000000000")
        with self.assertRaises(ValueError):
            decode_frame(frame + b"\0")


if __name__ == "__main__":
    unittest.main()
