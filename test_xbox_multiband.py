import math
import unittest

from settings import Settings
from sensa_multiband import MixState
from xbox_multiband import (BandAnalyzer, compose_bands, compose_envelope, ENVELOPE_MAX_TOTAL,
                            FrequencyHold, LevelHold, QUIET_BANDS)


def sine(seconds, amplitude, hz, sample_rate=48000):
    t = [i / sample_rate for i in range(int(seconds * sample_rate))]
    return [amplitude * math.sin(2 * math.pi * hz * time) for time in t]


def stereo(left, right):
    return [(l, r) for l, r in zip(left, right)]


def pcm_bytes(channels):
    import struct
    return b"".join(struct.pack("<hh", round(l * 32767), round(r * 32767)) for l, r in channels)


class AnalyzerTests(unittest.TestCase):
    def test_low_tone_lands_in_low_band_with_frequency(self):
        analyzer = BandAnalyzer()
        analyzer.push(pcm_bytes(stereo(sine(.12, .4, 60), sine(.12, .4, 60))))
        left, right = analyzer.render()
        low, high = left
        self.assertGreater(low[0], .2)
        self.assertLess(abs(low[1] - 60), 8)
        self.assertLess(high[0], .05)

    def test_high_tone_lands_in_high_band(self):
        analyzer = BandAnalyzer()
        analyzer.push(pcm_bytes(stereo(sine(.12, .4, 200), sine(.12, .4, 200))))
        left, right = analyzer.render()
        low, high = left
        self.assertLess(low[0], .05)
        self.assertGreater(high[0], .2)
        self.assertLess(abs(high[1] - 200), 15)

    def test_mixed_tones_fill_both_bands_independently(self):
        analyzer = BandAnalyzer()
        mixed = [l + r for l, r in zip(sine(.12, .4, 60), sine(.12, .2, 200))]
        analyzer.push(pcm_bytes(stereo(mixed, mixed)))
        left, _ = analyzer.render()
        low, high = left
        self.assertGreater(low[0], .2)
        self.assertLess(abs(low[1] - 60), 8)
        self.assertGreater(high[0], .1)
        self.assertLess(abs(high[1] - 200), 15)

    def test_sides_are_independent(self):
        analyzer = BandAnalyzer()
        analyzer.push(pcm_bytes(stereo(sine(.12, .4, 60), [0] * 5760)))
        left, right = analyzer.render()
        self.assertGreater(left[0][0], .2)
        self.assertLess(right[0][0], .05)

    def test_silence_is_quiet(self):
        analyzer = BandAnalyzer()
        analyzer.push(pcm_bytes(stereo([0] * 5760, [0] * 5760)))
        left, right = analyzer.render()
        self.assertEqual(left, QUIET_BANDS)
        self.assertEqual(right, QUIET_BANDS)


