# Wolverine DS5

把雷蛇 Wolverine V3 Pro 手柄呈现为虚拟 PS5 DualSense，让只支持 DualSense 触觉的 PC 游戏把震动送到这只手柄。Windows 托盘程序，个人项目。

## 工作原理

1. Go 接收程序 `wolverine-capture`（基于 [VIIPER](https://github.com/Winkless213/VIIPER/tree/wolverine-capture) 修改，GPL-3.0）在本机回环上通过 USB/IP 挂一只虚拟 DualSense；游戏把触觉作为四声道 USB 音频的后两路发给它。
2. 接收程序把触觉 PCM 和主机输出报告以 JSON Lines 写到 stdout；Python 桥接从 stdin 把实体手柄的输入回送，250ms 没有输入即回中。
3. Python 桥接把 PCM 转成手柄能播的参数：两种模式都取 10ms 峰值包络 ×1.2、再取 0.75 次方作强度。PC 模式经雷蛇 Sensa 驱动左右握把（该模式只有这两个执行器）；Xbox 模式默认走手柄的私有 Sensa 帧，同帧驱动四个马达（握把 216/116、扳机 249/149，均带频率）：有游戏 PCM 时握把由双频带分析驱动（5–80Hz 主频 + 84–400Hz 纹理，独立幅度/频率），没有 PCM 或本机缺少可用的雷蛇 HAR.dll 时分别回退到包络单频 / XUSB 四路强度。
4. PySide6 托盘程序负责启停、强度调节、按手柄模式选择桥接、驱动切换和用 HidHide 对游戏隐藏实体手柄。

## 功能

托盘程序分「状态」「震动」「设备与系统」三页：

- 状态：桥接启停、虚拟 DS5 挂载状态、马达电平。
- 震动：握把与扳机的强度和开关，按住 LT／RT 测试对应马达；PC 模式下扳机项不可用。
- 设备与系统：驱动模式切换（桥接模式／Xbox 模式）、开机自启、默认音频自动切回、隐藏实体手柄、日志。

## 环境要求与安装

- Windows 10/11。
- 已安装 [USBip-win2](https://github.com/vadimgrn/usbip-win2)、[HidHide](https://github.com/nefarius/HidHide) 和雷蛇 Synapse。安装器会检测这三项：USBip 和 HidHide 缺失时可在安装向导里选择自动安装（需要管理员权限与联网，固定安装官方 USBip 0.9.8.0 与 HidHide 1.5.230，装好后需重启一次）；雷云需要登录账号，安装器只打开下载页。已装的 USBip 低于 0.9.8.0 时，安装器同样提示并可自动升级：官方说明 0.9.7.8 可能内存损坏导致蓝屏。
- PC 模式从 Synapse 安装目录加载 HAR 与 Provider，本仓库不包含也不分发雷蛇文件。

### 安装包

从 [Releases](../../releases/latest) 下载 `Wolverine-DS5-Setup-1.0.4.exe` 安装，装完即可使用。安装包自带托盘程序、Go 接收程序 `wolverine-capture.exe` 和 `SDL3.dll`，不需要安装 Python。安装器会创建开始菜单和桌面快捷方式，装完自动跑一次隐藏自检并检查外部依赖；USBip 或 HidHide 缺失、USBip 版本过旧时可一键自动安装并复检；当时跳过的话，重新运行安装包会再次检测。覆盖安装前请先退出雷云：要替换的文件可能被 Razer App Engine 占用，安装程序会因此中止（退出码 5），退出雷云后重装即可。

### 从源码运行

依赖：Python 3.11+，`numpy`、`psutil`、`cryptography`、`PySide6-Essentials`、`PySide6-Fluent-Widgets`。仓库不含二进制：`wolverine-capture.exe` 需自行编译，`SDL3.dll` 从 [SDL 官方 release](https://github.com/libsdl-org/SDL/releases) 下载，都放在仓库根目录。

编译接收程序（需要 Go 工具链）：从上述 VIIPER 分支获取源码，在源码根目录执行

```powershell
go build -o wolverine-capture.exe ./cmd/wolverine-capture
```

把生成的 `wolverine-capture.exe` 放到本仓库根目录。

## 运行与退出行为

先启动托盘程序（由它拉起桥接），再进入游戏：

```powershell
pythonw app\main.py
```

设置保存在 `%APPDATA%\WolverineDS5\settings.json`，日志在 `%LOCALAPPDATA%\WolverineDS5\logs`；滑块改动通过 stdin 实时送到桥接。

PC 模式启动时检查雷云，未运行时通过安装器创建的开始菜单快捷方式自动打开；未找到入口会提示安装或手动启动。服务未就绪时显示「等待握把震动服务」，输入保持正常。握把是否就绪以雷蛇自己的日志为准（HapticService 登记了手柄才算）；雷云断网启动会进入离线模式、不加载手柄，此时显示「雷云离线，握把不可用」并弹一次提示，恢复网络后重启雷云即可。

开启隐藏后若已运行的 Steam 仍显示 Xbox，请完全退出游戏和 Steam 后重开；HidHide 设置不能替代应用重新枚举设备。

托盘「退出」会先卸载本程序的虚拟 DS5，再停止桥接、解除 Wolverine 的全部 PC 接口隐藏，并恢复残留的 Xbox WinUSB 绑定；驱动恢复可能要求管理员权限。恢复失败会保留程序并提示重试，结果写入日志目录的 `native-exit.log`。强度和隐藏偏好保留，下次打开时自动重新隐藏；雷云配置不变。窗口右上角 × 仍只收进托盘。

## 已知限制

- PC 模式扳机不可达：xusb22 的 `IOCTL_XUSB_SET_STATE` 只接受 5–6 字节，7 字节及以上返回错误 87；PC 模式的 Sensa 设备描述符也只有 2 个 bodypart（左右握把）。需要扳机反馈时切到 Xbox 模式。
- Xbox 模式的私有四马达输出依赖本机 Interhaptics `HAR.dll`（专有，不随包分发）；缺失时回退到 XUSB 四路强度，没有频率，左右握把手感不对称。私有帧每侧 2 点，少于 PC 模式的 3 频带 4 点；双频带分析靠自有 FFT，音色与 PC 模式的雷蛇 profile 不完全相同。
- 切到桥接模式（换 WinUSB）后需要拔插一次 USB：未拔插时 `WinUsb_Initialize` 返回 ERROR_INVALID_FUNCTION，桥接会一直停在 waiting。
- PC 模式依赖雷云运行。雷云的「音频转震动」实测不会传到握把（2026-10-30 实机：默认输出放 20 秒 45Hz 强低频，握把输出为零，桥接运行与停止两种情况都一样），不需要为它改雷云设置；只有真的遇到无端震动时才需要关掉它排查。
- HidHide 按设备实例隐藏；手柄换到未登记的 USB 口时，需要在「设备与系统」页重新开关一次。

## 目录结构

| 路径 | 内容 |
|---|---|
| `app/` | 托盘程序：入口、三页窗口、桥接进程、驱动切换、雷云检查。 |
| `tools/` | `build_candidate.py` 旁路打包与内容身份核对，以及驱动切换脚本。 |
| 根目录脚本 | `pc_bridge.py`、`gip_bridge.py`、`run_capture.py` 及 Sensa／XUSB 转换与检查脚本。 |
| `validation/` | 验证结果 JSON 与 250／1000Hz 流测试目录。 |
| `reference-licenses/` | 上游许可证文本。 |

## 开发与验证

测试：`python -m pytest -q`（`test_api_check.py` 需要已编译的 `wolverine-capture.exe`）。`tools/build_candidate.py` 用于旁路打包并核对包内容身份，不启动托盘、桥接或游戏。

## 许可与声明

本项目以 GNU GPL-3.0 发布，见 [LICENSE](LICENSE)。接收程序基于 VIIPER 修改，沿用上游 GPL-3.0；SDL3 使用 zlib 许可，上游许可证文本见 [reference-licenses/](reference-licenses/)。

雷蛇、Razer、Wolverine、DualSense 等名称归各自所有者。本项目与雷蛇、索尼没有关联。

## 文档

开发过程与硬件实测记录见 [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md)。
