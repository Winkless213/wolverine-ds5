# Wolverine DS5

把雷蛇 Wolverine V3 Pro 手柄呈现为虚拟 PS5 DualSense，让只支持 DualSense 触觉的 PC 游戏把震动送到这只手柄。Windows 托盘程序，个人项目。

## 工作原理

1. Go 接收程序 `wolverine-capture`（基于 [VIIPER](https://github.com/Winkless213/VIIPER/tree/wolverine-capture) 修改，GPL-3.0）在本机回环上通过 USB/IP 挂一只虚拟 DualSense；游戏把触觉作为四声道 USB 音频的后两路发给它。
2. 接收程序把触觉 PCM 和主机输出报告以 JSON Lines 写到 stdout；Python 桥接从 stdin 把实体手柄的输入回送，250ms 没有输入即回中。
3. Python 桥接把 PCM 转成手柄能播的参数：PC 模式（主路线）取 10ms 峰值包络 ×1.2，再取 0.75 次方作强度，经雷蛇 Sensa 驱动左右握把；Xbox 模式（备选）经 XUSB 驱动四个马达，含扳机。
4. PySide6 托盘程序负责启停、强度调节、按手柄模式选择桥接、驱动切换和用 HidHide 对游戏隐藏实体手柄。

## 功能

托盘程序分「状态」「震动」「设备与系统」三页：

- 状态：桥接启停、虚拟 DS5 挂载状态、马达电平。
- 震动：握把与扳机的强度和开关，按住 LT／RT 测试对应马达；PC 模式下扳机项不可用。
- 设备与系统：驱动模式切换（桥接模式／Xbox 模式）、开机自启、默认音频自动切回、隐藏实体手柄、日志。

## 环境要求与安装

- Windows 10/11。
- 已安装 [USBip-win2](https://github.com/vadimgrn/usbip-win2)、[HidHide](https://github.com/nefarius/HidHide) 和雷蛇 Synapse。安装器会检测这三项，缺失时给出下载链接。
- PC 模式从 Synapse 安装目录加载 HAR 与 Provider，本仓库不包含也不分发雷蛇文件。

### 安装包

从 [Releases](../../releases/latest) 下载 `Wolverine-DS5-Setup-1.0.0.exe` 安装，装完即可使用。安装包自带托盘程序、Go 接收程序 `wolverine-capture.exe` 和 `SDL3.dll`，不需要安装 Python。安装器会创建开始菜单和桌面快捷方式，装完自动跑一次隐藏自检并检查外部依赖。

### 从源码运行

依赖：Python 3.11+，`numpy`、`psutil`、`PySide6-Essentials`、`PySide6-Fluent-Widgets`。仓库不含二进制：`wolverine-capture.exe` 需自行编译，`SDL3.dll` 从 [SDL 官方 release](https://github.com/libsdl-org/SDL/releases) 下载，都放在仓库根目录。

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

PC 模式启动时检查雷云，未运行时通过安装器创建的开始菜单快捷方式自动打开；未找到入口会提示安装或手动启动。服务未就绪时显示「等待握把震动服务」，输入保持正常。

开启隐藏后若已运行的 Steam 仍显示 Xbox，请完全退出游戏和 Steam 后重开；HidHide 设置不能替代应用重新枚举设备。

托盘「退出」会先卸载本程序的虚拟 DS5，再停止桥接、解除 Wolverine 的全部 PC 接口隐藏，并恢复残留的 Xbox WinUSB 绑定；驱动恢复可能要求管理员权限。恢复失败会保留程序并提示重试，结果写入日志目录的 `native-exit.log`。强度和隐藏偏好保留，下次打开时自动重新隐藏；雷云配置不变。窗口右上角 × 仍只收进托盘。

## 已知限制

- PC 模式扳机不可达：xusb22 的 `IOCTL_XUSB_SET_STATE` 只接受 5–6 字节，7 字节及以上返回错误 87；需要扳机反馈时切到 Xbox 模式。
- Xbox 模式为备选：四个马达都可用，含扳机，但左右握把手感不对称。
- PC 模式依赖雷云运行；请关闭 Chroma 的「音频转震动」，否则会和桥接的震动叠加。
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
