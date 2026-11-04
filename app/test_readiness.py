"""启动自检：每条检查都要能单独失败、给出人话和修复动作；就绪判定不能靠桥接自报。"""
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import core, readiness
from app.readiness import Facts, FAIL, OK, SKIP, WARN, build_report, gather_facts
from settings import Settings

EXE = pathlib.Path(r"C:\Program Files\USBip\usbip.exe")


def facts(tmp_path, **changes):
    root = tmp_path
    for name in ("wolverine-capture.exe", "SDL3.dll", "ui/main.qml", "ui/StatusPage.qml"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    encoder = root / "encoder.dll"
    encoder.write_bytes(b"x")
    hide = {"active": True, "devices": ["USB\\VID_1532&PID_0A4C&MI_00\\PORT1"],
            "apps": [core.bridge_command(pc=True)[0]]}
    base = dict(root=root, mode="pc", instance="USB\\VID_1532&PID_0A4C\\PORT1",
                pad_instances=("USB\\VID_1532&PID_0A4C&MI_00\\PORT1",),
                bridge_running=True, bridge_state={"state": "connected", "grips_ready": True},
                settings=Settings(hide_physical=True), hide_state=hide, usbip_exe=EXE,
                usbip_ports="usbip://127.0.0.1:3240/1-1", synapse_installed=True,
                synapse_running=True, synapse_state="ready", encoder_path=encoder, encoder_sha="same",
                encoder_expected="same", audio_frames=120, audio_age=1.0)
    base.update(changes)
    return Facts(**base)


def states(report):
    return {check.id: check.state for check in report.checks}


def by_id(report, wanted):
    return next(check for check in report.checks if check.id == wanted)


def test_a_complete_machine_is_ready_and_says_so(tmp_path):
    report = build_report(facts(tmp_path))
    assert report.ready
    assert report.summary() == "系统就绪"
    assert states(report)["bridge"] == OK
    assert states(report)["game"] == OK


def test_no_controller_blocks_and_offers_a_recheck(tmp_path):
    report = build_report(facts(tmp_path, mode="absent", instance=None))
    check = by_id(report, "device")
    assert check.state == FAIL
    assert check.fix == "recheck"
    assert report.first_blocker().id == "device"


def test_xbox_mode_blocks_with_the_driver_switch_action(tmp_path):
    report = build_report(facts(tmp_path, mode="xbox"))
    check = by_id(report, "device")
    assert check.state == FAIL
    assert check.fix == "switch_pc"
    assert "PC 模式" in check.detail


def test_synapse_not_running_blocks_even_if_the_bridge_reports_grips_ready(tmp_path):
    report = build_report(facts(tmp_path, synapse_running=False))
    assert by_id(report, "synapse").state == FAIL
    assert not report.ready


def test_synapse_offline_and_unregistered_have_their_own_text(tmp_path):
    offline = build_report(facts(tmp_path, synapse_state="offline"))
    unregistered = build_report(facts(tmp_path, synapse_state="unregistered"))
    assert by_id(offline, "synapse").title == "雷云处于离线模式"
    assert by_id(unregistered, "synapse").title == "雷云还没认出手柄"


def test_unknown_synapse_state_warns_but_does_not_block(tmp_path):
    report = build_report(facts(tmp_path, synapse_state="unknown"))
    assert by_id(report, "synapse").state == WARN
    assert report.ready


def test_encoder_version_mismatch_blocks(tmp_path):
    report = build_report(facts(tmp_path, encoder_sha="other"))
    check = by_id(report, "encoder")
    assert check.state == FAIL
    assert "雷云版本" in check.title


def test_grip_error_is_translated_into_something_a_person_can_read(tmp_path):
    report = build_report(facts(tmp_path, bridge_state={
        "state": "connected", "grips_ready": False,
        "grip_error": "雷蛇编码器版本不匹配；多频候选未启动"}))
    check = by_id(report, "bridge")
    assert check.state == FAIL
    assert check.title == "雷云版本不受支持"
    assert "更新本程序" in check.detail


def test_a_generic_grip_error_keeps_its_original_text(tmp_path):
    report = build_report(facts(tmp_path, bridge_state={
        "state": "connected", "grips_ready": False, "grip_error": "Mixer shared memory missing"}))
    assert "Mixer shared memory missing" in by_id(report, "bridge").detail


def test_hiding_switched_off_is_a_warning_not_a_failure(tmp_path):
    # 关掉隐藏是用户的选择：只提醒游戏会看到两只手柄，不能把正常状态判成故障。
    report = build_report(facts(tmp_path, settings=Settings(hide_physical=False)))
    check = by_id(report, "hidhide")
    assert check.state == WARN
    assert check.fix == "enable_hide"
    assert report.ready


def test_hidhide_active_but_the_new_port_is_not_registered_blocks(tmp_path):
    hide = {"active": True, "devices": ["USB\\VID_1532&PID_0A4C&MI_00\\OTHER"],
            "apps": [core.bridge_command(pc=True)[0]]}
    report = build_report(facts(tmp_path, hide_state=hide))
    check = by_id(report, "hidhide")
    assert check.state == FAIL
    assert check.fix == "rehide"


def test_composite_instance_is_not_what_hidhide_hides(tmp_path):
    # 实机 2026-11-03：HidHide 名单里只有 MI_00/IG_* 子节点，拿复合设备的实例 ID 去比会一直报“还没隐藏”。
    report = build_report(facts(tmp_path, instance="USB\\VID_1532&PID_0A4C\\6&18811D57&0&1"))
    check = by_id(report, "hidhide")
    assert check.state == OK
    assert report.ready


def test_hidhide_missing_app_registration_blocks(tmp_path):
    hide = {"active": True, "devices": ["USB\\VID_1532&PID_0A4C&MI_00\\PORT1"], "apps": []}
    report = build_report(facts(tmp_path, hide_state=hide))
    assert by_id(report, "hidhide").title == "桥接程序未被 HidHide 放行"


def test_missing_usbip_blocks_with_the_install_action(tmp_path):
    report = build_report(facts(tmp_path, usbip_exe=tmp_path / "nope" / "usbip.exe"))
    check = by_id(report, "usbip")
    assert check.state == FAIL
    assert check.fix == "open_usbip"


def test_half_installed_usbip_warns_without_blocking(tmp_path):
    # 实机 2026-11-03：只装了 usbip2_ude 时本程序能用，但飞智 X-Haptics 判驱动不完整。
    report = build_report(facts(tmp_path, usbip_services=("usbip2_ude",)))
    check = by_id(report, "usbip")
    assert check.state == WARN
    assert check.fix == "open_usbip"
    assert "usbip2_filter" in check.detail
    assert report.ready


def test_deleted_usbip_driver_blocks_and_warns_against_manual_removal(tmp_path):
    # 事故背景：安全软件误杀后用户手动删 USBIP，USB 层损坏到只能重装系统。
    report = build_report(facts(tmp_path, usbip_services=("usbip2_filter",)))
    check = by_id(report, "usbip")
    assert check.state == FAIL
    assert check.fix == "open_usbip"
    assert "usbip2_ude" in check.detail
    assert "不要手动删除" in check.detail
    assert "重装系统" in check.detail
    assert not report.ready


def test_stale_game_audio_is_not_reported_as_fine(tmp_path):
    report = build_report(facts(tmp_path, audio_frames=120, audio_age=600))
    check = by_id(report, "game")
    assert check.state == WARN
    assert "中断" in check.title


def test_synapse_process_with_dead_grip_service_is_a_failure(tmp_path):
    report = build_report(facts(tmp_path, synapse_running=True, synapse_state="stopped"))
    check = by_id(report, "synapse")
    assert check.state == FAIL
    assert check.fix == "start_synapse"


def test_encoder_mismatch_does_not_offer_starting_synapse(tmp_path):
    report = build_report(facts(tmp_path, bridge_state={
        "state": "connected", "grips_ready": False,
        "grip_error": "雷蛇编码器版本不匹配；多频候选未启动"}))
    check = by_id(report, "bridge")
    assert check.state == FAIL
    assert check.fix == ""


def test_bridge_disconnect_offers_restart_not_synapse(tmp_path):
    report = build_report(facts(tmp_path, bridge_state={
        "state": "connected", "grips_ready": False,
        "grip_error": "Razer input disconnected"}))
    assert by_id(report, "bridge").fix == "restart_bridge"


def test_bridge_not_running_blocks_outside_diagnose_mode(tmp_path):
    report = build_report(facts(tmp_path, bridge_running=False, bridge_state={}))
    assert by_id(report, "bridge").state == FAIL
    assert by_id(report, "bridge").fix == "restart_bridge"


def test_diagnose_mode_skips_bridge_and_game(tmp_path):
    report = build_report(facts(tmp_path, environment_only=True, bridge_running=False, bridge_state={}))
    assert by_id(report, "bridge").state == SKIP
    assert by_id(report, "game").state == SKIP


def test_zero_gain_blocks_with_a_fix(tmp_path):
    report = build_report(facts(tmp_path, settings=Settings(grip_gain=0, grip_gain_left=0, grip_gain_right=0)))
    check = by_id(report, "settings")
    assert check.state == FAIL
    assert check.fix == "set_gain"


def test_no_game_audio_before_the_mount_is_a_warning_that_names_the_processes(tmp_path):
    report = build_report(facts(tmp_path, audio_frames=0, audio_age=None,
                                stale=({"name": "spider-man2.exe"},)))
    check = by_id(report, "game")
    assert check.state == WARN
    assert "spider-man2.exe" in check.detail
    assert report.ready  # 只是提醒，不该拦着人玩


def test_no_game_audio_without_old_processes_mentions_the_game_settings(tmp_path):
    report = build_report(facts(tmp_path, audio_frames=0, audio_age=None, stale=()))
    assert "游戏内震动" in by_id(report, "game").detail


def test_fix_texts_come_from_the_shared_table(tmp_path):
    report = build_report(facts(tmp_path, mode="xbox"))
    assert by_id(report, "device").fix_text == "切到 PC 模式"


def test_report_json_is_plain_data(tmp_path):
    data = build_report(facts(tmp_path)).to_dict()
    assert data["ready"] is True
    assert data["checks"][0]["state"] in (OK, WARN, FAIL, SKIP)
    assert all(isinstance(item["title"], str) for item in data["checks"])


def test_grip_only_failure_degrades_but_keeps_the_pad_usable(tmp_path):
    # 没有雷云时按键照常能用：不能把整个程序判成"未就绪"，那会让用户以为手柄映射坏了。
    report = build_report(facts(tmp_path, synapse_running=False))
    assert report.core_ready
    assert report.state == "degraded"
    assert report.summary().startswith("按键可用")
    assert by_id(report, "synapse").scope == "grips"


def test_a_core_failure_outranks_a_grip_failure_in_the_banner(tmp_path):
    report = build_report(facts(tmp_path, mode="absent", instance=None, synapse_running=False))
    assert report.state == "blocked"
    assert not report.core_ready
    assert report.first_blocker().id == "device"
    assert report.summary().startswith("未就绪")


def test_turning_grips_off_skips_the_razer_chain(tmp_path):
    report = build_report(facts(tmp_path, settings=Settings(grip_enabled=False)))
    assert report.ready
    assert report.state == "ready"
    assert by_id(report, "grips").state == SKIP
    assert "synapse" not in states(report)
    assert "encoder" not in states(report)


def test_grips_off_ignores_a_dead_grip_service(tmp_path):
    report = build_report(facts(tmp_path, settings=Settings(grip_enabled=False), bridge_state={
        "state": "connected", "grips_ready": False, "grip_error": "No Sensa device"}))
    assert by_id(report, "bridge").state == OK


def test_ready_synapse_says_when_and_which_device(tmp_path):
    # 支持排障：先说清「几点交给握把服务、哪台设备」，再谈设置对不对。
    report = build_report(facts(tmp_path, synapse_registration={
        "at": datetime.datetime(2026, 11, 4, 13, 35, 10), "name": "Sage T1"}))
    check = by_id(report, "synapse")
    assert check.state == OK
    assert "13:35" in check.detail
    assert "Sage T1" in check.detail


def test_encoder_mismatch_degrades_and_offers_a_prefilled_report(tmp_path):
    # 雷云会自动更新：硬拦等于把可用性绑在别人的发布节奏上，这里只降级并给一键反馈。
    report = build_report(facts(tmp_path, encoder_sha="other"))
    check = by_id(report, "encoder")
    assert check.state == FAIL
    assert check.fix == "report_issue"
    assert check.fix_text == "反馈问题"
    assert report.core_ready
    assert report.state == "degraded"


def test_write_files_puts_machine_and_human_reports_side_by_side(tmp_path):
    report = build_report(facts(tmp_path))
    json_path, text_path = readiness.write_files(report, tmp_path / "out")
    assert '"ready": true' in json_path.read_text(encoding="utf-8")
    assert "系统就绪" in text_path.read_text(encoding="utf-8")


def test_gather_facts_never_raises_when_hidhide_and_synapse_are_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("WOLVERINE_MULTIBAND", "1")
    monkeypatch.setattr(readiness.native, "hiding_state", lambda: (_ for _ in ()).throw(OSError("no hidhide")))
    monkeypatch.setattr(readiness.synapse, "find_shortcut", lambda: None)
    monkeypatch.setattr(readiness.synapse, "is_running", lambda: False)
    monkeypatch.setattr(readiness.synapse, "diagnose", lambda: "stopped")
    monkeypatch.setattr(readiness.core, "conflict_tools", lambda processes=None: [])
    monkeypatch.setattr(readiness.core, "usbip_ports", lambda: "")
    monkeypatch.setattr(readiness.pcm_encoder, "encoder_path", lambda: tmp_path / "missing.dll")
    monkeypatch.setattr(readiness, "_digest", lambda path: "sha")
    found = gather_facts(root=tmp_path, settings=Settings(), mode="pc", instance="X", hashes=False)
    report = build_report(found)
    assert by_id(report, "hidhide").state == FAIL
    assert by_id(report, "synapse").state == FAIL
    assert by_id(report, "encoder").state == FAIL
