# PyInstaller onedir：托盘程序（无控制台）+ 桥接（控制台，由托盘隐藏窗口启动）共用一个 _internal。
# 构建：python -m PyInstaller --noconfirm WolverineDS5.spec  → dist/WolverineDS5/
import os
import re

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

# 版本号只在 app/__init__.py 维护：关于页显示它，两个 exe 的文件属性也取它，安装器编译时核对。
with open(os.path.join(SPECPATH, "app", "__init__.py"), encoding="utf-8") as handle:
    version = re.search(r'__version__ = "(.+)"', handle.read())[1]
numbers = (tuple(int(part) for part in version.split(".")) + (0, 0, 0))[:4]


def version_info(description):
    return VSVersionInfo(ffi=FixedFileInfo(filevers=numbers, prodvers=numbers), kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Winkless213"),
            StringStruct("FileDescription", description),
            StringStruct("FileVersion", version),
            StringStruct("ProductName", "Wolverine DS5"),
            StringStruct("ProductVersion", version),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ])


datas = collect_data_files("qfluentwidgets") + [
    ("wolverine-capture.exe", "."),
    ("SDL3.dll", "."),
    ("xbox-sensa-device.json", "."),
    ("sensa-device.json", "."),
    ("tools/*.ps1", "tools"),
    ("reference-licenses/SDL-zlib.txt", "licenses"),
    ("reference-licenses/*", "licenses"),
]
common = dict(pathex=["."], datas=datas, excludes=[
    "tkinter", "matplotlib", "PySide6.QtWebEngineCore",
    # 本机 NumPy 可选依赖会拉入无关的模型/数据分析包，桥接只使用 NumPy FFT。
    "scipy", "pandas", "torch", "torchvision", "torchaudio", "tensorflow", "onnxruntime", "numba",
    "IPython", "pytest",
])

app = Analysis(["app/main.py"], **common)
bridge = Analysis(["bridge_main.py"], hiddenimports=["pc_bridge", "pycaw.pycaw", "pycaw.constants"], **common)
MERGE((app, "WolverineDS5", "WolverineDS5"), (bridge, "WolverineDS5-bridge", "WolverineDS5-bridge"))

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="WolverineDS5", console=False,
              version=version_info("Wolverine DS5"))
bridge_exe = EXE(PYZ(bridge.pure), bridge.scripts, [], exclude_binaries=True, name="WolverineDS5-bridge",
                 console=True, version=version_info("Wolverine DS5 bridge"))
COLLECT(app_exe, app.binaries, app.datas, bridge_exe, bridge.binaries, bridge.datas, name="WolverineDS5")
