"""用户可调参数：界面写入 %APPDATA%，桥接通过 stdin 实时接收。"""
from dataclasses import asdict, dataclass, fields
import json
import os
import pathlib

RANGES = {"grip_gain": (0.0, 1.5), "trigger_gain": (0.0, 1.5), "follow_ratio": (0.0, 1.0)}


@dataclass(frozen=True)
class Settings:
    grip_gain: float = 1.0
    trigger_gain: float = 1.0
    # DS5 的 0x21/0x25 是扳机阻力（拉弓、扣扳机的“硬”感），纽扣马达只能硬震，默认不转换；
    # 0x26 本身就是扳机震动，始终转换。
    trigger_resistance: bool = False
    # 扳机跟随握把：LT/RT 取 max(扳机效果, 比例 × 同侧握把)。
    trigger_follow: bool = False
    follow_ratio: float = 0.5
    audio_guard: bool = True

    @classmethod
    def from_dict(cls, data):
        values = {}
        for field in fields(cls):
            value = data.get(field.name)
            if field.type is bool and type(value) is bool:
                values[field.name] = value
            elif field.type is float and type(value) in (int, float):
                low, high = RANGES[field.name]
                values[field.name] = min(high, max(low, float(value)))
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
