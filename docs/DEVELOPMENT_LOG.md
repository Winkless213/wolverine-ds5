本文是开发过程的实测记录，按时间保留，可能包含未复现或已过时的结论。

下面是开发过程的实测记录（中文，按时间保留）。

---

**Wolverine DS5 · 2026-10-30（1.1.32 候选包：雷云退出改成手动拉起）**

- 版本 1.1.32，以 `dist/candidate-1.1.31` 为基线旁路构建；允许变化模块 `app/core.py`、`app/main.py`、`app/ui_model.py`、`app/__init__.py`，其余桥接字节码与基线一致，`package-check` `passed=true`（`WolverineDS5.exe` `19c85ed4…`，`WolverineDS5-bridge.exe` `5702d83f…`）。
- 交付：`dist/Wolverine-DS5-Setup-1.1.32.exe`（59.5 MB，SHA256 `5c798cb07f9e30998dbaa5710c16639c535fca85952d3301b00ece2483b4a9c1`）、`dist/Wolverine-DS5-1.1.32-patch.zip`（13.3 MB，两个 exe + marker + 两个 QML + 覆盖说明）。
- 真机验证（装好的 1.1.32）：启动时自动拉起雷云一次（14:36:36 开始，14:36:40 `started`，14:36:49 握把就绪）；中途退出雷云 → 14:37:37 `Grips: stopped`，点「启动雷云」→ 14:37:49 `started`、14:38:01 就绪；再退出一次且不点按钮（14:40:01 `Grips: stopped`），之后没有任何新的 `Synapse check started`，`RazerAppEngine` 进程保持 0；再点按钮 → 14:40:57 拉起、14:41:07 就绪。`--self-test` 退出码 0。
- 观察：这两次由按钮触发的检查在日志里和自动拉起无法区分（都是 `Synapse check started`），下次改日志时补 auto/manual 标记。

---

**Wolverine DS5 · 2026-10-30（雷云退出不再反复拉起，改成提示 + 启动按钮）**

- 现状：只要「PC 模式 + 握把没就绪」，`_probe` 每 2 秒就会走 `_ensure_synapse`（节流 60 秒）——用户主动退出雷云后，程序最多一分钟又把它拉起来，反复不停，等于跟用户对着干。
- 改动：自动拉起只做一次（桥接启动时，`synapse_tried` 记账）；中途雷云退出不再自动重试。改由界面提供入口——状态页「雷蛇 Sensa」行在雷云 `stopped`/`offline` 且桥接运行时显示「启动雷云」按钮（`synapseStartable`），托盘菜单同样加一项；点击走 `_ensure_synapse(manual=True)`，仍用 8 秒存活校验。
- 提示：先观察到握把就绪（`grips_were_ready`）之后雷云退出，弹一次托盘气泡「雷云已退出 … 点「启动雷云」恢复」，不拦截、不弹模态框；离线提示改成恢复网络后点按钮重开；状态说明改成「输入正常；点「启动雷云」恢复握把震动」。
- 测试：新增「自动只拉起一次、之后不重试」「按钮只在雷云 stopped/offline 时出现」「中途退出只提示一次且不重启雷云」；`app/test_app.py` + `app/test_core.py` 89 项通过，全仓 414 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。UI 截图：`output/frontend-qa/status-synapse-stopped-v1.png`（980）与 `status-synapse-stopped-wide-v1.png`（1180）。
- 未打包：随下次构建发布。

---

**Wolverine DS5 · 2026-10-30（1.1.31 候选包：停止桥接让回实体手柄 + 雷云启动校验）**

- 版本 1.1.31，以 `dist/candidate-1.1.30` 为基线旁路构建；允许变化模块 `app/core.py`、`app/main.py`、`app/synapse.py`、`app/__init__.py`，其余桥接字节码与基线一致，`package-check` `passed=true`（`WolverineDS5.exe` `492d8446…`，`WolverineDS5-bridge.exe` `8d759bf3…`）。
- 候选包继续写入 `_internal/multiband.enabled`；交付 `dist/Wolverine-DS5-Setup-1.1.31.exe`（59.5 MB，SHA256 `a54240d15bfae13c529ade964c89ac1d4e18484dd84bff96792bb9f70cabe14b`）与 `dist/Wolverine-DS5-1.1.31-patch.zip`（13.3 MB，两个 exe + marker + 覆盖说明）。
- 真机验证（装好的 1.1.31）：启动后雷云被自动拉起并站住（新的 8 秒校验报 `started`）、HidHide 生效、非白名单进程只看得到虚拟 DS5；点「停止桥接」后 `--cloak-off`、隐藏列表 0、非白名单进程改看到 `XInput Controller #1`，`hide_physical` 仍为 true；再点「启动桥接」后 `--cloak-on`、10 个接口重新隐藏、桥接 14:21:19 重新 `connected`。`--self-test` 退出码 0；全仓 412 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。
- 安装注意：雷云运行时覆盖安装会中止（exit 5；RestartManager 报告 `RazerAppEngine`/`RzEngineMon.exe` 占用了要替换的文件），先退出雷云再装；README 已补这条。另清理了调试时留在 HidHide 白名单里的 `python.exe`。

---

**Wolverine DS5 · 2026-10-30（停止桥接时把实体手柄让回去）**

- 现象：点「停止桥接」后游戏里一只手柄都没有。原因不是桥接坏了——停止只停桥接，HidHide 仍隐藏着实体手柄（`hide_physical=True`），虚拟 DS5 又已经卸载；只有「退出程序」才走 `restore_native` 解除隐藏（`native-exit.log` 14:10:45「原生恢复完成」，之后 `HidHideCLI --cloak-state` 已是 off，SDL 能看到 `XInput Controller #1`）。
- 改动：`_apply_mode` 把隐藏当成桥接的附属状态——桥接停（手动暂停、Xbox 模式）时临时解除隐藏，桥接重新起来之前自动重新隐藏；`hide_physical` 偏好在两个方向上都保持不变。`App` 新增 `hiding_active`（实际生效状态）与 `hide_transient`（临时操作标记）；`_hide_done` 对临时操作不写回 `hide_physical`，重新隐藏时只刷新 `hidden_devices`/`hidden_app`。
- 界面：手动停止时状态页说明改成「已手动停止，实体手柄已恢复可见，可在托盘菜单启动」；解除隐藏成功弹一次「实体手柄已恢复」。
- 测试：新增「停止桥接后解除隐藏且偏好保留」「再次启动会重新隐藏并拉起桥接」「没开隐藏偏好时不动 HidHide」「手动停止文案提到实体手柄」；全仓 412 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。
- 未验证：真机上 HidHide 的实际切换要装包后再测（源码运行时用的是真实设置，会改写放行路径，不适合验证）。

---

**Wolverine DS5 · 2026-10-30（更正：雷云「音频转震动」不影响握把）**

- 起因：README 与安装器写着「必须关闭 Chroma 的音频转震动，否则会和桥接的震动叠加」，但用户一直开着它，历次实机测试都没发现问题。
- 取证：`%LOCALAPPDATA%\Razer\RazerAppEngine\User Data\Logs\RzAudioCapture.log` 里 `RegisterHapticDataEvent` 确实把手柄登记为目标（`id: 2636-{…}`，bodyparts 216/116），音源是当时的默认输出端点（Shokz 耳机）；`CA2HDevice::Process sample rate changed … now: 48000` 证明放音时它确实初始化并开始处理。
- 实测：默认输出播放 20 秒 45Hz、0.6 幅度的强低频（1.5Hz 节拍），共两轮——桥接运行时一次，「停止桥接」后一次——用户两次都反馈握把没有震动；两轮期间 HapticService 与 A2H 日志都没有新增处理记录。
- 结论：该开关只登记了目标设备，没有产生握把输出（大概率只对 Sensa HD 类音频设备生效），所以开不开都不影响 PC 模式桥接。README 与安装器改成软提示，不再要求用户改雷云设置。
- 顺带：`app/core.py:audio_to_haptics_active()` 读的是 HapticService 里 `Audio2Haptics` 的音量命令行（只在雷云启动时出现），既证明不了「正在输出」，也没有接到界面上；暂留，等清理死代码时一起处理。

---

**Wolverine DS5 · 2026-10-30（雷云启动改成就绪校验）**

- 现象：`app/synapse.py:ensure_running()` 只要 `os.startfile` 成功就返回 `started`，界面随即弹「已启动雷云」；但引擎可能几秒后自己退出，界面随后变成「雷云未运行，握把不可用」，前后矛盾。本轮排查时 13:31 就遇到一次（启动 6 秒后退出）。
- 改动：拉起后进入 8 秒观察窗口（0.5 秒轮询，连续存活 2 秒才算站住），返回 `running` / `started` / `failed` / `missing`；`app/main.py` 收到 `failed` 时弹「雷云没有启动成功……请从开始菜单手动打开」，不再谎报成功。时钟与等待可注入，测试不真的睡。
- 测试：`app/test_synapse.py` 新增「一直起不来」「起来 1 秒又退出」「稳定存活」三项；`app/test_app.py` 新增失败提示一项。全仓 408 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。
- 背景（本次没改）：排查中 `RazerAppEngine.exe` 从 DSH 的 pwsh 子进程启动时直接退出码 9，`main.log`／`RzEngineMon.log`／WER／CrashDumps 全无痕迹，失败发生在 Electron 初始化之前；同一台机用 Explorer 启动已安装的 1.1.30 时自动拉起雷云正常（13:57:38 `Synapse: started`，12 个进程，13:57:50 `Grips: ready`）。因此判定与启动上下文有关，生产路径不受影响，不再追根因。
- 未打包：按用户要求随下次打包一起发。

---

**Wolverine DS5 · 2026-10-30（1.1.30 候选包：Xbox 模式提示与切回自动连接）**

- 版本 1.1.30，以 `dist/candidate-1.1.29` 为基线旁路构建；允许变化模块 `app/core.py`、`app/main.py`、`app/__init__.py`，其余桥接字节码与基线一致，`package-check` `passed=true`（`WolverineDS5.exe` `ebde5ff7…`，`WolverineDS5-bridge.exe` `ddf27033…`）。
- 候选包继续写入 `_internal/multiband.enabled`，默认「打击」档在实测包里生效；正式包仍不写该标记。
- 交付：`dist/Wolverine-DS5-Setup-1.1.30.exe`（59.5 MB，SHA256 `7e8e72bb1fb51348aa185a4f385037bea7c7cbf79df63eb44cc16e88a1afa009`）；静默安装 → 校验 exe 版本 1.1.30、marker、文档含本次条目、`StatusPage.qml` 含新的按钮隐藏绑定 → `--self-test` 退出码 0 → 静默卸载无残留。`dist/Wolverine-DS5-1.1.30-patch.zip`（13.3 MB，两个 exe + `multiband.enabled` + `ui/StatusPage.qml` + 覆盖说明）。
- 验证：构建脚本默认回归 110 项通过；全仓 405 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。
- 注意：这次只改了托盘程序侧（`app`），桥接逻辑没动；补丁包带上两个 exe 是因为版本号资源两边都写。

---

**Wolverine DS5 · 2026-10-30（Xbox 模式改成提示，拨回 PC 自动连接）**

- 用户要求：手柄在 Xbox 模式时接上托盘程序不要报错，只提醒切到 PC 模式；拨回 PC 模式后不重启程序、不拔插就能连上。
- 现状核对：`_apply_mode` 对 Xbox 模式本来就是故意停桥接（`wanted` 只含 `pc`/`absent`），界面给的是灰色 `stopped` 而不是红色 `error`；切回 PC 由 2 秒轮询 `_probe` 重新拉起 `pc_bridge`，桥接内部 `gip_bridge.reconnect_loop` 每秒重试打开实体手柄，设备一出现就自己连上。
- 改动：
  - `app/core.py`：Xbox／桥接模式的标题从“桥接已停止”改成“请切换到 PC 模式”，说明去掉没有依据的“重新插拔”，改成“拨到 PC 模式后会自动连接”；手动停止仍显示“桥接已停止”。另外区分雷云状态：雷云没运行时显示“雷云未运行，握把不可用”，不再一律“等待握把震动服务”（就是这句让人误以为桥接没连上）。
  - `app/main.py`：每次切到 Xbox 模式弹一次托盘气泡“手柄处于 Xbox 模式”；`_probe` 把模式变化写进 `startup.log`（`Mode: pc -> xbox (实例)`），诊断导出里能直接看到识别时刻；托盘菜单的黄色提示同步改词。
  - `ui/StatusPage.qml`：文案与标题相同时不再显示那个点不了的按钮（Xbox 模式下两者原本是同一句话）。
