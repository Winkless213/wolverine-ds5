"""虚拟 DS5 的扬声器 / 麦克风抢成 Windows 默认设备后切回原设备。

DS5 扬声器的 3/4 声道就是握把触觉，游戏声音落进默认设备会让手柄一直震；
用户自己选的非 DS5 设备不受影响。
"""
import threading

RENDER, CAPTURE = 0, 1
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications


class AudioGuard:
    def __init__(self, audio):
        self.audio = audio
        self.last_real = {}

    def check(self):
        for flow in (RENDER, CAPTURE):
            for role in ROLES:
                device = self.audio.default(flow, role)
                if device is None:
                    continue
                if not self.audio.is_ds5(device):
                    self.last_real[(flow, role)] = device
                    continue
                replacement = self._replacement(flow, role)
                if replacement:
                    self.audio.set_default(replacement, flow, role)
                    print(f"Default audio {('output', 'input')[flow]} role {role} restored from virtual DS5",
                          flush=True)

    def _replacement(self, flow, role):
        candidates = [device for device in self.audio.devices(flow) if not self.audio.is_ds5(device)]
        previous = self.last_real.get((flow, role))
        if previous in candidates:
            return previous
        return candidates[0] if candidates else None


class WindowsAudio:
    def __init__(self):
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize()
        self.utilities = AudioUtilities
        self.enumerator = AudioUtilities.GetDeviceEnumerator()
        self.names = {}

    def default(self, flow, role):
        try:
            return self.enumerator.GetDefaultAudioEndpoint(flow, role).GetId()
        except OSError:
            return None

    def devices(self, flow):
        collection = self.enumerator.EnumAudioEndpoints(flow, 1)
        return [collection.Item(index).GetId() for index in range(collection.GetCount())]

    def is_ds5(self, device):
        if device not in self.names:
            self.names[device] = self.utilities.CreateDevice(self.enumerator.GetDevice(device)).FriendlyName or ""
        return "DualSense" in self.names[device]

    def set_default(self, device, flow, role):
        from pycaw.constants import ERole
        self.utilities.SetDefaultDevice(device, roles=[ERole(role)])


def start(interval=1.0):
    """后台线程每秒检查一次；音频 API 不可用时只提示，不影响手柄桥接。"""
    def run():
        try:
            guard = AudioGuard(WindowsAudio())
        except Exception as error:
            print(f"Audio guard disabled: {error!r}", flush=True)
            return
        while not stop.wait(interval):
            try:
                guard.check()
            except Exception as error:
                print(f"Audio guard check failed: {error!r}", flush=True)

    stop = threading.Event()
    guard_thread = threading.Thread(target=run, daemon=True)
    guard_thread.start()
    return stop
