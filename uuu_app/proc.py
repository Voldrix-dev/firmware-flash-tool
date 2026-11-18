from .qt import QtCore


class UuuProcess(QtCore.QObject):
    output = QtCore.Signal(str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._stdout)
        self.proc.readyReadStandardError.connect(self._stderr)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error_occurred)
        self.error_flag = False
        self._stdout_buf = ""
        self._stderr_buf = ""

    def flash(self, dev_path, boot, firmware):
        self.error_flag = False
        # CMD_1 = "uuu -v -m", CMD_2 = "-b emmc_all" in original
        self.proc.start("uuu", ["-v", "-m", dev_path, "-b", "emmc_all", boot, firmware])

    def terminate(self):
        self.proc.terminate()

    def kill(self):
        self.proc.kill()

    def _stdout(self):
        chunk = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        self._stdout_buf += chunk
        self._process_buffer('_stdout_buf', self.output)

    def _stderr(self):
        chunk = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        self._stderr_buf += chunk
        self.error_flag = True
        self._process_buffer('_stderr_buf', self.error)

    def _process_buffer(self, attr_name, signal):
        buf = getattr(self, attr_name)
        while "\n" in buf or "\r" in buf:
            pos_n = buf.find("\n") if "\n" in buf else len(buf) + 1
            pos_r = buf.find("\r") if "\r" in buf else len(buf) + 1
            pos = min(pos_n, pos_r)
            piece = buf[:pos]
            buf = buf[pos + 1:]
            if piece:
                signal.emit(piece)
        setattr(self, attr_name, buf)

    def _finished(self, code, status):
        if self._stdout_buf:
            self.output.emit(self._stdout_buf)
            self._stdout_buf = ""
        if self._stderr_buf:
            self.error.emit(self._stderr_buf)
            self._stderr_buf = ""
        self.finished.emit(code, self.error_flag)

    def _error_occurred(self, error):
        self.error.emit(f"QProcess start error: {self.proc.errorString()}")
        self.error_flag = True

