"""连续 PCM 的离线 HAR 预演；从不加载 Provider。"""
import json
import time

import numpy as np

from capture_recorder import decode_audio_block
from pcm_to_sensa import HOP_FRAMES, SAMPLE_RATE, WINDOW_FRAMES, PcmToSensa, quiet_channels
from sensa_frame import decode_frame
from sensa_offline import HAR_SHA256, OfflineSensa


def verify_frame(encoded, channels):
    decoded = decode_frame(encoded)
    if not encoded and all(side["amplitude"] == 0 for side in channels):
        return decoded
    if [side["bodypart"] for side in decoded["channels"]] != [216, 116]:
        raise RuntimeError("HAR channel layout changed")
    for actual, expected in zip(decoded["channels"], channels):
        points = [point for band in actual["bands"] for point in band]
        strongest = max(points, key=lambda point: point["amplitude_code"])
        if expected["amplitude"] == 0 and strongest["amplitude_code"]:
            raise RuntimeError("HAR emitted amplitude on a silent channel")
        if abs(strongest["amplitude_code"] / 63 - expected["amplitude"]) > 1 / 63 + 1e-6:
            raise RuntimeError("HAR amplitude differs from the requested channel")
        if strongest["amplitude_code"]:
            frequency = 30 + strongest["frequency_code"] * 370 / 127
            if abs(frequency - expected["frequency_hz"]) > 370 / 127 + 1e-6:
                raise RuntimeError("HAR frequency differs from the requested channel")
    return decoded


class SensaPreview:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.log = (directory / "sensa-frames.jsonl").open("x", encoding="utf-8")
        try:
            self.engine = OfflineSensa()
        except Exception:
            self.log.close()
            raise
        self.converter = PcmToSensa()
        self.generation = self.next_frame = self.segment_start = 0
        self.source = self.last_audio = self.last_record = None
        self.steps = 0
        self.closed = False
        self.timings = []
        self.stats = {"hardware_output": False, "provider_loaded": False, "completed": False,
                      "game_capture_verified": False, "physical_latency_measured": False,
                      "arbitrary_pcm_verified": False, "har_sha256": HAR_SHA256,
                      "algorithm": "independent stereo dominant tone; phase and secondary tones discarded",
                      "analysis_window_ms": WINDOW_FRAMES / SAMPLE_RATE * 1000,
                      "hop_ms": HOP_FRAMES / SAMPLE_RATE * 1000, "timeout_ms": 50,
                      "parameter_frames": 0, "input_frames": 0, "missing_frames": 0,
                      "stale_blocks": 0, "duplicate_blocks": 0, "invalid_blocks": 0,
                      "discarded_tail_frames": 0, "timeouts": 0, "resets": 0,
                      "encoded_duration_ms_counts": {},
                      "stop_returned_empty": False}

    def _render(self, channels, **metadata):
        for side, channel in enumerate(channels):
            self.engine.set_tone(side, channel["amplitude"], channel["frequency_hz"])
        self.steps += 1
        encoded = self.engine.frame(self.steps * HOP_FRAMES / SAMPLE_RATE)
        decoded = verify_frame(encoded, channels)
        record = {"type": "sensa-preview", "source": self.source, "generation": self.generation,
                  "channels": channels, "hex": encoded.hex(), "encoded_duration_ms": decoded["duration_ms"],
                  "submitted_to_hardware": False, **metadata}
        self.log.write(json.dumps(record) + "\n")
        self.log.flush()
        durations = self.stats["encoded_duration_ms_counts"]
        key = str(decoded["duration_ms"])
        durations[key] = durations.get(key, 0) + 1
        self.last_record = record
        return record

    def silence(self, reason):
        self.stats["discarded_tail_frames"] += self.converter.buffered_frames
        self.converter.reset()
        self.segment_start = self.next_frame
        self.last_audio = None
        return self._render(quiet_channels(), reason=reason, end_frame=self.next_frame)

    def _reset(self, generation):
        self.stats["resets"] += 1
        quiet = self.silence("reset")
        self.generation = generation
        self.next_frame = self.segment_start = 0
        self.source = None
        return quiet

    def accept(self, message, now=None):
        if self.closed:
            raise RuntimeError("The preview is closed")
        if message["type"] == "reset":
            generation = message["generation"]
            if type(generation) is not int or generation < 1:
                self.silence("invalid-reset")
                raise ValueError("Invalid capture generation")
            return [self._reset(generation)] if generation > self.generation else []
        if message["type"] == "stopped":
            return [self.silence("host-stop")]
        if message["type"] != "audio":
            return []
        before = time.perf_counter_ns()
        try:
            generation, first, count, source, pcm = decode_audio_block(message)
            if generation == self.generation and self.source is not None and source != self.source:
                raise ValueError("Synthetic and USB input cannot share a generation")
        except (ValueError, TypeError, KeyError):
            self.stats["invalid_blocks"] += 1
            self.silence("invalid-input")
            raise
        if generation < self.generation:
            self.stats["stale_blocks"] += 1
            return []
        records = [self._reset(generation)] if generation > self.generation else []
        if first < self.next_frame:
            self.stats["duplicate_blocks"] += 1
            return records
        if first > self.next_frame:
            self.stats["missing_frames"] += first - self.next_frame
            records.append(self.silence("gap"))
            self.segment_start = first
        self.source = source
        self.next_frame = first + count
        self.stats["input_frames"] += count
        self.last_audio = time.monotonic() if now is None else now
        parameters = self.converter.push(pcm)
        for frame in parameters:
            records.append(self._render(frame["channels"], reason="parameters", warmup=frame["warmup"],
                                        end_frame=self.segment_start + frame["end_frame"]))
            self.stats["parameter_frames"] += 1
        if parameters:
            self.timings.append((time.perf_counter_ns() - before) / 1000)
        return records

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        if self.last_audio is not None and now - self.last_audio >= .05:
            self.stats["timeouts"] += 1
            return self.silence("timeout")
        return None

    def close(self, error=None):
        if self.closed:
            return
        self.closed = True
        if error is not None:
            self.stats["error"] = str(error)
        try:
            self.silence("close")
            self.engine.stop()
            self.stats["stop_returned_empty"] = not self.engine.frame((self.steps + 1) * HOP_FRAMES / SAMPLE_RATE)
            if not self.stats["stop_returned_empty"]:
                raise RuntimeError("HAR retained output after stop")
            self.stats["completed"] = error is None and self.stats["invalid_blocks"] == 0
        finally:
            self.engine.close()
            self.log.close()
            self.stats["frame_processing_us"] = ({name: float(np.percentile(self.timings, quantile))
                                                  for name, quantile in (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))}
                                                 if self.timings else {})
            self.stats["timing_scope"] = "Emission-block processing, HAR readback and file write only; excludes analysis history, input wait, USB, Provider and motors"
            (self.directory / "sensa-preview.json").write_text(json.dumps(self.stats, indent=2), encoding="utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _kind, error, _traceback):
        self.close(error)