- 真机验证（源码版、隔离配置目录，13:39 一轮）：13:39:19.2 拨到 Xbox → 13:39:21 识别 `pc -> xbox` 并停桥接；13:39:31.3 拨回 PC、设备重新枚举 → 桥接 0.9 秒报 `connected` → 13:39:35.2 雷云认出手柄转“已连接”。全程没拔线、没重启程序，用户确认两边提示都正常。
- 环境说明：这一轮雷云是程序拉起后 7 秒自己退出（`RazerAppEngine.exe` 退出码 9；本机 13:00 已退出过雷云），手动从开始菜单启动正常。与本次改动无关，但正是它让“等待握把震动服务”被读成“没连上”，所以一并修了文案。
- 测试：`app/test_app.py`、`app/test_core.py` 82 项通过；全仓 405 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题。
- 未做：Xbox 模式下不保持桥接常驻——那会让游戏看到一个没有震动的虚拟 DS5，和实体 Xbox 手柄抢主手柄。代价是 Xbox 模式期间虚拟 DS5 不存在，切回 PC 时是新起一个桥接进程（约 1 秒连上）。

---

**Wolverine DS5 · 2026-10-30（1.1.29 候选包：删除柔和握把后的构建）**

- 版本 1.1.29，以 `dist/candidate-1.1.28` 为基线旁路构建；允许变化模块：`app`、`app.window`、`app.ui_model`、`settings`、`pcm_to_sensa`、`pc_bridge`、`sensa_multiband`、`xbox_multiband`、`xbox_sensa`、`xusb_bridge`、`gip_bridge`，其余桥接字节码与基线一致，`package-check` `passed=true`。
- 候选包继续写入 `_internal/multiband.enabled`，默认「打击」档在多频段实测包里生效；正式包仍不写该标记。
- 交付：`dist/Wolverine-DS5-Setup-1.1.29.exe`（59.5 MB，SHA256 `a99ce3648bc0f2087fccd1548c556d00e27bda100998ea9b176501b4ac2d3ed0`）；静默安装→校验 exe 版本 1.1.29、marker、文档、StatusPage 已无柔和行→静默卸载无残留。`dist/Wolverine-DS5-1.1.29-patch.zip`（13.3 MB，两个 exe + `multiband.enabled` + 两个 QML）。
- 验证：默认回归 107 项通过；全仓 399 通过、13 项失败仍为既有 HAR/`test_run_capture` 环境问题；`--self-test` 退出码 0。

---

**Wolverine DS5 · 2026-10-30（删除柔和握把）**

- 用户决定砍掉柔和握把：它与「打击」档地板的组合尚未验证，且 PC / Xbox 两条输出路径各有一套整形规则，维护成本高于收益。
- 删除：`settings.grip_soft` 与界面开关；PC 路径的频率加权/主频下压（`pcm_to_sensa.envelope_tone` 的 soft 分支）、`sensa_multiband` 的柔和频段衰减、弱低频抬升、稳频/稳幅/斜坡（`FrequencyHold`/`LevelHold`/`SustainSoftener`/`PointRamp`）；Xbox 路径的 soft 分支与 `xusb_bridge.soft`。旧配置里的 `grip_soft` 键会被忽略。
- 验证：全仓 399 项通过，13 项失败仍为既有 HAR/`test_run_capture` 环境问题；删除的 33 项均为柔和握把专用用例。

---

**Wolverine DS5 · 2026-10-30（1.1.28 候选包：默认打击档 + 启用多频段）**

- 版本 1.1.28（`app/__init__.py`），以 `dist/candidate-1.1.27` 为基线旁路构建；允许变化的模块为 `app`、`app.core`、`app.synapse`、`app.ui_model`、`settings`、`pcm_encoder`、`sensa_multiband` 与入口，其余桥接字节码与基线一致，`package-check` `passed=true`。
- 候选包写入 `_internal/multiband.enabled`（`pc_bridge.main` 现有开关），让默认「打击」档在实测包里真正生效；`WolverineDS5.spec` 与安装器仍不写这个标记，正式包维持单频。
- 交付：`dist/Wolverine-DS5-Setup-1.1.28.exe`（59.5 MB，SHA256 `889c533709441a9fb6553e1caa0cdb7b9c5adba4cadf4ce3172790ed97400447`）；本机静默安装→校验 exe 版本 1.1.28、marker、文档与工具目录→静默卸载无残留。`dist/Wolverine-DS5-1.1.28-patch.zip`（13.3 MB，两个 exe + `multiband.enabled`）。
- 验证：构建脚本默认回归 126 项通过；全仓 432 通过，13 项失败仍为既有 HAR/`test_run_capture` 环境问题；候选包 `--self-test` 退出码 0（`qml=True`，capture/SDL3/设备清单齐全）。

---

**Wolverine DS5 · 2026-10-30（打击档实机确认，设为默认档）**

- 用户实机反馈（`work/dist-synapse-offline`，桥接模块与 profile10 逐字节一致，档位“打击”）：“打击档位非常非常不错，现在战斗确实不丢震动了，打击反馈也正常了”。10-29 的窗口 .03/.08 与档位地板 4 由此确认，“断成点”问题关闭。
- 改动：新增 `settings.DEFAULT_PROFILE = "full"`，`Settings` 默认值和非法值回退都用它；`app/ui_model.py`、`sensa_multiband.py` 里各自写死的 `"legacy"` 回退改为引用同一常量，改默认时不再漏一处。已保存的选择不迁移：设置文件里已有 `haptic_profile` 的（包括 `legacy`）保持原样，只有新装或从没存过档位的用户拿到“打击”。
- 测试：默认值相关 3 项改为 `full`，新增“已保存的旧版选择保持不变”；`test_transient_slots_are_dropped_instead_of_killing_the_output`、`test_faint_low_residue_is_lifted_into_a_layer_instead_of_read_as_noise` 原本隐含依赖旧默认档，分别显式固定为 `dynamic` / `legacy`（它们测的是非打击档的行为）。全仓 432 通过；13 项失败为既有环境问题（HAR 校验 12 项、`test_run_capture` 1 项），与本次无关。
- 注意：档位只在多频候选（`multiband.enabled` / `WOLVERINE_MULTIBAND=1`）生效；`WolverineDS5.spec` 与安装器目前都不写这个标记，正式包仍走单频 `SensaGrips`，默认档对它没有影响。
- 待确认：打击档地板 4 与柔和握把的组合——总强度 5–6 的弱低频帧不再进入“抬成稳定一层”的分支，按原样输出（旧版档会抬到 16）；柔和握把默认关闭，这次实机也是关闭，尚无反馈。`xbox_multiband.py` 仍未同步这套窗口与地板。
- 顺带核对：`ui/assets/fonts/RazerF5-*.ttf` 的字体元数据声明为 SIL Open Font License（改自 Titillium）；若按 OFL 随包分发，需要在 `reference-licenses/` 附上 OFL 授权文本，目前还没有。

---

**Wolverine DS5 · 2026-10-30（雷云离线不认手柄：握把就绪改看雷蛇日志）**

- 现象：早上断网时桥接自动拉起雷云（startup.log 10:20:40 `started`），雷云 10:21:04 在 dashboard 日志记 `No internet connection found. App is running in offline mode.`，设备列表为空，界面不提示；HapticService 一直没有 `DeviceAdded`，直到 10:29 手动重启雷云、10:29:41 才登记。
- 我们的误判：10:20:41 桥接已报 `grips_ready: true`。多频带输出只要能打开 HapticService 的共享内存就算就绪，而这个服务开机就在跑，不代表雷云已经把手柄交给它。
- 改动：`app/synapse.diagnose()` 读 HapticService 日志末尾，手柄（`2636-{ContainerId}`）最新一条是 `DeviceAdded` 且其后没有服务重启（`Establishing connection`）或与雷云失联（`RpcPing failed`）才算 `ready`；未登记时按雷云这次启动后的 dashboard 日志区分 `offline` / `unregistered`，雷云不在为 `stopped`，读不到日志为 `unknown`（沿用桥接自己的判断）。托盘每 5 秒在后台检查一次，未就绪时状态写“等待握把震动服务”；离线时写“雷云离线，握把不可用”并弹一次提示，只提示、不碰雷云进程。
- 复核：用本机真实日志截到早上各时刻回放，10:20:50 → `unregistered`、10:25 → `offline`、10:29:39 → `unregistered`、10:29:45 → `ready`，与实际时间线一致。
- 教训：判断外部服务“就绪”要看它对我们这台设备的登记，不能只看服务进程或共享内存在不在；依赖雷蛇日志格式，雷云升级后若检查一直是 `unknown`，先看日志行格式是否变了。

---

**Wolverine DS5 · 2026-10-29（打击档修“断成点”：窗口 .03/.08 + 档位地板 4）**

- 用户反馈“有改善但信息表达依然不准确”，追问后锁定为“断续不对：该连成一片的断成点”。用同一份真实录音按 40ms 帧统计活跃段：`full` 档 1–2 帧的孤立段占 20.6%（段长中位数 10 帧、间隙中位数 8 帧），比旧版 14.1%、动态 8.6% 都碎；`balanced` 19.1% 同样偏碎。
- 扫描窗口 × 弱帧地板共 12 组（`work/probe_continuity_sweep.py`）：只把地板降到 4 时孤立段 15.8%；只把窗口放到 .03/.08 时 12.5%；两者合用 6.1%，独立峰只从 1.13 降到 1.07 次/秒，包络相关 0.74→0.73。地板再降到 2 反而回升到 24.1%（零星噪声帧各自成段），所以停在 4。
- 复核（`work/probe_accuracy.py`）：`full` 存活帧 30.5%→33.8%、撞顶率 3.8%→4.0%（平衡档仍 18.8%）、幅度档位仍用满 32 级、滞后 0→10ms（窗口变长一个采样块）。频带分布不变。
- 改动：`pcm_encoder.game_profile("full")` 两带窗口 .02/.06 → .03/.08；`sensa_multiband.PROFILE_FLOOR = {"full": 4}`，`compose_frame` 按档位取弱帧阈值（其余档仍是全局 6，观感不变）。
- 验证：52 项 `test_sensa_multiband` 通过（短窗断言同步改成 .03/.08，新增 `test_full_profile_keeps_faint_frames_other_profiles_clear`：6 级弱帧在“打击”档保留、平衡档清零）；全仓 414 项通过，13 项 HAR 相关失败是本机 HAR 校验不匹配的既有环境问题。
- 未做：`xbox_multiband.py` 仍是自己的 `MIN_TOTAL = 6/63`，未同步这套窗口与地板。

---

**Wolverine DS5 · 2026-10-29（满配改为“打击”：三带被真实录音否掉）**

- 用户反馈满配在战斗里“傻震动，不是一拳一拳”。用真实游戏触觉录音（`captures/20261025-150823/usb-host-0002.wav`，60 秒）量化：满配原方案输出存活帧 49.2%、响帧 26.9%、独立峰 1.00 次/秒、与源包络相关 0.63——比平衡（1.10/23.3%）更“填满”，打击被抹平。
- 逐项对因：去掉 200–400 Hz 第三条带后峰 1.08、响帧 24.4%；把幅度/频率窗口从 .04/.125 缩到 .02/.06 后峰 1.22、响帧 19.9%；再换旧版那套松压缩（.5/.5/γ3）并抬音量到 1.2/.9，得到峰 1.35、响帧 13.2%、相关 0.72。
- 结论：第三条带和长频率窗会把帧持续填满，是“傻”的来源；打击分离主要靠短窗 + 松压缩。
- 改动：`full` 档改为两带（30–100 音量 1.2、100–200 音量 .9）、窗口 .02/.06、压缩 .5/.5/γ3、阈值 .004，冲击槽仍下发；界面标签由“满配”改为“打击”。移除刚加的 `PROFILE_FLOOR`（地板回到 6，实测地板 3 反而把峰从 1.35 降到 1.23）。
- 验证：65 项测试通过（新增 `test_full_profile_is_two_bands_with_short_windows_for_punch`）。

