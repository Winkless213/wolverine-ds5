"""量化主频近似的误差和算法响应；不测量马达或端到端延迟。"""
import datetime
import json
from pathlib import Path

import numpy as np

from pcm_to_sensa import PcmToSensa


def signal(tones, frames=5760, start_frame=0):
    time = (np.arange(frames) + start_frame) / 48000
    left = sum(amplitude * np.sin(2 * np.pi * frequency * time) for amplitude, frequency in tones)
    return np.column_stack((np.rint(left * 32767), np.zeros(frames))).astype("<i2").tobytes()


def inspect_mapping():
    cases = []
    for frequency in (30, 40, 60, 80, 110, 160, 200, 250, 320, 400):
        frames = PcmToSensa().push(signal(((.6, frequency),)))
        steady = [frame["channels"][0] for frame in frames if not frame["warmup"]]
        cases.append({"input_hz": frequency,
                      "max_steady_frequency_error_hz": max(abs(side["frequency_hz"] - frequency) for side in steady),
                      "max_steady_amplitude_error": max(abs(side["amplitude"] - .132) for side in steady),
                      "unexpected_steady_silent_frames": sum(side["amplitude"] == 0 for side in steady),
                      "first_nonzero_ms": next((frame["end_frame"] / 48 for frame in frames if frame["channels"][0]["amplitude"]), None),
                      "right_channel_nonzero_frames": sum(frame["channels"][1]["amplitude"] != 0 for frame in frames)})
    mixed = PcmToSensa().push(signal(((.2, 80), (.6, 240))))[-1]["channels"][0]
    converter = PcmToSensa()
    converter.push(signal(((.2, 160),)))
    rising = converter.push(signal(((.6, 160),), start_frame=5760))
    first = next(frame for frame in rising if abs(frame["channels"][0]["amplitude"] - .132) <= .0132)
    quiet = converter.push(b"\0" * 192 * 4)[-1]
    passed = (all(case["right_channel_nonzero_frames"] == 0 for case in cases)
              and all(case["max_steady_frequency_error_hz"] <= 5 for case in cases)
              and all(case["max_steady_amplitude_error"] <= .01 and case["unexpected_steady_silent_frames"] == 0 for case in cases)
              and abs(mixed["frequency_hz"] - 240) <= 3
              and all(side["amplitude"] == 0 for side in quiet["channels"]))
    return {"verified_at": datetime.datetime.now().astimezone().isoformat(), "passed": passed,
            "hardware_output": False, "physical_latency_measured": False,
            "scope": "Deterministic PCM-to-parameter characterization, before HAR quantization; not waveform or hardware fidelity",
            "acceptance": "Listed 30..400 Hz fixtures: <=5 Hz frequency error, <=0.01 amplitude error at gain 0.22 after warmup, no silent frames/right leakage; silence within one complete hop",
            "cases": cases, "multitone_input": [[.2, 80], [.6, 240]], "multitone_output": mixed,
            "secondary_tones_preserved": False, "phase_preserved": False,
            "amplitude_step_160hz_within_10_percent_ms": (first["end_frame"] - 5760) / 48,
            "silence_after_complete_zero_hop_ms": 4,
            "analysis_window_ms": 40, "note": "Narrow low-frequency tones use a sine/cosine/DC least-squares fit after warmup; complex waveforms remain approximate"}


if __name__ == "__main__":
    result = inspect_mapping()
    Path(__file__).with_name("sensa-mapping-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
