import os
import re
import time
from . import cfg
from .ovl import FileSettingsOverlay, UsbDevicesOverlay
from .panel import DevicePanelWidget
from .qt import QtCore, QtGui, QtWidgets
from .ui import MechanicalCounter
import qtawesome as qta


class UuuScanWorker(QtCore.QThread):
    """Парсит вывод `uuu -lsusb` в отдельном потоке, чтобы не тормозить GUI."""

    parsed = QtCore.Signal(dict)

    def __init__(self, raw, parent=None):
        super().__init__(parent)
        self._raw = raw

    def run(self):
        try:
            devices = self._parse(self._raw)
        except Exception:
            devices = {}
        self.parsed.emit(devices)

    @staticmethod
    def _parse(raw):
        devices = {}
        for line in raw.splitlines():
            if not re.match(r"^\s*\d+:\d+", line):
                continue
            parts = line.split()
            path = parts[0]
            mode = ""
            for part in parts:
                if part.endswith(":") and part != path:
                    mode = part
                    break
            serial = parts[-1] if parts[-1].isalnum() else ""
            devices[path] = {"mode": mode, "serial": serial}
        return devices


class FlasherFarmApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        cfg.load_firmware()
        self._init_state()
        self._create_ui()
        self._create_panels()
        self._connect_signals()
        self.refresh_file_label()
        self._create_timers()
        self._create_shortcuts()
        self.rebuild_panel_grid()
        self.start_usb_monitor()

    def _init_state(self):
        self.flash_count = 0
        self._roll_target = None
        self.fullscreen = False
        self.usb_devices_overlay = None
        self.file_settings_overlay = None
        self.panels = []
        self.panel_wrappers = []
        self.active_panels = [i < 5 for i in range(10)]
        self.desired_active_panels_count = 5
        self.visible_panels_count = 5
        self.uuu_process = None
        self.usb_devices = {}

    def _create_ui(self):
        self.setWindowTitle("Firmware Manager")
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        top_layout = QtWidgets.QHBoxLayout()
        self.clock_label = QtWidgets.QLabel()
        self.clock_label.setFixedWidth(65)
        self.clock_label.setStyleSheet("color: white; font-size: 16pt;")
        self.count_display = MechanicalCounter()
        self.count_display.rollFinished.connect(self._on_roll_finished)
        self.count_display.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.count_display.customContextMenuRequested.connect(self.show_count_menu)
        self.count_display.setToolTip("<span style='font-size:12px;'>Прошивок: 0. ПКМ: изменить или очистить</span>")
        self.btn_all_auto = self.create_button("fa5s.sync-alt", "Запуск панелей в автоматическом режиме")
        self.btn_all_once = self.create_button("fa5s.play", "Разовый запуск всех панелей")
        self.btn_all_stop = self.create_button("fa5s.stop", "Остановить работу панелей")
        self.btn_exit = self.create_button("fa5s.sign-out-alt", "Выход из приложения", icon_size=28)
        self.btn_files = self.create_button("fa5s.folder-open", "Firmware / boot files", icon_size=25)
        self.btn_help = self.create_button("fa5s.question", "Инструкция", icon_size=24)
        self.btn_help = self.create_button("fa5s.question", "Инструкция", icon_size=24)
        top_layout.addWidget(self.clock_label)
        top_layout.addWidget(self.btn_files)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_help)
        top_layout.addStretch()
        top_layout.addWidget(self.count_display)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_all_auto)
        top_layout.addWidget(self.btn_all_once)
        top_layout.addWidget(self.btn_all_stop)
        top_layout.addWidget(self.btn_exit)
        main_layout.addLayout(top_layout)
        self.grid_widget = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(5)
        main_layout.addWidget(self.grid_widget)

    def _create_panels(self):
        for i in range(10):
            panel_name = cfg.PANEL_NAMES[i]
            panel = DevicePanelWidget(panel_name, cfg.device_paths_by_panel.get(panel_name, ""))
            wrapper = QtWidgets.QFrame()
            wrapper.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
            wrapper.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
            layout = QtWidgets.QVBoxLayout(wrapper)
            layout.setContentsMargins(3, 3, 3, 3)
            layout.addWidget(panel)
            row, col = divmod(i, 5)
            self.grid_layout.addWidget(wrapper, row, col)
            self.panels.append(panel)
            self.panel_wrappers.append(wrapper)
            panel.path_changed.connect(self.on_panel_path_changed)
            panel.signals.count_lbl.connect(self.update_count_lbl)

    def _connect_signals(self):
        self.btn_exit.clicked.connect(self.close)
        self.btn_all_auto.clicked.connect(self.start_all_auto)
        self.btn_all_once.clicked.connect(self.start_all_once)
        self.btn_all_stop.clicked.connect(self.stop_all)
        self.btn_files.clicked.connect(self.show_file_settings_overlay)
        self.btn_help.clicked.connect(self.show_help_dialog)

    def create_button(self, icon, tooltip="", size=32, icon_size=24, object_name="all_button"):
        btn = QtWidgets.QPushButton()
        btn.setObjectName(object_name)
        btn.setIcon(qta.icon(icon, color="white"))
        btn.setIconSize(QtCore.QSize(icon_size, icon_size))
        btn.setFixedSize(size, size)
        btn.setToolTip(tooltip)
        return btn
    
    def _create_timers(self):
        self.clock_timer = QtCore.QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)
        self.update_clock()
        self.usb_scan_timer = QtCore.QTimer(self)
        self.usb_scan_timer.setInterval(1000)
        self.usb_scan_timer.timeout.connect(self.start_uuu_scan)
        self.usb_scan_timeout = QtCore.QTimer(self)
        self.usb_scan_timeout.setSingleShot(True)
        self.usb_scan_timeout.setInterval(5000)
        self.usb_scan_timeout.timeout.connect(self._uuu_scan_timeout)
        self.active_state_timer = QtCore.QTimer(self)
        self.active_state_timer.setInterval(700)
        self.active_state_timer.timeout.connect(self._apply_pending_deactivation)
        self.active_state_timer.start()

    def _create_shortcuts(self):
        self.shortcut_f11 = QtGui.QShortcut(QtGui.QKeySequence("F11"), self)
        self.shortcut_f11.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_f11.activated.connect(self.toggle_fullscreen)
        self.shortcut_f10 = QtGui.QShortcut(QtGui.QKeySequence("F10"), self)
        self.shortcut_f10.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_f10.activated.connect(self._handle_f10)
        self.f10_double_timer = QtCore.QTimer(self)
        self.f10_double_timer.setSingleShot(True)
        self.f10_double_timer.setInterval(350)
        self.f10_double_timer.timeout.connect(lambda: None)

        self.shortcut_ctrl_a = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+A"), self)
        self.shortcut_ctrl_a.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_a.activated.connect(self.start_all_auto)
        self.shortcut_ctrl_s = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        self.shortcut_ctrl_s.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_s.activated.connect(self.stop_all)
        self.shortcut_ctrl_q = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Q"), self)
        self.shortcut_ctrl_q.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_q.activated.connect(self.close)
        self.shortcut_ctrl_r = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+R"), self)
        self.shortcut_ctrl_r.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_r.activated.connect(self.start_all_once)
        self.shortcut_ctrl_u = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+U"), self)
        self.shortcut_ctrl_u.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_u.activated.connect(self.toggle_all_process_modes)
        self.panel_shortcuts = []
        for digit in "1234567890":
            sc = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{digit}"), self)
            sc.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            sc.activated.connect(lambda d=digit: self.set_visible_panels_count(10 if d == "0" else int(d)))
            self.panel_shortcuts.append(sc)
        self.shortcut_ctrl_x = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+X"), self)
        self.shortcut_ctrl_x.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_x.activated.connect(lambda: self.set_visible_panels_count(10))
        self._alt_chord_action = None
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _handle_f10(self):
        """Show the USB panel; double F10 toggles its pinned state."""
        if self.f10_double_timer.isActive():
            self.f10_double_timer.stop()
            if self.usb_devices_overlay is None:
                self.show_usb_devices_overlay()
            self.usb_devices_overlay.set_pinned(not self.usb_devices_overlay._pinned)
            self.usb_devices_overlay.show()
            self.usb_devices_overlay.raise_()
            return
        self.show_usb_devices_overlay()
        self.f10_double_timer.start()

    def update_clock(self):
        self.clock_label.setText(time.strftime("%H:%M"))

    def update_count_lbl(self):
        self.flash_count += 1
        self._roll_target = None
        self._render_count_lbl()

    def _render_count_lbl(self):
        if self.count_display.isRolling():
            return
        self.count_display.setValue(self.flash_count)
        self.count_display.setToolTip(f"<span style='font-size:12px;'>Прошивок: {self.flash_count}. "
            "ПКМ: изменить или очистить</span>")

    def count_lbl_reset(self):
        self.count_display.rollTo(0)
        self._roll_target = 0

    def _on_roll_finished(self):
        if self._roll_target is not None:
            self.flash_count = self._roll_target
            self._roll_target = None
            self._render_count_lbl()

    def count_lbl_edit(self):
        value, ok = QtWidgets.QInputDialog.getInt(self, "Счётчик прошивок", "Количество прошивок:", self.flash_count, 0, 999999, 1)
        if not ok:
            return
        self._roll_target = None
        self.flash_count = value
        self._render_count_lbl()

    def show_count_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        action_edit = menu.addAction("Редактировать...")
        menu.addSeparator()
        action_clear = menu.addAction("Очистить")
        selected = menu.exec(self.count_display.mapToGlobal(pos))
        if selected == action_edit:
            self.count_lbl_edit()
        elif selected == action_clear:
            self.count_lbl_reset()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.usb_devices_overlay is not None:
            self.usb_devices_overlay.restore_or_move_to_default()
        if self.file_settings_overlay is not None:
            self.file_settings_overlay.move(self.file_settings_overlay._clamp_pos(self.file_settings_overlay.pos()))

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            text_key = event.text().lower()
            action_keys = {
                QtCore.Qt.Key.Key_A: "A",
                QtCore.Qt.Key.Key_S: "S",
                QtCore.Qt.Key.Key_R: "R",
                QtCore.Qt.Key.Key_U: "U",
            }
            action_by_layout = {"ф": "A", "ы": "S", "к": "R", "г": "U"}
            panel_keys = {
                QtCore.Qt.Key.Key_1: "1",
                QtCore.Qt.Key.Key_2: "2",
                QtCore.Qt.Key.Key_3: "3",
                QtCore.Qt.Key.Key_4: "4",
                QtCore.Qt.Key.Key_5: "5",
                QtCore.Qt.Key.Key_6: "6",
                QtCore.Qt.Key.Key_7: "7",
                QtCore.Qt.Key.Key_8: "8",
                QtCore.Qt.Key.Key_9: "9",
                QtCore.Qt.Key.Key_0: "0",
                QtCore.Qt.Key.Key_X: "X",
            }
            panel_by_layout = {"ч": "X"}
            modifiers = event.modifiers()
            alt_down = bool(modifiers & QtCore.Qt.KeyboardModifier.AltModifier)
            action = action_keys.get(key) or action_by_layout.get(text_key)
            if self._alt_chord_action is None and alt_down and action is not None:
                self._alt_chord_action = action
                return True
            if self._alt_chord_action is not None:
                panel_key = panel_keys.get(key) or panel_by_layout.get(text_key)
                if panel_key is not None:
                    handler = {
                        "A": self._shortcut_auto_panel,
                        "S": self._shortcut_stop_panel,
                        "R": self._shortcut_once_panel,
                        "U": self._shortcut_process_panel,
                    }[self._alt_chord_action]
                    self._alt_chord_action = None
                    handler(panel_key)
                    return True
                self._alt_chord_action = None
        return super().eventFilter(obj, event)

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self.fullscreen = not self.fullscreen

    def refresh_file_label(self):
        def describe(file_value, resolved):
            if not file_value:
                return "не выбран"
            if resolved and not os.path.isfile(resolved):
                return f"{resolved}\n(файл отсутствует)"
            return resolved or file_value

        firm = describe(cfg.FIRM_FILE, cfg.FIRM_DATA)
        boot = describe(cfg.BOOT_FILE, cfg.BOOT_DATA)
        self.btn_files.setToolTip(f"Firmware: {firm}\n\nBoot: {boot}")

    def apply_firmware_file(self, value):
        cfg.FIRM_FILE = value.strip()
        cfg.FIRM_DATA = cfg.resolve_firmware_path(cfg.FIRM_FILE)
        cfg.reset_progress_calibration(cfg.FIRM_DATA)
        cfg.save_firmware()
        self.refresh_file_label()
        if self.file_settings_overlay is not None:
            self.file_settings_overlay.refresh_history()

    def apply_boot_file(self, value):
        cfg.BOOT_FILE = value.strip()
        cfg.BOOT_DATA = cfg.resolve_firmware_path(cfg.BOOT_FILE)
        cfg.save_firmware()
        self.refresh_file_label()
        if self.file_settings_overlay is not None:
            self.file_settings_overlay.refresh_history()

    def remove_firmware_history(self, value):
        cfg.history_list = [x for x in cfg.history_list if x != value]
        if cfg.FIRM_FILE == value:
            cfg.FIRM_FILE = cfg.history_list[0] if cfg.history_list else ""
            cfg.FIRM_DATA = cfg.resolve_firmware_path(cfg.FIRM_FILE) if cfg.FIRM_FILE else ""
            cfg.reset_progress_calibration(cfg.FIRM_DATA)
        cfg.save_firmware()
        self.refresh_file_label()

    def remove_boot_history(self, value):
        cfg.boot_history_list = [x for x in cfg.boot_history_list if x != value]
        if cfg.BOOT_FILE == value:
            cfg.BOOT_FILE = cfg.boot_history_list[0] if cfg.boot_history_list else ""
            cfg.BOOT_DATA = cfg.resolve_firmware_path(cfg.BOOT_FILE) if cfg.BOOT_FILE else ""
        cfg.save_firmware()
        self.refresh_file_label()

    def show_file_settings_overlay(self):
        if self.file_settings_overlay is not None and not self.file_settings_overlay.isHidden():
            self.file_settings_overlay.refresh_history()
            self.file_settings_overlay.show()
            self.file_settings_overlay.raise_()
            return
        dlg = FileSettingsOverlay(self)
        self.file_settings_overlay = dlg
        dlg.destroyed.connect(lambda: setattr(self, "file_settings_overlay", None))
        dlg.adjustSize()
        dlg.move_to_top_left()
        dlg.show()

    def parse_uuu_output(self, text):
        """Совместимость: парсинг в главном потоке (не используется для сканера)."""
        return UuuScanWorker._parse(text)

    def _uuu_finished(self):
        self.usb_scan_timeout.stop()
        proc = self.sender()
        if proc is None:
            proc = self.uuu_process
        if proc is None:
            return
        stdout = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        self._scan_worker = UuuScanWorker(stdout)
        self._scan_worker.parsed.connect(self._on_scan_parsed)
        self._scan_worker.start()
        proc.deleteLater()
        if self.uuu_process is proc:
            self.uuu_process = None

    def _on_scan_parsed(self, devices):
        self.usb_devices = devices
        if self.usb_devices_overlay is not None:
            self.usb_devices_overlay.update_devices(self.usb_devices)

    def _uuu_error(self):
        self.usb_scan_timeout.stop()
        proc = self.sender()
        if proc is None:
            proc = self.uuu_process
        if proc is None:
            return
        if self.usb_devices_overlay is not None:
            self.usb_devices_overlay.update_text(f"uuu error: {proc.errorString()}")
        proc.deleteLater()
        if self.uuu_process is proc:
            self.uuu_process = None

    def usb_devices_text(self):
        if not self.usb_devices:
            return "No devices"
        lines = []
        for path, dev in self.usb_devices.items():
            lines.append(f"{path:<6} {dev['mode']:<6} {dev['serial']}")
        return "\n".join(lines)

    def show_usb_devices_overlay(self):
        if self.usb_devices_overlay is None:
            self.usb_devices_overlay = UsbDevicesOverlay("", self)
            self.usb_devices_overlay.destroyed.connect(lambda: setattr(self, "usb_devices_overlay", None))
            self.usb_devices_overlay.adjustSize()
            self.usb_devices_overlay.move_to_bottom_right()
            self.usb_devices_overlay.show()
        self.usb_devices_overlay.update_text(self.usb_devices_text())

    def start_usb_monitor(self):
        if self.usb_scan_timer.isActive():
            return
        self.usb_scan_timer.start()
        self.start_uuu_scan()

    def stop_usb_monitor(self):
        self.usb_scan_timer.stop()
        self.usb_scan_timeout.stop()
        if self.uuu_process is not None:
            self.uuu_process.kill()

    def start_uuu_scan(self):
        if self.uuu_process is not None:
            return
        self.uuu_process = QtCore.QProcess(self)
        self.uuu_process.finished.connect(self._uuu_finished)
        self.uuu_process.errorOccurred.connect(self._uuu_error)
        self.usb_scan_timeout.start()
        self.uuu_process.start("uuu", ["-lsusb"])

    def _uuu_scan_timeout(self):
        """Если uuu -lsusb висит дольше 5 секунд, убиваем и перезапускаем."""
        if self.uuu_process is None:
            return
        if self.uuu_process.state() == QtCore.QProcess.ProcessState.Running:
            self.uuu_process.kill()
            self.uuu_process.deleteLater()
            self.uuu_process = None

    def usb_overlay_saved_pos(self):
        if not isinstance(cfg.usb_overlay_pos, dict):
            return None
        x = cfg.usb_overlay_pos.get("x")
        y = cfg.usb_overlay_pos.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            return None
        return QtCore.QPoint(x, y)

    def save_usb_overlay_position(self, pos):
        cfg.usb_overlay_pos = {"x": int(pos.x()), "y": int(pos.y())}
        cfg.save_firmware()

    def show_help_dialog(self):
        title, text = cfg.load_help_text()
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(760, 520)
        layout = QtWidgets.QVBoxLayout(dlg)
        viewer = QtWidgets.QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setPlainText(text)
        layout.addWidget(viewer)
        btn_close = QtWidgets.QPushButton("Закрыть")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec()

    def start_all_auto(self):
        for p in self.get_active_panels():
            p.toggle_auto()

    def toggle_all_process_modes(self):
        """Switch every panel to the opposite process mode."""
        use_script = not all(p.use_script_process for p in self.panels)
        for p in self.panels:
            p.set_process_mode(use_script)

    def _shortcut_panels(self, panel_key):
        if panel_key == "X":
            return self.get_active_panels()
        index = 9 if panel_key == "0" else int(panel_key) - 1
        if 0 <= index < len(self.panels) and self.active_panels[index]:
            return [self.panels[index]]
        return []

    def _shortcut_auto_panel(self, panel_key):
        for panel in self._shortcut_panels(panel_key):
            if not panel.auto and not panel.is_flashing:
                panel.toggle_auto()

    def _shortcut_stop_panel(self, panel_key):
        for panel in self._shortcut_panels(panel_key):
            panel.stop_worker()

    def _shortcut_once_panel(self, panel_key):
        for panel in self._shortcut_panels(panel_key):
            panel.start_once()

    def _shortcut_process_panel(self, panel_key):
        for panel in self._shortcut_panels(panel_key):
            panel.toggle_process_mode()

    def start_all_once(self):
        for p in self.get_active_panels():
            p.start_once()

    def stop_all(self):
        for p in self.get_active_panels():
            p.stop_worker()

    def get_active_panels(self):
        return [p for p, active in zip(self.panels, self.active_panels) if active]

    def _panel_is_busy(self, panel):
        return getattr(panel, 'is_flashing', False) or getattr(panel, 'auto', False)

    def _active_indices(self):
        return [idx for idx, is_active in enumerate(self.active_panels) if is_active]

    def _apply_pending_deactivation(self):
        current_active = len(self._active_indices())
        if current_active <= self.desired_active_panels_count:
            return
        changed = False
        for idx in reversed(self._active_indices()):
            if len(self._active_indices()) <= self.desired_active_panels_count:
                break
            panel = self.panels[idx]
            if self._panel_is_busy(panel):
                continue
            self.active_panels[idx] = False
            changed = True
        if changed:
            self.rebuild_panel_grid()

    def rebuild_panel_grid(self):
        active_wrappers = [w for w, active in zip(self.panel_wrappers, self.active_panels) if active]
        active_count = len(active_wrappers)
        self.visible_panels_count = active_count
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.grid_widget)
        for idx, wrapper in enumerate(self.panel_wrappers):
            wrapper.setVisible(self.active_panels[idx])
        if active_count == 0:
            return
        if active_count < 3:
            for idx, wrapper in enumerate(active_wrappers):
                self.grid_layout.addWidget(wrapper, 0, idx)
            return
        if active_count % 2 == 0:
            cols = active_count // 2
            for idx, wrapper in enumerate(active_wrappers):
                self.grid_layout.addWidget(wrapper, idx // cols, idx % cols)
            return
        cols = (active_count - 1) // 2
        self.grid_layout.addWidget(active_wrappers[0], 0, 0, 2, 1)
        for idx, wrapper in enumerate(active_wrappers[1:]):
            self.grid_layout.addWidget(wrapper, idx // cols, (idx % cols) + 1)

    def set_visible_panels_count(self, requested_count):
        normalized_count = requested_count if requested_count in range(1, 11) else 10
        self.desired_active_panels_count = normalized_count
        current_active_count = len(self._active_indices())
        if normalized_count > current_active_count:
            to_activate = normalized_count - current_active_count
            for idx, is_active in enumerate(self.active_panels):
                if to_activate == 0:
                    break
                if not is_active:
                    self.active_panels[idx] = True
                    to_activate -= 1
            self.rebuild_panel_grid()
            return
        if normalized_count < current_active_count:
            self._apply_pending_deactivation()
            return
        self.rebuild_panel_grid()

    def on_panel_path_changed(self, panel_name, path_value):
        cfg.device_paths_by_panel[panel_name] = path_value
        cfg.save_firmware()

    def closeEvent(self, event):
        self.stop_all()
        cfg.save_firmware()
        super().closeEvent(event)
