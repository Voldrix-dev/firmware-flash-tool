from .qt import QtCore, QtGui, QtWidgets, Signal


class RoundedProgressBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._color = QtGui.QColor("#6CEC70")
        self._mode = "flash"
        self._auto_color = True
        self._background = QtGui.QColor("#222")
        self._radius = 7
        self._text_color_light = QtGui.QColor("white")
        self._text_color_dark = QtGui.QColor("black")
        self.setMinimumHeight(20)

    def setValue(self, value):
        self._value = max(0, min(100, int(value)))
        if self._auto_color:
            self._color = self._color_for_progress()
        self.update()

    def setMode(self, mode):
        self._mode = mode
        self._auto_color = mode in ("sdps", "flash")
        if self._auto_color:
            self._color = self._color_for_progress()
        self.update()

    def setColor(self, color):
        self._auto_color = False
        self._color = QtGui.QColor(color)
        self.update()

    def _color_for_progress(self):
        if self._mode == "sdps":
            return QtGui.QColor("#FC0400")
        if self._value <= 50:
            start = (255, 0, 0)      # красный
            end = (255, 255, 0)       # жёлтый
            factor = self._value / 50
        else:
            start = (255, 255, 0)     # жёлтый
            end = (108, 236, 112)      # зелёный
            factor = (self._value - 50) / 50
        return QtGui.QColor(*[int(a + (b - a) * factor) for a, b in zip(start, end)])

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = self._radius
        painter.setBrush(self._background)
        painter.setPen(QtGui.QPen(QtGui.QColor("#555"), 1))
        painter.drawRoundedRect(rect, radius, radius)
        inner = rect.adjusted(2, 2, -2, -2)
        progress_width = int(inner.width() * (self._value / 100))
        if progress_width > 0:
            progress_rect = QtCore.QRect(inner.left(), inner.top(), progress_width, inner.height())
            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(inner), radius - 2, radius - 2)
            painter.setClipPath(path)
            painter.setBrush(self._color)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRect(progress_rect)
        painter.setClipping(False)
        text = f"{self._value}%"
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(self._text_color_light)
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        if progress_width > 0:
            clip_rect = QtCore.QRect(inner.left(), inner.top(), progress_width, inner.height())
            painter.setClipRect(clip_rect)
            painter.setPen(self._text_color_dark)
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)


