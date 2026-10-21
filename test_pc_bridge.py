import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import gip_bridge
import pc_bridge
import sdl_input
from gip_bridge import Status
from pc_bridge import LIMIT, RUMBLE_HZ, GripHaptics
from settings import Settings
from test_capture_recorder import block
from test_pcm_to_sensa import pcm_tones


def wait_for(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.001)
    return predicate()


class FakeGrips:
    def __init__(self):
        self.sides = [(0.0, 80.0), (0.0, 80.0)]
        self.sets = []
        self.renders = 0

    def set(self, side, amplitude, frequency):
        self.sides[side] = (amplitude, frequency)
        self.sets.append((side, amplitude, frequency))

    def render(self):
        self.renders += 1


def rumble_report(left, right):
    report = bytearray(48)
    report[0], report[1], report[3], report[4] = 2, 1, right, left
    return {"type": "output", "report": base64.b64encode(bytes(report)).decode("ascii")}


def feed(haptics, pcm, now=0, first=0, generation=1):
    for offset in range(0, len(pcm), 192):
        haptics.accept(block(generation, first + offset // 4, pcm[offset:offset + 192], "usb-host"), now=now)


class GripHapticsTests(unittest.TestCase):
    def setUp(self):
        self.grips = FakeGrips()
        self.haptics = GripHaptics(self.grips)

    def test_sub_30hz_game_haptics_vibrate_the_same_side_only(self):
        feed(self.haptics, pcm_tones(((.4, 18),), frames=2400))
        self.haptics.step(0, 0, now=.001)
        (left, frequency), (right, _) = self.grips.sides
        self.assertGreater(left, .05)
        self.assertEqual(frequency, 30)
        self.assertEqual(right, 0)

    def test_classic_rumble_drives_both_grips_at_the_resonance(self):
        self.haptics.accept(rumble_report(left=255, right=51), now=0)
        self.haptics.step(0, 0, now=0)
        (left, left_hz), (right, right_hz) = self.grips.sides
        self.assertEqual((left, left_hz, right_hz), (LIMIT, RUMBLE_HZ, RUMBLE_HZ))
        self.assertAlmostEqual(right, LIMIT * .2)

    def test_audio_timeout_clears_haptics_but_keeps_classic_rumble(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400))
        self.haptics.accept(rumble_report(left=0, right=128), now=0)
        self.haptics.step(0, 0, now=.01)
        self.assertGreater(self.grips.sides[0][0], 0)
        self.haptics.step(0, 0, now=.06)
        self.assertEqual(self.grips.sides[0][0], 0)
        self.assertGreater(self.grips.sides[1][0], 0)

    def test_host_stop_silences_everything(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400))
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.accept({"type": "stopped"}, now=0)
        self.haptics.step(0, 0, now=.001)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_grip_switch_and_gain(self):
        self.haptics.accept(rumble_report(left=255, right=128), now=0)
        self.haptics.settings = Settings(grip_gain=1.5)
        self.haptics.step(0, 0, now=0)
        self.assertAlmostEqual(self.grips.sides[0][0], min(1, LIMIT * 1.5))
        self.haptics.settings = Settings(grip_enabled=False)
        self.haptics.step(0, 0, now=.004)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_grip_test_follows_lt_rt_and_mutes_the_game(self):
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.test_target = "grip"
        self.haptics.step(255, 0, now=0)
        self.assertEqual(self.grips.sides, [(LIMIT, RUMBLE_HZ), (0, 80.0)])

    def test_trigger_test_is_silent_because_pc_mode_has_no_trigger_motors(self):
        self.haptics.accept(rumble_report(left=255, right=255), now=0)
        self.haptics.test_target = "trigger"
        self.haptics.step(255, 255, now=0)
        self.assertEqual([side[0] for side in self.grips.sides], [0, 0])

    def test_restarted_haptic_stream_resyncs_instead_of_failing(self):
        feed(self.haptics, pcm_tones(((.4, 120),), frames=960))
        feed(self.haptics, pcm_tones(((.4, 120),), frames=2400), first=50000)
        self.haptics.step(0, 0, now=.001)
        self.assertGreater(self.grips.sides[0][0], 0)
        self.assertEqual(self.haptics.stats["audio_resyncs"], 1)

    def test_unchanged_output_is_rendered_but_not_resent(self):
        self.haptics.accept(rumble_report(left=255, right=0), now=0)
        for step in range(5):
            self.haptics.step(0, 0, now=step * .004)
        self.assertEqual(len(self.grips.sets), 1)
        self.assertEqual(self.grips.renders, 5)

    def test_reattached_output_receives_the_current_state(self):
        self.haptics.accept(rumble_report(left=255, right=0), now=0)
        self.haptics.step(0, 0, now=0)
        fresh = FakeGrips()
        self.haptics.attach(fresh)
        self.haptics.step(0, 0, now=.004)
        self.assertEqual(fresh.sides[0], (LIMIT, RUMBLE_HZ))

    def test_soft_setting_switches_the_mapping_live(self):
        feed(self.haptics, pcm_tones(((.4, 160),), frames=2400))
        self.haptics.step(0, 0, now=.001)
        sharp = self.grips.sides[0]
        gip_bridge.handle_command(self.haptics, {"type": "settings", "settings": {"grip_soft": True}})
        feed(self.haptics, pcm_tones(((.4, 160),), frames=2400), first=600)
        self.haptics.step(0, 0, now=.002)
        self.assertLess(self.grips.sides[0][0], sharp[0] / 2)
        self.assertLess(self.grips.sides[0][1], 100)

    def test_settings_and_test_commands_reach_the_pc_haptics(self):
        gip_bridge.handle_command(self.haptics, {"type": "settings", "settings": {"grip_gain": .3}})
        gip_bridge.handle_command(self.haptics, {"type": "test", "target": "grip"})
        self.assertEqual((self.haptics.settings.grip_gain, self.haptics.test_target), (.3, "grip"))


