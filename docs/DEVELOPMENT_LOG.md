本文是开发过程的实测记录，按时间保留，可能包含未复现或已过时的结论。

下面是开发过程的实测记录（中文，按时间保留）。

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

**来源与构建**

- VIIPER 基于 `hbashton/VIIPER@b78e31e93e84b4cb7c4b4c15b8aace10749106d2`，修改位于 `device/dualsense/raw_haptics_capture*`、`device/dualsense/device.go` 和 `cmd/wolverine-capture/`。源码包保留 GPLv3 许可证。解压后在 `VIIPER/` 使用 Go 1.26.2 执行 `go build -o ../wolverine-capture.exe ./cmd/wolverine-capture`。上游另有一个用于扩展 E2E 的 SDL 子模块，源码包记录其固定提交而不内嵌；当前接收程序的构建不依赖该子模块。
- SDL 3.4.18，zlib 许可，见 `reference-licenses/SDL-zlib.txt`。
- 扳机协议参考 MIT 许可的 `WujekFoliarz/duaLib@03bad1bea2a36561b520846776f2a07ced6773e0`，见 `reference-licenses/`。
- XUSB 9 字节报文参考 [X1nput](https://github.com/araghon007/X1nput/tree/96538509155e887260f6caa797971eb680e4eae1)（MIT）；短脉冲时序字段核对 [xpadneo](https://github.com/atar-axis/xpadneo/blob/3879ba0f44e9bcfd500a5b92d02f83885f6b23c7/hid-xpadneo/src/xpadneo/rumble.c)。PadForge 的 XUSB writer 仅用于方案对照，未运行或安装整套应用。
- HAR 包装依据官方 Unity ABI 与本机 DLL 的独立 Ghidra 分析；REA 的 EXE 分析结果见上一级调研报告。本次 DLL 逆向不能计作 REA 成果。
- `sensa-device.json` 来自本机 Sage T1 历史服务元数据，仅用于离线构造，不能当成每次运行时的设备探测。

旧 `manifest.json` 是早期原型打包时的快照，不能用于校验之后的代码。