class ComposeTests(unittest.TestCase):
    def state(self, **overrides):
        values = {"settings": Settings(), "rumble": (0.0, 0.0), "test_target": None, "pressures": (0.0, 0.0)}
        values.update(overrides)
        return MixState(**values)

    def test_disabled_grips_are_quiet(self):
        bands = [((.5, 60), (0, 80))]
        self.assertEqual(compose_bands(bands, self.state(settings=Settings(grip_enabled=False))),
                         [QUIET_BANDS, QUIET_BANDS])

    def test_gain_scales_amplitude(self):
        bands = [((.5, 60), (0, 80)), QUIET_BANDS]
        result = compose_bands(bands, self.state(settings=Settings(grip_gain=.5)))
        self.assertAlmostEqual(result[0][0][0], .25, delta=1 / 63)

    def test_left_and_right_gain_are_applied_per_side(self):
        bands = [((.5, 60), (0, 80)), ((.5, 60), (0, 80))]
        result = compose_bands(bands, self.state(
            settings=Settings(grip_gain_left=.5, grip_gain_right=1.0)))
        self.assertAlmostEqual(result[0][0][0], .25, delta=1 / 63)
        self.assertAlmostEqual(result[1][0][0], .5, delta=1 / 63)

    def test_strong_rumble_takes_over_as_single_tone(self):
        bands = [((.1, 60), (0, 80)), QUIET_BANDS]
        result = compose_bands(bands, self.state(rumble=(.6, 0.0)))
        low, high = result[0]
        self.assertEqual(low, (.6, 50))
        self.assertEqual(high, (0, 80))

    def test_weak_rumble_does_not_take_over(self):
        bands = [((.5, 60), (0, 80)), QUIET_BANDS]
        result = compose_bands(bands, self.state(rumble=(.2, 0.0)))
        self.assertAlmostEqual(result[0][0][0], .5, delta=1 / 63)

    def test_soft_attenuates_high_band(self):
        plain = compose_bands([((0, 80), (.4, 200)), QUIET_BANDS], self.state())
        soft = compose_bands([((0, 80), (.4, 200)), QUIET_BANDS],
                             self.state(settings=Settings(grip_soft=True)))
        self.assertLess(soft[0][1][0], plain[0][1][0])
        self.assertGreater(soft[0][1][0], 0)

    def test_faint_low_content_is_lifted_not_flickering(self):
        # 6–12 级（≈0.1–0.19）以下的纯低频弱内容按比例抬到稳定一层。
        result = compose_bands([((.06, 60), (0, 80)), QUIET_BANDS], self.state(settings=Settings(grip_soft=True)))
        low, high = result[0]
        self.assertAlmostEqual(low[0], 16 / 63, delta=.02)
        self.assertEqual(high[0], 0)

    def test_total_is_capped(self):
        result = compose_bands([((.4, 60), (.4, 200)), QUIET_BANDS], self.state())
        total = result[0][0][0] + result[0][1][0]
        self.assertLessEqual(total, 32 / 63 + 1e-9)

    def test_envelope_low_levels_are_monotonic_and_not_gated(self):
        values = (.044, .088, .148, .201, .295, .496)
        outputs = []
        for value in values:
            result = compose_envelope([(value, 45), (0, 80)],
                                      [((0, 80), (0, 80)), QUIET_BANDS],
                                      self.state(settings=Settings(grip_soft=True)))
            outputs.append(result[0][0][0])
        self.assertGreater(outputs[0], 0)
        self.assertEqual(outputs, sorted(outputs))
        self.assertGreater(outputs[3], outputs[2])

    def test_envelope_soft_removes_high_frequency_texture(self):
        high_286 = compose_envelope([(.148, 45), (0, 80)],
                                    [((0, 80), (.08, 286)), QUIET_BANDS],
                                    self.state(settings=Settings(grip_soft=True)))
        high_120 = compose_envelope([(.148, 45), (0, 80)],
                                    [((0, 80), (.08, 120)), QUIET_BANDS],
                                    self.state(settings=Settings(grip_soft=True)))
        self.assertEqual(high_286[0][1][0], 0)
        self.assertGreater(high_120[0][1][0], 0)

    def test_envelope_cap_keeps_low_end_strength(self):
        result = compose_envelope([(.496, 45), (0, 80)],
                                  [((0, 80), (.2, 120)), QUIET_BANDS],
                                  self.state(settings=Settings(grip_soft=True)))
        total = result[0][0][0] + result[0][1][0]
        self.assertLessEqual(total, ENVELOPE_MAX_TOTAL + 1 / 63)
        self.assertGreater(result[0][0][0], .4)


class HoldTests(unittest.TestCase):
    def test_frequency_hold_stabilizes_small_jumps(self):
        hold = FrequencyHold()
        first = hold.apply([((.5, 60), (0, 80))])
        self.assertEqual(first[0][0][1], 60)
        second = hold.apply([((.5, 65), (0, 80))])
        self.assertEqual(second[0][0][1], 60)
        third = hold.apply([((.5, 64), (0, 80))])
        self.assertEqual(third[0][0][1], 60)

    def test_frequency_hold_tracks_large_jumps(self):
        hold = FrequencyHold()
        hold.apply([((.5, 60), (0, 80))])
        jumped = hold.apply([((.5, 65), (0, 80))])
        self.assertEqual(jumped[0][0][1], 60)
        jumped = hold.apply([((.5, 30), (0, 80))])
        self.assertEqual(jumped[0][0][1], 30)

    def test_level_hold_smooths_small_amplitude_changes(self):
        hold = LevelHold()
        hold.apply([((.5, 60), (0, 80))])
        result = hold.apply([((.49, 60), (0, 80))])
        self.assertAlmostEqual(result[0][0][0], .5, delta=1 / 63)
        result = hold.apply([((.3, 60), (0, 80))])
        self.assertAlmostEqual(result[0][0][0], .3, delta=1 / 63)

    def test_reset_clears_history(self):
        hold = FrequencyHold()
        hold.apply([((.5, 60), (0, 80))])
        hold.reset()
        self.assertEqual(hold.apply([((.5, 65), (0, 80))])[0][0][1], 65)


if __name__ == "__main__":
    unittest.main()
