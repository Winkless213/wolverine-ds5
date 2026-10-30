import unittest

import numpy as np

from pcm_to_sensa import EnvelopeToSensa, PcmToSensa


def pcm_tones(left=(), right=(), frames=4800):
    time = np.arange(frames) / 48000
    samples = np.zeros((frames, 2))
    for side, tones in enumerate((left, right)):
        for amplitude, frequency in tones:
            samples[:, side] += amplitude * np.sin(2 * np.pi * frequency * time)
    return np.rint(np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2").tobytes()


def convert(pcm, chunk_frames=48):
    converter = PcmToSensa()
    results = []
    for offset in range(0, len(pcm), chunk_frames * 4):
        results.extend(converter.push(pcm[offset:offset + chunk_frames * 4]))
    return results


class PcmTests(unittest.TestCase):
    def test_stereo_tones_keep_independent_frequencies_and_levels(self):
        final = convert(pcm_tones(((.6, 80),), ((.3, 160),)))[-1]
        for channel, frequency, amplitude in zip(final["channels"], (80, 160), (.132, .066)):
            self.assertAlmostEqual(channel["frequency_hz"], frequency, delta=3)
            self.assertAlmostEqual(channel["amplitude"], amplitude, delta=.008)
        self.assertEqual([channel["bodypart"] for channel in final["channels"]], [216, 116])

    def test_left_only_never_creates_right_energy(self):
        result = convert(pcm_tones(((.5, 120),)))
        self.assertTrue(any(frame["channels"][0]["amplitude"] > .08 for frame in result))
        self.assertTrue(all(frame["channels"][1]["amplitude"] == 0 for frame in result))

    def test_chunk_boundaries_do_not_change_parameters_or_sample_clock(self):
        pcm = pcm_tones(((.7, 110),), ((.4, 250),), frames=4992)
        self.assertEqual(convert(pcm, 48), convert(pcm, 37))
        self.assertEqual([item["end_frame"] for item in convert(pcm)], list(range(192, 4993, 192)))

    def test_silence_and_reset_discard_previous_tone(self):
        converter = PcmToSensa()
        converter.push(pcm_tones(((.8, 100),)))
        quiet = converter.push(b"\0" * 192 * 4)
        self.assertEqual([side["amplitude"] for side in quiet[-1]["channels"]], [0, 0])
        converter.push(pcm_tones(((.8, 100),), frames=48))
        converter.reset()
        quiet = converter.push(b"\0" * 192 * 4)
        self.assertEqual(quiet[-1]["end_frame"], 192)
        self.assertEqual([side["amplitude"] for side in quiet[-1]["channels"]], [0, 0])

    def test_dc_and_out_of_band_signal_are_not_relabelled_as_haptics(self):
        dc = np.full((4800, 2), 16000, dtype="<i2").tobytes()
        for pcm in (dc, pcm_tones(((.8, 1000),), ((.8, 2000),))):
            self.assertTrue(all(side["amplitude"] == 0 for side in convert(pcm)[-1]["channels"]))

    def test_multitone_is_explicitly_a_dominant_tone_approximation(self):
        frame = convert(pcm_tones(((.2, 80), (.6, 240))))[-1]
        self.assertAlmostEqual(frame["channels"][0]["frequency_hz"], 240, delta=3)
        self.assertLessEqual(frame["channels"][0]["amplitude"], .22)

    def test_amplitude_step_does_not_wait_for_the_whole_frequency_window(self):
        for frequency in (30, 80, 160, 320):
            converter = PcmToSensa()
            converter.push(pcm_tones(((.2, frequency),)))
            first = converter.push(pcm_tones(((.6, frequency),), frames=192))[0]
            self.assertAlmostEqual(first["channels"][0]["amplitude"], .132, delta=.0132)
            self.assertEqual(first["channels"][1]["amplitude"], 0)

    def test_invalid_pcm_is_rejected_before_buffering(self):
        converter = PcmToSensa()
        for pcm in (b"", b"\0", b"\0" * 6):
            with self.assertRaises(ValueError):
                converter.push(pcm)

    def test_30hz_stays_active_across_phase_changes_and_20hz_stays_out(self):
        for frequency in (30, 40, 20):
            for phase in (0, 1, 2):
                samples = .6 * np.sin(2 * np.pi * frequency * np.arange(5760) / 48000 + phase)
                pcm = np.column_stack((samples * 32767, np.zeros(5760))).astype("<i2").tobytes()
                steady = [frame["channels"][0] for frame in convert(pcm) if not frame["warmup"]]
                if frequency < 30:
                    self.assertTrue(all(side["amplitude"] == 0 for side in steady))
                else:
                    self.assertTrue(all(abs(side["frequency_hz"] - frequency) <= 1 for side in steady))
                    self.assertTrue(all(abs(side["amplitude"] - .132) < .005 for side in steady))


def envelope(pcm, chunk_frames=48):
    converter = EnvelopeToSensa()
    results = []
    for offset in range(0, len(pcm), chunk_frames * 4):
        results.extend(converter.push(pcm[offset:offset + chunk_frames * 4]))
    return results


class EnvelopeTests(unittest.TestCase):
    def test_sub_30hz_game_haptics_still_vibrate_at_the_lowest_sensa_frequency(self):
        # 10ms 包络短于 15Hz 周期，强度随相位起伏；要求的是“不被丢掉”，与已认可的实机映射一致。
        frames = [frame["channels"] for frame in envelope(pcm_tones(((.3, 15),))) if not frame["warmup"]]
        self.assertGreater(min(left["amplitude"] for left, _ in frames), .05)
        self.assertGreater(max(left["amplitude"] for left, _ in frames), .3)
        self.assertTrue(all(left["frequency_hz"] == 30 and right["amplitude"] == 0 for left, right in frames))

    def test_in_band_tones_keep_their_frequency_per_side(self):
        final = envelope(pcm_tones(((.3, 160),), ((.2, 80),)))[-1]["channels"]
        for channel, frequency, amplitude in zip(final, (160, 80), (.47, .34)):
            self.assertAlmostEqual(channel["frequency_hz"], frequency, delta=6)
            self.assertAlmostEqual(channel["amplitude"], amplitude, delta=.02)
        self.assertEqual([channel["bodypart"] for channel in final], [216, 116])

    def test_weak_game_haptics_are_lifted_but_keep_contrast(self):
        # 实测《死亡搁浅 2》多数触觉只有满幅 2% 左右，p90 约 25%；开平方后实机反馈整体偏强。
        weak = envelope(pcm_tones(((.02, 20),)))[-1]["channels"][0]["amplitude"]
        strong = envelope(pcm_tones(((.25, 20),)))[-1]["channels"][0]["amplitude"]
        self.assertAlmostEqual(weak, .06, delta=.015)
        self.assertAlmostEqual(strong, .4, delta=.05)

    def test_full_scale_is_capped(self):
        self.assertEqual(envelope(pcm_tones(((1, 60),)))[-1]["channels"][0]["amplitude"], 1)

    def test_silence_and_noise_floor_stop_output(self):
        converter = EnvelopeToSensa()
        converter.push(pcm_tones(((.5, 100),)))
        quiet = converter.push(pcm_tones(((.005, 100),), frames=960))[-1]["channels"]
        self.assertEqual([side["amplitude"] for side in quiet], [0, 0])

    def test_chunk_boundaries_do_not_change_parameters_or_sample_clock(self):
        pcm = pcm_tones(((.7, 18),), ((.4, 250),), frames=4992)
        self.assertEqual(envelope(pcm, 48), envelope(pcm, 37))
        self.assertEqual([item["end_frame"] for item in envelope(pcm)], list(range(192, 4993, 192)))

    def test_reset_discards_history(self):
        converter = EnvelopeToSensa()
        converter.push(pcm_tones(((.8, 100),), frames=1000))
        converter.reset()
        quiet = converter.push(b"\0" * 192 * 4)[-1]
        self.assertEqual(quiet["end_frame"], 192)
        self.assertEqual([side["amplitude"] for side in quiet["channels"]], [0, 0])

    def test_invalid_pcm_is_rejected(self):
        for pcm in (b"", b"\0", b"\0" * 6):
            with self.assertRaises(ValueError):
                EnvelopeToSensa().push(pcm)


if __name__ == "__main__":
    unittest.main()
