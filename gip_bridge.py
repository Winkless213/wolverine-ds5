"""GIP 输入 → wolverine-capture.exe → 虚拟 DS5 的完整桥接；DS5 输出经限幅映射回四马达。"""
import base64
import collections
import json
import os
import queue
import subprocess
import sys
import threading
import time

import audio_guard
import settings
from gip_host import GipHost, UsbTransport
from settings import Settings
from trigger_mapper import TriggerPair
from trigger_trace import TriggerTrace
from xusb_bridge import XusbBridge


class NullOutput:
    """手柄断开期间的马达输出：丢弃写入，扳机效果等状态仍在 Haptics 里持续更新。"""

    def set(self, left, right, lt, rt):
        pass

    def close(self):
        pass


class Haptics:
    """与 run_capture 同一条输出链：扳机效果 + 音频触觉/传统震动 → 限频的四路马达。

    GIP 路径按原生比例输出：游戏给多少强度，马达就出多少（满幅 = 100%），不另加上限。
    """

    def __init__(self, output, settings=None):
        envelope = os.environ.get("WOLVERINE_TRIGGER_ENVELOPE") == "1"
        self.mapper = TriggerPair(gain=1, feedback_envelope=envelope)
        if envelope:
            print("Trigger resistance mapping: contact pulse, 60ms hold + 180ms fade", flush=True)
        self.bridge = XusbBridge(output, limit=1)
        self.bridge.mix = self.mix
        self.settings = settings or Settings()
        self.test_target = None
        self.test_pressure = (0, 0)
        self.stalls = 0
        self.audio_errors = 0
        self.trace = TriggerTrace(os.environ.get("WOLVERINE_TRIGGER_TRACE_FLAG"))

    def mix(self, values, now):
        left, right, lt, rt = values
        grip = self.settings.grip_gain if self.settings.grip_enabled else 0
        trigger = self.settings.trigger_gain if self.settings.trigger_enabled else 0
        left, right, lt, rt = (min(1, value * gain) for value, gain in
                               ((left, grip), (right, grip), (lt, trigger), (rt, trigger)))
        if self.settings.trigger_follow and self.settings.trigger_enabled:
            ratio = self.settings.follow_ratio
            lt, rt = max(lt, values[0] * ratio), max(rt, values[1] * ratio)
        if self.test_target is not None:
            # 测试模式：LT/RT 的按压深度只驱动被测的一组马达（按当前强度），游戏输出与跟随全部屏蔽，避免串。
            gain = self.settings.grip_gain if self.test_target == "grip" else self.settings.trigger_gain
            pair = tuple(min(1, value * gain) for value in self.test_pressure)
            return (*pair, 0, 0) if self.test_target == "grip" else (0, 0, *pair)
        return left, right, lt, rt

    def attach(self, output):
        if isinstance(output, NullOutput):
            self.trace.close(time.monotonic())
        # 重连后的手柄马达是停的；清掉已发记录，让当前效果在下一轮立刻重发。
        self.bridge.output = output
        self.bridge.previous = (0, 0, 0, 0)
        self.bridge.last_poll = self.bridge.last_write = None

    def accept(self, message, now):
        if message["type"] == "output":
            report = base64.b64decode(message["report"], validate=True)
            malformed = self.mapper.malformed_reports
            self.mapper.update_report(report)
            if self.mapper.malformed_reports != malformed:
                self.bridge.stop()
                raise ValueError("Malformed trigger report; physical output stopped")
            self.trace.output(report, now)
            # hid-playstation：flag0 bit0 或 flag2 bit2 表示 byte3（右）/byte4（左）有效。
            if report[1] & 0x01 or len(report) > 39 and report[39] & 0x04:
                limit = self.bridge.stats["amplitude_limit"]
                self.bridge.rumble = (report[4] / 255 * limit, report[3] / 255 * limit)
        elif message["type"] == "reset":
            self.mapper.reset()
            self.trace.reset(now)
        elif message["type"] == "stopped":
            self.trace.close(now, "capture-stopped")
        try:
            self.bridge.accept(message, now=now)
        except (ValueError, TimeoutError):
            if message["type"] != "audio":
                raise
            # 游戏重开触觉流会让帧号跳变；只丢这一块并从新位置接上，不能拖垮输入链路。
            self.audio_errors += 1
            if message["generation"] >= self.bridge.generation:
                self.bridge.generation = message["generation"]
                self.bridge.next_frame = message["first_frame"] + message["frames"]

    def step(self, l2, r2, now):
        self.test_pressure = (l2 / 255, r2 / 255)
        triggers = self.mapper.sample(l2 / 255, r2 / 255, now)
        if not self.settings.trigger_resistance:
            # 阻力效果在纽扣马达上只能变成一下硬震，没有层次；只保留游戏明确要求的扳机震动。
            triggers = tuple(value if trigger.effect.mode == 0x26 else 0
                             for value, trigger in zip(triggers, (self.mapper.left, self.mapper.right)))
        try:
            self.bridge.poll(triggers, now=now)
        except TimeoutError:
            # 主循环卡顿（游戏加载、USB 读超时）时 poll 已把四路马达归零；
            # 长驻桥接不能因此退出，只计数并从下一轮继续。
            self.stalls += 1
            self.bridge.last_poll = None
        self.trace.sample({"l2": l2, "r2": r2, "triggers": list(self.bridge.previous[2:]),
                           "trigger_gain": self.settings.trigger_gain,
                           "resistance_enabled": self.settings.trigger_resistance,
                           "follow_enabled": self.settings.trigger_follow}, now)


