# 版本清单（幻影战狼 → 虚拟 DualSense）

每个候选包都用 `tools/build_candidate.py` 构建并通过 `package-check.json`（`passed: true`）；
发布包另有安装器产物与哈希，见 `RELEASE_CHECKLIST.md`。

## 1.1.46（当前发布候选，2026-11-04）

这一版修的是「发给别人之后会遇到什么」，不是新功能。

- 覆盖升级先优雅退出：单实例协议新增 `--quit`，安装器装前调用并由 `quit-app.ps1` 核实进程真的退出；
  卸载同样先请实例退出再兜底强杀。以前升级运行中的程序会撞「文件被占用 / 重试 / 忽略」，
  选忽略就得到半新半旧的目录，强杀则跳过原生恢复、留下被隐藏的手柄。
- 需要重启的安装不再立刻启动程序：写 RunOnce 与 `first-run.pending`，重启后自动打开并
  主动汇报第一次自检结果，不再让用户第一眼看到满屏红字。
- 自检拆成「按键链路 / 握把链路」两级：没有雷云、编码器不匹配只把横幅降级成琥珀色
  「按键可用，握把未就绪」，不再把整个程序判成不可用；握把总开关关闭时跳过雷云链路检查。
- 雷云更新导致编码器不匹配不再写「不能继续使用」，改为握把暂停 + 「反馈问题」一键打开
  带版本与自检结果的预填 Issue。
- 启动时最多每天一次检查 GitHub 新版本，状态页显示「发现新版 x.y.z」，点了去发布页；不自动更新。
- 构建产出 `_internal\package-hash.json`（2000+ 文件的 sha256），自检比对 4 个必需文件，
  杀软隔离或文件损坏会被发现。
- 安装包改用面向玩家的 `docs\USER_GUIDE.md`，升级时删除随包发出去的旧开发文档；
  新增 `tools/quit-app.ps1` 供安装器提前收尾。

产物：`WolverineDS5.exe` `c6095664…b35c`，`WolverineDS5-bridge.exe` `0dd3eae0…fc23`，
安装包 `work/release/installer/Wolverine-DS5-Setup-1.1.46.exe` `e36dd9d2…4e3b`（59.6 MB，未签名）。

## 1.1.45（2026-11-04）

- 启动失败不再弹 PyInstaller 的原始 traceback：缺文件（常见于杀毒软件拦截）时弹中文提示，
  说明加白名单/重装/日志位置，并写 `startup-crash.log`，退出码 3。
- 安装后自检增加 `psutil/_psutil_windows.pyd`、`_socket.pyd` 两项，缺一个就判失败、不放行。
- 安装包附带 `RELEASE_CHECKLIST.md` 与 `RELEASES.md`，用户可在 `docs\` 里直接查。

产物：`WolverineDS5.exe` `6e27d831…79f7`，`WolverineDS5-bridge.exe` `98602ab9…e775`，
安装包 `work/release/installer/Wolverine-DS5-Setup-1.1.45.exe`（哈希见 RELEASE_CHECKLIST.md）。

## 1.1.44（2026-11-04）

- 卸载安全边界落地：只做 detach / 解除 HidHide / 删计划任务 / 删开机自启，绝不删 USBIP 驱动、服务或驱动包。
- 卸载脚本修复路径空格导致的提权失败；取消 UAC 会明确告警并退出码 2；exe 损坏时脚本自带 fallback。
- `restore_native` 三步互不阻塞：detach 失败也会解除隐藏。
- 自检默认开启“对游戏隐藏实体手柄”；用户主动关闭只给提醒，不再判故障。
- 自检修正：陈旧的游戏触觉判中断、雷云握把服务已停判故障、握把错误按类型给对应修复按钮。
- 修复动作后 2.5 秒自动重查；卸载时清理开机自启项。
- 安装包只带 `install-dependencies.ps1`、`uninstall-cleanup.ps1`、`swap_winusb.ps1`，设备级改类脚本不再随包。

产物：`WolverineDS5.exe` `439fa6ea…fa6d`，`WolverineDS5-bridge.exe` `b694eec3…51a9`，
安装包 `work/release/installer/Wolverine-DS5-Setup-1.1.44.exe` `8cdb81a0…1596`（59.5 MB，未签名）。

## 1.1.43

- 依赖安装器按“完整安装”验收 USBIP：`usbip2_ude` + `usbip2_filter` 双服务，缺一个就重跑官方安装器。
- 安装器在依赖不完整时给出修复提示；自检对 `usbip2_ude` 缺失直接判故障，并劝阻手动删驱动。
- 卸载收尾接进 Inno `[UninstallRun]`。

## 1.1.42

- 卸载结果写入 `%TEMP%\WolverineDS5-uninstall-result.txt`（窗口版 exe 无控制台，卸载器只认文件）。

## 1.1.41

- 雷云唤醒改为「计划任务优先 → 快捷方式兜底 → 建任务后重试」，任务由程序用一次性 UAC 自动创建。
- 修复 `schtasks` 接管道导致检查线程永久卡死的问题。

## 1.1.40

- 自检的 HidHide 判定改比对手柄子节点（`MI_00` / `IG_*`），不再拿复合设备实例 ID 误报“这个 USB 口还没隐藏”。

## 1.1.39

- 程序可自动拉起雷云（计划任务路径），2 秒内完成且无 UAC。

## 1.1.38 / 1.1.37

- 引入启动自检（`app/readiness.py`）：完整性、手柄、雷云、编码器、桥接、HidHide、USBIP、设置、冲突软件、游戏链路。
- 状态页横幅 + 修复按钮；系统页“自检”卡片；`--diagnose` 无界面诊断。

## 更早

1.1.33–1.1.36：多频握把链路与候选包流程收敛，细节见 `docs/DEVELOPMENT_LOG.md`。
