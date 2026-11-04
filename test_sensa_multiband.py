import json
import struct
import threading
import time
from unittest.mock import Mock

import pytest

import sensa_multiband
from sensa_frame import decode_frame
from sensa_multiband import FrameTrace, MixState, PcmMailbox, MultibandGrips, compose_frame
from sensa_mixer import mixer_command, play_command, select_pc_device
from settings import Settings


DUAL = bytes.fromhex("513839c1ce0e70798a4c5262931493839c1ce0e70798a4c526293148")
LEFT = bytes.fromhex("51fc27e13f09f84200000000000000")
DEVICE = "2636-{01234567-89ab-4cde-8f01-23456789abcd}"


def totals(frame):
    return [sum(max(p["amplitude_code"] for p in band) for band in side["bands"])
            for side in decode_frame(frame)["channels"]]


def chunk(left, right=None, count=480):
    """10ms 双声道 S16LE，峰值 = 给定比例 × 满幅；编码器一个 chunk 正好一帧。"""
    right = left if right is None else right
    return struct.pack("<hh", round(left * 32767), round(right * 32767)) * count


def test_default_preserves_the_physically_tested_two_frequencies():
    frame = compose_frame(DUAL, MixState())
    assert frame == DUAL
    assert totals(frame) == [26, 26]


def test_left_and_right_gain_are_applied_per_side():
    state = MixState(settings=Settings(grip_gain_left=1.0, grip_gain_right=0.0))
    left, right = totals(compose_frame(DUAL, state))
    assert left > 0
    assert right == 0


def test_gain_keeps_low_frequency_and_two_separate_bands():
    from sensa_multiband import MAX_AMPLITUDE

    state = MixState(settings=Settings(grip_gain=1.5))
    sides = decode_frame(compose_frame(DUAL, state))["channels"]
    for side in sides:
        assert [band[0]["frequency_code"] for band in side["bands"]] == [7, 41]
        assert side["bands"][0][0]["amplitude_code"] > 14
    # 1.5 倍增益必须真的抬高中强帧；旧的 32 上限会把它压回 32，等于增益失效。
    assert 32 < max(totals(compose_frame(DUAL, state))) <= MAX_AMPLITUDE


def test_band_leakage_does_not_turn_a_single_low_tone_into_two_low_tones():
    from sensa_multiband import pack_frame

    leaked = decode_frame(DUAL)
    for side in leaked["channels"]:
        for point in side["bands"][1]:
            point["frequency_code"] = 7
    result = decode_frame(compose_frame(pack_frame(leaked), MixState()))
    assert all(band[0]["amplitude_code"] == 0 for side in result["channels"] for band in side["bands"][1:])
    stronger = compose_frame(pack_frame(leaked), MixState(rumble=(.25, .25)))
    assert totals(stronger) == [16, 16]


def test_left_pcm_and_right_classic_rumble_remain_independent():
    from sensa_multiband import MAX_AMPLITUDE

    result = compose_frame(LEFT, MixState(rumble=(0, .2)))
    left, right = decode_frame(result)["channels"]
    # 历史帧首点处于预热阶段，原始码为 4；不能把稳定 60Hz 的预期码 9 套到这个夹具。
    assert left["bands"][0][0]["frequency_code"] == 4
    assert right["bands"][0][0] == {"amplitude_code": 13, "frequency_code": 7}
    assert max(totals(result)) <= MAX_AMPLITUDE


@pytest.mark.parametrize("state", [MixState(settings=Settings(grip_enabled=False)),
                                  MixState(settings=Settings(grip_gain=0)),
                                  MixState(test_target="trigger")])
def test_disable_zero_gain_and_trigger_test_silence_all_bands(state):
    assert totals(compose_frame(DUAL, state)) == [0, 0]


def test_manual_grip_test_replaces_game_pcm_and_rumble():
    state = MixState(test_target="grip", pressures=(0, .25), rumble=(1, 1))
    assert totals(compose_frame(DUAL, state)) == [0, 16]


def test_manual_test_still_works_when_game_grips_are_disabled_but_cannot_outlive_input():
    state = MixState(settings=Settings(grip_enabled=False), test_target="grip", pressures=(.25, 0))
    assert totals(compose_frame(DUAL, state)) == [16, 0]
    mailbox = PcmMailbox()
    mailbox.configure(state, now=1)
    assert totals(compose_frame(DUAL, mailbox.take(now=1.2).state)) == [0, 0]


