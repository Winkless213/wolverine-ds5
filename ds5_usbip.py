"""USB/IP 服务端 + DualSense 虚拟设备，基于 Linux usbip 协议。"""
import socket
import struct
import threading
import time


# DS5 USB 描述符（简化版，只包含 HID 输入/输出）
DS5_DEVICE_DESC = bytes([
    0x12, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x40,
    0x4C, 0x05,  # VID 054C (Sony)
    0xCE, 0x0C,  # PID 0CE6 (DualSense)
    0x00, 0x01, 0x01, 0x02, 0x03, 0x01
])

DS5_CONFIG_DESC = bytes([
    # Configuration descriptor
    0x09, 0x02, 0x29, 0x00, 0x01, 0x01, 0x00, 0x80, 0xFA,
    # Interface descriptor (HID)
    0x09, 0x04, 0x00, 0x00, 0x02, 0x03, 0x00, 0x00, 0x00,
    # HID descriptor
    0x09, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x0B, 0x01,
    # Endpoint IN (0x81)
    0x07, 0x05, 0x81, 0x03, 0x40, 0x00, 0x05,
    # Endpoint OUT (0x02)
    0x07, 0x05, 0x02, 0x03, 0x40, 0x00, 0x05
])

# HID Report Descriptor (简化版，64 字节输入/输出)
DS5_HID_REPORT_DESC = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x05,  # Usage (Game Pad)
    0xA1, 0x01,  # Collection (Application)
    0x85, 0x01,  # Report ID (1)
    0x09, 0x30,  # Usage (X)
    0x09, 0x31,  # Usage (Y)
    0x09, 0x32,  # Usage (Z)
    0x09, 0x35,  # Usage (Rz)
    0x15, 0x00,  # Logical Minimum (0)
    0x26, 0xFF, 0x00,  # Logical Maximum (255)
    0x75, 0x08,  # Report Size (8)
    0x95, 0x04,  # Report Count (4)
    0x81, 0x02,  # Input (Data, Variable, Absolute)
    # 按钮
    0x05, 0x09,  # Usage Page (Button)
    0x19, 0x01,  # Usage Minimum (1)
    0x29, 0x0E,  # Usage Maximum (14)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x01,  # Logical Maximum (1)
    0x75, 0x01,  # Report Size (1)
    0x95, 0x0E,  # Report Count (14)
    0x81, 0x02,  # Input
    0x75, 0x02,  # Report Size (2) - padding
    0x95, 0x01,  # Report Count (1)
    0x81, 0x03,  # Input (Constant)
    # 扳机
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x33,  # Usage (Rx) - L2
    0x09, 0x34,  # Usage (Ry) - R2
    0x15, 0x00,  # Logical Minimum (0)
    0x26, 0xFF, 0x00,  # Logical Maximum (255)
    0x75, 0x08,  # Report Size (8)
    0x95, 0x02,  # Report Count (2)
    0x81, 0x02,  # Input
    # 填充到 64 字节
    0x75, 0x08,  # Report Size (8)
    0x95, 0x36,  # Report Count (54)
    0x81, 0x03,  # Input (Constant)
    # Output (震动)
    0x85, 0x02,  # Report ID (2)
    0x09, 0x00,  # Usage (Undefined)
    0x15, 0x00,  # Logical Minimum (0)
    0x26, 0xFF, 0x00,  # Logical Maximum (255)
    0x75, 0x08,  # Report Size (8)
    0x95, 0x30,  # Report Count (48)
    0x91, 0x02,  # Output
    0xC0  # End Collection
])


class Ds5Device:
    """简化的 DualSense HID 设备，只支持输入报告和震动输出。"""
    def __init__(self):
        self.input_state = self._default_input()
        self.output_request = None
        self.lock = threading.Lock()

    def _default_input(self):
        # DS5 输入报告格式（简化）
        return {
            "LX": 128, "LY": 128, "RX": 128, "RY": 128,
            "L2": 0, "R2": 0,
            "Buttons": 0, "DPad": 8  # 8 = 中立
        }

    def update_input(self, state):
        """更新输入状态（从 GIP 转换过来的 DS5 格式）。"""
        with self.lock:
            self.input_state = state

    def get_input_report(self):
        """生成 64 字节的 HID 输入报告。"""
        with self.lock:
            s = self.input_state
            report = bytearray(64)
            report[0] = 0x01  # Report ID
            # 摇杆（映射到 0-255）
            report[1] = (s["LX"] + 128) & 0xFF
            report[2] = (s["LY"] + 128) & 0xFF
            report[3] = (s["RX"] + 128) & 0xFF
            report[4] = (s["RY"] + 128) & 0xFF
            # 按钮（低 16 位）
            buttons = s["Buttons"]
            report[5] = buttons & 0xFF
            report[6] = (buttons >> 8) & 0xFF
            # DPad
            report[7] = s["DPad"]
            # 扳机
            report[8] = s["L2"]
            report[9] = s["R2"]
            return bytes(report)

    def set_output_report(self, data):
        """接收震动输出报告。"""
        if len(data) >= 5 and data[0] == 0x02:  # Report ID 2
            with self.lock:
                self.output_request = {
                    "right": data[1],  # 右马达
                    "left": data[2],   # 左马达
                    "rightTrigger": data[3],
                    "leftTrigger": data[4]
                }

    def read_output(self):
        """读取并清除震动请求。"""
        with self.lock:
            req = self.output_request
            self.output_request = None
            return req


