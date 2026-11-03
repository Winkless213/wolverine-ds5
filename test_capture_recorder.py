import base64
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from capture_recorder import CaptureRecorder, make_recorder, record


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

    def test_backwards_jump_starts_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            recorder.accept(block(1, 0, b"\0" * 4))
            recorder.next_frame = 100000
            recorder.accept(block(1, 0, b"\0" * 4))
            recorder.close()
            self.assertEqual(recorder.stats["resyncs"], 1)
            self.assertEqual(sorted(path.name for path in Path(folder).glob("*.wav")),
                             ["synthetic-0001-r1.wav", "synthetic-0001.wav"])

    def test_forward_gap_starts_new_file_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            recorder.accept(block(1, 0, b"\0" * 4))
            recorder.accept(block(1, 100000, b"\0" * 4))
            recorder.close()
            self.assertEqual(recorder.stats["resyncs"], 1)
            self.assertEqual(len(list(Path(folder).glob("*.wav"))), 2)

    def test_bad_payload_never_becomes_valid_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = CaptureRecorder(Path(folder))
            data = block(1, 0, b"\0" * 4)
            data["frames"] = 10
            with self.assertRaises(ValueError):
                recorder.accept(data)
            recorder.close()


class SwitchTests(unittest.TestCase):
    """开关与旁路降级由两条路径共用，所以在这里而不是各自的桥接里测。"""

    def test_switch_off_returns_no_recorder(self):
        for value in ("0", "", "true"):
            with patch.dict(os.environ, {"WOLVERINE_PLAY_RECORD": value}):
                self.assertIsNone(make_recorder(), f"WOLVERINE_PLAY_RECORD={value!r} 不该开录")
        os.environ.pop("WOLVERINE_PLAY_RECORD", None)
        self.assertIsNone(make_recorder())

    def test_switch_on_writes_under_localappdata(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"WOLVERINE_PLAY_RECORD": "1", "LOCALAPPDATA": folder}):
                recorder = make_recorder()
            self.assertIsNotNone(recorder)
            recorder.accept(block(1, 0, b"\0" * 4, "usb-host"))
            recorder.close()
            self.assertEqual(len(list(Path(folder, "WolverineDS5", "captures").glob("*/capture.json"))), 1)

    def test_record_passes_through_messages_the_recorder_ignores(self):
        recorder = Mock()
        self.assertIs(record(recorder, {"type": "output"}), recorder)
        self.assertIs(record(recorder, {"type": "status"}), recorder)
        recorder.accept.assert_not_called()
        self.assertIsNone(record(None, {"type": "audio"}))

    def test_record_disables_itself_on_failure_instead_of_raising(self):
        recorder = Mock()
        recorder.accept.side_effect = OSError("disk full")
        self.assertIsNone(record(recorder, {"type": "audio"}))


if __name__ == "__main__":
    unittest.main()