def test_mailbox_keeps_at_most_40ms_and_discards_audio_older_than_50ms():
    mailbox = PcmMailbox()
    mailbox.configure(MixState(), now=1)
    mailbox.push(b"\x01\x00\x00\x00" * 3000, now=1)
    batch = mailbox.take(now=1)
    assert len(batch.pcm) == 1920 * 4
    assert batch.epoch > 0
    mailbox.push(b"\x01\x00\x00\x00" * 48, now=1.01)
    expired = mailbox.take(now=1.07)
    assert expired.pcm == b""
    assert expired.last_audio is None


def test_clear_and_lost_heartbeat_cannot_replay_queued_pcm_or_rumble():
    mailbox = PcmMailbox()
    mailbox.configure(MixState(rumble=(1, 1)), now=1)
    mailbox.push(b"\x01\x00\x00\x00" * 480, now=1)
    mailbox.clear()
    assert mailbox.take(now=1).pcm == b""
    stalled = mailbox.take(now=1.2)
    assert not stalled.state.settings.grip_enabled
    assert totals(compose_frame(DUAL, stalled.state)) == [0, 0]


def test_mixer_packet_matches_the_observed_native_layout():
    packet = play_command("test", DEVICE, DUAL)
    assert packet[:5] == b"test\0"
    assert packet[128] == 12
    payload = b"\x01" + struct.pack("<H", len(DEVICE)) + DEVICE.encode()
    payload += struct.pack("<BI", 1, len(DUAL)) + DUAL
    assert packet[136:144] == struct.pack("<Q", len(payload))
    assert packet[144:] == payload
    assert mixer_command("test", 2)[128:] == bytes([2]) + bytes(15)


def test_mixer_transport_accepts_native_frames_with_other_nonzero_durations():
    frame = bytes([20 * 2 + 1]) + DUAL[1:]
    assert play_command("native", DEVICE, frame).endswith(frame)


def test_device_selection_uses_current_container_and_rejects_ambiguity():
    root = "USB\\VID_1532&PID_0A4C\\PORT1"
    container = "{01234567-89AB-4CDE-8F01-23456789ABCD}"
    assert select_pc_device({root: container, "USB\\VID_9999&PID_0001\\X": container}) == DEVICE
    with pytest.raises(ConnectionError):
        select_pc_device({root: container, root + "OTHER": "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"})
    with pytest.raises(ConnectionError):
        select_pc_device({"USB\\VID_1532&PID_0A3F\\PORT1": container})


def frame_bytes(duration=40, transient=False):
    """按 decode_frame 的位序拼一帧；transient=True 时带一个冲击槽。

    空频带/空冲击只写一个 0 标志位（解析器读到这里就 break），尾部补零到整字节。
    """
    bits = [format(duration, "07b")]
    for _ in range(2):
        bits.append("0")
        if transient:
            bits.append("1")
            bits.extend((format(30, "06b"), format(7, "07b"), format(20, "07b"), "0"))
        else:
            bits.append("0")
    text = "".join(bits)
    text += "0" * (-len(text) % 8)
    return bytes(int(text[index:index + 8], 2) for index in range(0, len(text), 8))


def test_transient_slots_are_dropped_instead_of_killing_the_output():
    # 当初是“动态”档触发的；“打击”档按设计下发冲击槽，不在此列。
    state = MixState(settings=Settings(haptic_profile="dynamic"))
    raw = frame_bytes(transient=True)
    assert any(side["transients"] for side in decode_frame(raw)["channels"])
    composed = compose_frame(raw, state)
    assert all(not side["transients"] for side in decode_frame(composed)["channels"])

    output, encoder, mixer = backend()
    encoder.encode.return_value = raw
    mailbox = PcmMailbox()
    try:
        mailbox.configure(state, now=1)
        mailbox.push(bytes(480 * 4), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        assert output.transient_slots == 1
        assert output.rejected_frames == 0
    finally:
        output.close()


def test_frames_with_the_wrong_duration_are_skipped_not_fatal():
    output, encoder, mixer = backend()
    encoder.encode.return_value = frame_bytes(duration=30)
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(), now=1)
        mailbox.push(bytes(480 * 4), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        assert output.rejected_frames == 1
        assert mixer.play.call_count == 0
    finally:
        output.close()


def test_transient_slots_survive_packing():
    from sensa_multiband import pack_frame

    source = {"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": 10, "frequency_code": 7}] * 4],
         "transients": [{"amplitude_code": 20, "frequency_code": 30, "time_ms": 12}]}
        for _ in range(2)]}
    slot = decode_frame(pack_frame(source))["channels"][0]["transients"][0]
    assert (slot["amplitude_code"], slot["frequency_code"], slot["time_ms"]) == (20, 30, 12)


