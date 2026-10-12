import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import run_capture
from test_capture_recorder import block
from test_pcm_to_sensa import pcm_tones
from test_trigger_mapper import FEEDBACK, OFF, report


class RunnerTests(unittest.TestCase):
    def test_reader_failure_or_overflow_stops_before_queued_trigger_output(self):
        from xusb_bridge import XusbBridge
        active = json.dumps({"type": "output", "report": base64.b64encode(report(left=FEEDBACK)).decode()}) + "\n"
        stopped = json.dumps({"type": "output", "report": base64.b64encode(report(left=OFF)).decode()}) + "\n"
        for failure, messages in (("invalid-json", [active, "{\n"]),
                                  ("queue-overflow", [active] * 512 + [stopped])):
            with self.subTest(failure=failure):
                output = Mock(calls=[], identity={"backend": "xusb"})
                bridge = XusbBridge(output)
                process = Mock(returncode=0, stdout=iter(messages))
                process.poll.return_value = 0
                def make_reader(*, target, **kwargs):
                    reader = Mock()
                    reader.start.side_effect = target
                    reader.is_alive.return_value = False
                    return reader
                with tempfile.TemporaryDirectory() as folder, patch.object(run_capture, "ROOT", Path(folder)), \
                        patch.object(run_capture.subprocess, "Popen", return_value=process), \
                        patch.object(run_capture.threading, "Thread", side_effect=make_reader), \
                        patch.object(run_capture, "RazerInput", return_value=Mock(identity="test")), \
                        patch.object(run_capture, "XusbBridge", return_value=bridge):
                    self.assertFalse(run_capture.run(1, False, xusb_output=True))
                output.set.assert_not_called()
                output.close.assert_called_once()

    def test_synthetic_capture_cannot_enable_physical_output(self):
        with patch.object(run_capture, "XusbBridge", side_effect=AssertionError("Hardware opened")), \
                self.assertRaises(ValueError):
            run_capture.run(1, True, xusb_output=True)

    def test_capture_start_failure_closes_enabled_output(self):
        from xusb_bridge import XusbBridge
        output = Mock(calls=[], identity={"backend": "xusb"})
        bridge = XusbBridge(output)
        with tempfile.TemporaryDirectory() as folder, patch.object(run_capture, "ROOT", Path(folder)), \
                patch.object(run_capture, "XusbBridge", return_value=bridge), \
                patch.object(run_capture, "RazerInput", return_value=Mock(identity="test")), \
                patch.object(run_capture.subprocess, "Popen", side_effect=OSError("host failed")):
            self.assertFalse(run_capture.run(1, False, xusb_output=True))
            summary = json.loads(next(Path(folder).glob("runs/*/run.json")).read_text(encoding="utf-8"))
            self.assertFalse(summary["hardware_output"])
            self.assertIn("host failed", summary["error"])
        output.close.assert_called_once()

    def test_input_cadence_supports_250_and_1000_without_catchup_bursts(self):
        for hz in (250, 1000):
            cadence = run_capture.InputCadence(hz)
            period = 1 / hz
            self.assertTrue(cadence.due(0))
            self.assertFalse(cadence.due(period / 2))
            self.assertTrue(cadence.due(period))
            self.assertTrue(cadence.due(.1))
            self.assertFalse(cadence.due(.1))
            self.assertFalse(cadence.due(.1 + period / 2))
            self.assertTrue(cadence.due(.1 + period))

    def test_optional_preview_consumes_the_capture_stream_and_stops(self):
        pcm = pcm_tones(((.6, 80),), ((.3, 160),))
        messages = [dict(block(1, offset // 4, pcm[offset:offset + 192]), host_queue_us=0)
                    for offset in range(0, len(pcm), 192)]
        for hz in (250, 1000):
            process = Mock(returncode=0, stdout=iter(json.dumps(item) + "\n" for item in messages))
            process.poll.return_value = 0
            with tempfile.TemporaryDirectory() as folder, patch.object(run_capture, "ROOT", Path(folder)), \
                    patch.object(run_capture.subprocess, "Popen", return_value=process):
                self.assertTrue(run_capture.run(1, True, sensa_preview=True, input_poll_hz=hz))
                summary = json.loads(next(Path(folder).glob("runs/*/run.json")).read_text(encoding="utf-8"))
                self.assertEqual(summary["input_poll_hz"], hz)
                self.assertFalse(summary["hardware_report_rate_verified"])
                self.assertEqual(summary["sensa_preview"]["parameter_frames"], 25)
                self.assertTrue(summary["sensa_preview"]["stop_returned_empty"])
                self.assertFalse(summary["sensa_preview"]["hardware_output"])

    def test_drains_tail_even_when_host_exits_before_reader(self):
        def delayed_stdout():
            time.sleep(.03)
            yield json.dumps({"type": "audio", "source": "synthetic", "generation": 1,
                              "first_frame": 0, "frames": 1, "sample_rate": 48000,
                              "host_queue_us": 0, "pcm": base64.b64encode(b"\1\0\2\0").decode()}) + "\n"

        process = Mock(returncode=0, stdout=delayed_stdout())
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as folder, patch.object(run_capture, "ROOT", Path(folder)), \
                patch.object(run_capture.subprocess, "Popen", return_value=process):
            self.assertTrue(run_capture.run(1, True))
            summary = json.loads(next(Path(folder).glob("runs/*/run.json")).read_text(encoding="utf-8"))
            self.assertEqual(summary["received_messages"], 1)
            self.assertEqual(summary["recording"]["frames"], 1)

    def test_live_capture_requires_a_stopped_record(self):
        process = Mock(returncode=0, stdout=iter(()))
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as folder, patch.object(run_capture, "ROOT", Path(folder)), \
                patch.object(run_capture.subprocess, "Popen", return_value=process), \
                patch.object(run_capture, "RazerInput", return_value=Mock(identity="test")), \
                patch.object(run_capture, "XusbBridge", side_effect=AssertionError("Hardware opened")):
            self.assertFalse(run_capture.run(1, False))


if __name__ == "__main__":
    unittest.main()