---

**Wolverine DS5 · 2026-10-29（满配试点档：三条带 + 冲击槽 + 弱帧地板）**

- 目的：单出一档 `full`（界面“满配”）做试点，把 T1 协议里还没用上的东西一次用上；其余五档（旧版/受控/平衡/平衡+/动态）参数不动，同一个包里直接 A/B。
- 三条带：编码器确实接受 3 条带（解码后 `raw_bands=3`），但带音量决定死活——100–200 Hz 给 0.2、200–400 Hz 给 0.05 时，250 Hz/8% 输出为 0；改成 0.6 / 0.3 后 150 Hz/8% → 11.2、250 Hz → 4.5、350 Hz → 3.3。EQ 在 200/400 Hz 只做 .8/.6 的轻度衰减。
- 弱帧地板：200–400 带多数帧只有 5 级左右，被 `MIN_TOTAL=6` 整段清零；满配档单独把地板降到 3（`PROFILE_FLOOR`），实测 250 Hz/8% 0→4.1、350 Hz 0→3.2、150 Hz 9.4。
- 冲击槽：`pack_frame` 以前恒写 0；现在满配档保留编码器给出的槽位（每侧最多 2 个，幅度按补偿缩放），其余档仍丢弃。离线 pack→decode 往返值一致；设备端是否真的渲染冲击槽还没实机确认，本次只验证到帧格式。
- 覆盖（8 频率 × 5 幅度，游戏常见 1–8%）：满配 26/40 有声格子，平衡+ 17、平衡 13、旧版 9、受控 7、动态 7。
- 界面六段按钮（46 宽、间距 5），1180 与 980 两种窗口宽度的真实渲染截图均无溢出。
- 验证：`test_sensa_multiband`、`test_settings`、`app/test_ui_model` 共 65 项通过。

---

**Wolverine DS5 · 2026-10-29（档位切换日志 + 各档信息量实测）**

- 桥接日志新增一行档位记录：启动与每次实际切换各打印 `PCM 档位：<name>`（切换时带 `（从 <old> 切换）`），此后“某档不对”可以直接对时间。
- 覆盖实测（`work/probe_coverage.py`，8 个频率 × 5 个幅度，游戏常见满幅 1–8%，grip_gain 0.8，真 DLL）：40 个格子里“至少有一帧出输出”的数量——平衡+ 17、平衡 13、旧版 9、受控（调音后）7、动态 7。
- 起振幅度（65Hz）：平衡+ 2%、平衡 3%、受控 5%、动态 5%（5% 时仅 10% 帧有声）、旧版 8%。频率上限：旧版 400Hz（但要很响）、动态标称 200Hz（实测 150Hz/8% 仍为 0）、平衡/平衡+ 150Hz、受控 130Hz。
- 结论：用户报告的“动态缺失”不是错觉——它是当前五档里对常见幅度覆盖最差的两个之一；若只想“不缺”，平衡+ 覆盖最广。动态要追平，参数已量好（低频段 0.3→0.8、中频段 0.1→0.2；实测 65Hz 8% 时 4.9→16.1、150Hz 8% 时 0→4.8），待确认后再改。

---

**Wolverine DS5 · 2026-10-29（修复：动态档的冲击槽把整条握把输出打断）**

- 现象：实机日志 20:45:51–20:47:25 共 37 条 `grip_error: PCM 编码帧不符合当前候选 profile`，约每秒一条：输出线程关闭 → 1 秒后重开，期间握把完全没有输出，听感是“断断续续、都变奇怪了”。
- 根因：`compose_frame` 把“带冲击槽的帧”判为非法。雷蛇“动态”档 `transients.volume = 1`，强起音时编码器会写冲击槽；而 `pack_frame` 只有持续频带通道，冲击槽本来就下发不了。其余档位 `transients.volume = 0`，所以只有动态会触发。
- 修复：冲击槽清零后继续合成（不再判非法）；时长不对的帧改为计数跳过，不再让整条输出线程重启。两类情况第一次出现各打一行日志（`transient_slots` / `rejected_frames`）作为可查证据。
- 测试：新增 `test_transient_slots_are_dropped_instead_of_killing_the_output`、`test_frames_with_the_wrong_duration_are_skipped_not_fatal`；`test_sensa_multiband`、`test_settings`、`app/test_ui_model` 共 61 项通过。
- 教训：离线合成信号（单频、点击）没有触发雷蛇的冲击检测，只有真实游戏音频才会；判断“某一档缺失”时应先看桥接日志里的 `grip_error`，再怀疑调音。

---

**Wolverine DS5 · 2026-10-29（修复：平衡+ 点了没反应）**

- 现象：五档界面里“平衡+”点不动。原因：`UiModel.setHapticProfile` 另有一份硬编码档位白名单（四档），新增 `balanced_plus` 后点击被静默丢弃，界面因此没有任何反馈。
- 修复：白名单改为引用 `settings.PROFILES`，不再在界面层重复维护档位列表；新增 `app/test_ui_model.py`，逐档断言点击都会下发设置、未知值被忽略。
- 教训：档位这类枚举在两处各写一份，新增第三/第五项时必然漏一处；界面层只做转发，合法性交给 `Settings.__post_init__` 或单一来源。
- 验证：`app/test_ui_model.py`、`test_settings`、`test_sensa_multiband` 共 59 项通过；候选包重打。

---

**Wolverine DS5 · 2026-10-29（平衡+ 与受控改调：先保信息，再谈轻重）**

- 用户反馈受控“太弱，没特色”。实测（`work/probe_controlled_variants.py`，只读编码器）：受控在游戏常见的满幅 1–8% 触觉下输出恒为 0（65Hz 8% = 0；130Hz 要到 15% 才出 0.9），根因是阈值 0.03 加松压缩（0.5/0.5/γ3），不是桥接链路问题。单独抬高频带音量或降低阈值都几乎无效，换压缩器效果最大。
- 受控改为“轻柔”档：保留 30–130→30–80 窄带与高频衰减；阈值 0.03→0.01、100Hz 以上 EQ 0.3→0.5、压缩器换成 0.25/0.3/γ5。改后 65Hz 5%→4.7、8%→9.3、15%→16.9（平衡同条件 9.9 / 16.4 / 22.8），约为平衡的 55%，仍有事件可感知。
- 新增 `balanced_plus`（界面“平衡+”）：平衡原样，只把检测阈值 0.01→0.004；游戏常见 2% 触觉从“恒 0”变成能出 3.3，3–5% 提高约 20–50%。
- 归属：雷蛇原文保留在 `game_profile()`，调音集中在 `pcm_encoder.TUNING` / `tuned_profile()`，无调音项的档位与原文逐字段一致（有测试守住）。
- 界面档位由四段改五段（按钮 50 宽、字号 11）；真实平台渲染截图 `output/frontend-qa/status-profile-row-5-v1.png` 与 `-min-v1.png` 确认 1180 与 980 宽度下都不溢出。
- 验证：`test_settings`、`test_sensa_multiband` 57 项通过。

---

**Wolverine DS5 · 2026-10-29（动态档电平补偿：弱段被整段清零）**

- 用户 A/B 结果：平衡最合意（有旧版的层次、没有旧版的刺手感）；动态也不错，但“缺失震动”。
- 离线测量（真 DLL，`work/probe_transients.py`，只读编码器）：同一段音频下动态档的频带幅度只有平衡的 38%（65Hz 稳态 48 vs 126），游戏式混合信号合成均值 96 vs 256；动态的弱帧多数落进 `compose_frame` 的 `MIN_TOTAL=6` 地板被整段清零。四档都不产生冲击槽、`compose_rejected=0`，所以不是编码帧被拒或线程崩溃，而是档位本身电平低 + 地板偏硬。
- 改动：`sensa_multiband.PROFILE_GAIN` 给动态档后级 2.0× 补偿（编码器预设仍是雷蛇原文）。补偿后 65Hz 与平衡持平（合成均值 255.8 vs 256），混合信号 96→192；强段仍受 `MAX_AMPLITUDE=32` 限制。
- 验证：53 项测试通过，新增 `test_dynamic_profile_makes_up_its_quieter_low_band`（同时守住 32 级上限）；候选包重打，界面与档位不变。

---

**Wolverine DS5 · 2026-10-29（触觉配置文件三档 + 旧版对照）**

- 从本机 Synapse `RzAudioCapture.log` 的 `CA2HDevice::SetProfile` 抓到雷蛇「音频到触觉」三档预设原文（受控／最佳平衡／动态），写入 [pcm_encoder.py](../pcm_encoder.py) 的 `game_profile(name)`；原双频带 profile 保留为 `legacy` 供 A/B。
- 三档差别：受控 30–130→30–80、阈值 0.03、100Hz 以上 EQ 0.3；最佳平衡 30–150→30–100、阈值 0.01、低频 EQ 2 倍；动态双频带 30–100/100–200、阈值 0.005、瞬态开启、压缩 0.25/0.3/γ5。
- 新增设置 `haptic_profile`（默认 legacy），界面「握把震动」卡片加四段选择；运行中切换由 `PcmEncoder.set_profile()` 重设编码器，`MultibandGrips` 每批比对设置并只下发一次。
- 验证：`test_settings`、`test_sensa_multiband` 52 项通过；全仓 400 通过，13 项离线 HAR 用例因本机 HAR 校验不匹配失败（与本次无关）；真 DLL 上四档均产出 40ms 帧（动态 2 频带，受控/平衡 1 频带）。界面用离屏渲染截图确认布局。
- 注意：该设置只在多频候选（`multiband.enabled` / `WOLVERINE_MULTIBAND=1`）生效；普通 PC 路径仍走单频 `SensaGrips`。

---

**Wolverine DS5 · 2026-10-25（真实游戏：输入修复，握把触觉音频通道未通）**

- 首次在真实游戏（蜘蛛侠 2，非 Steam exe）验证 Xbox 模式。发现并修复 capture 的一个传输层缺陷：usbip-win2 在 Windows 本地完成 SET_CONFIGURATION、不通过 USB/IP 发送该请求，而 VIIPER 服务器要求“配置已选中”才服务端点，导致虚拟 DS5 的所有非零端点请求被 errPipe 拒绝。输入因此完全不可用（HID 枚举正常但零输入报告）。
- 修复：`internal/server/usb/config.go` 增加 `AssumeConfiguredEndpoints`（默认关闭，保持上游语义），capture 启动时开启；`server.go` 的端点活跃判定在开启时跳过配置判据。新增 Go 测试；`internal/server/usb`、`device/dualsense`、`cmd/wolverine-capture` 三包测试通过。重建 capture 后输入恢复（HID 直读约 230–960 Hz，注入状态正确）。
- 发现虚拟 DS5 的输入端点修复后，游戏能识别并操作，但**握把无震动**。日志证据：游戏只发扳机 HID 效果（0x21 阻力曲线、0x26 弱脉冲 1/7 强度 180Hz），`haptic_audio_frames` 始终为 0，输出报文里传统震动字节全为 0。用 4 声道 WAV 直接向虚拟 DS5 的活跃渲染端点播放（pycaw 切换默认设备，测后恢复），capture 仍收 0 帧 → **虚拟 DS5 的音频流端点不可用**，与现代游戏的握把触觉通道无关。
- 待办：音频流端点位于 alt setting 1/2，usbip-win2 同样不发送 SET_INTERFACE，服务器按 alt 0 匹配导致语音端点请求被拒。下一步给 capture 的提交路径加诊断、确认 alt 语义并修复，用 4 声道 WAV 离线验证（无需游戏），再进真实游戏并录制扳机/握把数据。
- 打包：候选 1.1.1（含上述 capture 修复与 1.1.0 多频握把），`tools/build_candidate.py` 新增 `--allow-asset`（显式放行的包内二进制仍要求与仓库文件一致），构建校验通过。

---

