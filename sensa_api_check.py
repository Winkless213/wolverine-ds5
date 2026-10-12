"""离线验证 HAR 的左右通道、更新和停止；不会产生手柄震动。"""
import datetime
import json
import time
from pathlib import Path

from sensa_frame import decode_frame
from sensa_offline import HAR_SHA256, OfflineSensa


def inspect_engine():
    result = {"verified_at": datetime.datetime.now().astimezone().isoformat(),
              "har_sha256": HAR_SHA256, "hardware_output": False, "provider_loaded": False,
              "arbitrary_pcm_verified": False, "physical_latency_measured": False,
              "source": "synthetic parameter effects", "cases": [], "update_and_encode_us": []}
    with OfflineSensa() as engine:
        result.update(layout=engine.layout, max_frame_bytes=engine.max_frame_bytes)
        for step, (name, left, right) in enumerate((
                ("left80", (.22, 80), (0, 160)), ("right160", (0, 80), (.22, 160)),
                ("both", (.11, 80), (.22, 160)), ("quiet", (0, 80), (0, 160))), 1):
            before = time.perf_counter_ns()
            engine.set_tone(0, *left)
            engine.set_tone(1, *right)
            frame = engine.frame(step * .004)
            result["update_and_encode_us"].append((time.perf_counter_ns() - before) / 1000)
            decoded = decode_frame(frame)
            for channel, (amplitude, frequency) in zip(decoded["channels"], (left, right)):
                points = [point for band in channel["bands"] for point in band]
                peak = max(point["amplitude_code"] for point in points) / 63
                if abs(peak - amplitude) > 1 / 63:
                    raise RuntimeError(f"HAR amplitude or channel mismatch: {name}")
                if amplitude:
                    actual = 30 + max(points, key=lambda point: point["amplitude_code"])["frequency_code"] * 370 / 127
                    if abs(actual - frequency) > 370 / 127:
                        raise RuntimeError(f"HAR frequency mismatch: {name}")
            if len(decoded["channels"]) != 2:
                raise RuntimeError("HAR did not produce both channel slots")
            result["cases"].append({"name":name, "hex":frame.hex(), "decoded":decoded})
        engine.stop()
        result["stop_returned_empty"] = not engine.frame(.02)
        if not result["stop_returned_empty"]:
            raise RuntimeError("HAR retained an active frame after stop")
    for key, stereo in (("intervals", False), ("stereo_intervals", True)):
        result[key] = []
        for interval_ms, single_duration_ms in ((1, 2), (2, 3), (4, 6), (8, 12), (16, 24)):
            with OfflineSensa() as engine:
                engine.set_tone(0, .22, 80)
                if stereo:
                    engine.set_tone(1, .11, 160)
                frames = [decode_frame(engine.frame((step + 1) * interval_ms / 1000)) for step in range(3)]
                durations = [frame["duration_ms"] for frame in frames]
                # 双侧会触发原生时间回退；帧头覆盖时长不能替代调用周期。
                if durations != [60 if stereo else single_duration_ms] * 3:
                    raise RuntimeError(f"HAR frame timing changed for {key} at {interval_ms} ms")
                engine.stop()
                stopped = not engine.frame(4 * interval_ms / 1000)
                if not stopped:
                    raise RuntimeError("HAR retained output after the timing check")
                result[key].append({"compute_interval_ms": interval_ms,
                                    "target_bodyparts": [216, 116] if stereo else [216],
                                    "encoded_duration_ms": durations, "stop_returned_empty": stopped})
    result["encoded_duration_scope"] = "Native buffer horizon; not a send interval or measured playback latency"
    result["passed"] = True
    result["timing_scope"] = "Two HAR tone updates plus in-memory compute/encoding; excludes USB, RPC, provider and motors"
    return result


if __name__ == "__main__":
    output = Path(__file__).with_name("sensa-api-check.json")
    try:
        result = inspect_engine()
    except Exception as error:
        result = {"passed":False, "error":str(error), "hardware_output":False}
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key:value for key,value in result.items() if key != "cases"}))
    raise SystemExit(0 if result["passed"] else 1)
