"""输入转送与 DS5 录制；默认不震动，显式启用 XUSB 后发送四路限幅输出。"""
import argparse
import base64
import datetime
import json
import pathlib
import queue
import subprocess
import threading
import time

from capture_recorder import CaptureRecorder
from input_timing import InputCadence
from sdl_input import RazerInput, input_state
from trigger_mapper import TriggerPair
from xusb_bridge import XusbBridge

ROOT = pathlib.Path(__file__).resolve().parent


def run(seconds, synthetic, *, sensa_preview=False, input_poll_hz=1000, xusb_output=False):
    if synthetic and xusb_output:
        raise ValueError("Synthetic burst capture cannot enable physical output")
    cadence = InputCadence(input_poll_hz)
    directory = ROOT / "runs" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recorder = CaptureRecorder(directory)
    stats = {"source": "synthetic" if synthetic else "usb-host", "hardware_output": False,
             "hardware_output_requested": xusb_output,
             "physical_latency_measured": False, "input_updates": 0, "received_messages": 0,
             "reader_drops": 0, "host_dropped_frames": 0, "host_control_drops": 0,
             "input_poll_hz": input_poll_hz, "input_poll_calls": 0, "hardware_report_rate_verified": False,
             "stopped_received": False, "host_queue_us": [], "trigger_map_us": [], "completed": False}
    events = queue.Queue(maxsize=512)
    pad = process = reader = preview = bridge = None
    mapper = TriggerPair()
    reader_failure = []
    state = input_state([0] * 6, set())
    command = [str(ROOT / "wolverine-capture.exe")]
    command += ["--self-test"] if synthetic else ["--duration", f"{seconds}s"]
    try:
        if sensa_preview:
            from sensa_preview import SensaPreview
            preview = SensaPreview(directory)
        if not synthetic:
            pad = RazerInput()
            stats["input_device"] = pad.identity
        if xusb_output:
            bridge = XusbBridge()
        with (directory / "host.log").open("w", encoding="utf-8") as host_log, (directory / "events.jsonl").open("w", encoding="utf-8") as event_log:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=host_log, text=True, encoding="utf-8", bufsize=1)
            def read_messages():
                try:
                    for line in process.stdout:
                        message = json.loads(line)
                        message["_received_at"] = time.monotonic()
                        try:
                            events.put_nowait(message)
                        except queue.Full:
                            stats["reader_drops"] += 1
                except Exception as error:
                    reader_failure.append(str(error))
            reader = threading.Thread(target=read_messages, daemon=True)
            reader.start()
            last_sent, prior_state, previous_vibration = 0, None, (0, 0)
            until = time.perf_counter() + seconds + 3
            while (process.poll() is None or reader.is_alive() or not events.empty()) and time.perf_counter() < until:
                if pad and process.poll() is None and cadence.due(time.perf_counter()):
                    state = pad.read()
                    stats["input_poll_calls"] += 1
                    if state != prior_state or time.perf_counter() - last_sent > .05:
                        process.stdin.write(json.dumps({"type":"input", "state":state}) + "\n")
                        process.stdin.flush()
                        prior_state, last_sent = state, time.perf_counter()
                        stats["input_updates"] += 1
                for _ in range(32):
                    try:
                        message = events.get_nowait()
                    except queue.Empty:
                        break
                    stats["received_messages"] += 1
                    recorder.accept(message)
                    if preview:
                        preview.accept(message)
                    if message["type"] == "audio":
                        stats["host_queue_us"].append(message["host_queue_us"])
                    elif message["type"] == "output":
                        malformed_before = mapper.malformed_reports
                        mapper.update_report(base64.b64decode(message["report"], validate=True))
                        if bridge and mapper.malformed_reports != malformed_before:
                            raise ValueError("Malformed trigger report; physical output stopped")
                    elif message["type"] == "reset":
                        mapper.reset()
                    elif message["type"] == "stopped":
                        stats["stopped_received"] = True
                        stats["host_dropped_frames"] = message["dropped_frames"]
                        stats["host_control_drops"] = message["control_drops"]
                    if bridge:
                        if time.monotonic() - message["_received_at"] > .05:
                            raise TimeoutError("Local capture queue exceeded 50 ms")
                        bridge.accept(message, now=message["_received_at"])
                    event_log.write(json.dumps({key:value for key,value in message.items() if key != "pcm"}) + "\n")
                # 丢失的消息可能正是停止指令，不能继续刷新旧的扳机效果。
                if reader_failure or stats["reader_drops"]:
                    raise RuntimeError(f"Capture reader failed: reader={reader_failure}, drops={stats['reader_drops']}")
                before = time.perf_counter_ns()
                vibration = mapper.sample(state["L2"] / 255, state["R2"] / 255, time.perf_counter())
                stats["trigger_map_us"].append((time.perf_counter_ns() - before) / 1000)
                if vibration != previous_vibration:
                    event_log.write(json.dumps({"type":"trigger-preview", "values":vibration, "submitted_to_hardware":False}) + "\n")
                    previous_vibration = vibration
                if preview:
                    preview.poll()
                if bridge:
                    bridge.poll(vibration)
                time.sleep(.001)
            if process.poll() is None:
                raise RuntimeError("Capture host exceeded its lifetime")
            reader.join(timeout=1)
            if process.returncode != 0 or reader.is_alive() or not events.empty() or reader_failure or stats["reader_drops"]:
                raise RuntimeError(f"Capture transport failed: exit={process.returncode}, reader={reader_failure}, drops={stats['reader_drops']}")
            if not synthetic and not stats["stopped_received"]:
                raise RuntimeError("Capture host exited without final counters")
            if stats["host_dropped_frames"] or stats["host_control_drops"]:
                raise RuntimeError("Capture host reported dropped data; inspect the saved counters")
            stats["completed"] = True
    except (Exception, KeyboardInterrupt) as error:
        stats["error"] = str(error) or type(error).__name__
    finally:
        mapper.reset()
        if bridge:
            try:
                bridge.close()
            except Exception as error:
                stats["completed"] = False
                stats["error"] = f"XUSB cleanup failed: {error}; prior={stats.get('error')}"
            stats["xusb_output"] = {**bridge.stats, "identity": bridge.output.identity,
                                    "calls": bridge.output.calls}
            stats["hardware_output"] = bridge.stats["hardware_output_attempted"]
        if preview:
            try:
                preview.close(error=stats.get("error"))
            except Exception as error:
                stats["completed"] = False
                stats["error"] = f"Sensa preview cleanup failed: {error}"
            stats["sensa_preview"] = preview.stats
        if pad:
            pad.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if reader:
            reader.join(timeout=1)
        if process:
            for stream in (process.stdin, process.stdout):
                if hasattr(stream, "close"):
                    stream.close()
        recorder.close()
        stats["recording"] = recorder.stats
        stats["capture_lossless"] = stats["completed"] and not any(recorder.stats[key] for key in
                                                                 ("missing_frames", "stale_blocks", "duplicate_blocks"))
        stats["unsupported_trigger_modes"] = sorted(mapper.unsupported_modes)
        stats["malformed_trigger_reports"] = mapper.malformed_reports
        stats["game_haptics_verified"] = False
        (directory / "run.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(json.dumps({"directory":str(directory), "completed":stats["completed"], "recorded_frames":recorder.stats["frames"], "error":stats.get("error"), "hardware_output":stats["hardware_output"]}, ensure_ascii=False))
    return stats["completed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--sensa-preview", action="store_true", help="Encode and save HAR frames offline; no Provider or vibration")
    parser.add_argument("--xusb-output", action="store_true", help="Enable capped four-motor physical output in Xbox mode")
    parser.add_argument("--input-poll-hz", type=int, choices=(250, 1000), default=1000,
                        help="Software input polling target; does not set or measure the controller report rate")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error("seconds must be 1..300")
    if args.synthetic and args.xusb_output:
        parser.error("--synthetic cannot be combined with --xusb-output")
    raise SystemExit(0 if run(args.seconds, args.synthetic, sensa_preview=args.sensa_preview,
                              input_poll_hz=args.input_poll_hz, xusb_output=args.xusb_output) else 1)