class MechanicalCounter(QtWidgets.QWidget):
    """Счётчик-одометр: цифры на механических барабанчиках с последовательным переворотом."""

    rollFinished = Signal()

    CELL_HEIGHT = 30
    CELL_MIN_WIDTH = 22
    CELL_PADDING = 12
    DIGIT_GAP = 3
    FRAME_MARGIN = 4
    MIN_DIGITS = 3
    ANIM_STEP_MS = 16
    ANIM_DURATION_MS = 240
    STAGGER = 0.25
    OVERSHOOT = 1.35
    ROLL_DELAY_MS = 320
    ROLL_STEP_MS = 85
    ROLL_TOTAL_MS = 2600

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0
        self._cells = []
        self._elapsed = 0
        self._duration_ms = self.ANIM_DURATION_MS
        self._roll_delay_left = 0
        self._roll_left = 0
        self._roll_target = 0
        self._roll_plan = []
        self._roll_interval = self.ROLL_STEP_MS
        self._roll_tick_left = 0
        self._rolling = False
        self._font = QtGui.QFont("DejaVu Sans Mono")
        self._font.setBold(True)
        self._font.setPointSize(15)
        for _ in range(self.MIN_DIGITS):
            self._cells.append(self._new_cell())
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.ANIM_STEP_MS)
        self._timer.timeout.connect(self._on_tick)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self._update_size()

    @staticmethod
    def _new_cell():
        return {"base": 0, "steps": 0, "frac": 0.0}

    def value(self):
        return self._value

    def setValue(self, value):
        """Мгновенно переставить барабаны на значение."""
        self._stop_roll()
        self._apply_value(value)

    def rollTo(self, value, step=None, step_ms=None, delay_ms=ROLL_DELAY_MS):
        """Отмотать счётчик к value пошагово, с паузой перед началом отката.

        Шаг уменьшается по мере отката: сначала сотни, потом десятки, потом
        единицы — как будто разряды гасят по очереди, а не рывком.
        """
        target = max(0, int(value))
        if target == self._value:
            return
        self._snap()
        self._roll_target = target
        self._roll_plan = self._build_roll_plan(self._value, target)
        self._roll_left = len(self._roll_plan)
        self._roll_delay_left = max(0, int(delay_ms))
        interval = self.ROLL_STEP_MS if step_ms is None else max(self.ANIM_STEP_MS, int(step_ms))
        # Длинный отсчёт ужимаем по времени, чтобы он не длился вечно.
        if step is None and self._roll_left:
            interval = max(45, min(interval, self.ROLL_TOTAL_MS // self._roll_left))
        self._roll_interval = max(self.ANIM_STEP_MS, int(interval))
        self._roll_tick_left = 0
        self._duration_ms = max(self.ANIM_STEP_MS * 2, self._roll_interval)
        self._rolling = True
        self._timer.start()

    @staticmethod
    def _roll_step_for(value):
        """Наибольший разряд, который ещё можно уменьшить: 999 -> 100, 100 -> 10."""
        place = 1
        while place * 10 < value:
            place *= 10
        return place

    def _build_roll_plan(self, start, target):
        plan = []
        value = start
        guard = 0
        while value > target and guard < 400:
            guard += 1
            place = self._roll_step_for(value)
            nxt = value - place
            # Разряд гасим до конца, а не перескакиваем через его границу:
            # 199 -> 100, а не 199 -> 099.
            if value > place and nxt < place:
                nxt = place
            if nxt < target:
                nxt = target
            plan.append(nxt)
            value = nxt
        return plan

    def isRolling(self):
        return self._rolling

    def _stop_roll(self):
        self._rolling = False
        self._roll_left = 0
        self._roll_delay_left = 0
        self._roll_tick_left = 0
        self._roll_plan = []
        self._elapsed = 0
        self._duration_ms = self.ANIM_DURATION_MS

    def _apply_value(self, value):
        value = max(0, int(value))
        if value == self._value:
            return
        self._snap()
        if not self._rolling:
            self._duration_ms = self.ANIM_DURATION_MS
        needed = max(self.MIN_DIGITS, len(str(value)))
        while len(self._cells) < needed:
            self._cells.append(self._new_cell())
        old_text = str(self._value).zfill(len(self._cells))
        self._value = value
        new_text = str(value).zfill(len(self._cells))
        for cell, old_char, new_char in zip(self._cells, old_text, new_text):
            start = int(old_char)
            end = int(new_char)
            forward = (end - start) % 10
            if forward <= 5:
                cell["steps"] = forward
            else:
                cell["steps"] = forward - 10
            cell["base"] = start
            cell["frac"] = 0.0
        self._update_size()
        self._elapsed = 0
        if any(cell["steps"] for cell in self._cells):
            self._timer.start()
        self._update_cells()

    def _snap(self):
        self._timer.stop()
        for cell in self._cells:
            if cell["steps"]:
                cell["base"] = (cell["base"] + cell["steps"]) % 10
                cell["steps"] = 0
                cell["frac"] = 0.0

    def _on_tick(self):
        if self._rolling:
            if self._roll_delay_left > 0:
                self._roll_delay_left -= self.ANIM_STEP_MS
                return
            # Каждый щелчок отмотанного барабана — отдельный короткий переворот.
            if self._roll_tick_left > 0:
                self._roll_tick_left -= 1
                self._elapsed += self.ANIM_STEP_MS
                self._update_cells()
                return
            # Индекс шага берём до уменьшения счётчика, иначе теряется первый щелчок.
            nxt = self._roll_plan[len(self._roll_plan) - self._roll_left]
            self._roll_left -= 1
            self._apply_value(nxt)
            ticks = self._roll_interval // self.ANIM_STEP_MS
            self._roll_tick_left = ticks - 1
            if self._roll_left <= 0 or self._value <= self._roll_target:
                self._apply_value(self._roll_target)
                self._stop_roll()
                self.rollFinished.emit()
            return
        self._elapsed += self.ANIM_STEP_MS
        if self._update_cells():
            self._timer.stop()

    def _ease(self, p):
        c3 = self.OVERSHOOT + 1.0
        return 1.0 + c3 * (p - 1.0) ** 3 + self.OVERSHOOT * (p - 1.0) ** 2

    def _update_cells(self):
        finished = True
        total = len(self._cells)
        duration = self._duration_ms
        for i, cell in enumerate(self._cells):
            if not cell["steps"]:
                cell["frac"] = 0.0
                continue
            # Младший разряд ведёт, старшие подтягиваются за ним — как на одометре.
            delay = (total - 1 - i) * self.STAGGER * duration
            progress = (self._elapsed - delay) / duration
            if progress < 1.0:
                finished = False
            progress = max(0.0, min(1.0, progress))
            cell["frac"] = cell["steps"] * self._ease(progress)
        self.update()
        return finished

    def _cell_width(self):
        advance = QtGui.QFontMetrics(self._font).horizontalAdvance("0")
        return max(self.CELL_MIN_WIDTH, advance + self.CELL_PADDING)

    def _update_size(self):
        width = self._cell_width() * len(self._cells) + self.DIGIT_GAP * (len(self._cells) - 1)
        self.setFixedSize(
            width + self.FRAME_MARGIN * 2,
            self.CELL_HEIGHT + self.FRAME_MARGIN * 2,
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        painter.fillRect(self.rect(), QtGui.QColor("#181818"))
        cell_width = self._cell_width()
        height = self.CELL_HEIGHT
        x = self.FRAME_MARGIN
        for cell in self._cells:
            rect = QtCore.QRectF(x, self.FRAME_MARGIN, cell_width, height)
            self._paint_cell(painter, rect, cell)
            x += cell_width + self.DIGIT_GAP

    def _paint_cell(self, painter, rect, cell):
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, QtGui.QColor("#0b0b0b"))
        painter.setPen(QtGui.QColor("#f2f2f2"))
        # Окно цифр строим вокруг текущей позиции: при перелёте барабана frac
        # выходит за ±1, и фиксированный диапазон оставлял бы ячейку пустой.
        visible = int(round(cell["frac"]))
        first = min(0, visible) - 1
        last = max(0, visible) + 1
        for offset in range(first, last + 1):
            digit = (cell["base"] + offset) % 10
            band = QtCore.QRectF(
                rect.left(),
                rect.top() + (offset - cell["frac"]) * rect.height(),
                rect.width(),
                rect.height(),
            )
            painter.drawText(band, QtCore.Qt.AlignmentFlag.AlignCenter, str(digit))
        shade = QtGui.QLinearGradient(rect.topLeft(), QtCore.QPointF(rect.left(), rect.center().y()))
        shade.setColorAt(0.0, QtGui.QColor(0, 0, 0, 90))
        shade.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        painter.fillRect(QtCore.QRectF(rect.left(), rect.top(), rect.width(), rect.height() / 2), shade)
        painter.restore()
        painter.setPen(QtGui.QPen(QtGui.QColor("#4a4a4a"), 1))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        painter.setPen(QtGui.QPen(QtGui.QColor("#2e2e2e"), 1))
        painter.drawLine(
            QtCore.QPointF(rect.left() + 2, rect.center().y()),
            QtCore.QPointF(rect.right() - 2, rect.center().y()),
        )


class PanelSignals(QtCore.QObject):
    log = Signal(str, str)
    progress = Signal(int, str)
    set_bg = Signal(str)
    clear = Signal()
    info = Signal(str, str)
    auto_state = Signal(bool)
    error_marker = Signal(bool)
    count_lbl = Signal()


class ClickableLabel(QtWidgets.QLabel):
    clicked = Signal()
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