def test_full_profile_keeps_transient_slots_and_others_drop_them():
    from sensa_multiband import pack_frame

    source = {"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": 10, "frequency_code": 7}] * 4],
         "transients": [{"amplitude_code": 20, "frequency_code": 30, "time_ms": 12}]}
        for _ in range(2)]}
    raw = pack_frame(source)
    kept = decode_frame(compose_frame(raw, MixState(settings=Settings(haptic_profile="full"))))
    dropped = decode_frame(compose_frame(raw, MixState(settings=Settings(haptic_profile="balanced"))))
    assert kept["channels"][0]["transients"][0]["amplitude_code"] == 20
    assert dropped["channels"][0]["transients"] == []


def injector():
    from sensa_multiband import TransientInjector

    return TransientInjector()


def attack(source, level=.30):
    """安静 4 个 chunk 后跳到大电平；不消费触发结果，留给调用方 take() 或 compose_frame 取走。"""
    for _ in range(4):
        source.push(chunk(.01))
        source.take()
    source.push(chunk(level))


def test_a_rising_edge_in_the_source_injects_one_transient_slot():
    both = injector()
    attack(both)
    assert both.take() == (True, True)

    source = injector()
    for _ in range(4):
        source.push(chunk(.01))
        source.take()
    source.push(chunk(.30, .01))
    # 幅度 = 本帧主导频带峰值 14 × SLOT_GAIN 0.65 = 9；时间固定在帧首：攻击已经发生，不能延后。
    sides = decode_frame(compose_frame(DUAL, MixState(), source))["channels"]
    assert sides[0]["transients"] == [{"amplitude_code": 9, "frequency_code": 7, "time_ms": 0}]
    assert sides[1]["transients"] == []


def test_a_sustained_level_fires_once_on_its_onset_and_then_stays_quiet():
    source = injector()
    source.push(chunk(.30))
    assert source.take() == (True, True)
    for _ in range(8):
        source.push(chunk(.30))
        assert source.take() == (False, False)
    for _ in range(4):
        source.push(chunk(.01))
        source.take()
    source.push(chunk(.30))
    assert source.take() == (True, True)


def test_one_attack_cannot_fire_the_slot_twice():
    source = injector()
    attack(source)
    assert source.take() == (True, True)
    # 同一次攻击继续爬升（.30→.50 超过 1.6 倍）不是新攻击。
    source.push(chunk(.50))
    assert source.take() == (False, False)


def test_a_jump_inside_the_noise_floor_never_injects():
    source = injector()
    for _ in range(4):
        source.push(chunk(.001))
        source.take()
    source.push(chunk(.015))
    assert source.take() == (False, False)


def test_a_pending_edge_is_consumed_even_when_the_output_is_silenced():
    source = injector()
    attack(source)
    silenced = MixState(settings=Settings(grip_enabled=False))
    assert compose_frame(DUAL, silenced, source) == sensa_multiband.QUIET_FRAME
    assert source.take() == (False, False)


def test_injected_slots_cannot_overflow_the_six_bit_field():
    from sensa_multiband import MAX_AMPLITUDE, pack_frame

    loud = pack_frame({"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": MAX_AMPLITUDE, "frequency_code": 7}] * 4], "transients": []}
        for _ in range(2)]})
    source = injector()
    attack(source)
    composed = compose_frame(loud, MixState(settings=Settings(grip_gain=1.5)), source)
    assert len(composed) <= 52
    for side in decode_frame(composed)["channels"]:
        assert [point["amplitude_code"] for band in side["bands"] for point in band] == [63] * 4
        assert side["transients"] == [{"amplitude_code": 41, "frequency_code": 7, "time_ms": 0}]


