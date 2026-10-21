import json
import struct
import threading
import time
from unittest.mock import Mock

import pytest

from sensa_frame import decode_frame
from sensa_multiband import MixState, PcmMailbox, MultibandGrips, compose_frame
from sensa_mixer import mixer_command, play_command, select_pc_device
from settings import Settings


DUAL = bytes.fromhex("513839c1ce0e70798a4c5262931493839c1ce0e70798a4c526293148")
LEFT = bytes.fromhex("51fc27e13f09f84200000000000000")
DEVICE = "2636-{01234567-89ab-4cde-8f01-23456789abcd}"


def totals(frame):
    return [sum(max(p["amplitude_code"] for p in band) for band in side["bands"])
            for side in decode_frame(frame)["channels"]]


def test_default_preserves_the_physically_tested_two_frequencies():
    frame = compose_frame(DUAL, MixState())
    assert frame == DUAL
    assert totals(frame) == [26, 26]


def test_gain_and_softness_keep_low_frequency_and_two_separate_bands():
    state = MixState(settings=Settings(grip_gain=1.5, grip_soft=True))
    sides = decode_frame(compose_frame(DUAL, state))["channels"]
    for side in sides:
        assert [band[0]["frequency_code"] for band in side["bands"]] == [7, 41]
        assert side["bands"][0][0]["amplitude_code"] > 14
        assert 0 < side["bands"][1][0]["amplitude_code"] < 18
    assert max(totals(compose_frame(DUAL, state))) <= 32


@pytest.mark.parametrize("frequency,maximum_ratio", [(150, .4), (250, .22), (400, .16)])
def test_soft_mode_reduces_buzzy_high_band_without_turning_down_low_band(frequency, maximum_ratio):
    from sensa_multiband import SustainSoftener, pack_frame

    source = decode_frame(DUAL)
    for side in source["channels"]:
        for point in side["bands"][0]:
            point["amplitude_code"] = 4
        for point in side["bands"][1]:
            point.update(amplitude_code=20, frequency_code=round((frequency - 30) * 127 / 370))
    frame = compose_frame(pack_frame(source), MixState(settings=Settings(grip_soft=True)))
    softener = SustainSoftener()
    for step in range(41):
        output = softener.apply(frame, enabled=True, now=step * .01)
    softened = decode_frame(output)
    for before, after in zip(source["channels"], softened["channels"]):
        assert after["bands"][0] == before["bands"][0]
        assert 0 < after["bands"][1][0]["amplitude_code"] <= 20 * maximum_ratio
        assert after["bands"][1][0]["frequency_code"] == before["bands"][1][0]["frequency_code"]


def test_faint_low_details_become_a_layer_in_soft_mode():
    # 2026-10-20：极弱残留听成若有若无的微震，曾整段静音；
    # 2026-10-21 用户实机：摆荡时剩下的是“忽隐忽现的低频”，改成抬成稳定一层。
    from sensa_multiband import pack_frame

    source = decode_frame(DUAL)
    for side in source["channels"]:
        for point in side["bands"][0]:
            point["amplitude_code"] = 2
        for point in side["bands"][1]:
            point["amplitude_code"] = 0
    state = MixState(settings=Settings(grip_gain=.6, grip_soft=True))
    assert totals(compose_frame(pack_frame(source), state)) == [16, 16]


def test_short_combat_impacts_keep_the_previous_strength_and_envelope():
    from sensa_multiband import SustainSoftener, pack_frame, QUIET_FRAME

    source = decode_frame(DUAL)
    for side in source["channels"]:
        for point in side["bands"][0]:
            point["amplitude_code"] = 0
        for point, level in zip(side["bands"][1], (0, 4, 20, 0)):
            point["amplitude_code"] = level
    frame = compose_frame(pack_frame(source), MixState(settings=Settings(grip_soft=True)))
    softener = SustainSoftener()
    for step in range(100):
        current = frame if step % 15 < 10 else QUIET_FRAME
        assert softener.apply(current, enabled=True, now=step * .01) == current


def test_new_impact_restores_attack_after_sustained_hum_and_silence_resets():
    from sensa_multiband import SustainSoftener, pack_frame, QUIET_FRAME

    source = decode_frame(DUAL)
    for side in source["channels"]:
        for band in side["bands"]:
            for point in band:
                point["amplitude_code"] = 4
    hum = compose_frame(pack_frame(source), MixState(settings=Settings(grip_soft=True)))
    impact = compose_frame(DUAL, MixState(settings=Settings(grip_soft=True)))
    softener = SustainSoftener()
    outputs = [softener.apply(hum, enabled=True, now=step * .01) for step in range(50)]
    assert outputs[0] == hum
    assert totals(outputs[-1])[0] < totals(hum)[0]
    assert softener.apply(impact, enabled=True, now=.5) == impact
    assert softener.apply(QUIET_FRAME, enabled=True, now=.51) == QUIET_FRAME
    assert softener.apply(hum, enabled=True, now=.52) == hum