class UuuScriptProcess(QtCore.QObject):
    output = QtCore.Signal(str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal(int, bool)
    # A failed UUU command is not safe to repeat: the device may already be
    # in a partially changed state. Abort immediately instead.
    MAX_ATTEMPTS = 1
    COMMAND_TIMEOUT_MS = 60 * 1000
    FLASH_TIMEOUT_MS = 15 * 60 * 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = QtCore.QProcess(self)
        self.proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._stdout)
        self.proc.readyReadStandardError.connect(self._stderr)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error_occurred)
        self.error_flag = False
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._command_buf = ""
        self._started = False
        self._command_index = 0
        self._current_command = None
        self._attempt = 0
        self._stopping = False
        self._quit_sent = False
        self._command_timer = QtCore.QTimer(self)
        self._command_timer.setSingleShot(True)
        self._command_timer.timeout.connect(self._command_timeout)

    def flash(self, dev_path, boot, firmware):
        self.error_flag = False
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._command_buf = ""
        self._command_index = 0
        self._current_command = None
        self._attempt = 0
        self._started = False
        self._stopping = False
        self._quit_sent = False
        self.dev_path = dev_path
        self.boot = boot
        self.firmware = firmware
        self.commands = [
            f"SDPS: boot -scanterm -f {boot} -scanlimited 0x800000",
            "FB: ucmd setenv fastboot_dev mmc",
            "FB: ucmd setenv mmcdev ${emmc_dev}",
            "FB: ucmd mmc dev ${emmc_dev}",
            # UUU uses /* to expand the compressed firmware payload. Without
            # it a .bz2 file can be accepted immediately without flashing it.
            f"FB: flash -raw2sparse all {firmware}/*",
            f"FB: flash -scanterm -scanlimited 0x800000 bootloader {boot}",
            "FB: ucmd if env exists emmc_ack; then ; else setenv emmc_ack 0; fi;",
            "FB: ucmd mmc partconf ${emmc_dev} ${emmc_ack} 1 0",
            "FB: done",
            "FB: reboot",
        ]
        self.proc.start("uuu", ["-s", "-m", dev_path])

    def terminate(self):
        self._stopping = True
        self.proc.terminate()

    def kill(self):
        self._stopping = True
        self.proc.kill()

    def _stdout(self):
        chunk = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        self._stdout_buf += chunk
        self._process_output()

    def _stderr(self):
        chunk = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        self._stderr_buf += chunk
        self._process_buffer('_stderr_buf', self.error)

    def _process_output(self):
        chunk = self._stdout_buf
        self._command_buf += chunk
        self._stdout_buf = ""
        # Keep the panel's line-oriented output contract, while retaining a
        # separate buffer for the U> command prompt parser.
        self._stdout_buf = chunk
        self._process_buffer('_stdout_buf', self.output)
        self._check_command()

    def _check_command(self):
        while "U>" in self._command_buf:
            before, self._command_buf = self._command_buf.split("U>", 1)
            if self._current_command is None:
                if not self._started:
                    self._started = True
                    self._send_next_command()
                continue
            if "Fail" in before:
                self._command_failed()
                return
            if "Okay" in before:
                self._command_finished()
                return

    def _command_failed(self):
        command = self._current_command
        self._command_timer.stop()
        self.error_flag = True
        self.error.emit(f"Command failed: {command}")
        self._abort()

    def _command_finished(self):
        self._command_timer.stop()
        self._current_command = None
        self._attempt = 0
        self._command_index += 1
        QtCore.QTimer.singleShot(100, self._send_next_command)

    def _command_timeout(self):
        if self._stopping or self._current_command is None:
            return
        command = self._current_command
        self.error_flag = True
        self.error.emit(f"Command timeout: {command}")
        self._abort()

    def _send_next_command(self):
        if self._stopping:
            return
        if self._command_index >= len(self.commands):
            self._finish_all()
            return
        self._attempt = 1
        self._current_command = self.commands[self._command_index]
        self._send_current_command()

    def _send_current_command(self):
        if self._stopping:
            return
        command = self._current_command
        self.proc.write((command + "\n").encode("utf-8"))
        self.proc.waitForBytesWritten(1000)
        timeout = (
            self.FLASH_TIMEOUT_MS
            if command.startswith("FB: flash -raw2sparse")
            else self.COMMAND_TIMEOUT_MS
        )
        self._command_timer.start(timeout)

    def _finish_all(self):
        if self._quit_sent:
            return
        self._quit_sent = True
        self.proc.write(b"quit\n")
        self.proc.waitForBytesWritten(1000)

    def _abort(self):
        if self._quit_sent:
            return
        self._stopping = True
        self._quit_sent = True
        self._command_timer.stop()
        self.proc.write(b"quit\n")
        self.proc.waitForBytesWritten(1000)
        # Some libusb failures leave uuu waiting despite `quit`.
        QtCore.QTimer.singleShot(1000, self._terminate_after_abort)

    def _terminate_after_abort(self):
        if self.proc.state() == QtCore.QProcess.ProcessState.NotRunning:
            return
        self.proc.terminate()
        QtCore.QTimer.singleShot(1000, self._kill_after_abort)

    def _kill_after_abort(self):
        if self.proc.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.proc.kill()

    def _process_buffer(self, attr_name, signal):
        buf = getattr(self, attr_name)
        while "\n" in buf or "\r" in buf:
            pos_n = buf.find("\n") if "\n" in buf else len(buf) + 1
            pos_r = buf.find("\r") if "\r" in buf else len(buf) + 1
            pos = min(pos_n, pos_r)
            piece = buf[:pos]
            buf = buf[pos + 1:]
            if piece:
                signal.emit(piece)
        setattr(self, attr_name, buf)

    def _finished(self, code, status):
        if self._stdout_buf:
            self.output.emit(self._stdout_buf)
            self._stdout_buf = ""
        if self._stderr_buf:
            self.error.emit(self._stderr_buf)
            self._stderr_buf = ""
        self.finished.emit(code, self.error_flag)

    def _error_occurred(self, error):
        self.error.emit(f"QProcess start error: {self.proc.errorString()}")
        self.error_flag = True


def reboot_device(dev_path, parent=None):
    """Fire-and-forget QProcess reboot. No signals connected — cannot loop."""
    proc = QtCore.QProcess(parent)
    proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
    # -t 2: timeout 2s waiting for device, so it never hangs forever
    proc.start("uuu", ["-m", dev_path, "-t", "2", "-s"])
    proc.write(b"FB: reboot\nquit\n")
    proc.closeWriteChannel()