def handle_command(haptics, command):
    """界面经 stdin 发来的控制消息；返回 True 表示应当退出。"""
    if command.get("type") == "quit":
        return True
    if command.get("type") == "settings" and isinstance(command.get("settings"), dict):
        haptics.settings = Settings.from_dict(command["settings"])
    elif command.get("type") == "test" and command.get("target") in ("grip", "trigger", None):
        haptics.test_target = command["target"]
    return False


def input_due(last_state, state, now, last_sent):
    # 手柄只在变化时上报；按住不动也要在 capture 的 250ms 看门狗松开按键前重发。
    return state != last_state or now - last_sent >= .1


def read_capture_output(proc, events):
    """读取 wolverine-capture 的 stdout；震动在主线程下发，GipHost 不能跨线程写。"""
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            print(f"wolverine-capture output: {line.strip()}", flush=True)
            continue
        if msg.get("type") in ("output", "audio", "reset", "stopped"):
            msg["_received_at"] = time.monotonic()
            events.put(msg)
        if msg.get("type") == "output" and os.environ.get("GIP_BRIDGE_DUMP_OUTPUT"):
            print("output", base64.b64decode(msg["report"]).hex(), flush=True)
        if msg.get("type") == "stopped":
            print(f"wolverine-capture stopped: {msg}", flush=True)
            break
        elif msg.get("type") not in ("ready", "output", "audio", "reset"):
            print(f"wolverine-capture: {msg}", flush=True)


def attach_virtual_ds5(address, busid, run=subprocess.run):
    """桥接重启后 usbip-win2 不会自动重新导入；本端已挂上时跳过，避免出现两个 DS5。"""
    exe = os.environ.get("GIP_BRIDGE_USBIP_EXE", r"C:\Program Files\USBip\usbip.exe")
    host, port = address.rsplit(":", 1)
    ports = run([exe, "port"], capture_output=True, text=True).stdout
    if f"usbip://{address}/{busid}" in ports:
        print("Virtual DualSense already attached", flush=True)
        return
    result = run([exe, "-t", port, "attach", "-r", host, "-b", busid, "--once"], capture_output=True, text=True)
    print(f"usbip attach: {(result.stdout or result.stderr).strip()}", flush=True)


class Status:
    """给托盘程序的状态行：waiting / handshake / connected / lost，状态或附带原因变化时才输出。"""

    def __init__(self, write=None):
        self.write = write or (lambda line: print(line, flush=True))
        self.state = None

    def set(self, state, **details):
        if (state, details) != self.state:
            self.state = (state, details)
            self.write(json.dumps({"type": "status", "state": state, **details}))


STATUS = Status()
# 界面经 stdin 发来的命令；整个进程只有一个读线程，supervise 重启会话后命令也不会落进旧队列。
COMMANDS = queue.Queue()