def test_continuous_and_pulsed_sides_are_softened_independently():
    from sensa_multiband import SustainSoftener, pack_frame

    steady = compose_frame(DUAL, MixState(settings=Settings(grip_soft=True)))
    softener = SustainSoftener()
    for step in range(61):
        source = decode_frame(steady)
        if step % 10 >= 5:
            for band in source["channels"][1]["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
        output = decode_frame(softener.apply(pack_frame(source), enabled=True, now=step * .01))
        assert output["channels"][1] == source["channels"][1]
    assert output["channels"][0]["bands"][1][0]["amplitude_code"] < source["channels"][0]["bands"][1][0]["amplitude_code"]


def test_disabling_softness_or_losing_audio_clears_sustain_history():
    from sensa_multiband import SustainSoftener

    softener = SustainSoftener()
    for step in range(41):
        softener.apply(DUAL, enabled=True, now=step * .01)
    assert softener.apply(DUAL, enabled=False, now=.41) == DUAL
    assert softener.apply(DUAL, enabled=True, now=.42) == DUAL
    assert softener.apply(DUAL, enabled=True, now=.6) == DUAL


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
    result = compose_frame(LEFT, MixState(rumble=(0, .2)))
    left, right = decode_frame(result)["channels"]
    # 历史帧首点处于预热阶段，原始码为 4；不能把稳定 60Hz 的预期码 9 套到这个夹具。
    assert left["bands"][0][0]["frequency_code"] == 4
    assert right["bands"][0][0] == {"amplitude_code": 13, "frequency_code": 7}
    assert max(totals(result)) <= 32


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


def test_backend_softens_continuous_audio_and_restores_attack_after_gap():
    output, _, mixer = backend()
    mailbox = PcmMailbox()
    state = MixState(settings=Settings(grip_soft=True))
    baseline = compose_frame(DUAL, state)
    try:
        for step in range(41):
            now = 1 + step * .01
            mailbox.configure(state, now=now)
            mailbox.push(bytes(480 * 4), now=now)
            output.render_pcm(mailbox.take(now=now), now=now)
        assert totals(mixer.play.call_args.args[1])[0] < totals(baseline)[0]
        mailbox.configure(state, now=1.5)
        mailbox.push(bytes(480 * 4), now=1.5)
        output.render_pcm(mailbox.take(now=1.5), now=1.5)
        assert mixer.play.call_args.args[1] == baseline
    finally:
        output.close()


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


def test_high_band_is_trimmed_only_when_it_dominates_the_low_band():
    from sensa_multiband import shape_high_band

    def make(low, high):
        side = decode_frame(DUAL)["channels"][0]
        for band, code in ((side["bands"][0], 7), (side["bands"][1], 41)):
            for point in band:
                point["frequency_code"] = code
        for point in side["bands"][0]:
            point["amplitude_code"] = low
        for point in side["bands"][1]:
            point["amplitude_code"] = high
        return side

    swing = make(10, 14)
    shape_high_band(swing)
    assert swing["bands"][1][0]["amplitude_code"] == 9
    assert swing["bands"][0][0]["amplitude_code"] == 10

    combat = make(14, 10)
    shape_high_band(combat)
    assert combat["bands"][1][0]["amplitude_code"] == 10


def test_small_level_flicker_is_held_but_strong_changes_pass_through():
    from sensa_multiband import LevelHold, pack_frame

    def frame(low):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=low, frequency_code=7)
        return pack_frame(source)

    def level(sent):
        return totals(sent)[0]

    hold = LevelHold()
    assert level(hold.apply(frame(8))) == 8
    assert level(hold.apply(frame(7))) == 8
    assert level(hold.apply(frame(12))) == 12


def test_faint_residue_is_lifted_into_a_layer_and_strong_content_survives():
    # 2026-10-21 用户实机：极弱低频残留改为抬成一层（见 FaintLayer 之前的门限改判）。
    from sensa_multiband import pack_frame

    def make(low):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=low, frequency_code=7)
        return pack_frame(source)

    quiet = compose_frame(make(4), MixState(settings=Settings(grip_soft=True)))
    assert totals(quiet) == [16, 16]
    loud = compose_frame(make(14), MixState(settings=Settings(grip_soft=True)))
    assert totals(loud) == [14, 14]


def test_small_low_band_frequency_jitter_is_held_but_large_changes_track():
    from sensa_multiband import FrequencyHold, pack_frame

    def frame(code):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=8, frequency_code=code)
        return pack_frame(source)

    def code_of(sent):
        return decode_frame(sent)["channels"][0]["bands"][0][0]["frequency_code"]

    hold = FrequencyHold()
    assert hold.apply(frame(7)) == frame(7)
    assert code_of(hold.apply(frame(9))) == 7
    assert code_of(hold.apply(frame(16))) == 16
    assert code_of(hold.apply(frame(15))) == 16