**Wolverine DS5 · 2026-10-24（Xbox 握把升级为双频带多频管线）**

- 用户反馈私有 Sensa 的握把仍是旧 Xbox 单频不对称手感；根因是 Xbox 桥接的握把走包络单频，PC 模式的多频管线没接过来。
- 先尝试复用雷蛇 PCM 编码器（本机 DLL 接受 `xbox-sensa-device.json`，能稳定输出 29 字节帧），但其帧格式带内部压缩器状态、同输入相邻两次输出都不同，变长结构无法可靠解码，且该格式从未在私有通道上被硬件验证——放弃直接发送，改为自研分析（[xbox_multiband.py](../xbox_multiband.py)）：4096 点 Hann 滑窗 FFT + 4×补零，每侧输出（5–80Hz 主频、84–400Hz 纹理）两个独立（幅度, 频率）；84Hz 下沿是为避开 60Hz 主瓣泄漏。compose/整形从 `sensa_multiband` 移植：增益、经典震动接管（50Hz）、grip_soft 频段衰减与高频压制、弱低频抬升、总量上限、稳频（FrequencyHold）、稳幅（LevelHold）。
- 关键结构结论（HAR 差分探针，`work/xbox_slot_layout.py`）：Xbox 私有帧每 part 55 位步进，频带块 = present + 2 点 ×（6 位幅度 + 7 位频率）；同 part 挂两个不同频率的效果会落到同一块的两个点，幅度/频率各自独立——双频带体验因此可达。HAR 按效果频率路由，与创建顺序无关。
- 接线：`SensaStream` 内置 `PcmMailbox`（复用 PC 的邮箱），`_render_bands` 在直播音频存在时用多频管线、断流时回退已实机认可的包络单频；`GripHaptics.pcm` 改鸭子类型让 Xbox 流复用同一 accept/step 路径。编码器固定 6 效果槽（每侧 2 频带 + 2 扳机），首轮全建保证帧布局稳定。
- 验证：新增 `test_xbox_multiband`（16 项）与多频流测试；全仓 338 项通过；`work/xbox_multiband_smoke.py` 用真 HAR 走完 3 秒合成音频全链路（左手 60+200Hz 双频带、右手 60Hz、扳机同帧、停止干净）。
- 真机验收（2026-10-24）：`work/xbox_private_e2e.py` 430 帧全部 ACK、无 stall；左手双频带（60Hz 0.254 + 200Hz 0.143）、右手单频对照。用户确认：左右手感“明显不同，比之前好多了”，扳机“没变化”（保持既有体验）。

---

**Wolverine DS5 · 2026-10-14**

把 Razer Wolverine V3 Pro 呈现为虚拟 DualSense。**主路线是 PC 模式**：游戏的 DS5 触觉经雷蛇 Sensa 输出到左右握把，两侧对称，没有扳机震动。**Xbox 模式是备选**：四个马达都可用，含扳机，但左右握把手感不对称。托盘程序按手柄当前模式自动选择桥接。

**PC 模式（主路线）现状**

- 有线和 2.4G 接收器都在《死亡搁浅 2》中实测通过：按键、左右握把震动、拔线后自动恢复。用户确认两侧手感对称。两种连接在系统里同为 `1532:0A4C`，接收器名称带“2.4”；代码不区分，也不需要区分。
- 链路：VIIPER 虚拟 DS5 → 游戏的四声道 USB 音频后两路 → `pcm_to_sensa.EnvelopeToSensa` → `pc_bridge.SensaGrips`。`SensaGrips` 从雷蛇安装目录加载 HAR 与 Provider，不随包分发。
- 映射：先取 10ms 峰值包络 ×1.2，再取 0.75 次方作强度。主频取 5–400Hz 内的峰值，夹到 30–400Hz。游戏的传统震动按 50Hz 输出，与音频触觉两者取大。
- 实测《死亡搁浅 2》的触觉多数只有满幅 2% 左右，p90 约 25%。线性映射几乎摸不到；开平方又太平、整体偏强。0.75 次方经实机确认合适，对应关系：

  | 游戏信号 | 2% | 10% | 25% | 50% | 73%（实测最大） |
  |---|---|---|---|---|---|
  | 握把强度 | ≈6% | ≈19% | ≈37% | ≈62% | ≈82% |

- 雷云要求：
  - Synapse 必须运行，否则状态显示“等待 Sensa”。
  - 关闭 Chroma 的“音频转震动”，否则会和桥接的震动叠加。
  - 雷云的 Sensa 强度与托盘程序的“握把强度”相乘。用户实测：雷云拉到最低时，握把测试完全不震。
  - 灯光由雷云管理，桥接只读取 DS5 输出报告里的震动字节。
- 对游戏隐藏实体手柄：托盘程序“设备与系统”页的开关，经 UAC 调用 HidHide。
  - HidHide 按设备实例隐藏，开启时会登记当前所有 PC 模式实例（包括已拔出的）。
  - 手柄出现在未登记的 USB 口时，页面和托盘会提示重新开关一次。
- 10/14 13:47 实体手柄在 USB 上掉线一次，约 5 秒后自动重新接入，原因未查明。之后游戏没有再接管虚拟 DS5。开启隐藏并重启游戏后，没有再出现。

**PC 模式扳机不可达（10/14 结论）**

- PC 模式的 XInput 接口（xusb22）上，`IOCTL_XUSB_SET_STATE` 只接受 5–6 字节，也就是左右两路强度。7 字节及以上返回错误 87；按 Xbox 模式扳机格式用 WriteFile 发送，同样返回错误 87。
- WGI、GameInput 最终都走同一驱动。SDL 的 `trigger_rumble_reported: True` 是源码写死的标志，不是硬件能力探测。
- 雷蛇震动服务为该手柄只登记了两个马达。Synapse 在 PC 模式下没有任何震动测试，没有可抓包的扳机指令。
- 剩下的路只有绕过系统驱动、自行摸索固件协议，既没有资料也没有先例，不再投入。需要扳机反馈时，切到 Xbox 模式。

**托盘程序**

```powershell
pythonw app\main.py
```

- 依赖：Python 3.14、`numpy`、`PySide6-Essentials 6.12.0`、`PySide6-Fluent-Widgets 1.11.3`，以及已安装的 USBip 0.9.8.1 与 HidHide 1.5.230。
- 页面：
  - 状态页：桥接启停、虚拟 DS5 挂载状态、马达电平。
  - 震动页：握把与扳机的强度和开关，按住 LT／RT 测试对应马达。PC 模式下扳机项不可用。
  - 设备与系统页：驱动模式切换（仅 Xbox 路线）、开机自启、默认音频自动切回、隐藏实体手柄、日志。
- 设置保存在 `%APPDATA%\WolverineDS5\settings.json`，滑块改动通过 stdin 实时送到桥接。日志在 `%LOCALAPPDATA%\WolverineDS5\logs`。
- 托盘“退出”会先卸载本程序的虚拟 DS5，再停止桥接、解除战狼的全部 PC 接口隐藏，并恢复残留的 Xbox WinUSB 绑定；驱动恢复可能要求管理员权限。离线 Xbox 实例会恢复设备类别并核对 Windows 重装标记，下次接入 Xbox 模式时自动装回原厂驱动。恢复失败会保留程序并提示重试，结果记录在日志目录的 `native-exit.log`。强度和隐藏偏好保留，下次打开时自动重新隐藏；雷云配置不变。窗口右上角 × 仍只收进托盘。
- 测试：`python -m pytest -q`，当前 210 项通过。

以下为 Xbox 模式与早期原型的历史记录，保留原文。

---

已接入 Xbox 模式的 XUSB 四马达输出：左右 PCM 幅度驱动握把，DS5 扳机效果结合实体开度驱动 LT／RT。后台四路短震已获用户确认，游戏到手柄的完整桥接尚未完成。`bridge` 模式会发送真实震动；`check`、`pipeline`、`synthetic`、`capture` 保持无非零硬件输出。

用户 10/11 曾选择 Xbox 模式四路路线；10/13 起因左右手感不对称，改以 PC 模式为主，Xbox 模式保留为备选。

**Xbox 四路接入与证据（10/11，现为备选）**

- XUSB 后台台架按左握把、右握把、LT、RT 各 1 秒、间隔 2 秒、幅度 22/100 输出。用户确认“四路都分别震动了”。27 次写入全部完整成功，20 次非零调用均发生在其他应用前台；最终全零写入成功。用户没有单独确认该轮最终物理停止，不能补写为已确认。
- 相同节奏的 WGI 后台台架 API 全成功，用户确认“完全没有震动”。当前后台输出采用 XUSB；不把 WGI 返回值当作实体响应。
- 只读后台输入采集 346 个样本，读到 A、LT、RT；本轮输入测试没有发送非零输出。桥接入口已在同一进程打开真实输入和输出，空载 2 秒后归零退出，收到 0 帧触觉；仍不是输入与游戏触觉同时运行的证明。
- 当前 63 项原型测试、30 项相关台架测试通过。代码审阅复现了接收消息损坏／溢出后仍刷新旧扳机的问题，现已改为立即退出并归零；红／绿记录为 `validation/xusb-reader-stop-red.log`、`validation/xusb-reader-stop-green.log`。
- 本机 USB/IP → DS5 接收器 → 映射 → 记录式 XUSB 输出的 24,000 帧检查通过，左、右、LT、RT、静音分离正确，host 音频与控制丢失均为 0。输入为合成样本时钟、输出为记录器，没有挂载 Windows 虚拟设备或发送实体震动。
- `xusb_bridge.py` 复用左右主频分析的幅度，丢弃频率；扳机复用既有 DS5 效果与开度映射。幅度上限 0.22、最多 50Hz 写入、100ms 续发，50ms 主循环／音频看门狗。音频断流清握把；仍有效的扳机效果保留，主机停止、异常、断开或退出归零。完整游戏链路、长时稳定性与物理延迟尚未验收。

正式入口验证见 `validation/xusb-integration.json`；实体反馈和软件链路分别见项目 `work/rea-evidence/bench-xusb-background-20261011-072100-192862-observation.json`、`xinput-background-input-20261011-072614-760248.json`、`xusb-stream-check-20261011-073107-424090.json`。

**此前 PC/Sensa 检查（历史对照）**

- 39 项原型 Python 测试，以及 VIIPER 接收程序和 DualSense 模块的 Go 测试。项目 `work/` 中另有 24 项硬件入口、限时回放和前台停止回归：不带 `--play` 完全跳过输出初始化；真实 HAR 离线回读覆盖左右更新与效果到期，硬件播放、异常、失焦和超时分支用模拟对象验证。
- 实际本机 USB/IP 连接：按键状态往返、250ms 输入超时归零、原始左右触觉样本保持、扳机报告保持、音频通道重开与退出。
- 在合成样本时钟上分别以 250／1000Hz 更新输入，同时输送 48kHz 四声道 USB 音频。每轮提取 40,320 帧左右 PCM、生成 210 组 Sensa 参数；两轮 PCM 与编码参数逐字节一致，丢失计数为零。250Hz 还核对了两次更新之间的 630 次虚拟输入读取，状态保持正确。
- 48kHz S16LE 双声道录制，明确区分合成信号和 USB 来源；记录缺样、溢出、代次与电平。USB 来源本身不能证明来自游戏。
- DS5 Feedback / Weapon / Vibration 扳机模式的开度映射、单次脉冲、节奏预演。高频振动暂降级为强度，物理效果待验。
- 本机 HAR.dll 连续生成、解码左右独立参数帧；静音、缺样、50ms 断流、重开、非法输入和停止均清零。没有加载 Razer Provider。
- 30、40、60、80、110、160、200、250、320、400Hz 固定音调的稳态频率、幅度及左右隔离检查通过。已修复 30Hz 随相位被误判静音的问题。结果只覆盖列出的合成用例。
- 早前真实手柄只读输入运行 2 秒通过，收到 0 帧游戏触觉。本轮独立台架执行两次 0.25 秒参数效果，用户确认“先左后右，最后完全停止”；这只证明当前连接的左右握把短震与停止。
- 新的 4.8 秒连续 PCM 台架在真实 HAR 和系统时钟下转换 230,400 帧样本、回读 1,200 组左右参数，无跳过参数，停止回读为空。离线结果见项目 `work/rea-evidence/pcm-bench-realtime-offline.json`。随后第二轮实机已完成 1,200 次参数提交与清理，无跳过；用户确认左、右、双侧顺序、连续体感变化和最终完全停止。API 记录为 `work/rea-evidence/bench-sensa-pcm-20261011-040812-801724.json`，反馈在同名 `-observation.json`。信号为确定的合成 PCM，尚非游戏实录。
- PC 接收器已核对为名称带“2.4”的 `1532:0A4C`，用户确认已拔掉手柄 USB 线。250Hz 目标下的 2 秒只读输入完成 457 次读取，host 丢失计数为零；这不是硬件回报率测量。无线短震和相同 4.8 秒 PCM 回放均获用户确认左右顺序、连续变化及完全停止；提交 1,200 组参数，无跳过。记录为 `work/rea-evidence/bench-sensa-pcm-20261011-041631-115362.json` 及同名反馈文件。输入与触觉分别测试，尚非同时运行或长期无线稳定性验证。

