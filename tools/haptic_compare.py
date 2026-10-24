"""离线对比不同触觉映射在同一 WAV 录制上的输出。

用法：
  python tools/haptic_compare.py <input.wav> [--out report.html]

不启动桥接、不碰手柄。只读 WAV、调用 pcm_to_sensa 的映射器，输出指标和 HTML/SVG 图。
"""
import argparse
import html
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcm_to_sensa import EnvelopeToSensa, PcmToSensa

HOP = 192
SAMPLE_RATE = 48000


def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 2 or wav.getsampwidth() != 2 or wav.getframerate() != SAMPLE_RATE:
            raise ValueError("Expected stereo 16-bit 48kHz WAV")
        pcm = wav.readframes(wav.getnframes())
    samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).astype(np.float64) / 32768
    return pcm, samples


def rms_envelope(samples):
    usable = len(samples) // HOP * HOP
    frames = samples[:usable].reshape(-1, HOP, 2)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def run_converter(name, converter, pcm):
    left, right, freq_left, freq_right = [], [], [], []
    for offset in range(0, len(pcm), HOP * 4):
        block = pcm[offset:offset + HOP * 4]
        if len(block) != HOP * 4:
            break
        for result in converter.push(block):
            channels = result["channels"]
            left.append(channels[0]["amplitude"])
            right.append(channels[1]["amplitude"])
            freq_left.append(channels[0]["frequency_hz"])
            freq_right.append(channels[1]["frequency_hz"])
    return {
        "name": name,
        "left": np.array(left),
        "right": np.array(right),
        "freq_left": np.array(freq_left),
        "freq_right": np.array(freq_right),
    }


def correlation(a, b):
    if len(a) < 2 or len(b) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def metrics(series, reference):
    left, right = series["left"], series["right"]
    n = min(len(left), len(reference))
    active = (left + right) / 2 > .01
    return {
        "rms_left": float(np.sqrt(np.mean(left ** 2))) if len(left) else 0.0,
        "rms_right": float(np.sqrt(np.mean(right ** 2))) if len(right) else 0.0,
        "peak_left": float(np.max(left)) if len(left) else 0.0,
        "peak_right": float(np.max(right)) if len(right) else 0.0,
        "symmetry": correlation(left, right),
        "activity": float(np.mean(active)) if len(active) else 0.0,
        "freq_median_left": float(np.median(series["freq_left"][left > .01])) if np.any(left > .01) else 0.0,
        "freq_median_right": float(np.median(series["freq_right"][right > .01])) if np.any(right > .01) else 0.0,
        "envelope_correlation": correlation((left[:n] + right[:n]) / 2, reference[:n]) if n else 0.0,
    }


def svg_plot(title, series_list, colors, width=900, height=140):
    if not series_list or not len(series_list[0][1]):
        return ""
    n = max(len(values) for _, values in series_list)
    max_value = max(float(np.max(values)) for _, values in series_list if len(values)) or 1.0
    max_value = max(max_value, .05)
    points = []
    for (label, values), color in zip(series_list, colors):
        if not len(values):
            continue
        coords = []
        for i, value in enumerate(values):
            x = 40 + i / max(n - 1, 1) * (width - 50)
            y = height - 25 - (value / max_value) * (height - 45)
            coords.append(f"{x:.1f},{y:.1f}")
        points.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.2" points="{" ".join(coords)}"><title>{html.escape(label)}</title></polyline>')
    legend = " ".join(f'<span style="color:{color}">■ {html.escape(label)}</span>' for (label, _), color in zip(series_list, colors))
    return f'''<div class="plot"><div class="plot-title">{html.escape(title)} <span class="legend">{legend}</span></div>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
<rect x="0" y="0" width="{width}" height="{height}" fill="#11151c"/>
<line x1="40" y1="{height-25}" x2="{width-10}" y2="{height-25}" stroke="#444"/>
{"".join(points)}
</svg></div>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    pcm, samples = read_wav(args.wav)
    reference = rms_envelope(samples)

    soft = EnvelopeToSensa(limit=1)
    soft.soft = True
    converters = [
        ("PcmToSensa（当前 Xbox 默认）", PcmToSensa(limit=1)),
        ("EnvelopeToSensa（PC 默认）", EnvelopeToSensa(limit=1)),
        ("EnvelopeToSensa + soft（柔和握把）", soft),
    ]
    results = [run_converter(name, converter, pcm) for name, converter in converters]
    summaries = {result["name"]: metrics(result, reference[:, 0]) for result in results}

    out = args.out or args.wav.with_suffix(".haptic-compare.html")
    colors = ["#4fc3f7", "#81c784", "#ffb74d"]
    plots = [svg_plot("原始 PCM 包络（左/右）", [("左", reference[:, 0]), ("右", reference[:, 1])], ["#4fc3f7", "#ef5350"])]
    for result, color in zip(results, colors):
        plots.append(svg_plot(result["name"], [("左握把", result["left"]), ("右握把", result["right"])], [color, "#ef5350"]))
    rows = "".join(
        f"<tr><td>{html.escape(name)}</td>" + "".join(f"<td>{value:.4f}</td>" for value in summary.values()) + "</tr>"
        for name, summary in summaries.items()
    )
    headers = "".join(f"<th>{html.escape(key)}</th>" for key in next(iter(summaries.values())).keys())
    document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>触觉映射对比</title>
<style>
body{{background:#0b0e13;color:#e6edf3;font-family:system-ui,sans-serif;margin:24px;}}
h1{{font-size:20px;}} .plot{{margin:18px 0;}} .plot-title{{margin-bottom:6px;font-weight:600;}}
.legend{{font-size:12px;font-weight:400;margin-left:12px;}} table{{border-collapse:collapse;font-size:12px;}}
td,th{{border:1px solid #333;padding:6px 10px;text-align:right;}} td:first-child,th:first-child{{text-align:left;}}
</style></head><body>
<h1>触觉映射对比：{html.escape(args.wav.name)}</h1>
<p>采样 {len(samples)} 帧（{len(samples)/SAMPLE_RATE:.2f}s），hop={HOP} 帧（{HOP/SAMPLE_RATE*1000:.0f}ms）。指标仅供参考，最终手感仍需真机确认。</p>
{"".join(plots)}
<h2>指标</h2>
<table><tr><th>映射</th>{headers}</tr>{rows}</table>
</body></html>'''
    out.write_text(document, encoding="utf-8")
    print(json.dumps(summaries, indent=2, ensure_ascii=False))
    print(f"报告已写入：{out}")


if __name__ == "__main__":
    main()
