# 发布验收清单（1.1.47）

发布前按本清单逐项打勾；任一项失败就回到上一个已验证候选包，不在未知状态上继续叠加。
构建与校验流程见 `tools/build_candidate.py`；安装器编译见本文件末尾。

## 1. 产物身份

| 文件 | SHA256 |
| --- | --- |
| `WolverineDS5.exe` | `1046dfcc699d83fd6d724a822baa1b0dc7a06cd1cccdd4201465f2859f662e05` |
| `WolverineDS5-bridge.exe` | `a90ecd6c51107d0730795d5a5f072b353776c3f35eda8527953f27be019a8e74` |
| `_internal/wolverine-capture.exe` | `998b81e8841fa71f484a88a7b92c591449c6e984beab66e5110425d8e09b5033` |
| `_internal/SDL3.dll` | `2b4b128d8d510cc2d442693cf848c050d700d43dc667afe9e5fd82b0570d667e` |
| `_internal/package-hash.json` | 由构建生成，含 2099 条文件哈希；`package-check.json` 里 `manifest: true` |
| `_internal/tools/uninstall-cleanup.ps1` | 见安装目录同文件（1.1.46 起先 `--quit` 再兜底强杀） |

- 候选包：`dist/candidate-1.1.47`，`package-check.json` 的 `passed` 必须为 `true`
  （`source_unchanged_during_build`、`manifest` 也要为 `true`）。
- 安装包：`work/release/installer/Wolverine-DS5-Setup-1.1.47.exe`
  （59.6 MB，SHA256 `e35ac901d3af243ae7b0290e975fa084e3144278b6915f0e1691806cb57fe326`，未签名）。
- 版本号唯一来源：`app/__init__.py`；`WolverineDS5.spec` 把它写进 exe，安装器编译时用 `GetFileProductVersionString` 校验一致。
- 包内只带三个脚本：`install-dependencies.ps1`、`uninstall-cleanup.ps1`、`swap_winusb.ps1`；
  设备级改类的 `set_class.ps1` 不进用户安装包。`quit-app.ps1` 只给安装器临时解包用，不落盘。

## 2. 固定依赖

| 依赖 | 版本 | SHA256（安装包） |
| --- | --- | --- |
| USBip-win2 | 0.9.8.0 | `81f426741f7ee2ed991febe24a22daca8400b6ae2f171054e3fb404897e15d39` |
| HidHide | 1.5.230 | `f4bbbcb82e6258641b887c74bc81c4c5f66e4aa811808dfc304347687b7605f6` |
| Razer Synapse | 4.x（用户自行登录安装） | 不随包 |

USBip 必须**完整安装**：`usbip2_ude`（虚拟主机控制器）+ `usbip2_filter`（过滤驱动）两个服务都在。
只装一半时本程序仍能工作，但飞智 X-Haptics 等工具会判「USBIP 驱动不符合要求」。
`tools/install-dependencies.ps1` 与安装器都按这个标准验收，缺哪个就重跑官方安装器修复。

## 3. 干净机验收矩阵

在没有任何本程序痕迹的机器上，按顺序执行：

1. 运行安装包 → 出现依赖提示（USBip/HidHide 缺失或驱动不完整时）→ 选“是”，点一次 UAC。
   期望：依赖按固定版本静默安装，提示重启；结果文件 `%TEMP%\WolverineDS5-deps-result.txt` 里
   `usbip` 不是 `failed`/`incomplete`。安装器随后读这份结果复检完整性，仍不完整会给出修复提示。
   说明：与 DSX“手动点安装”的差别是我们能静默装（固定版本 + 哈希校验），用户只需确认一次；
   安装完仍由程序自检把关，不通过不放行。若以后需要严格手动步骤，把安装器这一步改成只打开
   `tools/install-dependencies.ps1` 的交互式运行即可，复检与门禁逻辑不变。