class UsbIpServer:
    """USB/IP 服务端（简化版，只支持单设备单连接）。"""
    OP_REQ_DEVLIST = 0x8005
    OP_REP_DEVLIST = 0x0005
    OP_REQ_IMPORT = 0x8003
    OP_REP_IMPORT = 0x0003
    USBIP_CMD_SUBMIT = 0x0001
    USBIP_RET_SUBMIT = 0x0003

    def __init__(self, device, port=3240):
        self.device = device
        self.port = port
        self.server_sock = None
        self.client_sock = None
        self.attached = False
        self.running = False
        self.thread = None

    def start(self):
        """启动 USB/IP 服务端。"""
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", self.port))
        self.server_sock.listen(1)
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        """服务循环。"""
        while self.running:
            try:
                self.server_sock.settimeout(1.0)
                client, addr = self.server_sock.accept()
                self.client_sock = client
                self.attached = True
                self._handle_client(client)
            except socket.timeout:
                continue
            except Exception:
                pass
            finally:
                if self.client_sock:
                    self.client_sock.close()
                    self.client_sock = None
                self.attached = False

    def _handle_client(self, sock):
        """处理客户端请求。"""
        while self.running:
            try:
                sock.settimeout(0.1)
                header = sock.recv(48)
                if not header:
                    break
                if len(header) < 8:
                    continue

                version, command, status = struct.unpack(">HHI", header[:8])

                if command == self.OP_REQ_DEVLIST:
                    self._send_devlist(sock)
                elif command == self.OP_REQ_IMPORT:
                    self._send_import(sock)
                elif command == self.USBIP_CMD_SUBMIT:
                    self._handle_submit(sock, header)
            except socket.timeout:
                continue
            except Exception:
                break

    def _send_devlist(self, sock):
        """发送设备列表。"""
        reply = struct.pack(">HHII", 0x0111, self.OP_REP_DEVLIST, 0, 1)  # 1 device
        reply += b"/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1\0".ljust(256, b"\0")
        reply += b"1-1\0".ljust(32, b"\0")
        reply += struct.pack(">IHHHHH", 2, 0x054C, 0x0CE6, 0x0100, 0, 0)
        reply += b"Sony\0".ljust(32, b"\0")
        reply += b"DualSense\0".ljust(32, b"\0")
        reply += b"0001\0".ljust(32, b"\0")
        reply += struct.pack(">IBBBB", 1, 0, 0, 1, 0)  # 1 interface
        sock.sendall(reply)

    def _send_import(self, sock):
        """发送导入响应。"""
        reply = struct.pack(">HHII", 0x0111, self.OP_REP_IMPORT, 0, 0)
        reply += b"/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1\0".ljust(256, b"\0")
        reply += b"1-1\0".ljust(32, b"\0")
        reply += struct.pack(">IHHHHH", 2, 0x054C, 0x0CE6, 0x0100, 0, 0)
        sock.sendall(reply)

    def _handle_submit(self, sock, header):
        """处理 URB 提交。"""
        # 简化：只处理 IN 中断传输（读取输入报告）
        seqnum = struct.unpack(">I", header[4:8])[0]
        ep = header[16] & 0x7F
        direction = header[16] >> 7

        if direction == 1 and ep == 1:  # IN endpoint 0x81
            # 发送输入报告
            report = self.device.get_input_report()
            reply = struct.pack(">IIIIIIIIII", 0x00000003, seqnum, 0, 0, 0, 0, 0, 0, len(report), 0)
            sock.sendall(reply + report)
        elif direction == 0 and ep == 2:  # OUT endpoint 0x02
            # 接收震动输出（这里简化处理，实际需要读取数据）
            reply = struct.pack(">IIIIIIIIII", 0x00000003, seqnum, 0, 0, 0, 0, 0, 0, 0, 0)
            sock.sendall(reply)

    def stop(self):
        """停止服务。"""
        self.running = False
        if self.client_sock:
            self.client_sock.close()
        if self.server_sock:
            self.server_sock.close()
        if self.thread:
            self.thread.join(timeout=2)


def main():
    device = Ds5Device()
    server = UsbIpServer(device, port=3240)

    print("Starting USB/IP server on port 3240...")
    server.start()

    print("Server ready. Attach with: usbip attach -r 127.0.0.1 -b 1-1")

    try:
        while True:
            time.sleep(1)
            if server.attached:
                print("Device attached")
            # 测试：模拟按钮按下
            device.update_input({
                "LX": 128, "LY": 128, "RX": 128, "RY": 128,
                "L2": 0, "R2": 0,
                "Buttons": 0x20,  # 测试按钮
                "DPad": 8
            })
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
