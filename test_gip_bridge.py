import base64
import collections
import io
import json
import queue
import unittest
from unittest.mock import Mock, patch

import gip_bridge
from gip_bridge import (Haptics, NullOutput, Status, attach_virtual_ds5, drain, handle_command, input_due,
                        read_commands, reconnect_loop, supervise)
from settings import Settings


ATTACHED = """Imported USB devices
====================
Port 01: device in use at High Speed(480Mbps)
         Sony Corp. : DualSense wireless controller (PS5) (054c:0ce6)
           -> usbip://127.0.0.1:3240/1-1
"""


class SettingsMixTests(unittest.TestCase):
    def test_resistance_effect_does_not_vibrate_by_default(self):
        # 0x21 在真 DS5 上是扳机阻力，不是震动；默认不转成纽扣马达震动。
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(trigger_report(right_effect=FULL_FEEDBACK), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        output.set.assert_not_called()

    def test_vibration_effect_still_vibrates_without_resistance_mapping(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(trigger_report(right_effect=bytes.fromhex("26c0030000481200003200")), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertAlmostEqual(output.set.call_args.args[3], 3 / 8)

    def test_trigger_gain_zero_turns_trigger_motors_off(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_gain=0, trigger_resistance=True))
        haptics.accept(trigger_report(right_effect=FULL_FEEDBACK), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        output.set.assert_not_called()

    def test_trigger_switch_off_silences_trigger_motors_and_follow(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_enabled=False, trigger_follow=True, follow_ratio=1))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertEqual(output.set.call_args.args, (1, 1, 0, 0))

    def test_grip_switch_off_silences_grips_but_keeps_triggers(self):
        output = Mock()
        haptics = Haptics(output, Settings(grip_enabled=False))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 1))

    def test_grip_test_maps_lt_rt_to_grips_and_silences_everything_else(self):
        # 测试握把时按 LT/RT 只震左/右握把；游戏效果和扳机跟随都不能串进来。
        output = Mock()
        haptics = Haptics(output, Settings(grip_enabled=False, trigger_follow=True, follow_ratio=1))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        handle_command(haptics, {"type": "test", "target": "grip"})
        haptics.step(l2=255, r2=0, now=.001)
        self.assertEqual(output.set.call_args.args, (1, 0, 0, 0))

    def test_trigger_test_maps_lt_rt_to_trigger_motors_with_gain(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_gain=.5))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        handle_command(haptics, {"type": "test", "target": "trigger"})
        haptics.step(l2=0, r2=255, now=.001)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, .5))

    def test_ending_the_test_restores_game_output(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        handle_command(haptics, {"type": "test", "target": "grip"})
        haptics.step(l2=0, r2=0, now=.001)
        handle_command(haptics, {"type": "test", "target": None})
        haptics.step(l2=0, r2=0, now=.03)
        self.assertEqual(output.set.call_args.args, (1, 1, 0, 0))

    def test_grip_gain_scales_classic_rumble(self):
        output = Mock()
        haptics = Haptics(output, Settings(grip_gain=.5))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        self.assertEqual(output.set.call_args.args[:2], (.5, .5))

    def test_trigger_gain_scales_and_clamps_at_full(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_gain=1.5))
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertEqual(output.set.call_args.args[3], 1)

    def test_trigger_follow_mirrors_same_side_grip(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_follow=True, follow_ratio=.5))
        haptics.accept(rumble_report(0x03, right=0, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        self.assertEqual(output.set.call_args.args, (1, 0, .5, 0))

    def test_trigger_follow_keeps_stronger_trigger_effect(self):
        output = Mock()
        haptics = Haptics(output, Settings(trigger_follow=True, follow_ratio=.2))
        haptics.accept(rumble_report(0x03, right=255, left=0), now=0)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertEqual(output.set.call_args.args[3], 1)

    def test_settings_command_applies_without_restart(self):
        output = Mock()
        haptics = Haptics(output)
        self.assertFalse(handle_command(haptics, {"type": "settings", "settings": {"grip_gain": 0}}))
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        output.set.assert_not_called()

    def test_quit_command_requests_shutdown(self):
        self.assertTrue(handle_command(Haptics(Mock()), {"type": "quit"}))

    def test_invalid_test_target_is_ignored(self):
        haptics = Haptics(Mock())
        handle_command(haptics, {"type": "test", "target": "speaker"})
        self.assertIsNone(haptics.test_target)

    def test_stdin_settings_reach_haptics_through_the_event_queue(self):
        events = queue.Queue()
        read_commands(io.StringIO('{"type": "settings", "settings": {"trigger_gain": 0}}\nnot json\n'), events)
        haptics = Haptics(Mock())
        drain(events, haptics, collections.Counter())
        self.assertEqual(haptics.settings.trigger_gain, 0)

    def test_stdin_quit_stops_the_bridge(self):
        events = queue.Queue()
        read_commands(io.StringIO('{"type": "quit"}\n'), events)
        with self.assertRaises(KeyboardInterrupt):
            drain(events, Haptics(Mock()), collections.Counter())


class StatusTests(unittest.TestCase):
    def test_status_is_emitted_only_when_it_changes(self):
        lines = []
        status = Status(lines.append)
        status.set("waiting")
        status.set("waiting")
        status.set("connected", handshake_s=1.5)
        self.assertEqual([json.loads(line) for line in lines],
                         [{"type": "status", "state": "waiting"},
                          {"type": "status", "state": "connected", "handshake_s": 1.5}])

    def test_managed_bridge_quits_when_the_app_closes_stdin(self):
        events = queue.Queue()
        read_commands(io.StringIO(""), events, quit_on_eof=True)
        with self.assertRaises(KeyboardInterrupt):
            drain(events, Haptics(Mock()), collections.Counter())

    def test_manual_bridge_ignores_stdin_eof(self):
        events = queue.Queue()
        read_commands(io.StringIO(""), events)
        self.assertTrue(events.empty())


class ProcessCommandTests(unittest.TestCase):
    """桥接内部重启（supervise）后，界面发来的设置仍要送达新一轮会话。"""

    def test_commands_from_the_process_reader_reach_a_fresh_session(self):
        commands = queue.Queue()
        read_commands(io.StringIO('{"type": "settings", "settings": {"grip_gain": 0.2}}\n'), commands)
        haptics = Haptics(Mock())
        drain(queue.Queue(), haptics, collections.Counter(), commands=commands)
        self.assertEqual(haptics.settings.grip_gain, 0.2)

    def test_restarted_serve_does_not_start_a_second_stdin_reader(self):
        # 两个线程同时读 stdin 会把命令分走，被旧会话的队列吞掉。
        capture = Mock()
        capture.stdout.readline.return_value = '{"type": "ready", "address": "127.0.0.1:3240", "busid": "1-1"}\n'
        with patch.object(gip_bridge, "threading") as threading, \
                patch.object(gip_bridge, "attach_virtual_ds5"), patch.object(gip_bridge.audio_guard, "start"), \
                patch.object(gip_bridge.settings, "load", return_value=Settings()), \
                patch.object(gip_bridge, "reconnect_loop", return_value=1):
            gip_bridge.serve(capture)
            gip_bridge.serve(capture)
        targets = [call.kwargs.get("target") for call in threading.Thread.call_args_list]
        self.assertNotIn(read_commands, targets)


class ReconnectTests(unittest.TestCase):
    def test_unplugged_controller_is_retried_while_virtual_ds5_stays(self):
        transport = Mock()
        opener = Mock(side_effect=[RuntimeError("USB device not found"), OSError("busy"), transport])
        session = Mock(return_value=1)
        self.assertEqual(reconnect_loop(opener, session, wait=Mock(), alive=lambda: True), 1)
        self.assertEqual(opener.call_count, 3)
        session.assert_called_once_with(transport)

    def test_disconnect_mid_session_closes_transport_and_reconnects(self):
        first, second = Mock(), Mock()
        opener = Mock(side_effect=[first, second])
        session = Mock(side_effect=[OSError("No such device"), 1])
        self.assertEqual(reconnect_loop(opener, session, wait=Mock(), alive=lambda: True), 1)
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_capture_exit_ends_reconnect_loop(self):
        opener = Mock(side_effect=RuntimeError("USB device not found"))
        alive = Mock(side_effect=[True, False])
        self.assertEqual(reconnect_loop(opener, Mock(), wait=Mock(), alive=alive), 1)

    def test_trigger_effect_sent_while_disconnected_applies_after_reconnect(self):
        haptics = Haptics(NullOutput())
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        output = Mock()
        haptics.attach(output)
        haptics.step(l2=0, r2=255, now=5)
        self.assertAlmostEqual(output.set.call_args.args[3], 1)


class AttachTests(unittest.TestCase):
    def test_restarted_bridge_attaches_its_own_virtual_ds5(self):
        run = Mock(return_value=Mock(stdout="Imported USB devices\n", returncode=0))
        attach_virtual_ds5("127.0.0.1:3240", "1-1", run=run)
        args = run.call_args.args[0]
        self.assertEqual(args[1:], ["-t", "3240", "attach", "-r", "127.0.0.1", "-b", "1-1", "--once"])

    def test_already_attached_device_is_not_attached_twice(self):
        run = Mock(return_value=Mock(stdout=ATTACHED, returncode=0))
        attach_virtual_ds5("127.0.0.1:3240", "1-1", run=run)
        self.assertEqual(run.call_count, 1)


class SuperviseTests(unittest.TestCase):
    def test_failed_bridge_is_restarted_until_clean_exit(self):
        run = Mock(side_effect=[1, RuntimeError("USB device not found"), 0])
        self.assertEqual(supervise(run=run, wait=Mock()), 0)
        self.assertEqual(run.call_count, 3)

    def test_ctrl_c_stops_without_restart(self):
        run = Mock(side_effect=KeyboardInterrupt)
        self.assertEqual(supervise(run=run, wait=Mock()), 0)
        self.assertEqual(run.call_count, 1)


class InputKeepaliveTests(unittest.TestCase):
    def test_held_state_is_resent_before_capture_watchdog_releases_it(self):
        # wolverine-capture 250ms 无输入即松开全部按键；按住不动时必须在此之前重发。
        self.assertTrue(input_due({"A": 1}, {"A": 1}, now=.1, last_sent=0))

    def test_unchanged_state_is_not_resent_every_loop(self):
        self.assertFalse(input_due({"A": 1}, {"A": 1}, now=.05, last_sent=0))

    def test_changed_state_is_sent_immediately(self):
        self.assertTrue(input_due({"A": 0}, {"A": 1}, now=.001, last_sent=0))


def trigger_report(right_effect=None, left_effect=None):
    report = bytearray(48)
    report[0] = 2
    if right_effect:
        report[1] |= 4
        report[11:22] = right_effect
    if left_effect:
        report[1] |= 8
        report[22:33] = left_effect
    return {"type": "output", "report": base64.b64encode(bytes(report)).decode()}


def rumble_report(flag0, right, left, flag2=0):
    report = bytearray(48)
    report[0], report[1], report[3], report[4], report[39] = 2, flag0, right, left, flag2
    return {"type": "output", "report": base64.b64encode(bytes(report)).decode()}


# 模式 0x21：全部 10 个区段最强（packed 3 位 = 7 → 1.0）；按原生比例还原后满幅 1.0。
FULL_FEEDBACK = bytes((0x21, 0xFF, 0x03, 0xFF, 0xFF, 0xFF, 0x3F, 0, 0, 0, 0))
# 模式 0x26：全部区段最强、50Hz（>20Hz 时降级为持续震动）。
FULL_VIBRATION = bytes((0x26, 0xFF, 0x03, 0xFF, 0xFF, 0xFF, 0x3F, 0, 0, 0x32, 0))


class HapticsTests(unittest.TestCase):
    def test_trigger_effect_drives_only_the_pressed_trigger_motor(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        left, right, lt, rt = output.set.call_args.args
        self.assertEqual((left, right, lt), (0, 0, 0))
        self.assertAlmostEqual(rt, 1)

    def test_game_strength_reaches_the_motor_in_native_proportion(self):
        output = Mock()
        haptics = Haptics(output)
        # DS2 实测效果：0x26，60% 行程以后，强度 3/8 档，50Hz。
        haptics.accept(trigger_report(right_effect=bytes.fromhex("26c00300004812000032 00".replace(" ", ""))), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        self.assertAlmostEqual(output.set.call_args.args[3], 3 / 8)

    def test_stopped_capture_clears_all_four_motors(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        haptics.accept({"type": "stopped"}, now=.002)
        haptics.step(l2=0, r2=255, now=.025)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_malformed_output_report_stops_motors_and_raises(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(trigger_report(right_effect=FULL_VIBRATION), now=0)
        haptics.step(l2=0, r2=255, now=.001)
        with self.assertRaises(ValueError):
            haptics.accept({"type": "output", "report": base64.b64encode(b"\x09").decode()}, now=.002)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_classic_rumble_drives_grip_motors_in_native_proportion(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x03, right=51, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        left, right, lt, rt = output.set.call_args.args
        self.assertAlmostEqual(left, 1)
        self.assertAlmostEqual(right, .2)
        self.assertEqual((lt, rt), (0, 0))

    def test_report_without_rumble_flag_keeps_the_current_rumble(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x03, right=0, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        haptics.accept(rumble_report(0x00, right=0, left=0), now=.002)
        haptics.step(l2=0, r2=0, now=.03)
        self.assertAlmostEqual(output.set.call_args.args[0], 1)

    def test_vibration_v2_flag_also_updates_rumble(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x02, right=0, left=255, flag2=0x04), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        self.assertAlmostEqual(output.set.call_args.args[0], 1)

    def test_main_loop_stall_stops_motors_then_keeps_running(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        haptics.step(l2=0, r2=0, now=.2)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))
        self.assertEqual(haptics.stalls, 1)
        haptics.accept(rumble_report(0x03, right=0, left=255), now=.21)
        haptics.step(l2=0, r2=0, now=.22)
        self.assertAlmostEqual(output.set.call_args.args[0], 1)

    def test_stopped_capture_cannot_revive_classic_rumble(self):
        output = Mock()
        haptics = Haptics(output)
        haptics.accept(rumble_report(0x03, right=255, left=255), now=0)
        haptics.step(l2=0, r2=0, now=.001)
        haptics.accept({"type": "stopped"}, now=.002)
        # 新一代 capture 会清掉 ended；旧的传统震动不能随之复活。
        haptics.accept({"type": "reset", "generation": 2}, now=.003)
        haptics.step(l2=0, r2=0, now=.03)
        self.assertEqual(output.set.call_args.args, (0, 0, 0, 0))

    def test_audio_frame_jump_resyncs_instead_of_raising(self):
        haptics = Haptics(Mock())
        haptics.accept(audio_block(first=0), now=0)
        # 剑星启动时重开触觉流，帧号跳变；桥接不能因此退出。
        haptics.accept(audio_block(first=5000), now=.001)
        self.assertEqual(haptics.audio_errors, 1)
        haptics.accept(audio_block(first=5048), now=.002)
        self.assertEqual(haptics.audio_errors, 1)
        self.assertEqual(haptics.bridge.stats["audio_frames"], 96)

    def test_late_audio_block_is_dropped_instead_of_raising(self):
        haptics = Haptics(Mock())
        haptics.accept(dict(audio_block(first=0), host_queue_us=80000), now=0)
        self.assertEqual(haptics.audio_errors, 1)
        haptics.accept(audio_block(first=48), now=.001)
        self.assertEqual(haptics.bridge.stats["audio_frames"], 48)


def audio_block(first, frames=48):
    return {"type": "audio", "generation": 1, "first_frame": first, "frames": frames,
            "source": "usb-host", "sample_rate": 48000,
            "pcm": base64.b64encode(bytes(frames * 4)).decode()}


if __name__ == "__main__":
    unittest.main()