2. 重启后安装器完成页勾“启动程序”。期望：安装目录自检通过（`--self-test` 退出码 0）。
3. 手柄接 PC 模式（有线或 2.4G 接收器）。期望：状态页「已连接」，`已连接 · MM:SS` 计时在走。
4. 雷云未启动时启动程序。期望：3 秒内自动拉起雷云（`startup.log` 出现 `Synapse: started`）；
   若该机器上雷云只能以管理员启动，会先弹一次 UAC 建计划任务，之后不再弹。
5. 状态页「全链路测试」。期望：左握把震 1.5 秒 → 停 0.3 秒 → 右握把震 1.5 秒（`bridge-*.log` 有
   `chain test: 330 frames`）。
6. 开一局有触觉的游戏。期望：握把跟随游戏音频震动，状态页「游戏触觉 已收到」。
7. 状态页→系统→「导出日志」。期望：导出包含自检结果、桥接日志与最近握把帧。
8. 退出程序（托盘→退出）。期望：实体手柄恢复可见，虚拟 DualSense 卸载（设备管理器无残留）。
9. 卸载程序。期望：卸载前自动收尾（放开实体手柄、卸掉虚拟手柄、删除
   `WolverineDS5-RazerSynapse` 计划任务），`%TEMP%\WolverineDS5-uninstall.log` 里 `--uninstall exit=0`，
   卸载后设备管理器无虚拟手柄、任务计划程序里无残留任务。

## 4. 卸载与驱动安全边界（重点）

历史事故：有用户被安全软件误杀组件后，手动删除了 USBIP 驱动，USB 层被破坏到只能重装系统。
所以本程序的卸载必须遵守下面的硬边界，任何改动都不得越过：

**卸载只做三件事**（`WolverineDS5.exe --uninstall`）：

1. `usbip detach` 解除虚拟 DualSense 挂载（只卸端口，不碰驱动）。
2. 解除 HidHide 隐藏并撤销桥接程序的放行，让实体手柄恢复可见。
3. 删除本程序自己创建的计划任务 `WolverineDS5-RazerSynapse`。

**卸载绝不做的事**：

- 不删除、不停用、不重装 `usbip2_ude` / `usbip2_filter` 服务；不删 DriverStore 里的 USBIP 驱动包。
  USBIP 只由官方安装器管理，本程序只在依赖缺失时**重新运行官方安装器**。
- 不对任何非本程序创建的 USB 设备做改类、换驱动、删除设备节点（`set_class.ps1` 已从安装包移除）。
- Xbox 模式的原厂驱动还原只针对 `VID_1532&PID_0A3F` 且必须处于 WinUSB + 系统待重装标记的设备；
  PC 模式手柄（0A4C）永远不进入这条路径。

**可复查证据**：

- `%TEMP%\WolverineDS5-uninstall-result.txt`：`restore_native=`、`delete_task=`、
  `usbip_services_before=`、`usbip_services_after=`、`usbip_untouched=ok|changed`。
- `%TEMP%\WolverineDS5-uninstall.log`：卸载脚本记录卸载前后 USBIP 服务状态，状态变化会写 WARNING。
- 自检项 `usbip`：`usbip2_ude` 缺失时直接 FAIL，并明确写“不要手动删除 USBIP 驱动或服务”
  以及“严重时要重装系统”，修复动作是重跑官方安装器。

**给用户的话术（发布说明必须写）**：

- 遇到杀毒软件报毒/误杀，先把这个程序加入白名单；**不要手动删除 USBIP 驱动或服务**。
- 真要卸载 USBIP，用官方安装包自带的卸载入口，并先确认没有任何虚拟手柄处于挂载状态。

## 5. 已知限制（如实写进发布说明）

- 安装包与本程序**未做代码签名**，SmartScreen 首次运行会提示未知发布者。
- 计划任务方案会让雷云以管理员权限运行：这是绕开雷云自身启动问题的取舍，卸载时会一并删除。
- 飞智 X-Haptics 的 XDS 模式还要求手柄固件支持“映射后 EF 临时模式”，幻影战狼可能不满足；
  与本程序的 USBip 驱动完整性无关。
