# PyInstaller onedir：托盘程序（无控制台）+ 桥接（控制台，由托盘隐藏窗口启动）共用一个 _internal。
# 构建：python -m PyInstaller --noconfirm WolverineDS5.spec  → dist/WolverineDS5/
from PyInstaller.utils.hooks import collect_data_files

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

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="WolverineDS5", console=False)
bridge_exe = EXE(PYZ(bridge.pure), bridge.scripts, [], exclude_binaries=True, name="WolverineDS5-bridge",
                 console=True)
COLLECT(app_exe, app.binaries, app.datas, bridge_exe, bridge.binaries, bridge.datas, name="WolverineDS5")
