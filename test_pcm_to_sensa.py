import unittest

import numpy as np

from pcm_to_sensa import PcmToSensa


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


if __name__ == "__main__":
    unittest.main()