- 本程序与其它虚拟手柄工具（DSX、飞智空间站等）不要同时运行。

## 5. 回滚点

- 上一个已验证候选：`dist/candidate-1.1.40`（`package-check.json` `passed: true`）。
- 安装器产物保留在 `work/release/installer/`，命名带版本号，回滚时重装旧版本即可；
  卸载会清理计划任务与 HidHide 配置，`%LOCALAPPDATA%\WolverineDS5` 下的日志与设置不删除（人工确认后再删）。

## 6. 本机实测证据（1.1.46 / 1.1.47，2026-11-04）

1.1.47（真机在线、升级、卸载全流程）：

- 真机全绿：手柄 PC 模式、雷云在线时 `--diagnose` 输出 `state=ready`，10 项检查全为 ok/skip。
- 桥接日志 `{"state": "connected", "backend": "sensa", "grips_ready": true}`；输入 999.3–999.6 Hz；
  虚拟 DualSense 挂在 Port 01（Sony 054c:0ce6，High Speed 480Mbps，zero-copy）。
- 全链路测试 `chain test: 330 frames`（左 1.5s + 0.3s + 右 1.5s），用户确认左右握把都震。
- 升级时程序正在运行：对运行中的 1.1.46 覆盖安装，退出码 0、耗时 17.1 秒；
  `native-exit.log` 新增「原生恢复完成」，说明走的是 `--quit` 正路而不是强杀。
- 卸载重测：`uninstall_exit=0`，结果文件
  `restore_native=ok / delete_task=ok / autostart=removed / usbip_untouched=ok / result=ok`；
  `usbip2_ude`、`usbip2_filter`、`HidHide` 服务前后状态一致；进程与安装目录清空；随后装回并重新连上。
- 握把服务登记信息上界面：`13:35 交给握把服务 · Sage T1`（`output/frontend-qa/system-realreport-1180-v1.png`）。
- 音频到触觉：2026-10-30 实测不影响握把（默认输出放 20 秒 45 Hz 强低频，桥接运行与停止两种情况握把输出都为 0）；
  代码里没有任何拦截逻辑，也不需要拦截。

1.1.46（构建、覆盖安装、首启提示）：

- 构建：`--base dist/candidate-1.1.45 --out dist/candidate-1.1.46`，`package-check.json`
  `passed=true / manifest=true / source_unchanged_during_build=true`；回归 184 项通过。
- 自检：候选包 `--self-test` 日志末行 `OK`（含 qml、`wolverine-capture.exe`、`SDL3.dll`、
  `psutil/_psutil_windows.pyd`、`_socket.pyd`、`libusb_package_dll`）。
