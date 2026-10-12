"""无驱动、无手柄输出的本机 USB/IP 和合成触觉接收检查。"""
import base64
import json
import pathlib
import socket
import struct
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent


def read_exact(stream, count):
    result = bytearray()
    while len(result) < count:
        chunk = stream.recv(count - len(result))
        if not chunk:
            raise RuntimeError("USB/IP response truncated")
        result.extend(chunk)
    return bytes(result)


def exercise_transfers(address, busid, process, audio_check=None):
    host, port = address.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=3) as stream:
        stream.sendall(struct.pack(">HHI", 0x111, 0x8003, 0) + busid.encode().ljust(32, b"\0"))
        if struct.unpack(">HHI", read_exact(stream, 8)) != (0x111, 3, 0):
            raise RuntimeError("Local USB/IP import failed")
        descriptor = read_exact(stream, 312)
        bus, device = struct.unpack_from(">II", descriptor, 288)
        sequence = 0

        def submit(endpoint, payload=b"", setup=b"\0"*8, packets=-1, input_size=0):
            nonlocal sequence
            sequence += 1
            direction = int(input_size > 0)
            header = struct.pack(">IIIIIIIIiI8s", 1, sequence, bus << 16 | device,
                                 direction, endpoint, 0, input_size or len(payload), 0, packets, 1, setup)
            tail = struct.pack(">IIII", 0, len(payload), 0, 0) if packets == 1 else b""
            stream.sendall(header + payload + tail)
            response = read_exact(stream, 48)
            command, returned_sequence = struct.unpack_from(">II", response)
            status, actual, _, returned_packets, errors = struct.unpack_from(">iIIiI", response, 20)
            if (command, returned_sequence, status, errors) != (3, sequence, 0, 0):
                raise RuntimeError(f"USB/IP transfer failed: seq={sequence}, status={status}, errors={errors}")
            data = read_exact(stream, actual) if direction else b""
            if returned_packets > 0:
                for _ in range(returned_packets):
                    _, length, transferred, packet_status = struct.unpack(">IIIi", read_exact(stream, 16))
                    if packet_status or transferred != length:
                        raise RuntimeError("ISO packet was not fully consumed")
            return data

        submit(0, setup=struct.pack("<BBHHH", 0, 9, 1, 0, 0))
        submit(0, setup=struct.pack("<BBHHH", 1, 11, 1, 1, 0))
        if audio_check is not None:
            return audio_check(submit)
        trigger = bytearray(48)
        trigger[0:2] = b"\x02\x04"
        trigger[11:15] = b"\x25\x84\0\x07"
        submit(3, bytes(trigger))
        pcm = b"".join(struct.pack("<hhhh", 30000, 20000, 1000+i, -1000-i) for i in range(48))
        submit(1, pcm, packets=1)
        process.stdin.write(json.dumps({"type":"input", "state":{"LX":42, "L2":173, "AccelZ":-8192}}) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + .2
        while True:
            report = submit(4, input_size=64)
            if len(report) == 64 and report[1] == 170 and report[5] == 173:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Input forwarding did not reach USB report")
        time.sleep(.3)
        report = submit(4, input_size=64)
        if report[1] != 128 or report[5] != 0:
            raise RuntimeError("Input watchdog did not release controls")
        submit(0, setup=struct.pack("<BBHHH", 1, 11, 0, 1, 0))
        submit(0, setup=struct.pack("<BBHHH", 1, 11, 1, 1, 0))
        submit(1, pcm, packets=1)
        # 等待本机记录线程排空；这不是延迟测量。
        time.sleep(.03)
    return bytes(trigger), b"".join(struct.pack("<hh", 1000+i, -1000-i) for i in range(48))


def inspect_host():
    binary = ROOT / "wolverine-capture.exe"
    synthetic = subprocess.run([str(binary), "--self-test"], check=True, capture_output=True, text=True, encoding="utf-8", timeout=15)
    block = json.loads(synthetic.stdout)
    pcm = base64.b64decode(block["pcm"], validate=True)
    if block["source"] != "synthetic" or block["frames"] != 48 or len(pcm) != 192:
        raise RuntimeError("Invalid synthetic PCM contract")
    if struct.unpack("<hhhh", pcm[:8]) != (1000, -1000, 1001, -1001):
        raise RuntimeError("Synthetic rear channel mismatch")
    with (ROOT / "api-check-host.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([str(binary), "--port", "0", "--duration", "10s"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8")
        try:
            ready = json.loads(process.stdout.readline())
            if ready.get("type") != "ready" or ready.get("hardware_output") is not False:
                raise RuntimeError(f"Host did not enter capture-only mode: {ready}")
            host, port = ready["address"].rsplit(":", 1)
            with socket.create_connection((host, int(port)), timeout=3) as stream:
                stream.sendall(struct.pack(">HHI", 0x111, 0x8005, 0))
                header = struct.unpack(">HHII", read_exact(stream, 12))
                if header != (0x111, 5, 0, 1):
                    raise RuntimeError(f"Unexpected device list header: {header}")
                device = read_exact(stream, 312)
                vendor, product = struct.unpack_from(">HH", device, 300)
                interfaces = read_exact(stream, device[311] * 4)
                if (vendor, product) != (0x054c, 0x0ce6):
                    raise RuntimeError("Virtual device is not DualSense")
                classes = list(interfaces[::4])
                if 1 not in classes or 3 not in classes:
                    raise RuntimeError("Audio or HID interface missing")
            trigger, expected_rear = exercise_transfers(ready["address"], ready["busid"], process)
            process.stdin.write('{"type":"quit"}\n')
            process.stdin.flush()
            messages = [json.loads(line) for line in process.stdout]
            if process.wait(timeout=5) != 0 or not any(item.get("type") == "stopped" for item in messages):
                raise RuntimeError("Host did not stop cleanly")
            audio = [item for item in messages if item.get("type") == "audio"]
            if len(audio) != 2 or any(base64.b64decode(item["pcm"], validate=True) != expected_rear for item in audio):
                raise RuntimeError("USB/IP rear PCM did not survive the real socket path")
            if audio[0]["generation"] >= audio[1]["generation"] or any(item["first_frame"] != 0 for item in audio):
                raise RuntimeError("Audio reopen did not establish a fresh generation")
            if not any(item.get("type") == "output" and base64.b64decode(item["report"]) == trigger for item in messages):
                raise RuntimeError("Trigger report changed on the socket path")
            final = next(item for item in messages if item.get("type") == "stopped")
            if final["dropped_frames"] or final["control_drops"]:
                raise RuntimeError("Local API test dropped data")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
    return {"verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "synthetic data over localhost USB/IP",
            "synthetic_rear_pcm_exact": True, "usbip_device_list_passed": True,
            "usbip_rear_pcm_exact": True, "trigger_report_exact": True,
            "input_roundtrip": True, "input_watchdog_neutral": True, "audio_reopen_generation": True,
            "identity": f"{vendor:04X}:{product:04X}", "interface_classes": classes,
            "clean_shutdown": True, "driver_installed": False, "windows_device_mounted": False,
            "game_capture_verified": False, "physical_output": False}


if __name__ == "__main__":
    result = inspect_host()
    (ROOT / "api-check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
