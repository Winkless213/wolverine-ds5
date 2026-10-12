"""列出每个音频输出端点上的会话（哪个进程在往哪个设备出声）和端点峰值。"""
import time

import comtypes
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, IAudioSessionManager2
from pycaw.constants import CLSID_MMDeviceEnumerator
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator

comtypes.CoInitialize()
enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
default = enumerator.GetDefaultAudioEndpoint(0, 1).GetId()
collection = enumerator.EnumAudioEndpoints(0, 1)
for index in range(collection.GetCount()):
    device = collection.Item(index)
    name = AudioUtilities.CreateDevice(device).FriendlyName
    meter = device.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None).QueryInterface(IAudioMeterInformation)
    peak = max(meter.GetPeakValue() for _ in range(20) if not time.sleep(.05))
    print(f"{'*' if device.GetId() == default else ' '} {name}  peak={peak:.3f}")
    manager = device.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
    sessions = manager.GetSessionEnumerator()
    for s in range(sessions.GetCount()):
        control = sessions.GetSession(s)
        from pycaw.pycaw import IAudioSessionControl2
        control2 = control.QueryInterface(IAudioSessionControl2)
        pid = control2.GetProcessId()
        state = control.GetState()
        if pid:
            print(f"    pid={pid} state={['inactive', 'active', 'expired'][state]}")
