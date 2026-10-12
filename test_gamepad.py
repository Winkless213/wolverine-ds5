"""Test Windows gamepad detection via pygame and xinput."""
import sys
import time

def test_pygame():
    """Test pygame joystick detection."""
    try:
        import pygame
        pygame.init()
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        print(f"pygame: {count} joystick(s) detected")
        for i in range(count):
            joy = pygame.joystick.Joystick(i)
            joy.init()
            print(f"  [{i}] {joy.get_name()}")
            print(f"      Axes: {joy.get_numaxes()}, Buttons: {joy.get_numbuttons()}")
        pygame.quit()
        return count > 0
    except ImportError:
        print("pygame not installed, skipping")
        return None

def test_xinput():
    """Test XInput detection."""
    try:
        import xinput
        for i in range(4):
            state = xinput.get_state(i)
            if state:
                print(f"XInput slot {i}: connected")
                return True
        print("XInput: no controllers detected")
        return False
    except ImportError:
        print("xinput not installed, skipping")
        return None

def test_windows_hid():
    """Test Windows HID device enumeration."""
    try:
        import hid
        print("\nHID devices with gamepad usage:")
        for dev in hid.enumerate():
            # USB HID usage page 0x01 (Generic Desktop), usage 0x05 (Game Pad) or 0x04 (Joystick)
            if dev['usage_page'] == 1 and dev['usage'] in (4, 5):
                print(f"  VID={dev['vendor_id']:04x} PID={dev['product_id']:04x}")
                print(f"    Product: {dev['product_string']}")
                print(f"    Usage: {dev['usage']} (0x04=Joystick, 0x05=GamePad)")
    except ImportError:
        print("hidapi not installed, skipping HID enumeration")

if __name__ == "__main__":
    print("Testing Windows gamepad APIs...\n")
    test_pygame()
    test_xinput()
    test_windows_hid()
