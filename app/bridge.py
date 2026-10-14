"""托管桥接子进程：stdout 按行解析成状态/电平信号，除电平外写入按天切分的日志。"""
import datetime

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from app import core


class Bridge(QObject):
    status = Signal(dict)
    meter = Signal(dict)
    running = Signal(bool)
    log = Signal(str)

    def __init__(self, command, cwd, log_dir, parent=None, make_command=None):
        super().__init__(parent)
        self.command, self.log_dir, self.log_day = command, log_dir, None
        # PC 模式与 Xbox 模式各有一个桥接脚本；None 表示还没按手柄模式选过。
        self.make_command, self.pc = make_command, None
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(cwd))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("WOLVERINE_MANAGED", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        # 关闭 stdin 后桥接会自行清理（停 capture、马达归零）；超时才强制结束。
        self.kill_timer = QTimer(self, singleShot=True, interval=5000, timeout=self.process.kill)

    @property
    def is_running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def set_pc(self, pc):
        # 只影响下一次启动；正在运行的桥接由调用方先停掉。
        self.pc = pc
        if self.make_command:
            self.command = self.make_command(pc)

    def start(self):
        if self.is_running:
            return
        self._write("--- bridge started: " + " ".join(self.command))
        self.process.start(self.command[0], self.command[1:])
        self.running.emit(True)

    def stop(self):
        if self.is_running:
            self.process.closeWriteChannel()
            self.kill_timer.start()

    def shutdown(self):
        self.stop()
        if self.is_running and not self.process.waitForFinished(5000):
            self.process.kill()
            self.process.waitForFinished(1000)

    def send(self, line):
        if self.process.state() == QProcess.ProcessState.Running:
            self.process.write((line + "\n").encode("utf-8"))

    def _read(self):
        while self.process.canReadLine():
            self._handle(bytes(self.process.readLine()).decode("utf-8", "replace"))

    def _handle(self, line):
        message = core.parse_line(line)
        if message["type"] == "meter":
            self.meter.emit(message)
            return
        self._write(line.rstrip("\r\n"))
        if message["type"] == "status":
            self.status.emit(message)
        else:
            self.log.emit(message["text"])

    def _finished(self, code, _status):
        self.kill_timer.stop()
        rest = bytes(self.process.readAll()).decode("utf-8", "replace")
        for line in rest.splitlines():
            self._handle(line)
        self._write(f"--- bridge exited (code {code})")
        self.running.emit(False)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._write(f"--- bridge failed to start: {self.process.errorString()}")
            self.running.emit(False)

    def _write(self, text):
        today = datetime.date.today()
        if today != self.log_day:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            core.prune_logs(self.log_dir)
            self.log_day = today
        stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(core.daily_log_path(self.log_dir, today), "a", encoding="utf-8") as file:
            file.write(f"{stamp} {text}\n")