def read_commands(stream, events, quit_on_eof=False):
    """界面通过 stdin 发 JSON 行。手动运行时 EOF 不代表退出；由托盘托管时界面关闭就要停桥接。"""
    for line in stream:
        try:
            command = json.loads(line)
        except ValueError:
            continue
        if isinstance(command, dict):
            events.put({"type": "command", "command": command})
    if quit_on_eof:
        events.put({"type": "command", "command": {"type": "quit"}})


def drain(events, haptics, counts, commands=None):
    for source in (COMMANDS if commands is None else commands, events):
        while not source.empty():
            message = source.get_nowait()
            if message["type"] == "command":
                # 命令在主线程执行，和马达输出不会并发；quit 走与 Ctrl+C 相同的清理路径。
                if handle_command(haptics, message["command"]):
                    raise KeyboardInterrupt
                continue
            counts[message["type"]] += 1
            haptics.accept(message, now=message["_received_at"])


def reconnect_loop(opener, session, wait, alive):
    """拔线或握手失败时只重开手柄 USB；虚拟 DS5 和 usbip 挂载不动，游戏不用重启。"""
    while alive():
        try:
            transport = opener()
        except (RuntimeError, OSError) as error:
            # 打不开就带原因留在 waiting；Status 去重，同一错误只输出一次。
            STATUS.set("waiting", error=str(error))
            wait()
            continue
        try:
            return session(transport)
        except OSError as error:
            STATUS.set("lost", error=repr(error))
            print(f"Controller lost ({error!r}); waiting for reconnect", file=sys.stderr, flush=True)
        finally:
            try:
                transport.close()
            except (OSError, RuntimeError) as error:
                # 已拔出的实体设备可能无法清理；不能因此销毁仍被游戏使用的虚拟 DS5。
                print(f"Controller cleanup failed ({error!r}); continuing reconnect", file=sys.stderr, flush=True)
        wait()
    return 1


