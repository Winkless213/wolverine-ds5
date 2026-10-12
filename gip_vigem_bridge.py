"""GIP to ViGEm DS4 bridge - simpler alternative to USB/IP."""
import sys
import time
import vgamepad as vg
from gip_host import GipHost, UsbTransport

class GipToDS4Bridge:
    def __init__(self):
        print("Initializing GIP to ViGEm DS4 bridge...")

        # Create virtual DS4
        self.gamepad = vg.VDS4Gamepad()
        print("Virtual DS4 created")

        # Initialize GIP host
        transport = UsbTransport(vid=0x1532, pid=0x0A3F)
        self.gip = GipHost(transport)

        # State tracking
        self.last_state = None
        self.gip_reports = 0
        self.input_updates = 0
        self.start_time = time.time()
        self.last_telemetry = time.time()

    def run(self):
        """Main loop: poll GIP input, update virtual DS4."""
        print("Waiting for GIP handshake...")

        # Handshake
        handshake_start = time.time()
        while self.gip.phase != "ready":
            self.gip.poll(timeout_ms=100)
            if time.time() - handshake_start > 5.0:
                print("ERROR: Handshake timeout")
                return 1

        handshake_time = time.time() - handshake_start
        print(f"GIP handshake complete in {handshake_time:.2f}s")
        print("Bridge ready! Virtual DS4 should now be visible to games.")
        print()

        # Main loop
        try:
            while True:
                # Poll GIP (non-blocking, 4ms timeout)
                changed = self.gip.poll(timeout_ms=4)
                if changed:
                    self.gip_reports += 1

                # Get current state
                state = self.gip.state()
                if state != self.last_state:
                    self.input_updates += 1
                    self.last_state = state
                    self._update_ds4(state)

                # Telemetry every 5 seconds
                now = time.time()
                if now - self.last_telemetry >= 5.0:
                    elapsed = now - self.start_time
                    hz = self.gip_reports / elapsed if elapsed > 0 else 0
                    print(f"{{\"elapsed_s\": {elapsed:.1f}, \"gip_reports\": {self.gip_reports}, "
                          f"\"gip_hz\": {hz:.1f}, \"input_updates\": {self.input_updates}}}")
                    self.last_telemetry = now

        except KeyboardInterrupt:
            print("\nBridge stopped by user")
            return 0

    def _update_ds4(self, state):
        """Update virtual DS4 with current GIP state."""
        # Buttons mapping (GIP -> DS4)
        buttons = state['buttons']

        # Face buttons
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_CROSS if buttons & 0x1000 else 0)      # A
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE if buttons & 0x2000 else 0)     # B
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SQUARE if buttons & 0x4000 else 0)     # X
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE if buttons & 0x8000 else 0)   # Y

        # Shoulder buttons
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT if buttons & 0x0100 else 0)   # LB
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT if buttons & 0x0200 else 0)  # RB

        # Special buttons
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHARE if buttons & 0x0040 else 0)      # View/Back
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS if buttons & 0x0080 else 0)    # Menu/Start
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT if buttons & 0x0020 else 0) # LS
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT if buttons & 0x0040 else 0)# RS

        # D-Pad (GIP uses discrete buttons, DS4 uses hat switch)
        dpad = 0x08  # neutral
        up = buttons & 0x0001
        down = buttons & 0x0002
        left = buttons & 0x0004
        right = buttons & 0x0008

        if up and not left and not right:
            dpad = 0x00  # N
        elif up and right:
            dpad = 0x01  # NE
        elif right and not up and not down:
            dpad = 0x02  # E
        elif down and right:
            dpad = 0x03  # SE
        elif down and not left and not right:
            dpad = 0x04  # S
        elif down and left:
            dpad = 0x05  # SW
        elif left and not up and not down:
            dpad = 0x06  # W
        elif up and left:
            dpad = 0x07  # NW

        # Set D-Pad direction
        if dpad != 0x08:
            self.gamepad.directional_pad(dpad)

        # Analog sticks (GIP: -32768..32767, DS4: -128..127)
        lx = max(-128, min(127, state['lx'] // 256))
        ly = max(-128, min(127, -state['ly'] // 256))  # Invert Y
        rx = max(-128, min(127, state['rx'] // 256))
        ry = max(-128, min(127, -state['ry'] // 256))  # Invert Y

        self.gamepad.left_joystick(x_value=lx, y_value=ly)
        self.gamepad.right_joystick(x_value=rx, y_value=ry)

        # Triggers (GIP: 0..1023, DS4: 0..255)
        lt = state['lt'] // 4
        rt = state['rt'] // 4

        self.gamepad.left_trigger(lt)
        self.gamepad.right_trigger(rt)

        # Update the gamepad
        self.gamepad.update()

if __name__ == "__main__":
    bridge = GipToDS4Bridge()
    sys.exit(bridge.run())
