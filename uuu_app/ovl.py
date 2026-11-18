import re
import os
from . import cfg
from .qt import QtCore, QtGui, QtWidgets
import qtawesome as qta


class UsbDevicesOverlay(QtWidgets.QFrame):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        self._anchor = parent
        self._drag_offset = None
        self._drag_start_global = None
        self._drag_started = False
        self._manual_position = False
        self._pinned = False
        self.setObjectName("usbOverlay")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))
        self.setStyleSheet(
            "QFrame#usbOverlay {"
            " background-color: #181818;"
            " border: 1px solid #5f6368;"
            " border-radius: 6px;"
            "}"
            "QFrame#usbOverlay QLabel#usbOverlayTitle {"
            " background: transparent;"
            " border: none;"
            " color: #f2f2f2;"
            " font-weight: 700;"
            " font-size: 13px;"
            " padding: 0px 2px 4px 2px;"
            "}"
            "QFrame#usbOverlay QToolButton#pinButton {"
            " background-color: #181818;"
            " border: none;"
            " padding: 0px;"
            "}"
            "QFrame#usbOverlay QListWidget#usbDeviceList {"
            " background-color: #101010;"
            " border: 1px solid #3c4043;"
            " border-radius: 4px;"
            " color: #e8eaed;"
            " font-family: 'DejaVu Sans Mono', 'Consolas', monospace;"
            " font-size: 12px;"
            " outline: 0;"
            " padding: 3px;"
            "}"
            "QFrame#usbOverlay QListWidget#usbDeviceList::item {"
            " min-height: 24px;"
            " padding: 3px 7px;"
            " border-radius: 3px;"
            " margin: 1px 0px;"
            "}"
            "QFrame#usbOverlay QListWidget#usbDeviceList::item:hover {"
            " background-color: #2b3137;"
            " color: #ffffff;"
            "}"
            "QFrame#usbOverlay QListWidget#usbDeviceList::item:selected {"
            " background-color: #3f5f46;"
            " color: #ffffff;"
            "}"
            "QFrame#usbOverlay QScrollBar:vertical {"
            " background: #101010;"
            " width: 8px;"
            "}"
            "QFrame#usbOverlay QScrollBar::handle:vertical {"
            " background: #555;"
            " border-radius: 4px;"
            " min-height: 18px;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header_pad = QtWidgets.QWidget()
        header_pad.setFixedSize(32, 22)
        self.title = QtWidgets.QLabel("Connected USB Devices")
        self.title.setObjectName("usbOverlayTitle")
        self.title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title.installEventFilter(self)
        self.pin_btn = QtWidgets.QToolButton()
        self.pin_btn.setObjectName("pinButton")
        self.pin_btn.setIcon(qta.icon("fa5s.thumbtack", color="#aaaaaa"))
        self.pin_btn.setCheckable(True)
        self.pin_btn.setFixedSize(22, 22)
        self.pin_btn.setToolTip("Pin and monitor USB devices")
        self.pin_btn.clicked.connect(self.toggle_pin)
        header.addWidget(header_pad)
        header.addWidget(self.title, 1)
        header.addWidget(self.pin_btn)
        layout.addLayout(header)
        self.viewer = QtWidgets.QListWidget()
        self.viewer.setObjectName("usbDeviceList")
        self.viewer.setMinimumSize(250, 200)
        self.viewer.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.viewer.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self.viewer.itemClicked.connect(self.copy_item_path)
        self.viewer.installEventFilter(self)
        self.viewer.viewport().installEventFilter(self)
        layout.addWidget(self.viewer)
        self.set_device_text(text)
        self.close_timer = QtCore.QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.start(7000)

    def set_device_text(self, text):
        self._text = text
        self.viewer.clear()
        lines = text.splitlines() if text else ["No devices"]
        for line in lines:
            item = QtWidgets.QListWidgetItem(line)
            path = self._path_from_line(line)
            if path:
                item.setData(QtCore.Qt.ItemDataRole.UserRole, path)
                item.setToolTip(f"Click to copy {path}")
            else:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self.viewer.addItem(item)

    def update_text(self, text):
        self.title.setText("Connected USB Devices")
        self.set_device_text(text)
        if not self._pinned:
            self.close_timer.start(7000)
        self.restore_or_move_to_default()
        self.show()
        self.raise_()

    def toggle_pin(self, checked):
        self.set_pinned(bool(checked))

    def set_pinned(self, pinned):
        self._pinned = pinned
        self.pin_btn.setChecked(pinned)
        if pinned:
            self.title.setText("Connected USB Devices")
            self.pin_btn.setIcon(qta.icon("fa5s.thumbtack", color="#ffffff"))
            self.close_timer.stop()
        else:
            self.pin_btn.setIcon(qta.icon("fa5s.thumbtack", color="#aaaaaa"))
            self.close_timer.start(7000)

    def update_devices(self, devices):
        lines = []
        for path, dev in devices.items():
            lines.append(f"{path:<6} {dev['mode']:<6} {dev['serial']}")
        self.set_device_text("\n".join(lines) if lines else "No devices")

    def copy_item_path(self, item):
        path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not path:
            return
        QtWidgets.QApplication.clipboard().setText(path)
        self.title.setText(f"Copied: {path}")
        if not self._pinned:
            self.close_timer.start(7000)

    def _path_from_line(self, line):
        m = re.match(r"^\s*(\d+:\d+)\b", line or "")
        return m.group(1) if m else ""

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.restore_or_move_to_default)
        QtCore.QTimer.singleShot(80, self.restore_or_move_to_default)
        QtCore.QTimer.singleShot(250, self.restore_or_move_to_default)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.restore_or_move_to_default()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            if self._drag_to_global(event.globalPosition().toPoint()):
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._finish_drag()
            super().mouseReleaseEvent(event)
            return
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._begin_drag(event.globalPosition().toPoint())
                return False
        elif event.type() == QtCore.QEvent.Type.MouseMove:
            if self._drag_offset is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                if self._drag_to_global(event.globalPosition().toPoint()):
                    event.accept()
                    return True
        elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_offset is not None:
                was_dragging = self._drag_started
                self._finish_drag()
                if was_dragging:
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def _begin_drag(self, global_pos):
        if not self._pinned:
            self.close_timer.stop()
        self._drag_offset = global_pos - self.mapToGlobal(QtCore.QPoint(0, 0))
        self._drag_start_global = global_pos
        self._drag_started = False

    def _drag_to_global(self, global_pos):
        if self._anchor is None:
            return False
        if not self._drag_started:
            distance = global_pos - self._drag_start_global
            if distance.manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return False
            self._drag_started = True
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))
        next_pos = self._anchor.mapFromGlobal(global_pos - self._drag_offset)
        self.move(self._clamp_pos(next_pos))
        self.raise_()
        return True

    def _finish_drag(self):
        was_dragging = self._drag_started
        self._drag_offset = None
        self._drag_start_global = None
        self._drag_started = False
        self._manual_position = True
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))
        if was_dragging and self._anchor and hasattr(self._anchor, "save_usb_overlay_position"):
            self._anchor.save_usb_overlay_position(self.pos())
        if not self._pinned:
            self.close_timer.start(7000)

    def _clamp_pos(self, pos):
        anchor = self._anchor
        if anchor is None:
            return pos
        area = anchor.rect()
        margin = 10
        max_x = max(margin, area.width() - self.width() - margin)
        max_y = max(margin, area.height() - self.height() - margin)
        x = min(max(margin, pos.x()), max_x)
        y = min(max(margin, pos.y()), max_y)
        return QtCore.QPoint(x, y)

    def restore_or_move_to_default(self):
        if self._manual_position:
            self.move(self._clamp_pos(self.pos()))
            self.raise_()
            return
        if self._anchor and hasattr(self._anchor, "usb_overlay_saved_pos"):
            saved_pos = self._anchor.usb_overlay_saved_pos()
            if saved_pos is not None:
                self.adjustSize()
                self.move(self._clamp_pos(saved_pos))
                self.raise_()
                return
        self.move_to_bottom_right()

    def move_to_bottom_right(self):
        anchor = self._anchor
        if anchor is None:
            return
        self.adjustSize()
        area = anchor.rect()
        margin = 10
        x = area.width() - self.width() - margin
        y = area.height() - self.height() - margin
        self.move(self._clamp_pos(QtCore.QPoint(x, y)))
        self.raise_()