def main(serve_capture=None):
    if serve_capture is None and os.environ.get("WOLVERINE_XBOX_SENSA") == "1":
        from xbox_sensa_bridge import serve as serve_capture
    print("Starting GIP to DualSense bridge...", flush=True)
    capture_proc = subprocess.Popen(
        [os.environ.get("GIP_BRIDGE_CAPTURE_EXE", "./wolverine-capture.exe"), "-port", "3240", "-duration", "24h"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,  # 让 stderr 直接输出，方便调试
        text=True,
        bufsize=1
    )
    try:
        return (serve_capture or serve)(capture_proc)
    except KeyboardInterrupt:
        print("\nStopping bridge...", flush=True)
        try:
            capture_proc.stdin.write(json.dumps({"type": "quit"}) + "\n")
            capture_proc.stdin.flush()
            capture_proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return 0
    finally:
        if capture_proc.poll() is None:
            capture_proc.terminate()
            capture_proc.wait(timeout=2)


def serve(capture_proc, make_haptics=lambda saved: Haptics(NullOutput(), saved), opener=UsbTransport,
          run_session=None):
    ready_line = capture_proc.stdout.readline()
    if not ready_line:
        print("ERROR: wolverine-capture failed to start", file=sys.stderr, flush=True)
        return 1
    ready_msg = json.loads(ready_line)
    if ready_msg.get("type") != "ready":
        print(f"ERROR: Unexpected message from wolverine-capture: {ready_msg}", file=sys.stderr, flush=True)
        return 1
    print(f"Virtual DualSense ready on {ready_msg['address']}, busid={ready_msg['busid']}", flush=True)

    events = queue.Queue()
    threading.Thread(target=read_capture_output, args=(capture_proc, events), daemon=True).start()
    attach_virtual_ds5(ready_msg["address"], ready_msg["busid"])

    haptics = make_haptics(settings.load())
    audio_guard.start(enabled=lambda: haptics.settings.audio_guard)
    counts = collections.Counter()
    STATUS.set("waiting")

    def wait():
        # 等手柄期间照常消费 capture 输出，重连后用的是最新扳机效果而不是积压的旧消息。
        end = time.monotonic() + 1
        while time.monotonic() < end:
            drain(events, haptics, counts)
            time.sleep(.01)

    run_session = run_session or session
    return reconnect_loop(opener, lambda transport: run_session(transport, capture_proc, events, haptics, counts),
                          wait, alive=lambda: capture_proc.poll() is None)


def session(transport, capture_proc, events, haptics, counts):
    gip = GipHost(transport)
    start = time.monotonic()
    STATUS.set("handshake")
    print("Waiting for GIP handshake...", flush=True)
    while gip.phase != "ready":
        if time.monotonic() - start > 5:
            STATUS.set("waiting", error="handshake timeout")
            raise TimeoutError("GIP handshake timeout; replug the controller if this repeats")
        gip.poll()
        drain(events, haptics, counts)
    print(f"GIP handshake complete in {time.monotonic() - start:.2f}s", flush=True)
    print("Bridge ready!", flush=True)
    STATUS.set("connected", handshake_s=round(time.monotonic() - start, 2))

    haptics.attach(gip)
    peak_motors = [0, 0, 0, 0]
    last_state = None
    last_sent = 0
    input_updates = 0
    last_stats = last_meter = time.monotonic()
    try:
        while True:
            gip.poll(timeout_ms=4)
            state = gip.state()
            if input_due(last_state, state, time.monotonic(), last_sent):
                try:
                    capture_proc.stdin.write(json.dumps({"type": "input", "state": state}) + "\n")
                    capture_proc.stdin.flush()
                except BrokenPipeError:
                    print("ERROR: wolverine-capture stdin broken", file=sys.stderr, flush=True)
                    return 1
                last_state = state
                last_sent = time.monotonic()
                input_updates += 1

            drain(events, haptics, counts)
            haptics.step(state["L2"], state["R2"], time.monotonic())
            peak_motors = [max(pair) for pair in zip(peak_motors, haptics.bridge.previous)]

            now = time.monotonic()
            if os.environ.get("WOLVERINE_MANAGED") and now - last_meter >= .05:
                print(json.dumps({"type": "meter", "motors": [round(value, 3) for value in haptics.bridge.previous],
                                  "l2": state["L2"], "r2": state["R2"], "buttons": state["Buttons"],
                                  "dpad": state["DPad"], "sticks": [state[axis] for axis in ("LX", "LY", "RX", "RY")]}),
                      flush=True)
                last_meter = now
            if now - last_stats >= 5.0:
                elapsed = now - start
                print(json.dumps({
                    "elapsed_s": round(elapsed, 1),
                    "gip_reports": gip.reports,
                    "gip_hz": round(gip.reports / elapsed, 1),
                    "input_updates": input_updates,
                    "motors": haptics.bridge.previous,
                    "peak_motors_5s": [round(value, 3) for value in peak_motors],
                    "haptic_audio_frames": haptics.bridge.stats["audio_frames"],
                    "haptic_audio_errors": haptics.audio_errors,
                    "capture_messages": dict(counts),
                    "unsupported_trigger_modes": sorted(haptics.mapper.unsupported_modes)
                }), flush=True)
                last_stats = now
                peak_motors = [0, 0, 0, 0]

            if capture_proc.poll() is not None:
                print("ERROR: wolverine-capture exited", file=sys.stderr, flush=True)
                return 1
    finally:
        haptics.attach(NullOutput())
        try:
            gip.set(0, 0, 0, 0)
        except OSError:
            pass


def supervise(run=main, wait=time.sleep):
    """桥接异常退出（拔线、握手超时、capture 退出）后自动重启；只有 Ctrl+C 结束。"""
    while True:
        try:
            if run() == 0:
                return 0
        except KeyboardInterrupt:
            return 0
        except Exception as error:
            print(f"ERROR: {error!r}", file=sys.stderr, flush=True)
        print("Bridge stopped; restarting in 3s", file=sys.stderr, flush=True)
        try:
            wait(3)
        except KeyboardInterrupt:
            return 0


def run(entry=main):
    """进程入口：stdin 只开一个读线程，供 supervise 的每一轮会话共用。"""
    threading.Thread(target=read_commands, args=(sys.stdin, COMMANDS),
                     kwargs={"quit_on_eof": bool(os.environ.get("WOLVERINE_MANAGED"))}, daemon=True).start()
    return supervise(run=entry)


if __name__ == "__main__":
    sys.exit(run())