- 覆盖安装：对 1.1.45 静默覆盖安装到 1.1.46，退出码 0；`_internal\package-hash.json` 出现，
  `docs\` 只剩 `USER_GUIDE.md` 与 `RELEASES.md`（旧的 DEVELOPMENT_LOG / TESTER_GUIDE / RELEASE_CHECKLIST 被清掉）。
- `--quit`：对运行中的 1.1.46 执行，0.8 秒返回 0，三个进程全部退出，
  `%LOCALAPPDATA%\WolverineDS5\logs\native-exit.log` 记录 `原生恢复完成`（说明走了原生恢复，不是强杀）。
- 自检分级：在无手柄状态下 `--diagnose` 输出 `state=blocked / core_ready=false`，
  `checks[].scope` 分别为 core/grips；雷云相关失败落在 grips，不再把按键链路判死。
- 首次自检标记：安装器写到 `{app}\_internal\first-run.pending`（运行时根目录，不是 `{app}`）；
  手动放入该文件后启动程序，标记被消费、进程正常退出，说明"重启后主动汇报"这条链路可用。
- UI 截图（`output/frontend-qa/`，真实 QML 渲染）：
  `status-update-1180-v1.png`、`status-update-min-v1.png`（980×760 最小档）、
  `system-degraded-1180-v1.png`——琥珀色「按键可用，握把未就绪」横幅、底部「发现新版 1.1.47」入口
  在 1180 与 980 两个宽度都不溢出。

## 7. 本机实测证据（1.1.44，2026-11-04 00:27）

- 启动程序：手柄接入即自连，输入 999.6 Hz，握把就绪；`--diagnose` 全绿。
- 全链路测试：`bridge-*.log` 记录 `chain test: 330 frames`（左 1.5s + 0.3s + 右 1.5s），用户确认左右握把都震。
- 卸载收尾（安装目录里的脚本，管理员授权后）：
  `%TEMP%\WolverineDS5-uninstall-result.txt` =
  `restore_native=ok / delete_task=ok / autostart=removed / usbip_untouched=ok / result=ok`。
- 卸载前后 USB 层快照对比（`work/usb_layer_snapshot.ps1`）：
  `usbip2_ude=Running,usbip2_filter=Stopped,HidHide=Running` 前后一致；
  驱动包 `usbip2_ude.inf`、`usbip2_filter.inf` 前后一致；USB 错误设备 0 → 0；
  虚拟手柄端口已卸载；HidHide 隐藏已解除（active False、隐藏设备 0）。
- 重新启动程序：计划任务被自动创建（`WolverineDS5-RazerSynapse`，State=Ready），
  雷云 3 秒内被拉起（`Synapse: started`），桥接重新挂上虚拟 DualSense。
- 自检门禁两个方向都实测：完整安装 `--self-test` 退出码 0（日志 `OK`）；
  临时移走 `_internal\SDL3.dll` 后退出码 3（日志 `FAILED`），恢复后又是 0。
- 启动失败提示实测（1.1.45）：在完整副本里改名 `_internal\psutil\_psutil_windows.pyd` 后启动，
  弹“Wolverine DS5 启动失败”中文提示（含白名单/重装/日志位置），`startup-crash.log` 记录
  `ModuleNotFoundError: No module named 'psutil._psutil_windows'`，不再出现 PyInstaller 原始 traceback。
- UI 截图（`output/frontend-qa/`）：
  - `real-status-desktop-v1.png` —— 运行中程序的真实窗口（1180 逻辑宽 @175%＝2065 设备像素）。
  - `system-realreport-1180-v1.png`、`system-realreport-min-v1.png` —— 用 `--diagnose` 产出的真实自检 JSON
    渲染的系统页（含 980×760 最小档），不是编造的 mock 状态。
  - `status-ready-desktop-v1.png` / `status-blocked-desktop-v1.png` —— 就绪与阻塞两态的布局回归图（mock 数据）。

## 8. 构建命令

```powershell
# 候选包（源码改动必须列进 --allow，否则 package-check 不通过）
python tools/build_candidate.py --base dist/candidate-1.1.46 --out dist/candidate-1.1.47 `
  --allow app/__init__.py app/synapse.py app/readiness.py app/test_synapse.py app/test_readiness.py `
  --marker multiband.enabled

# 安装包（版本号与候选包 exe 版本必须一致）
& "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe" `
  /DAppVersion=1.1.47 /DAppSrc=..\dist\candidate-1.1.47\WolverineDS5 installer\WolverineDS5.iss
```

注意：构建期间不要改仓库里的 `*.py`（`source_unchanged_during_build` 会变 false，得重建）。

## 9. 已知未做（下一轮）

- 代码签名（安装包与 exe 均未签名，SmartScreen 会提示未知发布者）。
- 干净机验收矩阵（第 3 节）仍未在陌生机器上跑过；本机是全套依赖已装好的开发机。
- 单频包下「全链路测试」按钮无输出（正式包必须带 `multiband.enabled`，已在构建命令里固定）。
- 审计提出的中低优先级项：HidHide 反向模式未在自检里区分、`attach_error` 在 connected 状态下的覆盖、
  `--diagnose` 在窗口版 exe 无控制台输出、`gripErrorTitle/Detail` 未被 QML 使用。