def test_injection_follows_the_profiles_that_already_send_transient_slots():
    source = injector()
    attack(source)
    state = MixState(settings=Settings(haptic_profile="dynamic"))
    assert all(not side["transients"] for side in decode_frame(compose_frame(DUAL, state, source))["channels"])


def test_encoder_transients_keep_their_slots_ahead_of_injected_ones():
    from sensa_multiband import pack_frame

    pair = pack_frame({"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": 14, "frequency_code": 7}] * 4],
         "transients": [{"amplitude_code": 20, "frequency_code": 30, "time_ms": 12},
                        {"amplitude_code": 21, "frequency_code": 31, "time_ms": 20}]}
        for _ in range(2)]})
    source = injector()
    attack(source)
    state = MixState(settings=Settings(haptic_profile="full"))
    assert [slot["time_ms"]
            for slot in decode_frame(compose_frame(pair, state, source))["channels"][0]["transients"]] == [12, 20]


def test_edges_in_different_chunks_of_one_batch_both_survive():
    source = injector()
    for _ in range(4):
        source.push(chunk(.01))
        source.take()
    source.push(chunk(.30, .01))
    source.push(chunk(.30, .30))
    # 一批里可能编码多个 10ms 块；左右分别在不同块起振时后一个不能顶掉前一个。
    assert source.take() == (True, True)


def test_the_injected_slot_follows_the_dominant_band_not_the_first_one():
    from sensa_multiband import pack_frame

    high = pack_frame({"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": 8, "frequency_code": 7}] * 4,
                   [{"amplitude_code": 20, "frequency_code": 41}] * 4], "transients": []}
        for _ in range(2)]})
    source = injector()
    attack(source)
    slots = [side["transients"] for side in decode_frame(compose_frame(high, MixState(), source))["channels"]]
    assert slots == [[{"amplitude_code": 13, "frequency_code": 41, "time_ms": 0}]] * 2


def test_a_silenced_side_gets_no_slot_even_though_its_edge_fired():
    source = injector()
    attack(source)
    state = MixState(settings=Settings(grip_gain_left=0.0, grip_gain_right=1.0))
    sides = decode_frame(compose_frame(DUAL, state, source))["channels"]
    assert sides[0]["transients"] == []
    assert sides[1]["transients"] == [{"amplitude_code": 9, "frequency_code": 7, "time_ms": 0}]


def test_injection_after_classic_rumble_replaced_the_bands_stays_in_range():
    from sensa_multiband import pack_frame

    source = injector()
    attack(source)
    composed = compose_frame(DUAL, MixState(rumble=(1.0, 1.0)), source)
    assert len(composed) <= 52
    assert pack_frame(decode_frame(composed)) == composed
    for side in decode_frame(composed)["channels"]:
        assert [point["amplitude_code"] for band in side["bands"] for point in band] == [63] * 4
        assert side["transients"] == [{"amplitude_code": 41, "frequency_code": 7, "time_ms": 0}]


def test_slot_gain_is_the_level_the_hardware_ab_test_approved():
    """0.65 不是算出来的，是实机拖出来的：强度 1.0 时「更猛烈浑厚、过了」，拖到 0.65 变「挺好」。

    槽 65% 落在 91Hz 以下、最大一档正好是 sensa-device.json 声明的 FrequencyResonance=50，
    等幅叠加等于在共振点双倍驱动。降电平就治好了，说明是过驱不是选错频率
    （蜘蛛侠 2 的打击内容本身就低频主导）。改这个数等于改一次已验收的手感，要有新的实机依据。
    """
    from sensa_multiband import SLOT_GAIN

    assert SLOT_GAIN == .65


def test_the_transient_switch_is_read_from_settings_on_every_batch():
    output, encoder, mixer = backend()
    mailbox = PcmMailbox()
    try:
        for enabled in (False, True, False):
            mailbox.configure(MixState(settings=Settings(haptic_transient=enabled)), now=1)
            mailbox.push(chunk(.01) * 3 + chunk(.30), now=1)
            output.render_pcm(mailbox.take(now=1), now=1)
            assert bool(decode_frame(mixer.play.call_args[0][1])["channels"][0]["transients"]) is enabled
        assert encoder.encode.call_count == 12
    finally:
        output.close()


