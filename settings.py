"""用户可调参数：界面写入 %APPDATA%，桥接通过 stdin 实时接收。"""
from dataclasses import asdict, dataclass, fields
import json
import os
import pathlib

RANGES = {"grip_gain": (0.0, 1.5), "grip_gain_left": (0.0, 1.5), "grip_gain_right": (0.0, 1.5),
          "trigger_gain": (0.0, 1.5), "follow_ratio": (0.0, 1.0)}
PROFILES = ("legacy", "controlled", "balanced", "balanced_plus", "dynamic", "full")
# 2026-10-30 实机确认“打击”战斗不丢震动、打击反馈正常，设为默认；已保存的选择不迁移。
DEFAULT_PROFILE = "full"


@dataclass(frozen=True)
class Settings:
    grip_enabled: bool = True
    # 旧版单旋钮保留作迁移入口；新界面分别写左右两侧。
    grip_gain: float = 1.0
    grip_gain_left: float = None
    grip_gain_right: float = None
    # PC 多频握把使用的雷蛇编码器 profile：默认“打击”（full）；legacy 为原双频带，其余档位抄自 Synapse 音频到触觉预设。
    haptic_profile: str = DEFAULT_PROFILE
    # 检测到打击瞬间额外推一把（自造冲击槽）。默认关：默认手感必须等于实机验收过的那一版，
    # 打开与否由用户当场 A/B 决定，不替他选。
    haptic_transient: bool = False
    # 只影响界面动效，不影响桥接。
    reduce_motion: bool = False
    trigger_enabled: bool = True
    trigger_gain: float = 1.0
    # DS5 的 0x21/0x25 是扳机阻力（拉弓、扣扳机的“硬”感），纽扣马达只能硬震，默认不转换；
    # 0x26 本身就是扳机震动，始终转换。
    trigger_resistance: bool = False
    # 扳机跟随握把：LT/RT 取 max(扳机效果, 比例 × 同侧握把)。
    trigger_follow: bool = False
    follow_ratio: float = 0.5
    audio_guard: bool = True
    # 保存运行时隐藏的偏好；托盘退出会撤销系统隐藏，下次启动再自动申请。
    # 默认开启：不隐藏时游戏会同时看到实体手柄和虚拟 DualSense，新手装上就会觉得“手柄乱了”。
    hide_physical: bool = True
    # 隐藏时已登记的 USB 端口实例；HidHide 按实例隐藏，换到新 USB 口的手柄不在其中，需要重新隐藏。
    hidden_devices: tuple = ()
    # 隐藏时放行的桥接程序；换成打包版或挪了目录后，新桥接不在 HidHide 放行名单里，也读不到手柄。
    hidden_app: str = ""

    def __post_init__(self):
        if self.haptic_profile not in PROFILES:
            object.__setattr__(self, "haptic_profile", DEFAULT_PROFILE)
        # 旧配置只有 grip_gain；缺哪一侧就把旧值迁移到哪一侧，显式 1.0 不被旧值覆盖。
        if self.grip_gain_left is None:
            object.__setattr__(self, "grip_gain_left", self.grip_gain)
        if self.grip_gain_right is None:
            object.__setattr__(self, "grip_gain_right", self.grip_gain)

    @classmethod
    def from_dict(cls, data):
        values = {}
        for field in fields(cls):
            value = data.get(field.name)
            if (field.type is bool and type(value) is bool) or (field.type is str and type(value) is str):
                values[field.name] = value
            elif field.type is float and type(value) in (int, float):
                low, high = RANGES[field.name]
                values[field.name] = min(high, max(low, float(value)))
            elif field.type is tuple and isinstance(value, (list, tuple)) and all(type(v) is str for v in value):
                values[field.name] = tuple(value)
        return cls(**values)


def default_path():
    return pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home())) / "WolverineDS5" / "settings.json"


def load(path=None):
    try:
        return Settings.from_dict(json.loads(pathlib.Path(path or default_path()).read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError):
        return Settings()


def save(settings, path=None):
    path = pathlib.Path(path or default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    temporary.replace(path)