class OpenTests(unittest.TestCase):
    def test_sensa_probe_does_not_block_the_input_poll_loop(self):
        started = threading.Event()
        release = threading.Event()

        def blocked_probe():
            started.set()
            release.wait(1)
            return Mock()

        worker = pc_bridge.SensaOutputWorker(factory=blocked_probe)
        try:
            self.assertTrue(started.wait(.2))
            worker.set(0, LIMIT, RUMBLE_HZ)
            worker.render()
            self.assertTrue(worker.thread.is_alive())
        finally:
            release.set()
            worker.close()

    def test_input_opens_without_waiting_for_sensa(self):
        pad = Mock()
        with patch.object(pc_bridge, "RazerInput", return_value=pad), \
                patch.object(pc_bridge, "SensaGrips") as factory:
            devices = pc_bridge.open_devices()
        self.assertIs(devices.pad, pad)
        factory.assert_not_called()
        pad.close.assert_not_called()
        devices.close()
        pad.close.assert_called_once()

    def test_sensa_can_recover_while_the_input_stays_open(self):
        pad, output = Mock(), Mock()
        devices = pc_bridge.Devices(pad, pc_bridge.SensaOutputWorker(
            factory=Mock(side_effect=[ConnectionError("starting"), output]), retry_seconds=.01), owns_grips=False)
        haptics = GripHaptics(devices.grips)
        haptics.accept(rumble_report(255, 0), now=0)
        devices.render(haptics, 0, 0, now=0)
        try:
            self.assertTrue(wait_for(lambda: output.set.called))
            pad.close.assert_not_called()
            self.assertIs(haptics.output, devices.grips)
            output.set.assert_called_once_with(0, LIMIT, RUMBLE_HZ)
        finally:
            devices.close()
            devices.grips.close()

    def test_lost_sensa_is_replaced_without_releasing_the_input(self):
        pad, lost, recovered = Mock(), Mock(), Mock()
        lost.render.side_effect = ConnectionError("radio switching")
        factory = Mock(side_effect=[lost, recovered])
        worker = pc_bridge.SensaOutputWorker(factory=factory, retry_seconds=.01)
        devices = pc_bridge.Devices(pad, worker, owns_grips=False)
        haptics = GripHaptics(worker)
        try:
            self.assertTrue(wait_for(lambda: worker.ready))
            devices.render(haptics, 0, 0, now=0)
            self.assertTrue(wait_for(lambda: factory.call_count == 2))
            devices.render(haptics, 0, 0, now=.004)
            self.assertTrue(wait_for(lambda: recovered.render.called))
            lost.close.assert_called_once()
            pad.close.assert_not_called()
        finally:
            worker.close()

    def test_game_haptics_received_during_reconnect_are_not_replayed_from_a_queue(self):
        output = Mock()
        worker = pc_bridge.SensaOutputWorker(factory=Mock(return_value=output))
        devices = pc_bridge.Devices(Mock(), worker, owns_grips=False)
        haptics = GripHaptics(worker)
        feed(haptics, pcm_tones(((.4, 120),), frames=2400), now=0)
        try:
            self.assertTrue(wait_for(lambda: worker.ready))
            devices.render(haptics, 0, 0, now=1)
            self.assertTrue(wait_for(lambda: output.render.called))
            output.set.assert_not_called()
        finally:
            worker.close()