def test_the_transient_switch_leaves_an_ascii_line_every_time_it_changes(capsys):
    # 必须是 ASCII：托盘把桥接 stdout 写进日志时编码是坏的，中文一律变成 U+FFFD 且不可恢复，
    # 用中文就等于这行证据在日志里读不出来。开和关都要留行，否则无法区分「关了」和「没生效」。
    output, _, _ = backend()
    mailbox = PcmMailbox()
    try:
        for enabled, expected in ((True, "haptic transient: on"), (True, None), (False, "haptic transient: off")):
            mailbox.configure(MixState(settings=Settings(haptic_transient=enabled)), now=1)
            mailbox.push(chunk(.01), now=1)
            output.render_pcm(mailbox.take(now=1), now=1)
            out = capsys.readouterr().out
            if expected is None:
                assert "haptic transient" not in out
            else:
                assert expected in out
    finally:
        output.close()


def test_render_pcm_feeds_the_injector_from_the_same_chunks_the_encoder_gets():
    output, encoder, mixer = backend()
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(settings=Settings(haptic_transient=True)), now=1)
        mailbox.push(chunk(.01) * 3 + chunk(.30), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        assert encoder.encode.call_count == 4
        sent = decode_frame(mixer.play.call_args[0][1])
        assert sent["channels"][0]["transients"] == [{"amplitude_code": 9, "frequency_code": 7, "time_ms": 0}]
    finally:
        output.close()


def test_full_profile_is_two_bands_with_short_windows_for_punch():
    from pcm_encoder import game_profile

    profile = game_profile("full")
    bands = profile["underlying_bands"]["bands"]
    assert [band["frequency_range"] for band in bands] == [{"min": 30, "max": 100},
                                                           {"min": 100, "max": 200}]
    assert all(band["amplitude_window_length"] == .03 for band in bands)
    assert all(band["frequency_window_length"] == .08 for band in bands)
    assert profile["compressor"] == {"amp_limit": 1, "amp_comp": .5, "amp_comp_ratio": .5, "gamma": 3}


def test_full_profile_keeps_its_analysis_floor_at_the_actuator_floor():
    """分析下限不要下探到 30Hz 以下：实机试过一轮就被否，听成「太浑厚」。

    2026-11-03 把 bands[0].frequency_range.min 从 30 放到 5（legacy 档的「宽进窄出」写法），
    离线四项指标全变好：活跃 59.8→60.1%、孤立段 6.9→6.6%、峰值 p90 47→49、包络相关 0.595→0.612。
    实机否掉了。机制是源里 22.4% 的 30Hz 以下能量被算进幅度估计后，按 30–100Hz 发出去，
    等于把深沉低频翻成持续轰鸣。包络相关升高恰恰因为它奖励「跟上源里的低频泥」，那不是还原度。
    """
    from pcm_encoder import game_profile

    low = game_profile("full")["underlying_bands"]["bands"][0]
    assert low["frequency_range"]["min"] == 30
    assert low["output_frequency_range"] == {"min": 30, "max": 100}


def test_full_profile_keeps_faint_frames_other_profiles_clear():
    """“打击”档地板 4：6 级的弱帧不再整段清零，其余档仍按全局 6 屏蔽。"""
    from sensa_multiband import pack_frame

    source = {"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": 6, "frequency_code": 7} for _ in range(4)]],
         "transients": []}
        for _ in range(2)]}
    raw = pack_frame(source)
    kept = decode_frame(compose_frame(raw, MixState(settings=Settings(haptic_profile="full"))))
    dropped = decode_frame(compose_frame(raw, MixState(settings=Settings(haptic_profile="balanced"))))
    assert kept["channels"][0]["bands"][0][0]["amplitude_code"] == 6
    assert dropped["channels"][0]["bands"][0][0]["amplitude_code"] == 0


