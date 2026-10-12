"""仅读取指定雷蛇手柄；本模块没有震动输出入口。"""
import ctypes as c
import pathlib
import time


def verified_xinput_alias():
    from xusb_output import XusbApi, find_razer_interface
    api = XusbApi()
    path, parents = find_razer_interface(api, only_interface=True)
    handle = api.open(path)
    try:
        compatibility = api.info(handle)
    finally:
        api.close(handle)
    if (compatibility["vendor"], compatibility["product"]) != ("045E", "02FF"):
        raise RuntimeError("XUSB identity does not match the SDL compatibility device")
    return {"vendor": "1532", "product": "0A3F", "path": path,
            "parents": parents, "compatibility": compatibility}


def select_device(devices, verify_alias=verified_xinput_alias):
    matches = [device for device in devices if device[1] == 0x1532 and device[2] in (0x0A3F, 0x0A4C)]
    if len(matches) == 1:
        ident, vendor, product = matches[0]
        return ident, {"vendor": f"{vendor:04X}", "product": f"{product:04X}"}
    # Xbox 模式使用微软兼容身份；仅在两端均唯一且实体父链吻合时关联。
    if not matches and len(devices) == 1 and devices[0][1:] == (0x045E, 0x02FF):
        return devices[0][0], verify_alias()
    raise RuntimeError(f"Expected one supported Razer device, found {len(matches)}")


def input_state(axes, buttons):
    state = dict(zip(("LX", "LY", "RX", "RY"), (max(-128, min(127, value // 256)) for value in axes[:4])))
    state.update(L2=round(max(0, axes[4]) * 255 / 32767), R2=round(max(0, axes[5]) * 255 / 32767),
                 Buttons=0, DPad=0, AccelZ=-8192)
    masks = {0:0x20, 1:0x40, 2:0x10, 3:0x80, 4:0x1000, 5:0x10000, 6:0x2000,
             7:0x4000, 8:0x8000, 9:0x100, 10:0x200}
    for button, mask in masks.items():
        if button in buttons:
            state["Buttons"] |= mask
    for button, mask in ((11,1), (12,2), (13,4), (14,8)):
        if button in buttons:
            state["DPad"] |= mask
    if state["L2"] > 0:
        state["Buttons"] |= 0x400
    if state["R2"] > 0:
        state["Buttons"] |= 0x800
    return state


class RazerInput:
    def __init__(self):
        self.pad = None
        self.dll = c.CDLL(str(pathlib.Path(__file__).with_name("SDL3.dll")))
        def bind(name, result, *args):
            function = getattr(self.dll, name)
            function.restype, function.argtypes = result, args
            return function
        hint = bind("SDL_SetHint", c.c_bool, c.c_char_p, c.c_char_p)
        for name in ("SDL_JOYSTICK_HIDAPI", "SDL_JOYSTICK_WGI", "SDL_JOYSTICK_GAMEINPUT",
                     "SDL_JOYSTICK_RAWINPUT", "SDL_JOYSTICK_DIRECTINPUT"):
            hint(name.encode(), b"0")
        hint(b"SDL_XINPUT_ENABLED", b"1")
        hint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        self.quit = bind("SDL_Quit", None)
        self.pump = bind("SDL_PumpEvents", None)
        self.close_pad = bind("SDL_CloseGamepad", None, c.c_void_p)
        self.connected = bind("SDL_GamepadConnected", c.c_bool, c.c_void_p)
        self.axis = bind("SDL_GetGamepadAxis", c.c_int16, c.c_void_p, c.c_int)
        self.button = bind("SDL_GetGamepadButton", c.c_bool, c.c_void_p, c.c_int)
        if not bind("SDL_Init", c.c_bool, c.c_uint32)(0x2000):
            raise RuntimeError("SDL input initialization failed")
        try:
            for _ in range(20):
                self.pump()
                time.sleep(.01)
            count = c.c_int()
            ids = bind("SDL_GetGamepads", c.POINTER(c.c_uint32), c.POINTER(c.c_int))(c.byref(count))
            vendor = bind("SDL_GetGamepadVendorForID", c.c_uint16, c.c_uint32)
            product = bind("SDL_GetGamepadProductForID", c.c_uint16, c.c_uint32)
            try:
                devices = [(ids[i], vendor(ids[i]), product(ids[i])) for i in range(count.value)]
            finally:
                bind("SDL_free", None, c.c_void_p)(ids)
            ident, identity = select_device(devices)
            self.pad = bind("SDL_OpenGamepad", c.c_void_p, c.c_uint32)(ident)
            if not self.pad:
                raise RuntimeError("Cannot open Razer input")
            self.identity = {**identity, "backend":"XInput via SDL", "hardware_output":False}
        except Exception:
            self.close()
            raise

    def read(self):
        self.pump()
        if not self.connected(self.pad):
            raise RuntimeError("Razer input disconnected")
        return input_state([self.axis(self.pad, i) for i in range(6)],
                           {i for i in range(15) if self.button(self.pad, i)})

    def close(self):
        if self.pad:
            self.close_pad(self.pad)
            self.pad = None
        self.quit()
