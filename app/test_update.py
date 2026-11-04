"""版本检查：只读一次发布信息，失败静默；不下载、不安装。"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import update


def test_version_tags_compare_numerically():
    assert update.is_newer("v1.1.46", "1.1.45")
    assert update.is_newer("v1.10.0", "1.9.9")
    assert not update.is_newer("v1.0.4", "1.1.46")
    assert not update.is_newer("v1.1.46", "1.1.46")
    assert not update.is_newer("", "1.1.46")
    assert not update.is_newer("nightly", "1.1.46")


def test_check_stays_quiet_within_the_interval(tmp_path):
    marker = tmp_path / "update-check.txt"
    marker.write_text("1000", encoding="utf-8")
    calls = []

    def fetch():
        calls.append(1)
        return "v9.9.9"

    assert update.check(marker, now=1000 + 60, fetch=fetch) == ""
    assert calls == []


def test_check_reports_a_newer_tag_and_records_the_time(tmp_path):
    marker = tmp_path / "update-check.txt"
    assert update.check(marker, now=5000, fetch=lambda: "v1.1.99") == "v1.1.99"
    assert marker.read_text(encoding="utf-8") == "5000"
    assert update.due(marker, now=5000 + 60) is False


def test_check_swallows_network_failures_without_marking_the_time(tmp_path):
    marker = tmp_path / "update-check.txt"

    def offline():
        raise OSError("no network")

    assert update.check(marker, now=10, fetch=offline) == ""
    assert not marker.exists()  # 没成功就别记时间，下次启动还能再试


def test_release_url_points_at_the_tag():
    assert update.release_url("v1.1.46").endswith("/wolverine-ds5/releases/tag/v1.1.46")