class FileSettingsOverlay(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._anchor = parent
        self._drag_offset = None
        self._drag_start_global = None
        self._drag_started = False
        self.setObjectName("fileOverlay")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))
        self.setStyleSheet(
            "QFrame#fileOverlay {"
            " background-color: #181818;"
            " border: 1px solid #5f6368;"
            " border-radius: 6px;"
            "}"
            "QFrame#fileOverlay QLabel#fileOverlayTitle {"
            " background: transparent;"
            " border: none;"
            " color: #f2f2f2;"
            " font-weight: 700;"
            " font-size: 13px;"
            " padding-bottom: 4px;"
            "}"
            "QFrame#fileOverlay QLabel {"
            " background: transparent;"
            " border: none;"
            " color: #dddddd;"
            "}"
            "QFrame#fileOverlay QLineEdit,"
            "QFrame#fileOverlay QComboBox {"
            " background-color: #101010;"
            " border: 1px solid #3c4043;"
            " border-radius: 4px;"
            " color: #eeeeee;"
            " padding: 4px;"
            "}"
            "QFrame#fileOverlay QPushButton {"
            " background-color: #2a2a2a;"
            " border: 1px solid #555;"
            " border-radius: 4px;"
            " color: #eeeeee;"
            " padding: 4px 8px;"
            "}"
            "QFrame#fileOverlay QPushButton:hover {"
            " background-color: #3a3a3a;"
            "}"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(7)
        self.title = QtWidgets.QLabel("Image Files")
        self.title.setObjectName("fileOverlayTitle")
        self.title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title.installEventFilter(self)
        layout.addWidget(self.title)

        fw_label = QtWidgets.QLabel("Firmware")
        layout.addWidget(fw_label)
        self.firm_combo = QtWidgets.QComboBox()
        self.firm_combo.setMinimumWidth(360)
        self.firm_combo.currentIndexChanged.connect(self._history_selected)
        self.firm_combo.view().setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.firm_combo.view().customContextMenuRequested.connect(self._history_menu)
        layout.addWidget(self.firm_combo)

        firm_row = QtWidgets.QHBoxLayout()
        self.firm_edit = QtWidgets.QLineEdit(cfg.FIRM_FILE)
        self.firm_edit.setReadOnly(True)
        self.firm_edit.setToolTip(self.firm_edit.text() or "No firmware selected")
        self.btn_firm_browse = QtWidgets.QPushButton("...")
        self.btn_firm_browse.clicked.connect(self.browse_firmware)
        firm_row.addWidget(self.firm_edit, 1)
        firm_row.addWidget(self.btn_firm_browse)
        layout.addLayout(firm_row)

        boot_label = QtWidgets.QLabel("Boot")
        layout.addWidget(boot_label)
        self.boot_combo = QtWidgets.QComboBox()
        self.boot_combo.setMinimumWidth(360)
        self.boot_combo.currentIndexChanged.connect(self._boot_history_selected)
        self.boot_combo.view().setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.boot_combo.view().customContextMenuRequested.connect(self._boot_history_menu)
        layout.addWidget(self.boot_combo)

        boot_row = QtWidgets.QHBoxLayout()
        self.boot_edit = QtWidgets.QLineEdit(cfg.BOOT_FILE)
        self.boot_edit.setReadOnly(True)
        self.boot_edit.setToolTip(self.boot_edit.text() or "No boot file selected")
        self.btn_boot_browse = QtWidgets.QPushButton("...")
        self.btn_boot_browse.clicked.connect(self.browse_boot)
        boot_row.addWidget(self.boot_edit, 1)
        boot_row.addWidget(self.btn_boot_browse)
        layout.addLayout(boot_row)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch()
        self.btn_close = QtWidgets.QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        close_row.addWidget(self.btn_close)
        layout.addLayout(close_row)
        self.refresh_history()

    def _fill_history_combo(self, combo, entries, current):
        combo.blockSignals(True)
        combo.clear()
        for path in entries:
            name = os.path.basename(path)
            combo.addItem(name, path)
            idx = combo.count() - 1
            full_path = cfg.resolve_firmware_path(path)
            exists = os.path.isfile(full_path)
            tooltip = full_path if exists else f"Файл отсутствует:\n{full_path}"
            combo.setItemData(idx, tooltip, QtCore.Qt.ItemDataRole.ToolTipRole)
            if not exists:
                combo.setItemData(idx, QtGui.QColor("#FF5D5B"), QtCore.Qt.ItemDataRole.ForegroundRole)
            if path == current:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def refresh_history(self):
        self._fill_history_combo(self.firm_combo, cfg.history_list, cfg.FIRM_FILE)
        self._fill_history_combo(self.boot_combo, cfg.boot_history_list, cfg.BOOT_FILE)
        self.firm_edit.setText(cfg.FIRM_FILE)
        self.firm_edit.setToolTip(cfg.FIRM_FILE or "No firmware selected")
        self.boot_edit.setText(cfg.BOOT_FILE)
        self.boot_edit.setToolTip(cfg.BOOT_FILE or "No boot file selected")

    def _history_selected(self, index):
        value = self.firm_combo.itemData(index)
        if value:
            self.firm_edit.setText(value)
            self.apply_firmware()

    def _boot_history_selected(self, index):
        value = self.boot_combo.itemData(index)
        if value:
            self.boot_edit.setText(value)
            self.apply_boot()

    def _show_history_menu(self, combo, pos, handler_name):
        index = combo.view().indexAt(pos)
        if not index.isValid():
            return
        value = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not value:
            return
        menu = QtWidgets.QMenu(self)
        action_remove = menu.addAction("Delete from history")
        selected_action = menu.exec(combo.view().viewport().mapToGlobal(pos))
        if selected_action != action_remove:
            return
        if self._anchor and hasattr(self._anchor, handler_name):
            getattr(self._anchor, handler_name)(value)
        self.refresh_history()

    def _history_menu(self, pos):
        self._show_history_menu(self.firm_combo, pos, "remove_firmware_history")

    def _boot_history_menu(self, pos):
        self._show_history_menu(self.boot_combo, pos, "remove_boot_history")

    def apply_firmware(self):
        value = self.firm_edit.text().strip()
        if not value:
            return
        if self._anchor and hasattr(self._anchor, "apply_firmware_file"):
            self._anchor.apply_firmware_file(value)
        self.refresh_history()

    def apply_boot(self):
        value = self.boot_edit.text().strip()
        if not value:
            return
        if self._anchor and hasattr(self._anchor, "apply_boot_file"):
            self._anchor.apply_boot_file(value)
        self.refresh_history()

    def browse_firmware(self):
        start_dir = cfg.DIR if os.path.isdir(cfg.DIR) else os.getcwd()
        selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Firmware File", start_dir, "Firmware files (*.wic *.img *.bin *.bz2);;All files (*)"
        )
        if selected_path:
            self.firm_edit.setText(selected_path)
            self.apply_firmware()

    def browse_boot(self):
        start_dir = cfg.DIR if os.path.isdir(cfg.DIR) else os.getcwd()
        selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Boot File", start_dir, "Boot files (*.bin *flash*);;All files (*)"
        )
        if selected_path:
            self.boot_edit.setText(selected_path)
            self.apply_boot()

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.move_to_top_left)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.move(self._clamp_pos(self.pos()))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            if self._drag_to_global(event.globalPosition().toPoint()):
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._finish_drag()
            super().mouseReleaseEvent(event)
            return
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            return False
        if event.type() == QtCore.QEvent.Type.MouseMove:
            if self._drag_offset is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                if self._drag_to_global(event.globalPosition().toPoint()):
                    event.accept()
                    return True
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_offset is not None:
                was_dragging = self._drag_started
                self._finish_drag()
                if was_dragging:
                    event.accept()
                    return True
        return super().eventFilter(obj, event)

    def _begin_drag(self, global_pos):
        self._drag_offset = global_pos - self.mapToGlobal(QtCore.QPoint(0, 0))
        self._drag_start_global = global_pos
        self._drag_started = False

    def _drag_to_global(self, global_pos):
        if self._anchor is None:
            return False
        if not self._drag_started:
            distance = global_pos - self._drag_start_global
            if distance.manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return False
            self._drag_started = True
            self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.ClosedHandCursor))
        next_pos = self._anchor.mapFromGlobal(global_pos - self._drag_offset)
        self.move(self._clamp_pos(next_pos))
        self.raise_()
        return True

    def _finish_drag(self):
        self._drag_offset = None
        self._drag_start_global = None
        self._drag_started = False
        self.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.OpenHandCursor))

    def _clamp_pos(self, pos):
        if self._anchor is None:
            return pos
        area = self._anchor.rect()
        margin = 10
        max_x = max(margin, area.width() - self.width() - margin)
        max_y = max(margin, area.height() - self.height() - margin)
        return QtCore.QPoint(min(max(margin, pos.x()), max_x), min(max(margin, pos.y()), max_y))

    def move_to_top_left(self):
        self.adjustSize()
        self.move(self._clamp_pos(QtCore.QPoint(75, 44)))
        self.raise_()
