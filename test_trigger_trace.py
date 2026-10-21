import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from gip_bridge import Haptics
from test_gip_bridge import FULL_FEEDBACK, FULL_VIBRATION, trigger_report
from trigger_trace import TriggerTrace


class TriggerTraceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.flag = Path(self.folder.name) / "record.flag"
        self.events = []
        self.trace = TriggerTrace(self.flag, self.events.append, seconds=1)
        self.state = {"l2": 0, "r2": 0, "triggers": [0, 0]}

    def report(self, now, **effects):
        self.trace.output(base64.b64decode(trigger_report(**effects)["report"]), now)

    def start(self):
        self.flag.touch()
        self.trace.sample(self.state, now=10)

    def test_start_preserves_independent_effects_received_while_idle(self):
        self.report(9, left_effect=FULL_FEEDBACK)
        self.report(9.1, right_effect=FULL_VIBRATION)
        self.assertEqual(self.events, [])
        self.start()
        start, sample = self.events
        self.assertEqual(start["event"], "start")
        self.assertEqual(start["effects"], {"left": FULL_FEEDBACK.hex(), "right": FULL_VIBRATION.hex()})
        self.assertEqual(sample["state"], self.state)
        self.assertEqual(sample["monotonic_s"], 10)
        self.report(10.01, left_effect=bytes([5]) + bytes(10))
        self.assertEqual(start["effects"]["left"], FULL_FEEDBACK.hex())

    def test_identical_reports_are_counted_and_changes_keep_original_bytes(self):
        self.start()
        message = trigger_report(right_effect=FULL_VIBRATION)
        raw = base64.b64decode(message["report"])
        self.trace.output(raw, 10.01)
        self.trace.output(raw, 10.02)
        self.trace.sample({**self.state, "r2": 128}, 10.03)
        self.trace.sample(self.state, 11.01)
        reports = [event for event in self.events if event["event"] == "output"]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["report_hex"], raw.hex())
        self.assertEqual(self.events[-2]["state"]["r2"], 128)
        self.assertEqual(self.events[-1]["event"], "stop")
        self.assertEqual(self.events[-1]["reports_seen"], 2)
        self.assertEqual(self.events[-1]["reason"], "duration")

    def test_deadline_does_not_restart_until_flag_is_removed(self):
        self.start()
        self.trace.sample(self.state, 11.01)
        self.trace.sample(self.state, 12)
        self.assertEqual(sum(event["event"] == "start" for event in self.events), 1)
        self.flag.unlink()
        self.trace.sample(self.state, 13)
        self.flag.touch()
        self.trace.sample(self.state, 14)
        self.assertEqual(sum(event["event"] == "start" for event in self.events), 2)

    def test_reset_is_visible_and_clears_cached_effects(self):
        self.start()
        self.report(10.01, right_effect=FULL_VIBRATION)
        self.trace.reset(10.02)
        self.assertEqual(self.events[-1]["event"], "reset")
        self.assertEqual(self.trace.effects, {"left": None, "right": None})
        self.flag.unlink()
        self.trace.sample(self.state, 10.3)
        self.assertEqual(self.events[-1]["reason"], "requested")

    def test_existing_flag_does_not_start_a_stale_capture(self):
        self.flag.touch()
        trace = TriggerTrace(self.flag, self.events.append)
        trace.sample(self.state, 10)
        self.assertEqual(self.events, [])

    def test_recording_does_not_change_hardware_commands(self):
        baseline_output, traced_output = Mock(), Mock()
        baseline = Haptics(baseline_output)
        with patch.dict(os.environ, {"WOLVERINE_TRIGGER_TRACE_FLAG": str(self.flag)}), patch("sys.stdout", new_callable=io.StringIO) as log:
            traced = Haptics(traced_output)
            self.flag.touch()
            for haptics in (baseline, traced):
                haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=10)
                haptics.step(0, 128, now=10.01)
                haptics.step(0, 255, now=10.05)
                haptics.accept(trigger_report(right_effect=bytes([5]) + bytes(10)), now=10.08)
                haptics.step(0, 0, now=10.1)
            events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(baseline_output.set.call_args_list, traced_output.set.call_args_list)
        self.assertTrue(any(event["event"] == "start" for event in events))
        self.assertTrue(any(event.get("state", {}).get("r2") == 255 for event in events))


if __name__ == "__main__":
    unittest.main()