class StatusDetailTests(unittest.TestCase):
    def test_changed_waiting_reason_is_reported_again(self):
        lines = []
        status = Status(lines.append)
        status.set("waiting", reason="input")
        status.set("waiting", reason="input")
        status.set("waiting", reason="sensa")
        self.assertEqual([json.loads(line)["reason"] for line in lines], ["input", "sensa"])


class GripTraceTests(unittest.TestCase):
    def test_audit_records_both_sources_without_changing_motor_output(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / "grip-trace.flag"
            events = []
            with patch.dict(os.environ, {"WOLVERINE_GRIP_TRACE_FLAG": str(flag)}):
                observed = GripHaptics(FakeGrips())
            baseline = GripHaptics(FakeGrips())
            observed.trace.write = events.append
            flag.touch()
            for haptics in (observed, baseline):
                feed(haptics, pcm_tones(((.2, 120),), frames=2400), now=0)
                haptics.accept(rumble_report(255, 0), now=.001)
                haptics.step(0, 0, now=.002)
            self.assertEqual(observed.output.sides, baseline.output.sides)
            sample = next(event["state"] for event in events if event["event"] == "sample")
            self.assertGreater(sample["pcm"][0][0], 0)
            self.assertEqual(sample["rumble"], [1, 0])
            self.assertEqual(sample["selected"], ["rumble", "quiet"])
            self.assertEqual(sample["output"], observed.previous)
            self.assertIsNone(sample["test_target"])
            self.assertTrue(all(event["type"] == "grip-trace" for event in events))

    def test_audit_does_not_mistake_the_manual_test_for_game_haptics(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / "grip-trace.flag"
            events = []
            with patch.dict(os.environ, {"WOLVERINE_GRIP_TRACE_FLAG": str(flag)}):
                haptics = GripHaptics(FakeGrips())
            haptics.trace.write = events.append
            flag.touch()
            haptics.test_target = "grip"
            haptics.step(255, 0, now=1)
            sample = next(event["state"] for event in events if event["event"] == "sample")
            self.assertEqual(sample["test_target"], "grip")
            self.assertEqual(sample["selected"], ["test", "quiet"])
            self.assertEqual(sample["output"][0], (LIMIT, RUMBLE_HZ))


class SessionCadenceTests(unittest.TestCase):
    def record_session(self, stall=False, physical_hz=1000):
        class Clock:
            now = 1.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += max(seconds, .0000001)

        clock = Clock()
        reads, renders = [], []

        def read():
            reads.append(clock.now)
            if stall and len(reads) == 3:
                clock.now += .020
            return {"L2": 0, "R2": 0, "Buttons": int(round((clock.now - 1) * 1000000) * physical_hz / 1000000)}

        devices = pc_bridge.Devices(Mock(), Mock())
        devices.pad.read.side_effect = read
        capture = Mock()
        capture.poll.side_effect = lambda: 0 if clock.now >= 1.030 else None
        haptics = Mock(previous=[(0, 80), (0, 80)])
        haptics.step.side_effect = lambda left, right, now: renders.append(now)
        with patch.object(pc_bridge, "time", clock), \
                patch.object(gip_bridge, "drain"), patch.object(gip_bridge, "STATUS"):
            pc_bridge.session(devices, capture, [], haptics, {})
        return reads, renders, capture

    def test_input_runs_at_1000_hz_while_grips_keep_250_hz(self):
        reads, renders, capture = self.record_session()
        self.assertGreaterEqual(len(reads), 29)
        self.assertGreaterEqual(len(renders), 7)
        self.assertLessEqual(len(renders), 9)
        self.assertEqual(capture.stdin.write.call_count, len(reads))
        self.assertTrue(all(b - a >= .003999 for a, b in zip(renders, renders[1:])))

    def test_late_input_does_not_catch_up_in_a_burst(self):
        reads, renders, _ = self.record_session(stall=True)
        self.assertGreaterEqual(len(reads), 9)
        self.assertTrue(all(b - a >= .000999 for a, b in zip(reads, reads[1:])))
        self.assertTrue(all(b - a >= .003999 for a, b in zip(renders, renders[1:])))

    def test_250_hz_source_keeps_its_updates_without_faking_new_states(self):
        reads, renders, capture = self.record_session(physical_hz=250)
        self.assertGreaterEqual(len(reads), 29)
        states = [json.loads(call.args[0])["state"] for call in capture.stdin.write.call_args_list]
        self.assertEqual([state["Buttons"] for state in states], list(range(8)))
        self.assertGreaterEqual(len(renders), 7)

    def test_blocked_sensa_startup_does_not_reduce_input_polling(self):
        started, release = threading.Event(), threading.Event()

        def blocked_probe():
            started.set()
            release.wait(1)
            return Mock()

        worker = pc_bridge.SensaOutputWorker(factory=blocked_probe)
        try:
            self.assertTrue(started.wait(.2))
            devices, capture = pc_bridge.Devices(Mock(), worker, owns_grips=False), Mock()
            reads = []

            class Clock:
                now = 1.0

                def monotonic(self):
                    return self.now

                def sleep(self, seconds):
                    self.now += max(seconds, .0000001)

            clock = Clock()
            devices.pad.read.side_effect = lambda: reads.append(clock.now) or {
                "L2": 0, "R2": 0, "Buttons": 0}
            capture.poll.side_effect = lambda: 0 if clock.now >= 1.030 else None
            haptics = GripHaptics(worker)
            with patch.object(pc_bridge, "time", clock), patch.object(gip_bridge, "drain"), \
                    patch.object(gip_bridge, "STATUS"):
                pc_bridge.session(devices, capture, [], haptics, {})
            self.assertGreaterEqual(len(reads), 29)
            devices.close()
        finally:
            release.set()
            worker.close()


class SessionReconnectTests(unittest.TestCase):
    def test_unplug_releases_held_controls_before_reopening_the_device(self):
        held = sdl_input.input_state([32767, 0, 0, 0, 32767, 32767], {0, 4, 11})
        devices, capture = pc_bridge.Devices(Mock(), Mock()), Mock()
        devices.pad.read.side_effect = [held, RuntimeError("unplugged")]
        capture.poll.return_value = None
        haptics = Mock(previous=[(0, 80), (0, 80)])
        with patch.object(gip_bridge, "drain"), patch.object(gip_bridge, "STATUS"):
            with self.assertRaises(ConnectionError):
                pc_bridge.session(devices, capture, [], haptics, {})
        sent = [json.loads(call.args[0])["state"] for call in capture.stdin.write.call_args_list]
        self.assertEqual(sent, [held, sdl_input.input_state([0] * 6, set())])
        capture.terminate.assert_not_called()

    def test_disconnect_silences_persistent_sensa_worker(self):
        output = Mock()
        worker = pc_bridge.SensaOutputWorker(factory=Mock(return_value=output))
        try:
            self.assertTrue(wait_for(lambda: worker.ready))
            worker.set(0, LIMIT, RUMBLE_HZ)
            worker.render()
            self.assertTrue(wait_for(lambda: output.set.called))

            devices, capture = pc_bridge.Devices(Mock(), worker, owns_grips=False), Mock()
            devices.pad.read.side_effect = [sdl_input.input_state([0] * 6, set()), RuntimeError("unplugged")]
            capture.poll.return_value = None
            haptics = Mock(previous=[(0, 80), (0, 80)])
            with patch.object(gip_bridge, "drain"), patch.object(gip_bridge, "STATUS"):
                with self.assertRaises(ConnectionError):
                    pc_bridge.session(devices, capture, [], haptics, {})
            self.assertEqual(worker.desired, [pc_bridge.QUIET, pc_bridge.QUIET])
        finally:
            worker.close()
        output.close.assert_called_once()

if __name__ == "__main__":
    unittest.main()
