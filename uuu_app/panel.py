import os
import time
from enum import Enum, auto

from . import cfg
from .proc import UuuProcess, UuuScriptProcess, reboot_device
from .qt import QtCore, QtGui, QtWidgets, Slot, Signal
from .ui import ClickableLabel, PanelSignals, RoundedProgressBar
from .util import format_t, is_main_log_noise
import qtawesome as qta


class ProgressMode(Enum):
    SDPS = auto()
    FLASH = auto()


class FlashStage(Enum):
    WAIT_DEVICE = "WAIT_DEVICE"
    SDPS_BOOT = "SDPS_BOOT"
    FLASH_ROOTFS = "FLASH_ROOTFS"
    FLASH_BOOTLOADER = "FLASH_BOOTLOADER"
    FINALIZE = "FINALIZE"
    DONE = "DONE"

class DevicePanelWidget(QtWidgets.QWidget):
    path_changed = Signal(str, str)

    def __init__(self, name, dev_path, parent=None):
        super().__init__(parent)
        self.name = name
        self.dev_path = dev_path
        self.auto = False
        self.stop_flag = False
        self.is_flashing = False
        self.require_disconnect = False
        self.post_flash_time = None
        self.last_flash_ok = False
        self.current_percent = 0
        self.uuu = None
        self.use_script_process = False
        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.timeout.connect(self._auto_timer_tick)
        self.raw_log_buffer = []
        self.last_error_log = ""
        self.status_state = "idle"
        self.progress_mode = ProgressMode.SDPS
        self.flash_stage = FlashStage.WAIT_DEVICE
        self.progress_total_bytes = 0
        self.byte_progress_max = 0
        self.is_progress_calibrator = False
        self.calibration_session_active = False
        self.blink_on_complete = False
        self.eta_samples = []          # (elapsed, percent) для сглаживания ETA
        self.eta_smoothed = None       # сглаженное оставшееся время, сек
        self.eta_text = "--:--"
        self.elapsed_text = "00:00"
        self.signals = PanelSignals()
        self.signals.log.connect(self.append_log)
        self.signals.progress.connect(self._update_progress)
        self.signals.set_bg.connect(self.set_bg)
        self.signals.clear.connect(self.clear_log)
        self.signals.info.connect(self.set_info)
        self.signals.auto_state.connect(self._set_auto_button_state)
        self.signals.error_marker.connect(self._set_error_marker_visible)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(3, 3, 3, 3)
        main_layout.setSpacing(3)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(5)
        self.lbl = ClickableLabel(name)
        self.lbl.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self.lbl.clicked.connect(self.show_error_log_dialog)
        self.lbl.setToolTip("")
        self.info_label = QtWidgets.QLabel("Not Run")
        self.info_label.setFixedWidth(82)
        self.info_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.last_error_hint = ""
        self.dev_entry = QtWidgets.QLineEdit()
        self.dev_entry.setFixedWidth(66)
        if self.dev_path:
            self.dev_entry.setText(self.dev_path)
        self.dev_entry.setToolTip("USB path (пример: 1:7)")
        self.dev_entry.returnPressed.connect(self.apply_dev_path)
        self.btn_once = QtWidgets.QPushButton()
        self.btn_once.setFixedSize(24, 24)
        self.btn_once.setIcon(qta.icon("fa5s.play", color="white"))
        self.btn_once.setToolTip("Однократный запуск прошивки")
        self.btn_auto = QtWidgets.QPushButton()
        self.btn_auto.setFixedSize(24, 24)
        self.btn_auto.setIcon(qta.icon("fa5s.sync-alt", color="white"))
        self.btn_auto.setToolTip("Вкл/Откл автоматического режима")
        self.btn_stop = QtWidgets.QPushButton()
        self.btn_stop.setFixedSize(24, 24)
        self.btn_stop.setIcon(qta.icon("fa5s.stop", color="white"))
        self.btn_stop.setToolTip("Остановить текущую прошивку")
        self.btn_process = QtWidgets.QPushButton()
        self.btn_process.setCheckable(True)
        self.btn_process.setFixedSize(24, 24)
        self.btn_process.setIcon(qta.icon("fa5s.code", color="white"))
        self.btn_process.setToolTip("Переключить способ прошивки: UuuProcess / UuuScriptProcess")
        header.addWidget(self.lbl)
        header.addWidget(self.info_label)
        header.addSpacing(8)
        header.addWidget(self.dev_entry)
        header.addStretch()
        header.addWidget(self.btn_once)
        header.addWidget(self.btn_auto)
        header.addWidget(self.btn_stop)
        header.addWidget(self.btn_process)
        main_layout.addLayout(header)
        frame = QtWidgets.QFrame()
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(2)
        self.text = QtWidgets.QTextEdit()
        self.text.setReadOnly(True)
        self.text.document().setDocumentMargin(2)
        self.eta_label = QtWidgets.QLabel()
        self.eta_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.eta_label.setStyleSheet("color: #ffd54f; font-weight: 700;")
        self.eta_label.setFixedWidth(80)
        self.eta_label.setToolTip("Оставшееся время (сглаженное по последним 3 обновлениям)")
        self.elapsed_label = QtWidgets.QLabel()
        self.elapsed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.elapsed_label.setStyleSheet("color: #88ddff; font-weight: 700;")
        self.elapsed_label.setFixedWidth(80)
        self.elapsed_label.setToolTip("Прошедшее время прошивки")
        self.eta_timer = QtCore.QTimer(self)
        self.eta_timer.setInterval(1000)
        self.eta_timer.timeout.connect(self._tick_elapsed)
        self.progress_bar = RoundedProgressBar()
        time_row = QtWidgets.QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(0)
        time_row.addWidget(self.elapsed_label)
        time_row.addWidget(self.progress_bar, 1)
        time_row.addWidget(self.eta_label)
        frame_layout.addWidget(self.text)
        frame_layout.addLayout(time_row)
        main_layout.addWidget(frame)
        self.btn_once.clicked.connect(self.start_once)
        self.btn_auto.clicked.connect(self.toggle_auto)
        self.btn_stop.clicked.connect(self.stop_worker)
        self.btn_process.toggled.connect(self._set_process_mode)
        self.set_bg("idle")

    @Slot(bool)
    def _set_process_mode(self, use_script):
        if self.is_flashing:
            self.btn_process.blockSignals(True)
            self.btn_process.setChecked(self.use_script_process)
            self.btn_process.blockSignals(False)
            self.signals.log.emit("Нельзя менять процесс во время прошивки", "yellow")
            return
        self.use_script_process = use_script
        mode = "UuuScriptProcess" if use_script else "UuuProcess"
        self.btn_process.setStyleSheet(
            "QPushButton { background-color: #8BC34A; color: black; }" if use_script else ""
        )
        self.btn_process.setIcon(qta.icon("fa5s.code", color="black" if use_script else "white"))
        self.btn_process.setToolTip(f"Текущий процесс: {mode}. Нажмите для переключения")
        self.signals.log.emit(f"Process: {mode}", "#AAAAAA")

    def set_process_mode(self, use_script):
        """Set the process mode through the same path as the panel button."""
        self.btn_process.setChecked(bool(use_script))

    def toggle_process_mode(self):
        self.set_process_mode(not self.use_script_process)

    def apply_dev_path(self):
        text = self.dev_entry.text().strip()
        if text:
            self.dev_path = text
            self.signals.log.emit(f"dev_path -> {text}", "#6CEC70")
            self.signals.info.emit("Ready", "idle")
            self.path_changed.emit(self.name, text)

    def get_usb_devices(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "usb_devices"):
                return parent.usb_devices
            parent = parent.parent()
        return {}
    
    def usb_device_present(self):
        devices = self.get_usb_devices()
        for path, dev in devices.items():
            if path != self.dev_path:
                continue
            mode = dev.get("mode", "")
            if cfg.DEVICE_KEY in mode:
                return True
        return False

    @Slot(str, str)
    def append_log(self, msg, color_tag):
        fmt = QtGui.QTextCharFormat()
        fmt.setForeground(QtGui.QColor(color_tag))
        cursor = self.text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(msg + "\n", fmt)
        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()

    @Slot(str)
    def set_bg(self, status):
        bg_colors = {"idle": "#111111", "working": "#222222", "ok": "#6CEC70", "error": "#FF5D5B", "warning": "#FFEB3B"}
        fg_colors = {"idle": "#CCCCCC", "working": "#FFFFFF", "ok": "#FFFFFF", "error": "#FFFFFF", "warning": "#000000"}
        bg = bg_colors.get(status, "#111111")
        fg = fg_colors.get(status, "#FFFFFF")
        self.text.setStyleSheet(
            f"QTextEdit {{ background-color: {bg}; color: {fg}; }} QTextEdit QWidget {{ background-color: {bg}; }}"
        )

    @Slot(str, str)
    def set_info(self, info, status):
        self.status_state = status
        fg_colors = {"idle": "#C700BD", "working": "#CCCCCC", "ok": "#00FC0D", "error": "#FF0000", "warning": "#FFEB3B"}
        fg = fg_colors.get(status, "#CCCCCC")
        self.info_label.setStyleSheet(f"color: {fg};")
        self.info_label.setText(info)

    @Slot(int, str)
    def _update_progress(self, value, color):
        if color in ("sdps", "flash"):
            self.progress_bar.setMode(color)
        elif color == "red":
            color = "#FA3B37"
            self.progress_bar.setColor(color)
        self.progress_bar.setValue(value)

    @Slot(bool)
    def _set_auto_button_state(self, active):
        if active:
            self.btn_auto.setStyleSheet("QPushButton { background-color: yellow; }")
            self.btn_auto.setIcon(qta.icon("fa5s.sync-alt", color="black"))
        else:
            self.btn_auto.setStyleSheet("")
            self.btn_auto.setIcon(qta.icon("fa5s.sync-alt", color="white"))

    @Slot(bool)
    def _set_error_marker_visible(self, visible):
        if visible:
            self.lbl.setText(f"{self.name} !")
            self.lbl.setStyleSheet("color: #ffd54f; font-weight: 700;")
            self.lbl.setToolTip(self.last_error_hint or "Error details are available")
        else:
            self.lbl.setText(self.name)
            self.lbl.setStyleSheet("")
            self.lbl.setToolTip("")

    @Slot()
    def clear_log(self):
        self.text.clear()

    def _uuu_output(self, raw):
        self._append_raw_log(raw)
        line = cfg.ansi_escape.sub("", raw).strip()
        if not line:
            return
        if ">Start Cmd:" in line:
            command = line.split(">Start Cmd:", 1)[1].strip()
            self._handle_flash_command(command)
            self.signals.log.emit(line, "white")
            return
        m = cfg.percent_re.search(line)
        if m:
            percent = int(m.group(1))
            percent = max(0, min(100, percent))
            self._set_progress(percent)
            return
        if (self.progress_mode == ProgressMode.FLASH
                and self.flash_stage == FlashStage.FLASH_ROOTFS
                and cfg.byte_progress_re.fullmatch(line)):
            value = int(line)
            # A non-calibrating panel may pick up the hint after the owner
            # finishes, but it must never update the hint itself.
            if self.is_progress_calibrator:
                self.byte_progress_max = max(self.byte_progress_max, value)
            if not self.progress_total_bytes:
                self.progress_total_bytes = cfg.get_progress_total_bytes(cfg.FIRM_DATA)
            if self.progress_total_bytes:
                percent = int(value * 100 / self.progress_total_bytes)
                self._set_progress(percent)
            return
        if cfg.byte_progress_re.fullmatch(line) or cfg.hex_value_re.fullmatch(line):
            return
        if is_main_log_noise(line):
            return
        self.signals.log.emit(line, "white")

    def _handle_flash_command(self, command):
        if command.startswith("SDPS: boot"):
            self.flash_stage = FlashStage.SDPS_BOOT
            self.progress_mode = ProgressMode.SDPS
            self._reset_progress()
        elif command.startswith("FB: flash -raw2sparse"):
            self.flash_stage = FlashStage.FLASH_ROOTFS
            self.progress_mode = ProgressMode.FLASH
            self._reset_progress()
        elif command.startswith("FB: flash") and "bootloader" in command:
            self.flash_stage = FlashStage.FLASH_BOOTLOADER
        elif command.startswith("FB: done"):
            self.flash_stage = FlashStage.FINALIZE
            self._set_progress(100)
            self.flash_stage = FlashStage.DONE

    def _set_progress(self, value):
        value = max(0, min(100, int(value)))
        if value >= self.current_percent:
            self.current_percent = value
            self._update_eta(value)
            self.signals.progress.emit(value, self.progress_mode.name.lower())

    def _tick_elapsed(self):
        if not self.is_flashing or self.start_time is None:
            return
        self.elapsed_text = format_t(time.time() - self.start_time)
        self.elapsed_label.setText(self.elapsed_text)

    def _update_eta(self, percent):
        if not self.is_flashing or self.start_time is None:
            return
        elapsed = time.time() - self.start_time
        if percent >= 100:
            self.eta_text = "Готово"
            self.eta_smoothed = None
        elif self.progress_mode == ProgressMode.SDPS and percent < 10:
            self.eta_text = "Калибровка..."
        elif percent <= 0:
            self.eta_text = "--:--"
        else:
            remaining = elapsed * (100 - percent) / percent
            self.eta_samples.append((elapsed, percent))
            if len(self.eta_samples) > 3:
                self.eta_samples.pop(0)
            # Сглаживаем: берём среднее по последним 3 замерам,
            # чтобы ETA не прыгал от одного обновления к другому.
            values = []
            for e, p in self.eta_samples:
                if p > 0:
                    values.append(e * (100 - p) / p)
            if values:
                self.eta_smoothed = sum(values) / len(values)
                self.eta_text = format_t(int(self.eta_smoothed))
            else:
                self.eta_smoothed = None
                self.eta_text = "--:--"
        self.eta_label.setText(self.eta_text)

    def _reset_progress(self):
        self.current_percent = 0
        self.signals.progress.emit(0, self.progress_mode.name.lower())

    def _uuu_error(self, raw):
        self._append_raw_log(raw)
        line = cfg.ansi_escape.sub("", raw).strip()
        if line:
            self.signals.log.emit(f"[ERR] {line}", "#FF5D5B")

    def _flash_finished(self, rc, error_flag):
        self.eta_timer.stop()
        if rc == 0 and not error_flag and self.is_progress_calibrator and self.byte_progress_max:
            key = os.path.abspath(cfg.FIRM_DATA)
            old = cfg.progress_size_hints.get(key, 0)
            if self.byte_progress_max > old:
                cfg.progress_size_hints[key] = self.byte_progress_max
                cfg.save_firmware()
        if self.calibration_session_active:
            cfg.finish_progress_calibration()
            self.calibration_session_active = False
        if self.flash_stage != FlashStage.DONE:
            self.flash_stage = FlashStage.FINALIZE
        if self.stop_flag:
            self.signals.log.emit(f"[{self.name}] Stopped by user", "yellow")
            self.signals.set_bg.emit("idle")
            self.signals.info.emit("Not Run", "idle")
            self.signals.progress.emit(0, "red")
            self.eta_label.setText("--:--")
            self.elapsed_label.setText(self.elapsed_text)
            self.eta_samples = []
            self.eta_smoothed = None
            self.is_flashing = False
            return
        dt = format_t(time.time() - self.start_time)
        self.elapsed_label.setText(dt)
        if rc == 0 and not error_flag:
            self.signals.set_bg.emit("ok")
            self.signals.info.emit("Done", "ok")
            self.blink_on_complete = True
            self.signals.log.emit(f"[{self.name}] SUCCESS ({dt})", "#070bf2")
            self.last_error_log = ""
            self.last_error_hint = ""
            self.last_flash_ok = True
            self.signals.error_marker.emit(False)
            # UuuScriptProcess already includes `FB: reboot` in its command
            # sequence. Sending a second reboot here is unnecessary and can
            # produce a misleading extra device event.
            if not self.use_script_process:
                try:
                    reboot_device(self.dev_path, parent=self)
                except Exception as exc:
                    self.signals.log.emit(f"Reboot err: {exc}", "#FF5D5B")
                self.signals.log.emit("Reboot sent", "#070bf2")
            self.signals.count_lbl.emit()
            # Ждём физического отключения платы, чтобы AUTO не начал шить заново
            self.post_flash_time = time.time()
            self.require_disconnect = True
            QtCore.QTimer.singleShot(2000, self._clear_flashing_flag)
        else:
            self.signals.set_bg.emit("error")
            self.signals.info.emit("Error", "error")
            self.signals.progress.emit(0, "red")
            self.signals.log.emit(f"[{self.name}] Flash failed rc={rc}", "#FF5D5B")
            raw = "".join(self.raw_log_buffer)
            short, block = self._build_error_hint(raw)
            self.last_error_hint = short
            self.last_error_log = (f"Panel: {self.name}\n"
                f"USB path: {self.dev_path}\n"
                f"Exit code: {rc}\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'-'*80}\n"
                + block
                + raw
            )
            self.signals.error_marker.emit(True)
            # При ошибке блокировку не ставим — плата уже могла отвалиться сама
            self.require_disconnect = False
            self.is_flashing = False

    def _clear_flashing_flag(self):
        self.is_flashing = False

    def _append_raw_log(self, chunk: str):
        if chunk is None:
            return
        text = chunk.replace("\r\n", "\n").replace("\r", "\n")
        text = cfg.ansi_escape.sub("", text)
        if text and not text.endswith("\n"):
            text += "\n"
        self.raw_log_buffer.append(text)

    def _build_error_hint(self, raw_text: str):
        txt = (raw_text or "").lower()
        if "libusb_error_no_device" in txt:
            short_hint = "USB disconnect during transfer."
            detailed_hint = (
                "Hint:\n"
                "- Detected issue: USB device disconnected during transfer.\n"
                "- Check cable/connector quality and board power stability.\n"
                "- Avoid unstable USB hubs/adapters.\n"
                + "-" * 80
                + "\n"
            )
            return short_hint, detailed_hint
        return "", ""

    def _flash_once_cycle(self):
        self.blink_on_complete = False
        if not self.dev_path:
            self.signals.log.emit("Device path is not set.", "#FF5D5B")
            self.signals.info.emit("No device", "error")
            self.signals.progress.emit(0, "red")
            return

        if not cfg.FIRM_DATA or not os.path.isfile(cfg.FIRM_DATA):
            self.signals.log.emit(f"Firmware file not found: {cfg.FIRM_DATA}", "#FF5D5B")
            self.signals.info.emit("No firmware", "error")
            self.signals.progress.emit(0, "red")
            return

        if not os.path.isfile(cfg.BOOT_DATA):
            self.signals.log.emit(f"Boot file not found: {cfg.BOOT_DATA}", "#FF5D5B")
            self.signals.info.emit("No boot", "error")
            self.signals.progress.emit(0, "red")
            return

        self.is_flashing = True
        self.raw_log_buffer.clear()
        self.signals.error_marker.emit(False)
        self.signals.clear.emit()
        self.signals.set_bg.emit("working")
        self.signals.info.emit("Flashing...", "working")
        self.last_flash_ok = False
        self.start_time = time.time()
        self.progress_mode = ProgressMode.SDPS
        self.flash_stage = FlashStage.WAIT_DEVICE
        self.current_percent = 0
        self.eta_samples = []
        self.eta_smoothed = None
        self.eta_text = "--:--"
        self.elapsed_text = "00:00"
        self.eta_label.setText(self.eta_text)
        self.elapsed_label.setText(self.elapsed_text)
        self.eta_timer.start()
        # Reset the measurement only at the beginning of a new flash, never
        # for every Start Cmd emitted by uuu.
        self.byte_progress_max = 0
        self.progress_total_bytes = cfg.get_progress_total_bytes(cfg.FIRM_DATA)
        self.is_progress_calibrator = cfg.claim_progress_calibrator(cfg.FIRM_DATA, self.name)
        self.calibration_session_active = True
        
        if self.uuu:
            self.uuu.deleteLater()
            self.uuu = None
            
        process_class = UuuScriptProcess if self.use_script_process else UuuProcess
        self.uuu = process_class(self)
        self.uuu.output.connect(self._uuu_output)
        self.uuu.error.connect(self._uuu_error)
        self.uuu.finished.connect(self._flash_finished)
        self.uuu.flash(self.dev_path, cfg.BOOT_DATA, cfg.FIRM_DATA)

    def _auto_timer_tick(self):
        if not self.auto or self.stop_flag or self.is_flashing:
            return
        if not self.dev_path:
            self.signals.info.emit("No device", "error")
            self.signals.progress.emit(0, "red")
            return
            
        is_present = self.usb_device_present()
        
        if getattr(self, 'require_disconnect', False):
            if not is_present:
                self.require_disconnect = False
                self.post_flash_time = None
                # Сохраняем зелёный фон если последняя прошивка прошла успешно
                if self.last_flash_ok:
                    self.signals.set_bg.emit("ok")
                    self.signals.info.emit("Waiting", "ok")
                else:
                    self.signals.set_bg.emit("idle")
                    self.signals.info.emit("Waiting", "idle")
                self.signals.progress.emit(0, "red")
                # self.signals.log.emit("Board disconnected. Ready.", "white")
            else:
                if self.post_flash_time and (time.time() - self.post_flash_time > 4.0):
                    self.signals.set_bg.emit("warning")
                    self.signals.info.emit("Stuck!", "warning")
                    self.signals.log.emit("WARNING: Board stuck in SDPS (Defective?). Please disconnect!", "#000000")
                    self.auto = False
                    self.signals.auto_state.emit(False)
            return

        if not is_present:
            self.signals.info.emit("Waiting", "idle")
            self.signals.progress.emit(0, "red")
            return
            
        self._flash_once_cycle()

    def start_once(self):
        if self.is_flashing or self.auto:
            self.signals.log.emit("Worker already running", "yellow")
            return
        self.stop_flag = False
        self.require_disconnect = False
        self._flash_once_cycle()

    def toggle_auto(self):
        if self.is_flashing:
            self.signals.log.emit("Worker already running", "yellow")
            return
        if self.auto:
            self.stop_worker()
            return
        self.auto = True
        self.stop_flag = False
        self.signals.auto_state.emit(True)
        self.signals.log.emit(f"[{self.name}] Auto mode started", "white")
        self.signals.info.emit("Waiting", "idle")
        self.auto_timer.start(1000)

    def stop_worker(self):
        self.auto = False
        self.stop_flag = True
        self.auto_timer.stop()
        if self.uuu:
            try:
                self.uuu.kill()
                self.signals.log.emit("Process terminated", "yellow")
            except Exception as exc:
                self.signals.log.emit(f"Stop error: {exc}", "#FF5D5B")
        self.signals.auto_state.emit(False)
        self.signals.set_bg.emit("idle")
        self.signals.info.emit("Not Run", "idle")
        self.signals.progress.emit(0, "red")

    def show_error_log_dialog(self):
        if not self.last_error_log:
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"Error details - {self.name}")
        dlg.resize(900, 520)
        layout = QtWidgets.QVBoxLayout(dlg)
        text = QtWidgets.QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self.last_error_log)
        layout.addWidget(text)
        btn_close = QtWidgets.QPushButton("Close")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec()
