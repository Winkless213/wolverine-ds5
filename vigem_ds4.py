"""ViGEm DS4 虚拟设备，通过 vgamepad 库控制。"""
try:
    import vgamepad as vg
except ImportError:
    print("ERROR: vgamepad not installed. Run: pip install vgamepad")
    raise


class VigemDs4:
    """ViGEm 虚拟 DS4 设备。"""
    def __init__(self):
        self.gamepad = vg.VDS4Gamepad()
        self.last_rumble = None

    def update_input(self, state):
        """更新输入状态（DS5 格式 → DS4）。"""
        # 摇杆：-128..127 → 0..255
        self.gamepad.left_joystick(
            x_value=state["LX"] + 128,
            y_value=state["LY"] + 128
        )
        self.gamepad.right_joystick(
            x_value=state["RX"] + 128,
            y_value=state["RY"] + 128
        )

        # 扳机：0..255
        self.gamepad.left_trigger(value=state["L2"])
        self.gamepad.right_trigger(value=state["R2"])

        # 按钮映射
        buttons = state["Buttons"]
        dpad = state["DPad"]

        # DS4 按钮（按位检查）
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SQUARE) if buttons & 0x10 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_SQUARE)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_CROSS) if buttons & 0x20 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_CROSS)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE) if buttons & 0x40 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_CIRCLE)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE) if buttons & 0x80 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_TRIANGLE)

        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT) if buttons & 0x100 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT) if buttons & 0x200 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT)

        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_SHARE) if buttons & 0x1000 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_SHARE)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS) if buttons & 0x2000 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_OPTIONS)

        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT) if buttons & 0x4000 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT)
        self.gamepad.press_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT) if buttons & 0x8000 else self.gamepad.release_button(vg.DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT)

        # DPad (DS5 用 0-7 表示八个方向，8 表示中立)
        if dpad == 0:  # 上
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH)
        elif dpad == 1:  # 右上
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHEAST)
        elif dpad == 2:  # 右
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST)
        elif dpad == 3:  # 右下
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHEAST)
        elif dpad == 4:  # 下
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH)
        elif dpad == 5:  # 左下
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHWEST)
        elif dpad == 6:  # 左
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST)
        elif dpad == 7:  # 左上
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHWEST)
        else:  # 8 或其他 = 中立
            self.gamepad.directional_pad(direction=vg.DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE)

        # 提交更新
        self.gamepad.update()

    def read_output(self):
        """读取震动输出（ViGEm 目前不支持读取震动反馈）。"""
        # ViGEm 不提供震动反馈接口，返回 None
        return None

    def close(self):
        """关闭虚拟设备。"""
        # vgamepad 会在对象销毁时自动清理
        pass
