import json
import tempfile
import unittest
from pathlib import Path

from sensa_frame import decode_frame
from sensa_preview import SensaPreview, verify_frame
from sensa_offline import OfflineSensa
from pcm_to_sensa import quiet_channels
from test_capture_recorder import block
from test_pcm_to_sensa import pcm_tones


def feed(preview, pcm, generation=1, first=0, now=0):
    records = []
    for offset in range(0, len(pcm), 192):
        records.extend(preview.accept(block(generation, first + offset // 4, pcm[offset:offset + 192]), now=now))
    return records


def peaks(record):
    decoded = decode_frame(bytes.fromhex(record["hex"]))
    return [max(point["amplitude_code"] for band in side["bands"] for point in band)
            for side in decoded["channels"]]


class PreviewTests(unittest.TestCase):
    def test_even_one_native_amplitude_code_is_not_silence(self):
        with OfflineSensa() as engine:
            engine.set_tone(0, 0, 80)
            engine.set_tone(1, .017, 80)
            encoded = engine.frame(.004)
            with self.assertRaises(RuntimeError):
                verify_frame(encoded, quiet_channels())

    def test_continuous_pcm_reaches_real_har_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            with SensaPreview(Path(folder)) as preview:
                frames = feed(preview, pcm_tones(((.6, 80),), ((.3, 160),)))
                final = frames[-1]
                self.assertEqual(final["end_frame"], 4800)
                self.assertEqual(peaks(final), [8, 4])
                self.assertEqual(final["source"], "synthetic")
            self.assertTrue(preview.stats["stop_returned_empty"])
            self.assertFalse(preview.stats["hardware_output"])
            self.assertEqual(preview.stats["parameter_frames"], 25)
            saved = json.loads((Path(folder) / "sensa-preview.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["completed"])

    def test_native_duration_is_recorded_separately_from_parameter_hop(self):
        with tempfile.TemporaryDirectory() as folder, SensaPreview(Path(folder)) as preview:
            record = feed(preview, pcm_tones(((.6, 80),), ((.3, 160),)))[-1]
            self.assertEqual(preview.stats["hop_ms"], 4)
            self.assertEqual(record["encoded_duration_ms"], 60)
            self.assertEqual(set(preview.stats["encoded_duration_ms_counts"]), {"60"})
            self.assertEqual(sum(preview.stats["encoded_duration_ms_counts"].values()), preview.steps)

    def test_gap_emits_silence_and_never_reuses_old_left_tone(self):
        with tempfile.TemporaryDirectory() as folder, SensaPreview(Path(folder)) as preview:
            feed(preview, pcm_tones(((.8, 80),)))
            frames = feed(preview, pcm_tones(right=((.5, 160),), frames=1920), first=4848)
            self.assertEqual(frames[0]["reason"], "gap")
            self.assertEqual(peaks(frames[0]), [0, 0])
            self.assertTrue(all(peaks(frame)[0] == 0 for frame in frames))
            self.assertEqual(preview.stats["missing_frames"], 48)

    def test_new_generation_rejects_late_blocks(self):
        with tempfile.TemporaryDirectory() as folder, SensaPreview(Path(folder)) as preview:
            feed(preview, pcm_tones(((.8, 80),)))
            quiet = preview.accept({"type": "reset", "generation": 2})
            self.assertEqual(peaks(quiet[-1]), [0, 0])
            self.assertEqual(preview.accept(block(1, 4800, b"\0" * 192)), [])
            frames = feed(preview, pcm_tones(right=((.5, 160),)), generation=2)
            self.assertTrue(all(peaks(frame)[0] == 0 for frame in frames))
            self.assertEqual(preview.stats["stale_blocks"], 1)

    def test_timeout_clears_once_and_new_audio_can_resume(self):
        with tempfile.TemporaryDirectory() as folder, SensaPreview(Path(folder)) as preview:
            feed(preview, pcm_tones(((.8, 80),)), now=1)
            self.assertIsNone(preview.poll(1.04))
            self.assertEqual(peaks(preview.poll(1.06)), [0, 0])
            self.assertIsNone(preview.poll(1.2))
            frames = feed(preview, pcm_tones(right=((.5, 160),)), first=4800, now=1.2)
            self.assertEqual(peaks(frames[-1])[0], 0)
            self.assertGreater(peaks(frames[-1])[1], 0)
            self.assertEqual(preview.stats["timeouts"], 1)

    def test_malformed_audio_clears_the_active_effect(self):
        with tempfile.TemporaryDirectory() as folder, SensaPreview(Path(folder)) as preview:
            feed(preview, pcm_tones(((.8, 80),)))
            invalid = block(1, 4800, b"\0" * 192)
            invalid["sample_rate"] = 44100
            with self.assertRaises(ValueError):
                preview.accept(invalid)
            self.assertEqual(preview.stats["invalid_blocks"], 1)
            self.assertEqual(peaks(preview.last_record), [0, 0])

    def test_duplicate_and_incomplete_hop_cannot_invent_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            with SensaPreview(Path(folder)) as preview:
                first = block(1, 0, b"\0" * 192)
                preview.accept(first)
                self.assertEqual(preview.accept(first), [])
            self.assertEqual(preview.stats["duplicate_blocks"], 1)
            self.assertEqual(preview.stats["parameter_frames"], 0)
            self.assertEqual(preview.stats["discarded_tail_frames"], 48)


if __name__ == "__main__":
    unittest.main()
