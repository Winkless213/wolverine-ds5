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

    def test_decodes_native_encoder_optional_bands_and_stereo_boundary(self):
        # 编码器 v2.0.1.11 的真实 Sage 元数据、单频带配置、仅左声道 60Hz 输出。
        frame = bytes.fromhex("51fc27e13f09f84200000000000000")
        result = decode_frame(frame)
        self.assertEqual(result["duration_ms"], 40)
        left, right = result["channels"]
        self.assertEqual(left, {"bodypart": 216, "bands": [[{"amplitude_code":63, "frequency_code":4}] * 4], "transients": []})
        self.assertEqual(right, {"bodypart": 116, "bands": [[{"amplitude_code":0, "frequency_code":0}] * 4], "transients": []})

    def test_optional_band_frame_keeps_strict_length_and_padding_checks(self):
        frame = bytes.fromhex("51fc27e13f09f84200000000000000")
        for invalid in (frame[:-1], frame + b"\0", frame[:-1] + b"\x01"):
            with self.subTest(frame=invalid.hex()), self.assertRaises(ValueError):
                decode_frame(invalid)


if __name__ == "__main__":
    unittest.main()
