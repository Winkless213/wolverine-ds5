"""测试桥接程序的输入映射：显示当前按键和摇杆状态。"""
import json
import subprocess
import sys
import time


def button_names(buttons):
    """解码按钮位掩码。"""
    names = []
    mapping = [
        (0x10, "Square"), (0x20, "Cross"), (0x40, "Circle"), (0x80, "Triangle"),
        (0x100, "L1"), (0x200, "R1"), (0x400, "L2"), (0x800, "R2"),
        (0x1000, "Share"), (0x2000, "Options"), (0x4000, "L3"), (0x8000, "R3"),
        (0x10000, "PS")
    ]
    for mask, name in mapping:
        if buttons & mask:
            names.append(name)
    return ", ".join(names) if names else "None"


def dpad_name(dpad):
    """解码 DPad 值。"""
    return ["Up", "NE", "Right", "SE", "Down", "SW", "Left", "NW", "Center"][dpad] if dpad < 9 else "Unknown"


def main():
    print("Starting input test...", flush=True)

    proc = subprocess.Popen(
        ["python", "gip_bridge.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # 跳过启动消息
    for _ in range(10):
        line = proc.stdout.readline()
        if not line:
            break
        if "Bridge ready" in line:
            break

    print("\nPress buttons and move sticks on the controller...\n", flush=True)

    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break

            try:
                msg = json.loads(line)
                if msg.get("type") == "input" and "state" in msg:
                    state = msg["state"]
                    print(f"LX={state['LX']:4d} LY={state['LY']:4d} "
                          f"RX={state['RX']:4d} RY={state['RY']:4d} "
                          f"L2={state['L2']:3d} R2={state['R2']:3d} "
                          f"DPad={dpad_name(state['DPad']):6s} "
                          f"Buttons=[{button_names(state['Buttons'])}]",
                          end="\r", flush=True)
            except:
                pass

    except KeyboardInterrupt:
        print("\n\nStopping...", flush=True)
    finally:
        proc.terminate()
        proc.wait(timeout=2)


if __name__ == "__main__":
    main()
