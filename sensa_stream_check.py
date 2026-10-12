"""合成四声道经真实本机 USB/IP、Go 接收器、左右转换与 HAR 回读。"""
import base64
import datetime
import hashlib
import json
import math
from pathlib import Path
import queue
import struct
import subprocess
import threading
import time

from api_check import exercise_transfers
from capture_recorder import CaptureRecorder
from sensa_frame import decode_frame
from sensa_preview import SensaPreview

ROOT = Path(__file__).resolve().parent


def usb_pcm(first, left, right):
    payload, rear = bytearray(), bytearray()
    for frame in range(first, first + 48):
        values = [round(32767 * amplitude * math.sin(2 * math.pi * frequency * frame / 48000))
                  for amplitude, frequency in (left, right)]
        # 前两路故意放大，避免把扬声器误采为触觉后仍然通过。
        payload.extend(struct.pack("<hhhh", 24000, -18000, *values))
        rear.extend(struct.pack("<hh", *values))
    return bytes(payload), bytes(rear)


def assert_tones(record, tones):
    decoded = decode_frame(bytes.fromhex(record["hex"]))
    if [side["bodypart"] for side in decoded["channels"]] != [216, 116]:
        raise RuntimeError("Missing independent left/right frame slots")
    measured = []
    for side, (amplitude, frequency) in zip(decoded["channels"], tones):
        point = max((point for band in side["bands"] for point in band), key=lambda item: item["amplitude_code"])
        actual_amplitude = point["amplitude_code"] / 63
        actual_frequency = 30 + point["frequency_code"] * 370 / 127
        if abs(actual_amplitude - amplitude * .22) > 1 / 63 + .004:
            raise RuntimeError("PCM-to-HAR level or channel mismatch")
        if amplitude and abs(actual_frequency - frequency) > 5:
            raise RuntimeError("PCM-to-HAR dominant frequency mismatch")
        if not amplitude and point["amplitude_code"]:
            raise RuntimeError("Silent PCM channel leaked into a native frame")
        measured.append({"bodypart": side["bodypart"], "amplitude_code": point["amplitude_code"],
                         "frequency_hz": actual_frequency if amplitude else None})
    return measured


