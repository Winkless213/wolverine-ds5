"""WinUSB 实机探测：握手、读输入；--play 时按左握把、右握把、LT、RT 各 1 秒短震。"""
import argparse
import datetime
import json
import pathlib
import time

from gip_host import GipHost, UsbTransport

ROOT = pathlib.Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--play", action="store_true", help="Send four capped 1 s pulses after the handshake")
    args = parser.parse_args()
    result = {"started": datetime.datetime.now().isoformat(), "phase": None, "reports": 0,
              "pulses": [], "error": None}
    transport = UsbTransport()
    read = transport.read
    counts = result["received"] = {}

    def counted(timeout_ms):
        packet = read(timeout_ms)
        if packet:
            key = f"0x{packet[0]:02x}"
            counts[key] = counts.get(key, 0) + 1
        return packet
    transport.read = counted
    host = GipHost(transport)
    try:
        deadline = time.monotonic() + 5
        while host.phase != "ready":
            if time.monotonic() > deadline:
                raise TimeoutError(f"Handshake did not finish (phase={host.phase})")
            host.poll()
        result["handshake_s"] = round(5 - (deadline - time.monotonic()), 3)
        print(f"handshake ok in {result['handshake_s']} s; press buttons / pull triggers")
        start, plan = time.monotonic(), []
        if args.play:
            plan = [(1 + 2 * i, values) for i, values in enumerate(((.22, 0, 0, 0), (0, .22, 0, 0),
                                                                     (0, 0, .22, 0), (0, 0, 0, .22)))]
        active, last_print = None, 0
        while time.monotonic() - start < args.seconds:
            host.poll()
            elapsed = time.monotonic() - start
            for at, values in plan:
                if at <= elapsed < at + 1 and active != values:
                    host.set(*values)
                    active = values
                    result["pulses"].append({"at_s": round(elapsed, 3), "values": values})
                elif active == values and elapsed >= at + 1:
                    host.set(0, 0, 0, 0)
                    active = None
            if active and elapsed - last_print >= .1:
                host.set(*active)
            if elapsed - last_print >= .1:
                last_print = elapsed
                print(json.dumps(host.state()), end="\r")
        result["reports"] = host.reports
        result["report_hz"] = round(host.reports / args.seconds, 1)
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        result["phase"] = host.phase
        host.close()
        out = ROOT / "validation" / f"gip-probe-{datetime.datetime.now():%Y%m%d-%H%M%S}.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("\n" + json.dumps(result))


if __name__ == "__main__":
    main()