结果见 `validation/summary.json`、`api-check.json`、`sensa-api-check.json`、`sensa-stream-check.json` 和 `sensa-mapping-check.json`。对应 Go 源码包已独立解压重编译，合成 PCM 与交付程序一致，见 `validation/source-rebuild.json`。日志中的预期失败用例是回归测试，不是实机故障。

**运行**

在本目录打开 PowerShell：

```powershell
.\Run.ps1 -Mode check
.\Run.ps1 -Mode pipeline
.\Run.ps1 -Mode synthetic -SensaPreview -InputPollHz 250
.\Run.ps1 -Mode synthetic -SensaPreview -InputPollHz 1000
```

`check` 验证软件和本机 API；`pipeline` 覆盖两种逻辑输入节奏、七个连续音频场景和转换误差。两者均无需手柄或驱动。`synthetic` 只有 48 帧，用于入口与退出冒烟，不足一个 192 帧参数更新块；连续转换以 `pipeline` 为准。

显式启用四路输出：

```powershell
.\Run.ps1 -Mode bridge -Seconds 60 -InputPollHz 250
```

仅在 Xbox 模式、唯一目标手柄和已挂载虚拟 DS5 的条件下做游戏试验。`--synthetic` 与 `--xusb-output` 不可组合，避免把突发自测样本当成实时回放。

只读实体输入可使用 `-Mode capture -Seconds 60 -InputPollHz 250` 或 `1000`；加 `-SensaPreview` 会同时保存离线参数。结果保存在 `runs/时间戳/`。未挂载虚拟 USB 设备时不会收到游戏输出，零帧不能算游戏验证成功。

启动脚本优先使用本机已有的 Codex Python；其他机器需要 64 位 Python 3.11+ 和 `requirements.txt` 中的 NumPy 2.3.5（`python -m pip install -r requirements.txt`）。SDL3.dll 已随附。Sensa 离线检查需要已经安装的雷蛇 HAR.dll，并核对本次测试版本的 SHA-256；不随包分发专有雷蛇 DLL。

**250／1000Hz 兼容边界**

| 实体连接模式 | 用户提供的最高回报率 | 软件读取设置 | 实体输出证据 |
|---|---:|---|---|
| Xbox 模式（当前路线） | 250Hz | `-Mode bridge -InputPollHz 250` | XUSB 后台四路短震分别确认；游戏链路未验收，不使用 Sensa |
| PC 模式＋接收器 | 250Hz | `-InputPollHz 250` | 设备识别、只读输入、左右短震、连续参数变化及停止已验证；尚非游戏链路 |
| 有线 PC 模式 | 1000Hz | `-InputPollHz 1000`（默认） | 左右短震、连续参数变化及停止均获用户确认，尚非游戏链路 |

这三种模式的最高回报率是用户提供的条件，本轮没有测量硬件。设置只控制软件读取目标，不切换手柄模式或设置固件回报率；实际次数写入 `run.json` 的 `input_poll_calls`。Windows 调度和转换耗时会影响实际读取间隔，指定 1000 不代表实测达到 1000Hz。晚到时读取最新状态，不补发旧输入。

当前实体输入使用 SDL/XInput。Xbox 模式在 SDL 下显示兼容身份 `045E:02FF`；仅当 SDL 设备和 XUSB 接口均唯一，且实体 USB 父链确认 `1532:0A3F` 时接纳，不按槽位顺序猜设备。原 PC 模式 `1532:0A3F`／`1532:0A4C` 识别保留；此前有线和接收器均显示 `1532:0A4C`，需结合名称、实例路径与连接确认区分。

输入读取的 1／4ms、PCM 的 48,000 帧/秒和参数更新的 4ms 是三个独立时钟。降低输入读取频率不会抽掉音频样本；参数更新也不代表马达频率或发送回报率。`sensa-stream-check.json` 的两档检查采用合成样本时钟，不是实体吞吐量或无线质量测试。

帧头还表示原生缓冲覆盖时长：已核验的 HAR 构建在单目标 4ms 步长下写入 6ms，左右同时生成时写入 60ms。单目标的 1／2／4／8／16ms 步长结果是 2／3／6／12／24ms，双目标均为 60ms，见 `sensa-api-check.json` 的两组检查。日志逐帧保存 `encoded_duration_ms`，汇总保存其计数；该值不是发送周期，也不是实测物理延迟。软件保持 4ms 参数更新，不凭帧头数值改动播放调度。

**文件与下一步**

| 文件 | 用途 |
|---|---|
| `wolverine-capture.exe` | 仅监听 `127.0.0.1:3241` 的虚拟 DS5 接收程序；不自动挂载、不安装驱动 |
| `run_capture.py`、`capture_recorder.py`、`sdl_input.py` | 实体输入转送、左右触觉 WAV 录制、状态与丢失记录 |
| `trigger_mapper.py` | DS5 扳机效果与实体开度转为两个独立震动强度；接入 XUSB 输出 |
| `xusb_output.py`、`xusb_bridge.py` | 实体父链识别、四路短脉冲、限幅、续发、看门狗与退出归零 |
| `pcm_to_sensa.py`、`sensa_preview.py` | 连续左右主频/幅度提取、HAR 回读校验、断流清零及参数日志 |
| `sensa_offline.py`、`sensa_frame.py` | HAR 参数 API 包装与 Sage T1 压缩帧解析；仅支持已验证构建和布局 |
| `api_check.py`、`sensa_api_check.py`、`sensa_stream_check.py`、`sensa_mapping_check.py` | API、连续链路和转换损失检查 |
| `VIIPER-source.zip` | 生成接收程序的完整对应源码，含修改、上游许可证和文件哈希 |

旧 Sensa 转换保留左右目标 216／116，使用 40ms 历史，每 4ms 输出每侧一个 30–400Hz 主频和幅度，幅度上限为 0.22。NumPy 提供 FFT、Hann 窗和最小二乘；次要频率与相位会丢失，宽带和瞬态波形不能据此声称保真。原生帧的幅度 6 位、频率 7 位还会引入量化损失。帧结构虽有每侧 3 个频带，本次测试的多效果叠加方式没有保留三频，不能据此断言所有 HAR 接口都只能单频。

同一连续相位 160Hz 幅度阶跃、只替换幅度估计器的对照中，达到新幅度 10% 范围的样本时钟响应由 28ms 降至 4ms，见 `validation/envelope-comparison.json`。频率估计仍使用 40ms 历史。处理耗时统计只覆盖发帧块转换、HAR 回读及写文件，不含输入等待、历史窗口、USB、Provider 或马达；原生编码帧时长也不能当成实际震动延迟。

本轮左右握把短震与停止已有用户确认，API 记录与反馈分别在项目 `work/rea-evidence/bench-sensa-20261011-040118.json` 及同名 `-observation.json`。第二轮使用项目 `work/sensa_pcm_bench.py` 验证连续体感：左侧 1 秒、右侧 1 秒、双侧反向扫频 1.2 秒，含静音共 4.8 秒；用户确认顺序、连续变化与最终停止。用户最后一下感觉在左侧，尚未进行同频同强度的左右校准。复用本包转换器，幅度上限 0.22；原生效果不循环且有限长，50ms 提交间隔异常会退出并停止。调度稍晚时保留全部 PCM 分析样本，只发送最新参数，并记录跳过数。

独立硬件台架默认只预览计划，实际播放需显式 `--play`。`work/wgi_foreground_bench.py --backend xusb --background --play` 复用已验证的后台四路测试，需点击启动且有限时。WGI 的早前前台结果不能代替后台结果；本轮后台无响应，故不作为桥接输出。旧 Sensa Provider 初始化可能触发提示震动，XUSB 路线不加载该 Provider。

Windows 虚拟 DS5 挂载与卸载已通过。剩余验收是真实游戏触觉信号、输入与四路同时运行、停止／断开及长时稳定性。当前按用户选择改用《死亡搁浅 2：冥滩之上》；独立扳机短震已有确认，游戏效果与物理延迟尚未验收。

USB/IP 0.9.8.1 已按用户授权安装。安装包哈希与官方 release 一致，Windows Authenticode 和启用吊销检查的证书链均通过；补入了当前用户 CA 存储的官方中间证书和有效 CRL，没有添加根证书。已安装的两份内核驱动及其 catalog 均为有效微软签名，`usbip2_ude` 和 `usbip2_filter` 均运行，虚拟主控制器状态 OK。安装器返回 3010，并遵守 `/NORESTART`；用户随后自行重启，重启状态已经核实。系统还原点未能创建；已保存安装前驱动状态和 USB 注册表快照，但它们不能替代系统还原点。官方卸载入口为 `C:\Program Files\USBip\unins000.exe`。

重启前的输入初始化失败保留为历史证据；重启后实体父链 `1532:0A3F`、SDL 兼容身份 `045E:02FF` 已恢复，本次有效 XInput 槽位为 1。实际 list 返回 bus id `1-1`，attach 返回端口 1；Windows 枚举出的 DualSense 音频、HID 和 USB Composite 均正常。40 秒只读运行完成 8,949 次读取、762 次转送、丢失为 0，随后精确卸载本次端口，虚拟设备消失。没有发送实体震动。

每次先启动接收器，再通过 `usbip.exe --tcp-port 3241 list --remote 127.0.0.1` 获取真实 bus id；用 `usbip.exe --tcp-port 3241 attach --remote 127.0.0.1 --bus-id <实际ID> --terse` 挂载。结束时仅执行 `usbip.exe detach --port <本次返回端口>`，不使用 detach-all，也不硬编码上次端口。

