import unittest

from audio_guard import AudioGuard, RENDER, CAPTURE


class FakeAudio:
    def __init__(self, defaults, active):
        self.defaults, self.active, self.calls = dict(defaults), active, []

    def default(self, flow, role):
        return self.defaults.get((flow, role))

    def is_ds5(self, device):
        return device.startswith("ds5")

    def devices(self, flow):
        return self.active[flow]

    def set_default(self, device, flow, role):
        self.calls.append((device, flow, role))
        self.defaults[(flow, role)] = device


def all_roles(flow, device):
    return {(flow, role): device for role in range(3)}


class AudioGuardTests(unittest.TestCase):
    def test_ds5_taking_default_output_is_switched_back(self):
        audio = FakeAudio(all_roles(RENDER, "speakers"), {RENDER: ["speakers", "ds5-out"], CAPTURE: []})
        guard = AudioGuard(audio)
        guard.check()
        audio.defaults.update(all_roles(RENDER, "ds5-out"))
        guard.check()
        self.assertEqual(audio.defaults[(RENDER, 1)], "speakers")
        self.assertEqual(len(audio.calls), 3)

    def test_ds5_microphone_taking_default_input_is_switched_back(self):
        audio = FakeAudio(all_roles(CAPTURE, "mic"), {RENDER: [], CAPTURE: ["mic", "ds5-mic"]})
        guard = AudioGuard(audio)
        guard.check()
        audio.defaults.update(all_roles(CAPTURE, "ds5-mic"))
        guard.check()
        self.assertEqual(audio.defaults[(CAPTURE, 2)], "mic")

    def test_unplugged_previous_device_falls_back_to_another_real_device(self):
        audio = FakeAudio(all_roles(RENDER, "headphones"), {RENDER: ["speakers", "ds5-out"], CAPTURE: []})
        guard = AudioGuard(audio)
        guard.check()
        audio.defaults.update(all_roles(RENDER, "ds5-out"))
        guard.check()
        self.assertEqual(audio.defaults[(RENDER, 0)], "speakers")

    def test_ds5_already_default_at_start_is_replaced(self):
        audio = FakeAudio(all_roles(RENDER, "ds5-out"), {RENDER: ["ds5-out", "speakers"], CAPTURE: []})
        AudioGuard(audio).check()
        self.assertEqual(audio.defaults[(RENDER, 1)], "speakers")

    def test_ds5_left_alone_when_it_is_the_only_device(self):
        audio = FakeAudio(all_roles(RENDER, "ds5-out"), {RENDER: ["ds5-out"], CAPTURE: []})
        AudioGuard(audio).check()
        self.assertEqual(audio.calls, [])

    def test_user_choice_of_real_device_is_never_overridden(self):
        audio = FakeAudio(all_roles(RENDER, "speakers"), {RENDER: ["speakers", "headphones"], CAPTURE: []})
        guard = AudioGuard(audio)
        guard.check()
        audio.defaults.update(all_roles(RENDER, "headphones"))
        guard.check()
        self.assertEqual(audio.calls, [])


if __name__ == "__main__":
    unittest.main()
