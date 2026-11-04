"""启动自检：把「能不能玩」拆成可复核的检查项。

界面、`--diagnose` 与诊断导出共用同一份结果；所有检查只读，不启动桥接、不改驱动、不碰手柄。
检查项分成两类：环境（装没装、跑没跑、版本对不对）和链路（桥接、握把、游戏触觉），
第一条失败项就是界面横幅要显示的内容。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
from dataclasses import dataclass, field

from app import core, native, synapse
import pcm_encoder

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"

RANK = {OK: 0, SKIP: 0, WARN: 1, FAIL: 2}

# 官方安装包会同时注册这两个服务；只有 usbip2_ude 时本程序能用，但飞智等工具会判驱动不完整。
USBIP_SERVICES = ("usbip2_ude", "usbip2_filter")

# 修复动作 id 与界面按钮文案；App.apply_fix 负责真正执行。
FIX_TEXTS = {
    "recheck": "重新检查",
    "switch_pc": "切到 PC 模式",
    "start_synapse": "启动雷云",
    "open_synapse": "打开雷云下载页",
    "restart_bridge": "重启桥接",
    "enable_hide": "开启隐藏",
    "rehide": "重新隐藏",
    "open_hidhide": "安装 HidHide",
    "open_usbip": "安装 USBip",
    "enable_grip": "开启握把震动",
    "set_gain": "恢复强度",
    "report_issue": "反馈问题",
}

# 桥接的 grip_error 是英文/内部错误，直接显示会让人以为是雷云没识别手柄。
GRIP_ERRORS = (
    ("编码器版本不匹配", "雷云版本不受支持",
     "雷云更新后编码器接口变了，握把暂时不可用，按键照常；更新本程序后恢复"),
    ("No Sensa device", "雷云没有把手柄交给握把服务",
     "先确认雷云正在运行并已登录、手柄在雷云里可见，再点「重新检查」"),
    ("HAR.Init failed", "雷蛇触觉服务启动失败", "重启雷云后重试；仍然失败请导出日志"),
    ("Razer input disconnected", "手柄已断开", "重新插上线或打开手柄，桥接会自动重连"),
    ("Expected one supported Razer device", "没有找到手柄，或同时连接了两只",
     "只保留一只幻影战狼 V3 Pro；同时插线和接收器会让程序无法选择"),
    ("手柄连接已改变", "手柄连接方式变了，正在重建输出", "等 1-2 秒；如果不恢复请重启桥接"),
    ("usbip attach", "虚拟手柄挂载失败", "确认 USBip 驱动已安装并重启过电脑"),
)


def grip_error_text(error):
    """把桥接的 grip_error 翻成（标题，说明）；未识别的错误原样返回。"""
    if not error:
        return "", ""
    for needle, title, detail in GRIP_ERRORS:
        if needle.lower() in error.lower():
            return title, detail
    return "握把输出不可用", error


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    state: str
    detail: str = ""
    fix: str = ""
    evidence: str = ""
    fix_text: str = ""
    # core = 按键/触摸板链路，缺了就没法玩；grips = 握把震动链路，缺了按键照常可用。
    scope: str = "core"

    def with_fix_text(self):
        return self if self.fix_text or not self.fix else _replace(self, fix_text=FIX_TEXTS.get(self.fix, ""))


def _replace(check, **changes):
    data = {name: getattr(check, name)
            for name in ("id", "title", "state", "detail", "fix", "evidence", "fix_text", "scope")}
    data.update(changes)
    return Check(**data)


@dataclass
class Report:
    checks: tuple
    generated_at: float = 0.0

    @property
    def blockers(self):
        return tuple(check for check in self.checks if check.state == FAIL)

    @property
    def core_blockers(self):
        return tuple(check for check in self.blockers if check.scope == "core")

    @property
    def grip_blockers(self):
        return tuple(check for check in self.blockers if check.scope == "grips")

    @property
    def warnings(self):
        return tuple(check for check in self.checks if check.state == WARN)

    @property
    def ready(self):
        return not self.blockers

    @property
    def core_ready(self):
        """按键与触摸板链路可用；握把失败不算在这个口径里。"""
        return not self.core_blockers

    @property
    def state(self):
        if self.core_blockers:
            return "blocked"
        return "degraded" if self.grip_blockers else "ready"

    def first_blocker(self):
        # 核心链路优先：握把坏了也要先把"手柄连没连上"告诉用户。
        for check in self.blockers:
            if check.scope == "core":
                return check
        return self.blockers[0] if self.blockers else None

    def summary(self):
        if self.ready:
            return "系统就绪" if not self.warnings else f"系统就绪（{len(self.warnings)} 项提醒）"
        blocker = self.first_blocker()
        if blocker.scope == "grips":
            return f"按键可用，握把未就绪：{blocker.title}"
        return f"未就绪：{blocker.title}"

    def to_dict(self):
        return {"ready": self.ready, "state": self.state, "core_ready": self.core_ready,
                "summary": self.summary(),
                "checks": [{"id": c.id, "title": c.title, "state": c.state, "detail": c.detail,
                            "fix": c.fix, "fix_text": c.fix_text, "evidence": c.evidence,
                            "scope": c.scope}
                           for c in self.checks]}

    def text(self):
        lines = [f"# {self.summary()}"]
        for c in self.checks:
            lines.append(f"[{c.state.upper():4}] {c.title}" + (f"：{c.detail}" if c.detail else ""))
        return "\n".join(lines)


@dataclass
class Facts:
    root: pathlib.Path | None = None
    mode: str | None = None
    instance: str | None = None
    # HidHide 藏的是 MI_00/IG_* 这些子节点，复合设备的实例 ID 不在隐藏名单里，别拿它比。
    pad_instances: tuple = ()
    bridge_running: bool = False
    bridge_state: dict = field(default_factory=dict)
    settings: object | None = None
    hide_state: dict | None = None
    hide_error: str = ""
    usbip_exe: pathlib.Path | None = None
    usbip_ports: str = ""
    usbip_services: tuple = USBIP_SERVICES
    synapse_installed: bool | None = None
    synapse_running: bool | None = None
    synapse_state: str | None = None
    encoder_path: pathlib.Path | None = None
    encoder_sha: str | None = None
    encoder_expected: str = pcm_encoder.ENCODER_SHA256
    multiband: bool = True
    conflicts: tuple = ()
    stale: tuple = ()
    audio_frames: int = 0
    audio_age: float | None = None
    environment_only: bool = False


def check_integrity(facts):
    if facts.root is None:
        return Check("integrity", "安装文件", SKIP, "源码运行，跳过文件完整性")
    required = ("wolverine-capture.exe", "SDL3.dll", "ui/main.qml", "ui/StatusPage.qml")
    missing = [name for name in required if not (facts.root / name).exists()]
    if missing:
        return Check("integrity", "安装文件不完整", FAIL,
                     "缺少 " + "、".join(missing) + "；可能是杀毒软件隔离或安装被中断，请重新安装",
                     evidence="missing=" + ",".join(missing))
    manifest = facts.root / "package-hash.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return Check("integrity", "安装文件校验失败", WARN, f"清单读不出来：{error}")
        hashes = data.get("files") if isinstance(data, dict) and "files" in data else data
        if not isinstance(hashes, dict):
            return Check("integrity", "安装文件校验失败", WARN, "清单格式不对，跳过校验")
        # 只比对启动必需的几个文件：全量 2000+ 文件哈希会让每 15 秒的自检变得很重。
        bad = [name for name in required
               if (facts.root / name).exists() and name in hashes
               and _digest(facts.root / name) != hashes[name]]
        if bad:
            return Check("integrity", "安装文件被改动或损坏", FAIL,
                         "与包清单不一致：" + "、".join(bad) + "；请重新安装",
                         evidence="mismatch=" + ",".join(bad))
    return Check("integrity", "安装文件完整", OK)


def _digest(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def check_device(facts):
    mode = facts.mode
    if mode in (None, "absent"):
        return Check("device", "没有检测到手柄", FAIL,
                     "用 USB 线或 2.4G 接收器连接手柄，然后点「重新检查」", fix="recheck")
    if mode in ("xbox", "bridge"):
        return Check("device", "手柄在 Xbox 模式", FAIL,
                     "握把震动只支持 PC 模式；切到 PC 模式需要一次管理员权限和拔插一次", fix="switch_pc")
    return Check("device", "手柄已连接", OK, facts.instance or "")


def check_synapse(facts):
    if facts.synapse_installed is False:
        return Check("synapse", "雷云未安装", FAIL,
                     "握把震动由雷云驱动；装好并登录后再点「重新检查」", fix="open_synapse")
    if facts.synapse_running is False:
        return Check("synapse", "雷云未运行", FAIL,
                     "点「启动雷云」；如果自动启动失败，请从开始菜单手动打开", fix="start_synapse")
    state = facts.synapse_state
    if state == "stopped":
        # 进程还在但雷云的握把服务已经掉了：界面上会显示“运行中”，实际握把不工作。
        return Check("synapse", "雷云握把服务已停止", FAIL,
                     "点「启动雷云」重开；仍然不行就退出雷云后重新打开", fix="start_synapse")
    if state == "offline":
        return Check("synapse", "雷云处于离线模式", FAIL,
                     "雷云没联网时不会加载手柄；恢复网络后点「启动雷云」重开", fix="start_synapse")
    if state == "unregistered":
        return Check("synapse", "雷云还没认出手柄", FAIL,
                     "确认手柄在雷云里可见；点「启动雷云」重开雷云后重试", fix="start_synapse")
    if state == "unknown":
        return Check("synapse", "读不到雷云日志", WARN,
                     "无法确认手柄是否已登记；如果握把测试有输出，可以继续")
    return Check("synapse", "雷云已就绪", OK)


def check_encoder(facts):
    if not facts.multiband:
        return Check("encoder", "多频路径未启用", WARN, "当前是源码/旧包运行路径，握把效果与出货包不同")
    if facts.encoder_path is None or not facts.encoder_path.exists():
        return Check("encoder", "雷云编码器缺失", FAIL,
                     "握把震动需要雷云自带的编码器；确认雷云安装完整后重装雷云", fix="open_synapse")
    if facts.encoder_expected and facts.encoder_sha and facts.encoder_sha != facts.encoder_expected:
        # 雷云会自动更新，硬拦等于把可用性绑在别人的发布节奏上；降级成握把不可用 + 一键反馈。
        return Check("encoder", "雷云版本不受支持", FAIL,
                     "雷云更新后编码器接口变了，握把暂时不可用，按键照常。"
                     "点「反馈问题」把版本信息发给作者，更新本程序后恢复",
                     evidence=f"sha256={facts.encoder_sha}", fix="report_issue")
    return Check("encoder", "雷云编码器版本匹配", OK)


def check_bridge(facts):
    if facts.environment_only:
        return Check("bridge", "桥接未在诊断模式启动", SKIP)
    if not facts.bridge_running:
        return Check("bridge", "桥接没有运行", FAIL, "点「重启桥接」；如果反复失败请导出日志", fix="restart_bridge")
    state = facts.bridge_state or {}
    if state.get("state") != "connected":
        return Check("bridge", "桥接没有连上手柄", FAIL,
                     state.get("error") or "等待重连；重新插线或重启桥接", fix="restart_bridge")
    if facts.settings is not None and not getattr(facts.settings, "grip_enabled", True):
        return Check("bridge", "桥接已连接（握把震动已关闭）", OK)
    if state.get("grips_ready") is False:
        title, detail = grip_error_text(state.get("grip_error"))
        error = str(state.get("grip_error") or "")
        # 只有“雷云没起/没登记”这类问题才配「启动雷云」；编码器不匹配、桥接断线重开雷云没用。
        if any(needle in error.lower() for needle in ("encoder", "编码器", "版本")):
            fix = ""
        elif any(needle in error.lower() for needle in ("usbip", "attach", "disconnect", "断开", "重连")):
            fix = "restart_bridge"
        else:
            fix = "start_synapse"
        return Check("bridge", title or "握把服务未就绪", FAIL,
                     detail or "等雷云识别手柄后重试", fix=fix,
                     evidence=error, scope="grips")
    return Check("bridge", "桥接已连接，握把已就绪", OK)


def check_hidhide(facts):
    settings = facts.settings
    wanted = bool(getattr(settings, "hide_physical", False))
    if not wanted:
        # 关掉隐藏是用户的选择，不算故障：只提醒游戏会看到两只手柄。
        return Check("hidhide", "实体手柄未隐藏", WARN,
                     "游戏会同时看到实体手柄和虚拟 DualSense；需要隐藏时打开「对游戏隐藏实体手柄」",
                     fix="enable_hide")
    if facts.hide_error:
        return Check("hidhide", "HidHide 不可用", FAIL,
                     f"{facts.hide_error}；装好 HidHide 后点「重新隐藏」", fix="open_hidhide")
    if facts.hide_state is None:
        return Check("hidhide", "无法读取 HidHide 状态", WARN, "没有安装 HidHide 时无法对游戏隐藏实体手柄")
    if not facts.hide_state.get("active"):
        return Check("hidhide", "实体手柄未隐藏", FAIL, "HidHide 没有生效；点「重新隐藏」", fix="enable_hide")
    devices = {str(item).upper() for item in facts.hide_state.get("devices", ())}
    targets = {str(item).upper() for item in facts.pad_instances}
    if targets and not targets.issubset(devices):
        return Check("hidhide", "这个 USB 口还没隐藏", FAIL,
                     "换过接口后属于新实例，点「重新隐藏」；隐藏后需要重开游戏", fix="rehide")
    apps = {str(item).lower() for item in facts.hide_state.get("apps", ())}
    bridge = core.bridge_command(pc=True)[0].lower()
    if bridge not in apps:
        return Check("hidhide", "桥接程序未被 HidHide 放行", FAIL, "点「重新隐藏」重新登记", fix="rehide")
    return Check("hidhide", "实体手柄已隐藏", OK)


def check_usbip(facts):
    if facts.usbip_exe is None or not facts.usbip_exe.exists():
        return Check("usbip", "USBip 未安装", FAIL,
                     "虚拟手柄依赖 USBip 驱动；安装并重启后点「重新检查」", fix="open_usbip")
    missing = [name for name in USBIP_SERVICES if name not in facts.usbip_services]
    if "usbip2_ude" in missing:
        # 实测事故：安全软件误杀后又手动删 USBIP，USB 层被破坏到只能重装系统。
        # 这条必须拦住并明确劝阻，别让用户自己去“清理驱动”。
        return Check("usbip", "USBip 驱动被删除或不完整", FAIL,
                     "缺少 usbip2_ude，虚拟手柄挂不上。不要手动删除 USBIP 驱动或服务"
                     "（会破坏 USB 层，严重时要重装系统）；点「安装 USBip」重跑官方安装器修复后重启",
                     fix="open_usbip")
    if missing:
        return Check("usbip", "USBip 驱动不完整", WARN,
                     f"缺少 {'、'.join(missing)}；本程序仍能工作，但飞智 X-Haptics 等工具会报驱动不符合要求。"
                     "点「安装 USBip」重新运行官方安装器补全", fix="open_usbip")
    attached = core.usbip_attached(facts.usbip_ports)
    if facts.environment_only:
        return Check("usbip", "USBip 已安装", OK if attached else SKIP,
                     "" if attached else "启动应用后会自动挂载虚拟手柄")
    if not facts.bridge_running:
        return Check("usbip", "虚拟手柄未挂载", WARN, "启动桥接后自动挂载")
    if not attached:
        detail = (facts.bridge_state or {}).get("error") or (facts.bridge_state or {}).get("attach_error") or "usbip attach 没有成功"
        return Check("usbip", "虚拟手柄挂载失败", FAIL, detail, fix="restart_bridge")
    return Check("usbip", "虚拟手柄已挂载", OK)


def check_settings(facts):
    settings = facts.settings
    if settings is None:
        return Check("settings", "设置不可读", WARN, "无法确认握把开关与强度")
    if not getattr(settings, "grip_enabled", True):
        return Check("settings", "握把震动已关闭", FAIL, "打开「握把震动」总开关后重试", fix="enable_grip")
    gain = getattr(settings, "grip_gain", 1.0)
    if not gain:
        return Check("settings", "握把强度为 0", FAIL, "把握把强度调到 100% 后重试", fix="set_gain")
    return Check("settings", "握把开关与强度正常", OK)


def check_conflicts(facts):
    if facts.conflicts:
        return Check("conflicts", "检测到会抢手柄的软件", WARN,
                     "、".join(facts.conflicts) + " 也会挂虚拟手柄；关闭它们后再进游戏")
    return Check("conflicts", "没有冲突软件", OK)


def check_game(facts):
    if facts.environment_only or not facts.bridge_running:
        return Check("game", "游戏链路尚未开始", SKIP)
    names = "、".join(item.get("name", "?") for item in facts.stale[:4])
    if facts.audio_frames <= 0:
        if names:
            return Check("game", "游戏可能在应用之前启动", WARN,
                         f"{names} 比虚拟手柄先启动；如果里面有游戏，请退出游戏重新进入")
        return Check("game", "还没收到游戏触觉", WARN,
                     "如果游戏正在震动场景，说明游戏没把触觉发给虚拟手柄：检查游戏内震动开关、"
                     "Steam Input 是否接管、以及游戏是否支持 DualSense 触觉")
    age = "刚刚" if facts.audio_age is None else f"{facts.audio_age:.0f} 秒前"
    if facts.audio_age is not None and facts.audio_age > 30:
        return Check("game", "游戏触觉中断了", WARN,
                     f"最近一次收到触觉是 {age}，累计 {facts.audio_frames} 帧；"
                     "如果游戏正在震动却没有输出，检查游戏是否切走了默认音频设备")
    return Check("game", "游戏触觉已收到", OK, f"最近一次收到触觉：{age}，累计 {facts.audio_frames} 帧")


# 这些检查只影响握把震动；按键与触摸板不依赖它们，失败时不该把整个程序判成不可用。
GRIP_CHECKS = {"synapse", "encoder", "settings", "game"}


def build_report(facts):
    checks = [check_integrity(facts), check_device(facts), check_bridge(facts), check_hidhide(facts),
              check_usbip(facts), check_conflicts(facts)]
    if facts.settings is not None and not getattr(facts.settings, "grip_enabled", True):
        # 用户主动关掉握把：雷云、编码器这些检查都没有意义，别再拿红字吓人。
        checks.append(Check("grips", "握把震动已关闭", SKIP,
                            "打开「握把震动」总开关后重新检查；按键与触摸板不受影响", scope="grips"))
    else:
        checks.extend([check_synapse(facts), check_encoder(facts), check_settings(facts), check_game(facts)])
    scoped = [_replace(check, scope="grips" if check.id in GRIP_CHECKS or check.scope == "grips" else "core")
              for check in checks]
    return Report(tuple(check.with_fix_text() for check in scoped))


def _usbip_exe():
    default = pathlib.Path(os.environ.get("GIP_BRIDGE_USBIP_EXE", r"C:\Program Files\USBip\usbip.exe"))
    if default.exists():
        return default
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        candidate = pathlib.Path(base) / "USBip" / "usbip.exe"
        if candidate.exists():
            return candidate
    return default


def usbip_services():
    """USBip 官方安装包注册的两个驱动服务；缺 usbip2_filter 时别的工具会判驱动不完整。"""
    import winreg

    found = []
    for name in USBIP_SERVICES:
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{name}").Close()
        except OSError:
            continue
        found.append(name)
    return tuple(found)


def pad_instances(present=True):
    """会被 HidHide 藏起来的那批实体手柄节点；和 native.configure_hiding 用的是同一套匹配。"""
    found = []
    for kind in ("USB", "HID"):
        try:
            found.extend(instance for instance in core.usb_instances(present=present, enumerator=kind)
                         if native.is_pc_pad(instance))
        except OSError:
            continue
    return tuple(found)


def gather_facts(root=None, settings=None, mode=None, instance=None, bridge_running=False,
                 bridge_state=None, audio_frames=0, audio_age=None, stale=(), environment_only=False,
                 processes=None, hashes=True):
    """收集一次检查所需的全部只读事实。调用方可以传入已知的 mode/instance 避免重复查询 PnP。"""
    root = pathlib.Path(root) if root is not None else core.root_dir()
    if mode is None:
        instance, service = core.find_controller()
        mode = core.driver_mode(service, instance)
    hide_state, hide_error = None, ""
    try:
        hide_state = native.hiding_state()
    except Exception as error:  # HidHide 没装时 IOCTL 直接失败，这正是要展示的事实。
        hide_error = str(error)
    exe = _usbip_exe()
    ports = core.usbip_ports() if exe.exists() else ""
    try:
        installed = synapse.find_shortcut() is not None
        running = synapse.is_running()
        state = synapse.diagnose()
    except Exception:
        installed, running, state = None, None, "unknown"
    encoder = pcm_encoder.encoder_path()
    sha = _digest(encoder) if hashes and encoder.exists() else None
    multi = os.environ.get("WOLVERINE_MULTIBAND") == "1" or (root / "multiband.enabled").exists()
    found_conflicts = tuple(core.conflict_tools(processes))
    return Facts(root=root, mode=mode, instance=instance, pad_instances=pad_instances(),
                 bridge_running=bridge_running,
                 bridge_state=bridge_state or {}, settings=settings, hide_state=hide_state,
                 hide_error=hide_error, usbip_exe=exe, usbip_ports=ports, usbip_services=usbip_services(),
                 synapse_installed=installed,
                 synapse_running=running, synapse_state=state, encoder_path=encoder, encoder_sha=sha,
                 multiband=multi, conflicts=found_conflicts, stale=tuple(stale),
                 audio_frames=audio_frames, audio_age=audio_age, environment_only=environment_only)


def diagnose(root=None, settings=None):
    """无界面诊断：只检查环境，不启动桥接。给安装器和 `--diagnose` 用。"""
    return build_report(gather_facts(root=root, settings=settings, environment_only=True))


def write_files(report, directory):
    """把诊断结果写到固定位置；返回 (json 路径, 文本路径)。"""
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    json_path = directory / "WolverineDS5-diagnose.json"
    text_path = directory / "WolverineDS5-diagnose.txt"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(report.text() + "\n", encoding="utf-8")
    return json_path, text_path