《蜘蛛侠 2》的 300 秒只读录制收到了 852,000 帧、17.75 秒累计音频，丢失为 0，但左右 PCM 峰值仅 1/32768，扳机映射峰值为 0，不能认定获得有效游戏触觉。用户反馈游戏进入后仍异常，随后要求改用《死亡搁浅 2》。Sony SDK 未安装、修复或降级；单次报错不能证明系统缺 SDK。《死亡搁浅 2》的 [Steam 官方页](https://store.steampowered.com/app/3280350/)明确支持有线 DualSense 触觉和自适应扳机，本轮只读采集已结束，尚未启用实体输出。

《死亡搁浅 2》的 300 秒试验累计录到 5,418,720 帧、112.89 秒左右音频，PCM 整数峰值为 `[32279, 32279]`，缺帧、接收丢失与 host 丢失均为 0。扳机映射峰值仍为 `[0, 0]`，没有发送实体震动；非零录音本身不证明信号来源或完整游戏链路。游戏同时识别实体 Xbox 和虚拟 DS5，原生 Sce 控制器已连接，保留日志窗口记录主玩家控制器切换 113 次，主要在 0 与 12 间切换；用户看到 Xbox 按键提示。采集结束后仅卸载本次端口，虚拟 DS5 已移除。证据为 `ds2-trial-20261011-122032.json`、`ds2-input-20261011-122032.log`、`20261011-202034-397794-capture-review.json`。

用户已授权安装和配置仅对《死亡搁浅 2》隐藏实体雷蛇的 HidHide，重启由用户安排。官方 HidHide 1.5.230 已安装，退出码 0；安装包哈希与固定版本 winget manifest 一致，安装器、内核驱动、catalog 和 CLI 的签名核验通过。驱动与 Watchdog 正在运行，CLI 仍为 `--cloak-off --inv-off`、隐藏设备数 0；本次安装后尚未重启。重启后保存现有配置，核对 inverse 应用名单语义，再仅对 DS2 配置隔离并限时重测；退出恢复原配置。双输入、有效扳机效果、输入与四路输出同时工作及实体停止仍待验收。安装与状态证据为 `hidhide-installation.json`、`hidhide-installed-state.json`。

安装与重启状态见项目 `work/rea-evidence/usbip-installation.json`、`usbip-installed-state.json`；首次失败保留在 `usbip-windows-mount-20261011-075453.json`，重启后挂载通过为 `usbip-windows-mount-20261011-080210.json`。游戏前一轮录制及复核为 `usbip-windows-mount-20261011-080502.json`、`20261011-160504-408605-capture-review.json`。旧 ZIP 与 manifest 仍是此前快照。

**Wolverine DS5 · 2026-10-24（安装器自动补全依赖）**

- USBip-win2 或 HidHide 缺失时，安装器询问后以管理员身份运行 `tools/install-dependencies.ps1`（一次 UAC）：优先 winget 静默安装（`vadimgrn.usbip-win2`、`Nefarius.HidHide`），失败回退官方安装包并按脚本内固定 SHA256 校验；安装后复检文件与驱动服务，结果写入 `%TEMP%\WolverineDS5-deps-result.txt`，安装器读取后仍缺失的项给出手动下载地址。
- 雷云 Synapse 官方是联网引导安装器、必须登录账号，无法无人值守完成，仍只提示并打开下载页。
- 静默安装（`WizardSilent`）跳过依赖对话框，避免无人值守时卡在 UAC 或弹窗。
- 验证：Windows PowerShell 5.1 下 `-CheckOnly` 检测三项均 present；安装目录内脚本可运行；1.0.2 静默安装、自检、卸载均 exit 0；回退安装包 URL 与硬编码哈希一致。自动安装路径尚未在"依赖真缺失"的机器上实测，winget 提权行为和 HidHide 重启要求待真机确认。

**Wolverine DS5 · 2026-10-24（1.0.3：依赖改为固定版本安装）**

- 复核 1.0.2 的自动安装路径时发现：winget 清单里的 USBip 只有 0.9.7.8，回退安装包也取自同一清单；官方发布说明写明 0.9.7.8 可能内存损坏导致蓝屏，0.9.8.0 修复。本机自 10-12 起运行 0.9.8.0（卸载项 InstallDate 20261012，OSSign 签名，与上游 v.0.9.8.0 同为提交 `83bd1f78`），此后的实测都基于该版本；10-14 依赖清单里写的 0.9.8.1 应为 0.9.8.0。
- 依赖改为直接下载固定版本的官方安装包（USBip 0.9.8.0、HidHide 1.5.230），校验 SHA256 后静默安装，不再调用 winget。两者在 winget 里的下载源本来就是 GitHub，去掉 winget 不影响网络可达性。
- 安装器经 `ShellExec` 拉起的是 32 位 PowerShell（Inno 探针实测 `[IntPtr]::Size` 为 4），`$env:ProgramFiles` 指向 `Program Files (x86)`，原路径检测始终落空、只靠服务检测兜住；改用 `ProgramW6432`。原 winget 调用在 PS 5.1 `Stop` 模式下 `2>&1` 遇到 stderr 会直接抛异常、跳过回退安装，随 winget 一并移除。
- 下载前启用 TLS 1.2 并关闭进度条；自动安装成功后由 `NeedRestart` 在完成页要求重启。UAC 被取消时 `ShellExec` 返回 False 而不抛异常，原 `try/except` 里的提示不会出现，改为按返回值提示。
- 验证：32 位 PowerShell 下的桩测试 14 项通过（路径检测、两个固定安装包真实下载与哈希、安装参数、哈希不符不执行安装、返回值为单一字符串）；脚本 `-CheckOnly` 在 32/64 位下均为 present；非管理员令牌（`runas /trustlevel:0x20000`）运行 `-AutoInstall` 返回 `error=elevation`；1.0.3 静默安装 exit 0、安装目录内脚本与仓库一致、自检 OK、静默卸载干净。依赖真缺失时的交互流程（询问 → UAC → 安装 → 复检 → 完成页重启）仍未在干净机器上实测。

**Wolverine DS5 · 2026-10-24（1.0.4：检测已装 USBip 版本）**

- 安装器与 `tools/install-dependencies.ps1` 读取 `Program Files\USBip\usbip.exe` 的文件版本（上游安装包的版本号即取自该文件），低于 0.9.8.0 视为过旧：向导在依赖对话框里列出当前版本并询问是否自动升级；脚本结果为 `usbip=outdated`，带 `-AutoInstall` 时下载同一固定安装包覆盖安装，复检版本达标才记为 `installed`。读不到版本号时按已安装处理。最低版本在 `WolverineDS5.iss` 的 `UsbipMinVersion` 与脚本的 `$UsbipMinVersion` 各定义一次，需同步修改。
- 覆盖升级靠上游安装包自动卸载旧版：0.9.5.0 起各版 AppId 相同（`{199505b0-…}`），固定的 0.9.8.0 安装包在安装前经 UninsIS 以 `/SILENT /SUPPRESSMSGBOXES /NORESTART` 卸载旧版；0.9.3.x 的 AppId 不同，不在此列。
- UAC 被取消时原提示「右键以管理员身份运行 `tools\install-dependencies.ps1`」走不通：.ps1 右键菜单没有以管理员身份运行，且不带 `-AutoInstall` 只检测不安装。改为提示重新运行安装包，README 同步。
- 验证：32 位 PowerShell 下桩测试 26 项通过（新增：以低版本 PE 文件冒充 `usbip.exe` 时判为过旧、未要求安装时返回 `outdated`、升级后复检达标为 `installed`、升级后版本仍旧为 `failed`、缺失时的全新安装路径不变）；由真实 `[Code]` 生成的 Inno 探针（只替换 MsgBox、ShellExec 和 Program Files 路径）跑 7 种场景，对话框文字、提权参数与完成页重启判断符合预期；Inno 版本比较 0.9.7.8、0.9.7.99 低于 0.9.8.0，0.9.8.1、0.9.10.0、1.0.0.0 不低于；1.0.4 静默安装 exit 0、安装目录内脚本与仓库一致、自检 OK、`-CheckOnly` 为 present、静默卸载干净。真实的 0.9.7.8 → 0.9.8.0 升级未实测：不在本机安装已知有蓝屏问题的版本。
- 托盘程序版本号一直没跟上：`app/__init__.py` 自 1.0.0 起就是 `0.1.0`，关于页因此显示 0.1.0，两个 exe 也没有文件版本。现在版本号只在 `app/__init__.py` 维护，`WolverineDS5.spec` 把它写进两个 exe 的版本资源；安装器编译时用 `GetFileProductVersionString` 核对随包 `WolverineDS5.exe` 与 `AppVersion`，不一致直接 `#error` 中止编译，防止再打出版本对不上的包。
- 版本号改动必须重新构建 onedir 包，不能继续复用 1.0.1 的包。重建用 `tools/build_candidate.py` 以 1.0.1 包为基线逐模块比对字节码：除 `app`（版本号所在模块）外全部一致，接收程序与随包资产哈希不变；该脚本原先按 `<模块>.py` 定位源码，现在支持包目录（`app` → `app/__init__.py`）。
- 验证：两个 exe 的 FileVersion/ProductVersion 均为 1.0.4.0，自检 OK；1.0.4 静默安装、安装后自检、`-CheckOnly`、静默卸载均 exit 0。新包比 1.0.1 多出 `_internal/tools/install-dependencies.ps1`（PyInstaller 把 `tools` 当包收集，内容与仓库副本一致），安装器实际用的是 `{app}\tools` 下那一份，不影响运行。

**Wolverine DS5 · 2026-10-24（1.0.4 后：补全 Xbox 桥接 pyusb/libusb 依赖）**

- 1.0.4 随包桥接缺少 `pyusb`/`libusb_package` 及其 DLL `libusb-1.0.dll`，Xbox 模式启动 `gip_host.UsbTransport` 时会 `ImportError`，被 `supervise` 每 3 秒重启，表现为界面一直"正在连接"。PC 模式不受影响（不实例化 `UsbTransport`）。
- 修复：`requirements.txt` 添加 `pyusb==1.3.1`、`libusb-package==1.0.30.0`；`WolverineDS5.spec` 给桥接 `hiddenimports` 显式加入 `usb`、`usb.core`、`usb.util`、`usb.backend.libusb1`、`libusb_package`，并用 `collect_data_files("libusb_package")` 把 DLL 同时收集到 `libusb_package` 包目录（`libusb_package.get_library_path()` 在打包后从这里找）；托盘 `--self-test` 增加 `libusb_package.get_library_path()` 存在性检查；`tools/build_candidate.py` 的 `compiled()` 对仓库中无源码的第三方模块直接放行，避免加入新依赖后比对失败。
- 验证：候选包 `work/build-104-xusbfix/WolverineDS5` 自检 `libusb_package_dll=True`、整体 `OK`；桥接 exe 内出现 `libusb_package`、`usb.core`、`usb.util`、`usb.backend.libusb1`；`_internal/` 同时有 `libusb-1.0.dll`（hook）和 `libusb_package/libusb-1.0.dll`（供 `get_library_path()`）。`tools/build_candidate.py` 的基线比对仍报 `passed=false`，原因是本机构建环境当前为 `numpy==2.4.3`，而基线 `dist/WolverineDS5` 是 `numpy==2.3.5`，缺失 `numpy._core._machar` 等内部模块，与本次修复无关。

**Wolverine DS5 · 2026-10-24（Xbox 模式支持柔和握把）**

- 原"柔和握把"开关标注"仅 PC 模式"：PC 模式在 [pc_bridge.py](pc_bridge.py) 用 `EnvelopeToSensa` 做包络映射并写 Sensa 帧到两个握把；Xbox 模式在 [xusb_bridge.py](xusb_bridge.py) 用 `PcmToSensa` 做主频映射并写 XUSB 四马达报文，因此不曾读取 `settings.grip_soft`。
- 修复：[xusb_bridge.py](xusb_bridge.py) 增加 `soft` 参数：关时保持 `PcmToSensa`（现有 Xbox 手感），开时切到 `EnvelopeToSensa(soft=True)`（与 PC 模式同一套包络/加权逻辑）；[gip_bridge.py](gip_bridge.py) 在创建 `XusbBridge` 和收到 `settings` 更新时同步 `grip_soft`；[app/window.py](app/window.py) 去掉"仅 PC 模式"文案。
- 说明：Xbox 模式最终输出仍是 XUSB 9 字节报文，每个马达只有强度字节，没有频率信息，因此柔和握把的频率压低部分不会体现在硬件上，只保留高频能量的振幅衰减；对称/非对称差异也来源于此——PC 的 Sensa 帧可以携带左右独立频带，XUSB 只能发四个独立强度。
- 验证：`test_xusb_bridge.py` 新增 `test_soft_mode_uses_envelope_converter_with_soft_flag`、`test_set_soft_switches_converter_at_runtime`；`test_xusb_bridge.py`、`test_gip_bridge.py`、`app/test_app.py` 共 96 项通过。

**Wolverine DS5 · 2026-10-24（Xbox 模式默认改用包络映射）**

- 原 Xbox 模式默认用 `PcmToSensa`（主频映射），左右声道各抓一个主导频率，幅度忽高忽低且常不对称，真机手感明显劣于 PC 模式。
- 现将 [xusb_bridge.py](xusb_bridge.py) 的默认转换器改为 `EnvelopeToSensa`（与 PC 模式同一包络算法），`grip_soft` 只在其上叠加高频加权；扳机马达仍由扳机效果映射独立驱动，不经过该转换器，因此不受影响。
- 验证：`test_xusb_bridge.py`/`test_gip_bridge.py`/`test_pc_bridge.py` 共 83 项通过；线下对比工具显示包络映射左右一致性不低于主频映射、包络相关性相当。真机手感待确认。

**Wolverine DS5 · 2026-10-24（修复 XUSB 马达量程被压死）**

- [xusb_output.py](xusb_output.py) 的 `build_report` 原先把马达字节按 `value*100` 且上限 `.25` 发送，最大只到 25；对照 X1nput 参考实现（`*255`）与 XInput 惯例，马达字节应为 0–255 全量程。旧代码把动态范围压到约 10%，是 Xbox 模式"又弱又没层次"的首要原因。
- 修复：马达字节改为 `round(value*255)`，校验范围放宽到 0..1；新增满量程断言。扳机与握把四通道位置不变。
- 验证：`test_xusb_output.py` 等 100 项通过。真机强度/层次待确认；若全量程过强可再引入用户可调上限。

**Wolverine DS5 · 2026-10-24（Xbox 模式改用私有 Sensa 同帧驱动四个马达）**

- 实机确认 Xbox 模式的私有 16/0E 流能在同一帧里独立驱动 4 个马达并带频率。探测依次只发握把（216/116）、只发扳机（249/149，20/80/180Hz）、左右分开发、四马达同帧：592 帧全部收到 0x10 ack，用户确认每段手感都对、频率可分辨、左右可分辨。记录见 `validation/xbox-private-triggers-20261024.json`。
- 依据是设备元数据的差别：Xbox 模式 `xbox-sensa-device.json` 有 4 个 bodypart（握把 20–300Hz、扳机 0–300Hz 共振 20Hz），PC 模式 `sensa-device.json` 只有 2 个（握把 30–400Hz）。所以「PC 级握把 + 扳机可控」只能在 Xbox 模式成立。
- 代码变更：[xbox_sensa.py](xbox_sensa.py) 的 `set_triggers` 改成收 `(幅度, 频率)` 成对参数并夹到 0–300Hz，`XboxEncoder.frame` 去掉单独的 `trigger_hz`；[xbox_sensa_bridge.py](xbox_sensa_bridge.py) 的 `Triggers` 在私有流在场时把扳机写进同一帧、不再发 GIP 0x0F，双通道互相覆盖的 `refresh` 补偿随之删除，只保留「关掉扳机震动当拍就停」的 `stop_now`；`XboxHaptics.step` 先算扳机再渲染握把，避免扳机落后一个渲染周期（代价是仪表镜像的握把值晚一拍，已在测试里断言下一拍归零）。
- 扳机载波：`TriggerPair(tone=True)` 时不再用幅度门控模拟 20Hz 以下的节奏，改为把 DS5 0x26 效果自带的频率直接交给执行器；20Hz 以上的载波此前被显式降级成持续震动。
- 默认路线：`gip_bridge.select_serve()` 在 `xbox_sensa.available()`（64 位 + HAR.dll 校验和匹配）时默认走私有四马达，`WOLVERINE_XBOX_SENSA=0` 强制回到旧的 GIP 扳机路线；HAR 是专有二进制、不随包分发，缺失的机器自动回退。spec 已补 `xbox_sensa`/`xbox_sensa_bridge` 的延迟导入。
- 排查中确认的两个环境事实：强制换 WinUSB 之后必须拔插一次，否则 `CreateFile` 成功但 `WinUsb_Initialize` 返回 ERROR_INVALID_FUNCTION(1)、pyusb 表现为 claim Access denied；GIP 握手偶发被设备拒绝（auth step 0x05），重开即成功。提权运行、停 Microsoft GameInput、HidHide 都与占用无关（HidHide 当时为 inactive、隐藏名单为空）。
- 验证：319 项单元测试通过（含用真 HAR 的 `NativeEncoderTests`）。真机端到端（游戏 → 虚拟 DS5 → 私有四马达）待跑。

**来源与构建**

- VIIPER 基于 `hbashton/VIIPER@b78e31e93e84b4cb7c4b4c15b8aace10749106d2`，修改位于 `device/dualsense/raw_haptics_capture*`、`device/dualsense/device.go` 和 `cmd/wolverine-capture/`。源码包保留 GPLv3 许可证。解压后在 `VIIPER/` 使用 Go 1.26.2 执行 `go build -o ../wolverine-capture.exe ./cmd/wolverine-capture`。上游另有一个用于扩展 E2E 的 SDL 子模块，源码包记录其固定提交而不内嵌；当前接收程序的构建不依赖该子模块。
- SDL 3.4.18，zlib 许可，见 `reference-licenses/SDL-zlib.txt`。
- 扳机协议参考 MIT 许可的 `WujekFoliarz/duaLib@03bad1bea2a36561b520846776f2a07ced6773e0`，见 `reference-licenses/`。
- XUSB 9 字节报文参考 [X1nput](https://github.com/araghon007/X1nput/tree/96538509155e887260f6caa797971eb680e4eae1)（MIT）；短脉冲时序字段核对 [xpadneo](https://github.com/atar-axis/xpadneo/blob/3879ba0f44e9bcfd500a5b92d02f83885f6b23c7/hid-xpadneo/src/xpadneo/rumble.c)。PadForge 的 XUSB writer 仅用于方案对照，未运行或安装整套应用。
- HAR 包装依据官方 Unity ABI 与本机 DLL 的独立 Ghidra 分析；REA 的 EXE 分析结果见上一级调研报告。本次 DLL 逆向不能计作 REA 成果。
- `sensa-device.json` 来自本机 Sage T1 历史服务元数据，仅用于离线构造，不能当成每次运行时的设备探测。

旧 `manifest.json` 是早期原型打包时的快照，不能用于校验之后的代码。

**Wolverine DS5 · 2026-10-25（QML 界面 1.1.5 候选）**

- 界面从 qfluentwidgets 三页改为 Qt Quick：`ui/main.qml` + 状态/震动/系统三页，Python `app/ui_model.py` 暴露状态、电平、设置，`app/qml_window.py` 管窗口生命周期和托盘；窗口 1180×780、无边框、可拖拽/最大化/最小化/右下缩放，关闭默认收进托盘。
- 视觉按雷云 4 的深灰 + 雷蛇绿：顶部 Tab 胶囊、绿色卡片标题、点阵背景、官方 Wolverine V3 Pro 手柄渲染 + 左右握把标注线；扳机与 Xbox 驱动入口不出现。
- 动效：Tab 胶囊滑动、页面淡入、电平/输出柱缓动、连接点脉冲、滑杆脉冲、Toast；新增 `reduce_motion` 设置（只影响界面动效）。
- 验证：395 项测试 + 34 subtests 通过；`tools/build_candidate.py` 以 1.1.4 为基线构建 `dist/candidate-1.1.5`，package-check `passed=true`；打包 exe `--self-test` 报 `qml=True`、`OK`。
- 未完成：安装包未重打；真实桌面拖拽/托盘/多显示器与长时间电平刷新待实测；官方手柄渲染图发布前需确认素材授权或替换自有素材。

**Wolverine DS5 · 2026-10-25（1.1.6：删掉接管前检测，修字体清晰度）**

- 删除 `_warn_conflicts` 及 HidHide 成功后的“重启 Steam/游戏”提示；不再在隐藏实体手柄后弹“可能和虚拟手柄抢信号”。底层枚举函数保留但不再被界面调用。
- 字号整体上调：正文 11→12/13、卡片标题 14→16、电平/输出数字 20/25→22/27；灰度文字提亮（#8C→#AA、#9A→#B8、#D0→#E4），主文字 #F2；字体改回 Segoe UI，并调用 `QQuickWindow.setTextRenderType(NativeTextRendering)` 使用 Windows 原生字形。
- 验证：395 项测试 + 34 subtests 通过；`dist/candidate-1.1.6` package-check passed；打包 `--self-test` qml=True；175% 缩放下真实窗口截图字重与边缘明显更实。
- 未完成：安装包仍未重打；1.1.6 的桌面拖拽/托盘/多显示器待用户实测。

**Wolverine DS5 · 2026-10-25（1.1.7：黑色显示框与字号/对比度）**

- 卡片从 `#282828` 改为 `#161616`（比页面 `#1F1F1F` 更黑），描边 `#3A3A3A`；按钮/胶囊同步压暗，形成雷云式黑色显示框。
- 正文字号再上调、灰色文字提亮，字体使用 Segoe UI + `NativeTextRendering`；卡片标题 16、正文 12/13、电平/输出数字 22/27。
- 1.1.7 候选 `dist/candidate-1.1.7` package-check passed，打包自检 `qml=True`；真实 175% 缩放下截图确认字重与卡片对比度。
- 事故：构建新候选时误删了仍在运行的 1.1.5 目录，缺失 `base_library.zip` 导致其退出时原生恢复失败并驻留；已从 1.1.6 包补齐缺失文件供其退出，后续不再覆盖运行中的包目录。

**Wolverine DS5 · 2026-10-25（1.1.8：修复退出时 utf-8-sig 缺失）**

- 现象：退出时原生恢复失败，提示 `unknown encoding: utf-8-sig`，程序按设计保留以便重试，表现为无法退出。
- 根因：打包环境未收集 `encodings.utf_8_sig`，而 `core.run_elevated` 用 `Path.write_text(..., encoding="utf-8-sig")` 写 PowerShell 脚本。
- 修复：改成直接写 UTF-8 BOM 字节（`b"\xef\xbb\xbf" + utf-8`），不再依赖该编解码器；spec 同时补 `encodings.utf_8_sig` 兜底。1.1.8 候选 package-check passed、自检 qml=True。

**Wolverine DS5 · 2026-10-25（1.1.13：清理状态页说明文字与绿色悬停）**

- 状态页删除“左右握把的大马达”“调整握把触觉的整体强度”“按雷蛇 profile 压低高频…”三条说明，以及输出卡片底部的两行注释和重复的“100% 增益”角标；设置行改为单行标题 + 右侧控件，测试按钮收进“震动测试”行。
- 四状态条改为 `#191919` 实底、1px 描边，文字 11→13px、标签提亮到 `#E4E4E4`、状态值白色加粗；手柄左侧说明同步改为 13px，并把 Python 状态文案缩短为“PC 模式：震动经 Sensa 输出到左右握把”，避免最小窗口 980px 下尾字换行。
- 移除卡片、Tab、停止桥接、测试、日志按钮的绿色 hover 底色/描边与 140–160ms 颜色动画，以及手柄图的 hover 缩放；可点击元素只保留指针形状。
- 输出柱宽度 44→56、标签 11→12px；关于卡片删除重复的“当前：…”状态行，系统设置说明做轻度压缩。
- 验证：398 项测试 + 34 subtests 通过；`dist/candidate-1.1.13` package-check `passed=true`；打包自检 `qml=True`、`OK`；离屏 QML 渲染 1180×780 与最小 980×760 两档截图，最小宽度下无截断。

**Wolverine DS5 · 2026-10-25（1.1.14：标题栏品牌与系统页减项）**

- 标题栏文案从“WOLVERINE / DS5”改为“Wolverine to DS5”；左侧绿色 W 方块换成用户提供的绿色手柄图形 `ui/assets/brand-gamepad.png`（透明底、4 倍、颜色统一到 `#44D62C`）。
- 系统页删除“减少动画”整行及开关；`reduce_motion` 仍作为内部设置保留（默认关闭），页面过渡继续尊重它，但界面不再暴露。
- 验证：398 项测试 + 34 subtests 通过；`dist/candidate-1.1.14` package-check `passed=true`；打包自检 `qml=True`、`OK`；175% 原生截图确认标题栏图标与文案。

**Wolverine DS5 · 2026-10-25（1.1.15：删除关于卡片，压低电平绿）**

- 删除系统页“关于”卡片（版本与说明），系统页只保留设置卡片，按内容高度顶部对齐。
- 对照 Synapse 4 参考截图采样：品牌主绿仍是 `#44D62C`，与参考一致；大面积“实时输出”电平柱改用暗一档的 `#35A827`，降低整块高亮，Tab/开关/滑杆保持原绿色。
- 验证：398 项测试 + 34 subtests 通过；`dist/candidate-1.1.15` package-check `passed=true`；打包自检 `qml=True`、`OK`；1180×780 与最小 980×760 两档离屏截图确认无截断。

**Wolverine DS5 · 2026-10-25（1.1.16：系统页四行等高铺满）**

- 1.1.15 删除关于卡片后，系统卡片按内容高度顶部对齐会在下方留下大块点阵空白；改为设置卡片填满内容区，四个 SettingRow 等分高度，保持分隔线与控件右对齐。
- 验证：398 项测试 + 34 subtests 通过；`dist/candidate-1.1.16` package-check `passed=true`；打包自检 `qml=True`、`OK`；1180×780 与最小 980×760 两档截图确认无截断。

**Wolverine DS5 · 2026-10-25（1.1.17：应用名称统一）**

- 标题栏文案改为“Wolverine to DS5”，左侧 W 方块换成用户提供的手柄图形；右下状态栏、窗口标题、托盘提示/通知，以及 exe 的 ProductName/FileDescription 同步改为“Wolverine to DS5”。
- 验证：`dist/candidate-1.1.17` package-check `passed=true`；版本元数据 1.1.17。

**Wolverine DS5 · 2026-10-25（1.1.19：左右握把独立强度与点击联动）**

- 设置新增 `grip_gain_left` / `grip_gain_right`（0–150%），旧 `grip_gain` 自动迁移到两侧；PC、Sensa、Xbox 私有流与 GIP 四条路径都按左右分别乘增益。
- 状态页改为“总开关 / 左握把强度 / 右握把强度 / 柔和 / 测试”五行（行高 44）；总开关关闭时两条强度、柔和、测试和手柄标注一起禁用变灰。
- 手柄图左右标注显示实时百分比（如“左握把 100%”），点击选中对应侧；下方对应强度行左侧亮绿色细条、标注加粗并下划线，不弹窗、不滚动。滑杆 0% 即该侧关闭。
- 两页正文改用 RazerF5（从本机 Synapse 4 提取 Regular/SemiBold），白字降到 `#D0D0D0` / `#C8C8C8` / `#E0E0E0`；RazerF5 为专有字体，分发前需确认授权。
- 验证：404 项测试 + 34 subtests 通过；`dist/candidate-1.1.19` package-check `passed=true`；打包自检 `qml=True`、`OK`；1180×780 与最小 980×760 截图，并检查左侧选中 / 总开关关闭两种状态。

**Wolverine DS5 · 2026-10-25（1.1.20：总开关关闭时结束测试）**

- 总开关关闭时如果握把测试仍在运行，主动发送结束测试，避免测试按钮被禁用后无法停止。
- 验证：404 项测试 + 34 subtests 通过；`dist/candidate-1.1.20` package-check `passed=true`；打包自检 `qml=True`、`OK`；实际鼠标点击手柄左右标注可把选中侧从 -1 切到 0/1。

**Wolverine DS5 · 2026-10-25（1.1.21：修正旧增益迁移）**

- 旧 `grip_gain` 只在左右字段缺失时迁移；显式设置 100% 不再被旧单旋钮值覆盖，避免老配置用户无法把两侧调回满强度。
- 验证：405 项测试 + 34 subtests 通过；`dist/candidate-1.1.21` package-check `passed=true`；打包自检 `qml=True`、`OK`。

**Wolverine DS5 · 2026-10-25（1.1.22：字体加大加粗）**

- 正文、状态、按钮改用 Roboto（Regular/Medium/Bold），卡片标题保留 RazerF5 SemiBold；设置标题 14→15px 并加粗、状态条 13→14px、卡片标题 16→17px、输出数字 27→28px、按钮/页脚 +1px，白色文字提亮到 `#D8D8D8` / `#E8E8E8`。
- 状态条高度 38→40px；总开关关闭时滑杆、数值块改灰并隐藏脉冲，避免“关了还像开着”。
- 验证：405 项测试 + 34 subtests 通过；`dist/candidate-1.1.22` package-check `passed=true`；打包自检 `qml=True`、`OK`；1180×780 与 980×760 截图确认无截断。

**Wolverine DS5 · 2026-10-25（1.1.23：中文回退到雅黑）**

- 根因：随包的 Roboto/RazerF5 只有拉丁字形，QML 里 `font.family: "Roboto"` 把中文交给 Qt 的平台回退，Windows 上落到宋体；宋体笔画细、带衬线，之前几轮调大调粗都只作用在拉丁字形上。用 `QTextLayout.glyphRuns()` 取证：`总开关` 解析到 `SimSun/Regular`；默认字体带上回退链后同一段文字解析到 `Microsoft YaHei UI/Bold`。
- 修复：`app/qml_window.py` 新增 `install_ui_fonts()`，注册 Roboto 三个字重并把应用默认字体设成 `Roboto → Microsoft YaHei UI → Microsoft YaHei → Segoe UI`；QML 侧删掉全部 36 处 `font.family`（QML 6.12 的 font 值类型没有 `families` 属性，逐项写 family 会把回退链换成单一字体）。中文文案统一 600 字重（雅黑没有 Medium，500 会退回 Regular）；设置标题 15→16px、说明 13→14px、状态条 14→15px、卡片标题 17→18px、输出数字 28→30px、Tab 15→16px、按钮与 Toast +1px。
- 回归测试：`app/test_app.py` 新增两条——应用默认字体必须带 `Microsoft YaHei UI` 回退；QML 文件不得再出现 `font.family`。
- 验证：407 项测试 + 34 subtests 通过；`dist/candidate-1.1.23` package-check `passed=true`；打包自检 `qml=True`、`OK`；真实 Windows 平台渲染截图确认中文为雅黑粗体而非宋体，1180×780 与最小 980×760 均无截断。

**Wolverine DS5 · 2026-10-25（1.1.24：握把强度改回单一滑块）**

- 用户反馈左右分开调太麻烦，要求回到一个总强度；同时删掉手柄图上的“左握把 / 右握把”百分比标注。
- 界面：状态页“左握把强度 / 右握把强度”两行合并为一行“握把强度”（0–150%），滑杆读写 `gripGainPercent`；`ui_model.setGripGain` 现在同时写 `grip_gain` 与左右两侧，桥接侧仍按左右分路计算，旧配置不缺字段。
- 手柄图：`ControllerHero` 只剩产品图，删除左右标注、引线、定位点与脉冲动画，以及 `selectedGrip` / `gripSelected` 这套点击选中链路；`Placeholder` 去掉左右百分比属性。
- 回归测试：新增 `test_one_grip_slider_drives_both_sides`（总强度写入必须同步两侧）。
- 验证：408 项测试 + 34 subtests 通过；`dist/candidate-1.1.24` package-check `passed=true`；打包自检 `qml=True`、`OK`；1180×780 与最小 980×760 截图确认无截断。

**Wolverine DS5 · 2026-10-25（1.1.25：PC 强度回到单一总增益）**

- 用户实测发现同一份配置下 1.1.4 与 1.1.24 手感不同：1.1.4 的滑杆只写 `grip_gain`，桥接也只读它；1.1.24 的界面显示 `grip_gain`，桥接却读 `grip_gain_left/right`。两侧落后于滑杆时就会出现“界面显示 120、实际按 100 输出”的错位。
- 修复：`pc_bridge.GripHaptics.mix` 改回 1.1.4 语义，左右都取 `settings.grip_gain`；`test_pc_bridge` 的左右独立用例改成“PC 只看总增益、左右字段不影响输出”。
- 柔和握把保持代码默认关闭（`settings.py` 默认 False），用户配置也已改回关闭。
- 验证：408 项测试 + 34 subtests 通过；`dist/candidate-1.1.25` package-check `passed=true`。

**Wolverine DS5 · 2026-10-25（1.1.26：View + 右摇杆模拟触摸板滑动）**

- 用户提出功能缺口：虚拟 DS5 只有触摸板“按下”，没有滑动/触点。方案定为“按住 View + 右摇杆当触点”，保留原来 View 轻点＝触摸板点击。
- 实现：`sdl_input.input_state` 增加触摸合成——View 按住且右摇杆偏出死区（8000/32767≈24%）时，把右摇杆位置线性映射到 DS5 触摸板绝对坐标（中心 960×540，满偏 1919/1079），置 `Touch1Active`、`Touch1Tracking`，并跳过 View 的点击位，避免一次滑动被游戏当成按住点击。摇杆在死区内仍按点击处理。
- 说明：坐标是绝对映射，摇杆居中即触点回到触摸板中心；capture 侧字段（`Touch1X/Y`、`Touch1Active`、`Touch1Tracking`）本来就支持，无需改 Go 端。
- 验证：410 项测试 + 34 subtests 通过（新增 2 项触摸板用例）；`dist/candidate-1.1.26` package-check `passed=true`。

**Wolverine DS5 · 2026-10-26（1.1.27：握把未就绪时的测试按钮提示 + 诊断补全）**

- 测试反馈“软件内测试没震动”。对照诊断文件（`WolverineDS5-diagnostics-*.txt`）发现两个事实：① 应用启动后到雷云被拉起之间 `grips_ready=false`、`grip_error="No Sensa device; Razer Synapse must be running"`，这段窗口里测试按钮无输出；② 同一份日志里 `09:06:39`/`09:22:03` 出现过 `[[0.98,50]]`/`[[1,50]]`，说明就绪后测试确实有输出。
- 修复（体验层，非 bug）：`gripReady` 从桥接状态透传到 `UiModel`，未就绪时“震动测试”按钮变灰并显示“等待雷云…”，下方提示“雷云还没识别到握把，此时测试不会有输出”，鼠标区域禁用。
- 诊断增强：`app/log_export.py` 的导出文件新增 `--- bridge status ---`（含 `state`/`backend`/`grips_ready`/`grip_error`），以后反馈可直接看是否处在等待窗口。
- 验证：410 项测试 + 34 subtests 通过；`dist/candidate-1.1.27` package-check `passed=true`；未就绪态渲染截图 `output/frontend-qa/qml-grip-not-ready.png`。

**Wolverine DS5 · 2026-10-26（测试交付物：安装器、覆盖包、使用说明与恢复单）**

- 安装器脚本 `installer/WolverineDS5.iss` 支持命令行指定版本与源目录（`/DAppVersion=1.1.27 /DAppSrc=..\dist\candidate-1.1.27\WolverineDS5`），`VersionInfoVersion` 由 `AppVersion` 推导；安装时随包附 `docs/TESTER_GUIDE.md`，开始菜单增加“使用说明”。
- 产出 `dist/Wolverine-DS5-Setup-1.1.27.exe`（59.5 MB，SHA256 `ED26206095…`），本机静默安装→校验 exe 版本/文档/工具目录→静默卸载，无残留。
- 免安装覆盖包 `dist/Wolverine-DS5-1.1.27-patch.zip`（13.3 MB）：只含 `WolverineDS5.exe`、`WolverineDS5-bridge.exe` 与两个改动的 QML，用于“不能重装”的测试机。
- `docs/TESTER_GUIDE.md` 增补“刚打开应用握把要等 10–20 秒”与“测试没反应先看什么”。

**Wolverine DS5 · 2026-10-26（测试机事故：360 清理导致 BCD 损坏，非本软件）**

- 测试人员用 360 卸载时，提示“木马”后自动清理；随后重启键鼠全部失效，再重启变成 `0xc0000001` → 按恢复后变 `0xc0000098`（`\BCD` 无效），按 F1 回环。
- 判断：第一次是 360 清掉了启动相关的驱动/未签名文件（`0xc0000001`）；第二次是启动修复找不到有效系统时重写 BCD 被打断，留下无操作系统的引导项（`0xc0000098`）。本软件不安装任何驱动，HidHide/USBip 为第三方且安装器校验哈希；`wolverine-capture.exe` 为无签名 Go 构建，是误报重点。
- 处置文档：新增 `docs/RECOVERY_BCD.md`（U 盘进 WinRE → `bcdboot C:\Windows /s S: /f UEFI` 重建引导；含华硕 F8、VMD/RST 看不到硬盘、EFI 分区损坏等分支），可整篇转给测试人员或维修店。
- 预防：安装说明与测试说明补充“把安装目录和 `wolverine-capture.exe` 加入杀软信任区；测试机不要点 360 的‘一键修复 / 开机加速 / 驱动清理’”。