def test_profile_is_logged_on_start_and_on_switch(capsys):
    output, encoder, _ = backend()
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(), now=1)
        mailbox.push(bytes(480 * 4), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        mailbox.configure(MixState(settings=Settings(haptic_profile="dynamic")), now=1.02)
        mailbox.push(bytes(480 * 4), now=1.02)
        output.render_pcm(mailbox.take(now=1.02), now=1.02)
    finally:
        output.close()
    text = capsys.readouterr().out
    assert "PCM 档位：full" in text
    assert "PCM 档位：dynamic（从 full 切换）" in text


def backend():
    encoder = Mock()
    encoder.encode.return_value = DUAL
    mixer = Mock()
    output = MultibandGrips(encoder_factory=lambda: encoder, mixer_factory=lambda: mixer,
                            target_finder=lambda: DEVICE)
    return output, encoder, mixer


def test_identical_frames_are_only_written_once_per_keepalive_window():
    output, _, mixer = backend()
    mailbox = PcmMailbox()
    state = MixState()
    try:
        for step in range(3):
            now = 1 + step * .02
            mailbox.configure(state, now=now)
            mailbox.push(bytes(480 * 4), now=now)
            output.render_pcm(mailbox.take(now=now), now=now)
        assert mixer.play.call_count == 1
        mailbox.configure(state, now=1.2)
        mailbox.push(bytes(480 * 4), now=1.2)
        output.render_pcm(mailbox.take(now=1.2), now=1.2)
        assert mixer.play.call_count == 2
    finally:
        output.close()


def test_profile_change_reaches_the_encoder_once():
    output, encoder, _ = backend()
    mailbox = PcmMailbox()
    dynamic = MixState(settings=Settings(haptic_profile="dynamic"))
    try:
        for step in range(2):
            now = 1 + step * .02
            mailbox.configure(dynamic, now=now)
            mailbox.push(bytes(480 * 4), now=now)
            output.render_pcm(mailbox.take(now=now), now=now)
        encoder.set_profile.assert_called_once_with("dynamic")
    finally:
        output.close()


def sampled(amplitude, bands=1):
    from sensa_multiband import pack_frame

    frequencies = (7, 41, 74)[:bands]
    return pack_frame({"duration_ms": 40, "channels": [
        {"bands": [[{"amplitude_code": amplitude, "frequency_code": code} for _ in range(4)]
                   for code in frequencies], "transients": []} for _ in range(2)]})


def test_dynamic_profile_makes_up_its_quieter_low_band():
    frame = sampled(10)
    assert totals(compose_frame(frame, MixState())) == [10, 10]
    assert totals(compose_frame(frame, MixState(settings=Settings(haptic_profile="dynamic")))) == [20, 20]
    # 2.0 补偿必须真的落到输出上：20 × 2 = 40。旧的 32 上限会把它钳回 32，
    # 补偿在中强段完全空转（统一乘再按固定合计归一，数学上互相抵消）。
    assert totals(compose_frame(sampled(20), MixState(settings=Settings(haptic_profile="dynamic")))) == [40, 40]


def test_loud_frames_reach_the_full_six_bit_range_instead_of_half():
    from sensa_multiband import MAX_AMPLITUDE

    assert MAX_AMPLITUDE == 63
    # 两带各 60，合计 120 超过任何上限；压到 63 而不是 32，才用满 6 位幅度码。
    assert totals(compose_frame(sampled(60, bands=2), MixState())) == [62, 62]


def test_grip_gain_stays_linear_for_frames_the_old_ceiling_flattened():
    # 原始合计 50：旧的 32 上限把 1.0/0.9/0.8 三档全压成 32，旋钮在中强段没有分辨力。
    frame = sampled(25, bands=2)
    scaled = [totals(compose_frame(frame, MixState(settings=Settings(grip_gain=gain))))[0]
              for gain in (1.0, .9, .8, .6)]
    assert scaled == [50, 44, 40, 30]
    assert scaled == sorted(scaled, reverse=True)


def test_ceiling_cannot_push_a_code_past_the_six_bit_field():
    from sensa_multiband import MAX_AMPLITUDE

    # 单带满幅 + 1.5 增益 + 动态档 2.0 补偿：钳位是唯一挡住 6 位溢出的东西。
    # 上限若放到 126（两带合计容量），单带时峰值会被算到 126，写进 6 位字段会串位毁帧；
    # 63 是「合计上限同时保证每个码合法」的最大取值。
    assert MAX_AMPLITUDE <= 63
    state = MixState(settings=Settings(grip_gain=1.5, haptic_profile="dynamic"))
    for side in decode_frame(compose_frame(sampled(63), state))["channels"]:
        for band in side["bands"]:
            for point in band:
                assert 0 <= point["amplitude_code"] <= 63


def test_balanced_plus_only_lowers_the_detection_threshold():
    from pcm_encoder import game_profile

    plus = game_profile("balanced_plus")
    band = plus["underlying_bands"]["bands"][0]
    assert band["minimal_amplitude_threshold"] == .004
    band["minimal_amplitude_threshold"] = .01
    assert plus == game_profile("balanced")


def test_controlled_tuning_keeps_the_narrow_band_but_catches_weaker_events():
    from pcm_encoder import game_profile, tuned_profile

    raw = game_profile("controlled")
    tuned = tuned_profile("controlled")
    assert raw["underlying_bands"]["bands"][0]["minimal_amplitude_threshold"] == .03
    band = tuned["underlying_bands"]["bands"][0]
    assert band["minimal_amplitude_threshold"] == .01
    assert band["frequency_range"] == {"min": 30, "max": 130}
    assert band["output_frequency_range"] == {"min": 30, "max": 80}
    assert tuned["compressor"] == {"amp_limit": 1, "amp_comp": .25, "amp_comp_ratio": .3, "gamma": 5}
    assert [keyframe["volume"] for keyframe in tuned["haptic_EQ"]["keyframes"]] == [1, 1, .5, .5]


def test_profiles_without_tuning_stay_verbatim():
    from pcm_encoder import game_profile, tuned_profile

    for name in ("legacy", "balanced", "dynamic"):
        assert tuned_profile(name) == game_profile(name)


def test_razer_presets_keep_the_recorded_band_layout():
    from pcm_encoder import game_profile

    dynamic = game_profile("dynamic")
    assert dynamic["transients"]["volume"] == 1
    assert [band["frequency_range"] for band in dynamic["underlying_bands"]["bands"]] == [
        {"min": 30, "max": 100}, {"min": 100, "max": 200}]
    controlled = game_profile("controlled")["underlying_bands"]["bands"][0]
    assert controlled["output_frequency_range"] == {"min": 30, "max": 80}
    with pytest.raises(ValueError):
        game_profile("nope")


def test_backend_sends_latest_pcm_then_silence_after_timeout():
    output, encoder, mixer = backend()
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(), now=1)
        mailbox.push(bytes(480 * 4), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        assert totals(mixer.play.call_args.args[1]) == [26, 26]
        mailbox.configure(MixState(), now=1.06)
        output.render_pcm(mailbox.take(now=1.06), now=1.06)
        assert totals(mixer.play.call_args.args[1]) == [0, 0]
    finally:
        output.close()
    mixer.close.assert_called_once()
    encoder.close.assert_called_once()


def test_backend_stop_is_attempted_even_if_quiet_send_fails():
    output, encoder, mixer = backend()
    mixer.play.side_effect = OSError("lost transport")
    with pytest.raises(OSError):
        output.close()
    mixer.stop.assert_called_once()
    mixer.close.assert_called_once()
    encoder.close.assert_called_once()


def test_bridge_queues_host_pcm_and_keeps_settings_and_stop_commands():
    from pc_bridge import GripHaptics, SensaOutputWorker
    from test_capture_recorder import block

    started, release = threading.Event(), threading.Event()
    backend = Mock()

    def slow_start():
        started.set()
        release.wait(1)
        return backend

    mailbox = PcmMailbox()
    worker = SensaOutputWorker(factory=slow_start, pcm=mailbox)
    try:
        assert started.wait(.3)
        haptics = GripHaptics(worker, Settings(grip_gain=1.5))
        now = time.monotonic()
        data = bytes(192)
        haptics.accept(block(1, 0, data, "usb-host"), now=now)
        haptics.step(0, 0, now=now)
        batch = mailbox.take(now=now)
        assert batch.pcm == data
        assert batch.state.settings.grip_gain == 1.5
        haptics.accept({"type": "stopped"}, now=now)
        haptics.step(0, 0, now=now)
        assert mailbox.take(now=now).last_audio is None
    finally:
        release.set()
        worker.close()


def test_worker_retries_failed_multiband_output_without_blocking_input():
    from pc_bridge import SensaOutputWorker
    from test_pc_bridge import wait_for

    first, recovered = Mock(), Mock()
    first.render_pcm.side_effect = OSError("lost mapping")
    factory = Mock(side_effect=[first, recovered])
    worker = SensaOutputWorker(factory=factory, pcm=PcmMailbox(), retry_seconds=.01)
    try:
        worker.render()
        assert wait_for(lambda: recovered.render_pcm.called)
        first.close.assert_called_once()
        assert worker.ready
    finally:
        worker.close()


def test_frame_trace_records_sent_frames_and_stops_at_the_limit(tmp_path):
    from sensa_multiband import FrameTrace

    trace = FrameTrace(tmp_path / "frames.jsonl")
    trace.LIMIT = 3
    state = MixState()
    for step in range(5):
        trace.record(trace.started + step * .01, DUAL, LEFT, state)
    trace.flush()
    rows = [json.loads(line) for line in (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["t"] for row in rows] == [0.0, 0.01, 0.02]
    assert rows[0]["sent"] == DUAL.hex() and rows[0]["raw"] == LEFT.hex()
    assert rows[0]["changed"] is True


def test_frame_trace_records_the_encoder_frame_not_a_copy_of_the_sent_one(tmp_path, monkeypatch):
    trace = FrameTrace(tmp_path / "frames.jsonl")
    monkeypatch.setattr(sensa_multiband, "trace_enabled", lambda: True)
    monkeypatch.setattr(sensa_multiband, "FrameTrace", lambda path=None: trace)
    output, _, _ = backend()
    mailbox = PcmMailbox()
    state = MixState(settings=Settings(grip_gain_left=0.0, grip_gain_right=1.0))
    try:
        mailbox.configure(state, now=1)
        mailbox.push(bytes(480 * 4), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
    finally:
        output.close()
    trace.flush()
    row = json.loads((tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()[0])
    # raw 必须是编码器交出来的帧。旧代码把 compose_frame 的返回值同时写进 sent 和 raw，
    # changed 恒为 False，钳位与地板到底改了什么在日志里完全看不见（2026-11-03 实机 23000 行全是死列）。
    assert row["raw"] == DUAL.hex()
    assert row["changed"] is True
    assert totals(bytes.fromhex(row["sent"])) == [0, 26]

def test_chain_test_encodes_a_left_then_right_tone_through_the_shipping_encoder():
    import numpy as np
    output, encoder, mixer = backend()
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(chain=1), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        chunks = [call.args[0] for call in encoder.encode.call_args_list]
        assert len(chunks) == 330
        left = np.frombuffer(chunks[0], dtype="<i2").reshape(-1, 2)
        assert abs(int(left[:, 0].max())) > 1000 and not left[:, 1].any()
        right = np.frombuffer(chunks[200], dtype="<i2").reshape(-1, 2)
        assert abs(int(right[:, 1].max())) > 1000 and not right[:, 0].any()
        assert mixer.play.call_count == 1
    finally:
        output.close()


def test_chain_test_sends_one_frame_per_10ms_and_only_regenerates_on_a_new_token():
    output, encoder, mixer = backend()
    mailbox = PcmMailbox()
    try:
        mailbox.configure(MixState(chain=1), now=1)
        output.render_pcm(mailbox.take(now=1), now=1)
        assert mixer.play.call_count == 1
        for step in range(1, 5):
            now = 1 + step * .01
            mailbox.configure(MixState(chain=1), now=now)
            output.render_pcm(mailbox.take(now=now), now=now)
        assert mixer.play.call_count == 5
        assert encoder.encode.call_count == 330
        mailbox.configure(MixState(chain=1), now=1.2)
        output.render_pcm(mailbox.take(now=1.2), now=1.2)
        assert encoder.encode.call_count == 330
        mailbox.configure(MixState(chain=2), now=1.3)
        output.render_pcm(mailbox.take(now=1.3), now=1.3)
        assert encoder.encode.call_count == 660
    finally:
        output.close()