def test_faint_low_residue_is_lifted_into_a_layer_instead_of_read_as_noise():
    # 2026-10-21 用户实机：极弱的低频残留忽隐忽现，被听成底噪；抬成稳定的一层。
    from sensa_multiband import pack_frame

    def frame(low, high):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for band, code, level in ((side["bands"][0], 7, low), (side["bands"][1], 41, high)):
                for point in band:
                    point.update(amplitude_code=level, frequency_code=code)
        return pack_frame(source)

    def bands(frame_bytes):
        return [max(point["amplitude_code"] for point in band)
                for band in decode_frame(frame_bytes)["channels"][0]["bands"]]

    state = MixState(settings=Settings(grip_soft=True))
    assert bands(compose_frame(frame(3, 0), state)) == [16, 0]
    assert bands(compose_frame(frame(3, 2), state)) == [16, 2]
    assert bands(compose_frame(frame(9, 0), state)) == [9, 0]
    assert bands(compose_frame(frame(0, 0), state)) == [0, 0]


def test_faint_lift_only_applies_to_the_soft_game_path():
    from sensa_multiband import pack_frame

    source = decode_frame(DUAL)
    for side in source["channels"]:
        for band in side["bands"]:
            for point in band:
                point["amplitude_code"] = 0
        for point in side["bands"][0]:
            point.update(amplitude_code=3, frequency_code=7)
    frame = pack_frame(source)
    assert totals(compose_frame(frame, MixState())) == [0, 0]
    assert totals(compose_frame(frame, MixState(settings=Settings(grip_soft=True)))) == [16, 16]


def test_in_frame_ramp_smooths_moderate_level_changes_on_the_four_points():
    # 2026-10-21 实机：编码器把同一个值复制到全部四点（历史 66000 帧无一例外），
    # 幅度变化只能是 10ms 硬台阶，听感上的颗粒来自这里。
    from sensa_multiband import PointRamp, pack_frame

    def frame(low):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=low, frequency_code=7)
        return pack_frame(source)

    def points(sent):
        return [point["amplitude_code"] for point in decode_frame(sent)["channels"][0]["bands"][0]]

    ramp = PointRamp()
    assert points(ramp.apply(frame(8))) == [8, 8, 8, 8]
    assert points(ramp.apply(frame(10))) == [8, 9, 10, 10]
    assert points(ramp.apply(frame(8))) == [10, 9, 8, 8]
    assert points(ramp.apply(frame(9))) == [8, 8, 9, 9]


def test_ramp_keeps_strong_attacks_and_silence_hard_edged():
    from sensa_multiband import PointRamp, QUIET_FRAME, pack_frame

    def frame(low):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=low, frequency_code=7)
        return pack_frame(source)

    def points(sent):
        return [point["amplitude_code"] for point in decode_frame(sent)["channels"][0]["bands"][0]]

    ramp = PointRamp()
    ramp.apply(frame(4))
    assert points(ramp.apply(frame(20))) == [20, 20, 20, 20]
    assert ramp.apply(QUIET_FRAME) == QUIET_FRAME
    assert points(ramp.apply(frame(9))) == [9, 9, 9, 9]


def test_backend_writes_in_frame_ramps_only_while_soft_mode_is_on():
    from sensa_multiband import pack_frame

    def frame(low):
        source = decode_frame(DUAL)
        for side in source["channels"]:
            for band in side["bands"]:
                for point in band:
                    point["amplitude_code"] = 0
            for point in side["bands"][0]:
                point.update(amplitude_code=low, frequency_code=7)
        return pack_frame(source)

    output, encoder, mixer = backend()
    encoder.encode.side_effect = [frame(14), frame(17)] * 30
    mailbox = PcmMailbox()
    state = MixState(settings=Settings(grip_soft=True))
    plain = MixState(settings=Settings(grip_soft=False))

    def sent_frames():
        return [call.args[1] for call in mixer.play.call_args_list]

    def ramped(frames):
        return any(len({point["amplitude_code"] for point in band}) > 1
                   for frame in frames
                   for side in decode_frame(frame)["channels"] for band in side["bands"])

    def feed(origin, state):
        for step in range(6):
            now = origin + step * .01
            mailbox.configure(state, now=now)
            mailbox.push(bytes(480 * 4), now=now)
            output.render_pcm(mailbox.take(now=now), now=now)

    try:
        feed(1, state)
        assert ramped(sent_frames())
        mixer.play.reset_mock()
        feed(2, plain)
        assert not ramped(sent_frames())
    finally:
        output.close()


def test_frame_trace_records_sent_frames_and_stops_at_the_limit(tmp_path):
    from sensa_multiband import FrameTrace

    trace = FrameTrace(tmp_path / "frames.jsonl")
    trace.LIMIT = 3
    state = MixState(settings=Settings(grip_soft=True))
    for step in range(5):
        trace.record(trace.started + step * .01, DUAL, LEFT, state)
    trace.flush()
    rows = [json.loads(line) for line in (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["t"] for row in rows] == [0.0, 0.01, 0.02]
    assert rows[0]["sent"] == DUAL.hex() and rows[0]["raw"] == LEFT.hex()
    assert rows[0]["changed"] is True and rows[0]["soft"] is True
