import base64
import tempfile
import unittest
import wave
from pathlib import Path

from capture_recorder import CaptureRecorder


def block(generation, first, pcm, source="synthetic"):
    return {"type": "audio", "source": source, "generation": generation,
            "sample_rate": 48000, "first_frame": first, "frames": len(pcm) // 4,
            "pcm": base64.b64encode(pcm).decode("ascii")}


class CaptureRecorderTests(unittest.TestCase):
    def test_recording_preserves_stereo_and_pads_reported_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            recorder.accept(block(1, 0, bytes.fromhex("01 00 02 00")))
            recorder.accept(block(1, 3, bytes.fromhex("03 00 04 00")))
            recorder.close()
            with wave.open(str(Path(folder) / "synthetic-0001.wav"), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 2)
                self.assertEqual(audio.getframerate(), 48000)
                self.assertEqual(audio.readframes(4), bytes.fromhex("01 00 02 00 00 00 00 00 00 00 00 00 03 00 04 00"))
            self.assertEqual(recorder.stats["missing_frames"], 2)

    def test_old_generation_after_reset_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            recorder.accept({"type": "reset", "generation": 2})
            recorder.accept(block(1, 0, b"\0" * 4))
            recorder.close()
            self.assertEqual(recorder.stats["stale_blocks"], 1)
            self.assertEqual(list(Path(folder).glob("*.wav")), [])

    def test_bad_payload_never_becomes_valid_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            data = block(1, 0, b"\0" * 4)
            data["frames"] = 10
            with self.assertRaises(ValueError):
                recorder.accept(data)
            recorder.close()


if __name__ == "__main__":
    unittest.main()