class StreamCheck:
    def __init__(self, messages, recorder, preview, process, input_poll_hz):
        self.messages, self.recorder, self.preview = messages, recorder, preview
        self.process, self.input_poll_hz = process, input_poll_hz
        self.audio_blocks = 0
        self.input_updates = 0
        self.input_report_checks = 0
        self.held_input_reports = 0
        self.expected_input = (128, 0, 0)
        self.input_watchdog_neutral = self.audio_timeout_silent = False
        self.pcm_digest, self.parameter_digest = hashlib.sha256(), hashlib.sha256()
        self.cases = []

    def read_input(self, submit):
        report = submit(4, input_size=64)
        self.input_report_checks += 1
        if len(report) != 64:
            raise RuntimeError("Virtual DS5 input report is incomplete")
        return report[1], report[5], report[6]

    def update_input(self, submit):
        lx, l2, r2 = (42, 173, 29) if self.input_updates % 2 == 0 else (-42, 29, 173)
        self.expected_input = (lx + 128, l2, r2)
        self.process.stdin.write(json.dumps({"type": "input", "state": {"LX": lx, "L2": l2, "R2": r2}}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + .2
        while True:
            if self.read_input(submit) == self.expected_input:
                self.input_updates += 1
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Concurrent controller input did not reach the virtual DS5")

    def check_timeout(self, submit):
        time.sleep(.3)
        if self.read_input(submit) != (128, 0, 0):
            raise RuntimeError("Input watchdog did not release both triggers")
        self.input_watchdog_neutral = True
        quiet = self.preview.poll()
        if quiet is None or quiet["reason"] != "timeout":
            raise RuntimeError("Audio timeout did not clear Sensa parameters")
        assert_tones(quiet, ((0, 80), (0, 160)))
        self.audio_timeout_silent = True

    def receive(self, expected=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            item = self.messages.get(timeout=max(.001, deadline - time.monotonic()))
            self.recorder.accept(item)
            records = self.preview.accept(item)
            for record in records:
                if record.get("reason") == "parameters":
                    self.parameter_digest.update(bytes.fromhex(record["hex"]))
            if item["type"] == "audio":
                self.audio_blocks += 1
                pcm = base64.b64decode(item["pcm"], validate=True)
                if expected is None or pcm != expected:
                    raise RuntimeError("Raw rear PCM changed or arrived unexpectedly")
                self.pcm_digest.update(pcm)
                return item
            if item["type"] == "stopped":
                if expected is not None or item["dropped_frames"] or item["control_drops"]:
                    raise RuntimeError("Host stopped early or dropped capture data")
                return item
        raise RuntimeError("No capture response before deadline")

    def send(self, submit):
        first = 0
        previous_generation = None
        scenarios = (("left80", (.6, 80), (0, 160)), ("right160", (0, 80), (.5, 160)),
                     ("both", (.6, 110), (.3, 250)), ("quiet", (0, 110), (0, 250)),
                     ("left30", (.6, 30), (0, 40)), ("right40", (0, 30), (.5, 40)),
                     ("reopen-right200", (0, 80), (.5, 200)))
        for name, left, right in scenarios:
            if name.startswith("reopen"):
                self.check_timeout(submit)
                previous_generation = self.preview.generation
                submit(0, setup=struct.pack("<BBHHH", 1, 11, 0, 1, 0))
                submit(0, setup=struct.pack("<BBHHH", 1, 11, 1, 1, 0))
                first = 0
            for _ in range(120):
                # 用 PCM 样本时钟交错输入，核对兼容性，不把执行耗时冒充实机回报率。
                if self.audio_blocks % (1000 // self.input_poll_hz) == 0:
                    self.update_input(submit)
                else:
                    if self.read_input(submit) != self.expected_input:
                        raise RuntimeError("Virtual DS5 did not hold the latest 250 Hz input state")
                    self.held_input_reports += 1
                payload, expected = usb_pcm(first, left, right)
                submit(1, payload, packets=1)
                item = self.receive(expected)
                if item["first_frame"] != first or item["source"] != "usb-host":
                    raise RuntimeError("Sample clock or transport provenance mismatch")
                first += 48
            if previous_generation is not None and self.preview.generation <= previous_generation:
                raise RuntimeError("Audio reopen did not change the capture generation")
            self.cases.append({"name": name, "generation": self.preview.generation, "input_tones": [left, right],
                               "decoded": assert_tones(self.preview.last_record, (left, right))})


def inspect_stream(input_poll_hz):
    directory = ROOT / "validation" / (f"stream-{input_poll_hz}hz-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    recorder = CaptureRecorder(directory)
    preview = SensaPreview(directory)
    messages = queue.Queue(maxsize=1024)
    failures = []
    process = reader = None
    result = {"verified_at": datetime.datetime.now().astimezone().isoformat(), "passed": False,
              "fixture_source": "synthetic tones over a real localhost USB/IP socket",
              "input_poll_hz": input_poll_hz, "input_rate_clock": "synthetic PCM sample clock; not wall-clock throughput",
              "hardware_report_rate_verified": False,
              "hardware_output": False, "provider_loaded": False, "driver_installed": False,
              "windows_device_mounted": False, "game_capture_verified": False,
              "physical_latency_measured": False, "directory": str(directory),
              "capture_binary_sha256": hashlib.sha256((ROOT / "wolverine-capture.exe").read_bytes()).hexdigest()}
    started = time.perf_counter()
    try:
        with (directory / "host.log").open("w", encoding="utf-8") as host_log:
            process = subprocess.Popen([str(ROOT / "wolverine-capture.exe"), "--port", "0", "--duration", "20s"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=host_log,
                                       text=True, encoding="utf-8")

            def read_messages():
                try:
                    for line in process.stdout:
                        messages.put(json.loads(line), timeout=3)
                except Exception as error:
                    failures.append(str(error))

            reader = threading.Thread(target=read_messages, daemon=True)
            reader.start()
            ready = messages.get(timeout=5)
            if ready.get("type") != "ready" or ready.get("hardware_output") is not False:
                raise RuntimeError("Capture host is not in offline mode")
            check = StreamCheck(messages, recorder, preview, process, input_poll_hz)
            exercise_transfers(ready["address"], ready["busid"], process, check.send)
            process.stdin.write('{"type":"quit"}\n')
            process.stdin.flush()
            final = check.receive()
            if process.wait(timeout=5) != 0 or final["type"] != "stopped":
                raise RuntimeError("Capture host failed to stop")
            reader.join(timeout=1)
            if reader.is_alive() or failures or not messages.empty():
                raise RuntimeError(f"Capture reader did not drain: {failures}")
            if check.audio_blocks != 840 or preview.stats["parameter_frames"] != 210:
                raise RuntimeError("Continuous PCM or parameter frames were lost")
            if check.input_updates != 840 * input_poll_hz // 1000:
                raise RuntimeError("Controller input cadence was not exercised completely")
            if check.input_updates + check.held_input_reports != 840:
                raise RuntimeError("Virtual DS5 input was not checked between audio blocks")
            result.update(cases=check.cases, pcm_blocks=check.audio_blocks, exact_rear_pcm=True,
                          input_frames=preview.stats["input_frames"], clean_shutdown=True,
                          input_updates=check.input_updates, input_report_checks=check.input_report_checks,
                          held_input_reports=check.held_input_reports,
                          input_watchdog_neutral=check.input_watchdog_neutral, audio_timeout_silent=check.audio_timeout_silent,
                          pcm_sha256=check.pcm_digest.hexdigest(), parameter_frames_sha256=check.parameter_digest.hexdigest(),
                          host_dropped_frames=final["dropped_frames"], host_control_drops=final["control_drops"])
            result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        if process:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            if reader:
                reader.join(timeout=1)
            process.stdin.close()
            process.stdout.close()
        try:
            preview.close(error=result.get("error"))
        except Exception as error:
            result.update(passed=False, error=f"Preview shutdown failed: {error}")
        recorder.close()
        result.update(preview=preview.stats, recording=recorder.stats, wall_seconds=time.perf_counter() - started)
        if any(recorder.stats[key] for key in ("missing_frames", "stale_blocks", "duplicate_blocks")):
            result.update(passed=False, error="PCM recording was not lossless")
        (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def inspect_rates():
    runs = [inspect_stream(hz) for hz in (250, 1000)]
    passed = all(run["passed"] for run in runs)
    same_pcm = passed and runs[0]["pcm_sha256"] == runs[1]["pcm_sha256"]
    same_parameters = passed and runs[0]["parameter_frames_sha256"] == runs[1]["parameter_frames_sha256"]
    result = {"verified_at": datetime.datetime.now().astimezone().isoformat(),
              "passed": passed and same_pcm and same_parameters, "input_rates_hz": [250, 1000],
              "same_pcm_across_input_rates": same_pcm, "same_parameters_across_input_rates": same_parameters,
              "hardware_output": False, "hardware_report_rate_verified": False, "runs": runs}
    (ROOT / "sensa-stream-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = inspect_rates()
    print(json.dumps({key: value for key, value in result.items() if key != "runs"}))
    for run in result["runs"]:
        print(json.dumps({key: run.get(key) for key in ("input_poll_hz", "passed", "directory", "pcm_blocks", "input_updates", "error")}))
    raise SystemExit(0 if result["passed"] else 1)
