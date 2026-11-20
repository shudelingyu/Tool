"""LogLens 自定义控件：拖拽遮罩、统计图表、日志树、详情面板等。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Optional, Sequence

from PyQt5.QtCore import (
    QDate,
    QEasingCurve,
    QModelIndex,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTime,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDateEdit,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTextEdit,
    QTimeEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from .analysis import (
    FieldStat,
    LogGroup,
    Query,
    Summary,
    TimeHistogram,
    build_pattern,
    find_spans,
    select_time_context,
)
from .icons import icon, logo_pixmap
from .parser import LEVELS, LogEntry, ParseResult
from .theme import (
    ACCENT,
    BORDER,
    FAINT,
    LEVEL_CHIP_CHECKED,
    MUTED,
    TEXT,
    TEXT_SECONDARY,
    level_background,
    level_color,
    mono_family,
    qcolor,
    ui_family,
)

# ---------------------------------------------------------------------------
# 树模型数据角色
# ---------------------------------------------------------------------------

ROLE_GROUP = Qt.UserRole + 1
ROLE_GROUP_KEY = Qt.UserRole + 2
ROLE_GROUP_ENTRIES = Qt.UserRole + 3
ROLE_GROUP_SHARE = Qt.UserRole + 4
ROLE_GROUP_HINT = Qt.UserRole + 5
ROLE_GROUP_LEVEL = Qt.UserRole + 6
ROLE_GROUP_POPULATED = Qt.UserRole + 7
ROLE_ENTRY = Qt.UserRole + 11
ROLE_LEVEL = Qt.UserRole + 12
ROLE_TS = Qt.UserRole + 13
ROLE_MODULE = Qt.UserRole + 14
ROLE_MESSAGE = Qt.UserRole + 15
ROLE_SPANS = Qt.UserRole + 16
ROLE_NOTICE = Qt.UserRole + 17
ROLE_GROUP_SHOWN = Qt.UserRole + 18
ROLE_CONTEXT_ANCHOR = Qt.UserRole + 19
ROLE_CONTEXT_SIZE = Qt.UserRole + 20

PER_GROUP_LIMIT = 1000
EXPAND_BUDGET = 7000

def font(size: float, weight: int = QFont.Normal) -> QFont:
    """size 以 96 DPI 下的磅值为设计基准，换算为逻辑像素以适配高 DPI。"""
    value = QFont(ui_family())
    value.setPixelSize(max(1, round(size * 4 / 3)))
    value.setWeight(weight)
    return value


def mono_font(size: float, weight: int = QFont.Normal) -> QFont:
    value = QFont(mono_family())
    value.setPixelSize(max(1, round(size * 4 / 3)))
    value.setStyleHint(QFont.Monospace)
    value.setWeight(weight)
    return value


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def format_count(value: int) -> str:
    return f"{value:,}"


def format_percent(part: int, total: int) -> str:
    if total <= 0:
        return "0%"
    return f"{part / total * 100:.1f}%"


def format_interval(seconds: int) -> str:
    if seconds < 60:
        return f"每 {seconds} 秒"
    if seconds < 3600:
        return f"每 {seconds // 60} 分钟"
    if seconds < 86400:
        return f"每 {seconds // 3600} 小时"
    return f"每 {seconds // 86400} 天"


class ElidedLabel(QLabel):
    """按宽度省略文本，同时保留完整 tooltip。"""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.ElideRight, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(16)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt 命名
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._refresh()

    def fullText(self) -> str:  # noqa: N802
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._full_text:
            super().setText("")
            return
        width = max(0, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._full_text, self._mode, width))


class FlowLayout(QLayout):
    """自动换行的流式布局，用于级别筛选标签。"""

    def __init__(self, parent=None, margin: int = 0, hspacing: int = 6, vspacing: int = 6):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            space_x = self._hspacing
            space_y = self._vspacing
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + margins.bottom()


# ---------------------------------------------------------------------------
# 拖拽与提示
# ---------------------------------------------------------------------------


class DropOverlay(QWidget):
    """全窗口拖拽遮罩，提供明确的视觉反馈。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(130)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)
        self._hiding = False

    def show_overlay(self) -> None:
        if self.isVisible() and not self._hiding:
            return
        self._hiding = False
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0)
        self._animation.start()

    def hide_overlay(self) -> None:
        if not self.isVisible():
            return
        self._hiding = True
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.start()

    def _on_animation_finished(self) -> None:
        if self._hiding:
            self.setVisible(False)
            self._hiding = False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 118))

        width = min(520, max(360, self.width() - 80))
        height = 268
        card = QRectF(
            (self.width() - width) / 2,
            (self.height() - height) / 2 - 12,
            width,
            height,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 248))
        painter.drawRoundedRect(card, 18, 18)

        dash = QRectF(card.adjusted(10, 10, -10, -10))
        pen = QPen(QColor("#BFDBFE"), 1.6, Qt.DashLine)
        pen.setDashPattern([4, 3])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(dash, 13, 13)

        logo = logo_pixmap(64)
        painter.drawPixmap(
            QRectF(card.center().x() - 32, card.top() + 34, 64, 64),
            logo,
            QRectF(0, 0, logo.width(), logo.height()),
        )

        painter.setPen(QColor(TEXT))
        painter.setFont(font(15, QFont.DemiBold))
        painter.drawText(
            QRectF(card.left(), card.top() + 116, card.width(), 30),
            Qt.AlignHCenter | Qt.AlignVCenter,
            "松开以导入日志文件",
        )
        painter.setPen(QColor(MUTED))
        painter.setFont(font(10))
        painter.drawText(
            QRectF(card.left() + 24, card.top() + 152, card.width() - 48, 24),
            Qt.AlignHCenter | Qt.AlignVCenter,
            "支持 TXT / LOG / JSONL 等任意文本日志 · 自动识别编码",
        )
        painter.setPen(QColor(FAINT))
        painter.setFont(font(9))
        painter.drawText(
            QRectF(card.left(), card.top() + 190, card.width(), 24),
            Qt.AlignHCenter | Qt.AlignVCenter,
            "拖拽到窗口任意位置即可",
        )


class Toast(QWidget):
    """右下角（底部居中）轻量提示，自动淡出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setVisible(False)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._label = QLabel("", self)
        self._label.setWordWrap(False)
        self._label.setStyleSheet("color:#F8FAFC;font-size:11px;background:transparent;")
        self._icon = QLabel("", self)
        self._icon.setFixedSize(18, 18)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(9)
        layout.addWidget(self._icon)
        layout.addWidget(self._label)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.fade_out)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._hide_after = False
        self._animation.finished.connect(self._on_finished)

    def show_message(self, text: str, kind: str = "success") -> None:
        colors = {
            "success": "#34D399",
            "error": "#F87171",
            "info": "#60A5FA",
            "warning": "#FBBF24",
        }
        names = {"success": "check", "error": "warning", "info": "spark", "warning": "warning"}
        self._icon.setPixmap(icon(names.get(kind, "check"), colors.get(kind, "#34D399"), 16).pixmap(16, 16))
        self._label.setText(text)
        self._label.adjustSize()
        width = min(620, self._label.width() + 64)
        self.setFixedWidth(width)
        self.adjustSize()
        if self.parentWidget() is not None:
            self._place()
        self.show()
        self.raise_()
        self._hide_after = False
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(1.0)
        self._animation.start()
        self._timer.start(3200)

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._hide_after = True
        self._animation.stop()
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(0.0)
        self._animation.start()

    def _on_finished(self) -> None:
        if self._hide_after:
            self.setVisible(False)
            self._hide_after = False

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            max(12, (parent.width() - self.width()) // 2),
            max(12, parent.height() - self.height() - 24),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
        painter.setBrush(QColor(15, 23, 42, 245))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)


# ---------------------------------------------------------------------------
# 统计卡片与图表
# ---------------------------------------------------------------------------


class MiniStat(QWidget):
    def __init__(self, caption: str, color: str = TEXT, parent=None):
        super().__init__(parent)
        self._value = QLabel("0")
        self._value.setObjectName("StatValue")
        self._value.setStyleSheet(f"color:{color};")
        self._caption = QLabel(caption)
        self._caption.setObjectName("StatCaption")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(self._value)
        layout.addWidget(self._caption)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class StatStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._total = MiniStat("总条目", TEXT)
        self._matched = MiniStat("当前匹配", ACCENT)
        self._errors = MiniStat("错误", "#DC2626")
        self._warnings = MiniStat("警告", "#D97706")
        for index, widget in enumerate(
            (self._total, self._matched, self._errors, self._warnings)
        ):
            if index:
                separator = QFrame()
                separator.setObjectName("Separator")
                separator.setFixedWidth(1)
                separator.setFixedHeight(28)
                layout.addWidget(separator)
            layout.addWidget(widget, 1)

    def set_values(self, total: int, matched: int, errors: int, warnings: int) -> None:
        self._total.set_value(format_count(total))
        self._matched.set_value(format_count(matched))
        self._errors.set_value(format_count(errors))
        self._warnings.set_value(format_count(warnings))


class LegendRow(QWidget):
    def __init__(self, level: str, parent=None):
        super().__init__(parent)
        self._level = level
        self._count = 0
        self._total = 0
        self.setFixedHeight(16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, count: int, total: int) -> None:
        self._count = count
        self._total = total
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(level_color(self._level)))
        painter.drawEllipse(QRectF(0, (self.height() - 6) / 2, 6, 6))

        painter.setFont(font(8.3))
        painter.setPen(QColor(TEXT_SECONDARY))
        painter.drawText(
            QRectF(11, 0, self.width() - 11, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._level,
        )
        text = f"{format_count(self._count)} · {format_percent(self._count, self._total)}"
        painter.setFont(mono_font(7.8))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(11, 0, self.width() - 11, self.height()),
            Qt.AlignVCenter | Qt.AlignRight,
            text,
        )


class DonutChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts: dict[str, int] = {}
        self._total = 0
        self._hover = -1
        self.setMinimumSize(96, 96)
        self.setMaximumHeight(112)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedSize(104, 104)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._counts = dict(counts)
        self._total = sum(counts.values())
        self._hover = -1
        self.update()

    def _segments(self):
        total = self._total
        if total <= 0:
            return []
        segments = []
        start = 90.0
        for level in LEVELS:
            count = self._counts.get(level, 0)
            if count <= 0:
                continue
            span = 360.0 * count / total
            segments.append((level, start, span, count))
            start += span
        return segments

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height())
        thick = 13.0
        rect = QRectF(
            (self.width() - side) / 2 + thick / 2 + 2,
            (self.height() - side) / 2 + thick / 2 + 2,
            side - thick - 4,
            side - thick - 4,
        )
        painter.setPen(QPen(QColor("#EDF2F8"), thick, Qt.SolidLine, Qt.FlatCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        segments = self._segments()
        for index, (level, start, span, _count) in enumerate(segments):
            shown = max(0.0, span - (1.4 if len(segments) > 1 else 0.0))
            width = thick + (3 if index == self._hover else 0)
            pen = QPen(qcolor(level_color(level)), width, Qt.SolidLine, Qt.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, int((start + 0.7) * 16), int(-shown * 16))

        painter.setPen(QColor(TEXT))
        if 0 <= self._hover < len(segments):
            level, _start, _span, count = segments[self._hover]
            painter.setFont(font(13, QFont.DemiBold))
            painter.drawText(
                QRectF(0, side / 2 - 22, self.width(), 24),
                Qt.AlignCenter,
                format_percent(count, self._total),
            )
            painter.setFont(font(8.2, QFont.DemiBold))
            painter.setPen(qcolor(level_color(level)))
            painter.drawText(
                QRectF(0, side / 2 + 2, self.width(), 18),
                Qt.AlignCenter,
                level,
            )
        else:
            painter.setFont(font(15, QFont.DemiBold))
            painter.drawText(
                QRectF(0, side / 2 - 20, self.width(), 24),
                Qt.AlignCenter,
                format_count(self._total),
            )
            painter.setFont(font(8.2))
            painter.setPen(QColor(FAINT))
            painter.drawText(
                QRectF(0, side / 2 + 3, self.width(), 18),
                Qt.AlignCenter,
                "条日志",
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        segments = self._segments()
        if not segments:
            return
        center = QPointF(self.width() / 2, self.height() / 2)
        dx = event.pos().x() - center.x()
        dy = event.pos().y() - center.y()
        radius = math.hypot(dx, dy)
        side = min(self.width(), self.height())
        outer = side / 2 - 2
        inner = outer - 20
        hover = -1
        if inner <= radius <= outer + 4:
            angle = (math.degrees(math.atan2(dx, -dy))) % 360.0
            for index, (_level, start, span, _count) in enumerate(segments):
                if start <= angle < start + span:
                    hover = index
                    break
        if hover != self._hover:
            self._hover = hover
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.update()


class DistributionCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("级别分布")
        title.setObjectName("CardTitle")
        hint = QLabel("悬停查看占比")
        hint.setObjectName("CardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self._donut = DonutChart()
        body.addWidget(self._donut, 0, Qt.AlignTop)
        legend_wrap = QWidget()
        legend_layout = QVBoxLayout(legend_wrap)
        legend_layout.setContentsMargins(0, 3, 0, 0)
        legend_layout.setSpacing(1)
        self._rows = {level: LegendRow(level) for level in LEVELS}
        for level in LEVELS:
            row = self._rows[level]
            row.setVisible(False)
            legend_layout.addWidget(row)
        self._empty = QLabel("暂无数据")
        self._empty.setObjectName("Muted")
        self._empty.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        legend_layout.addWidget(self._empty)
        legend_layout.addStretch(1)
        body.addWidget(legend_wrap, 1)
        layout.addLayout(body)

    def set_counts(self, counts: dict[str, int]) -> None:
        self._donut.set_counts(counts)
        total = sum(counts.values())
        has_data = total > 0
        self._empty.setVisible(not has_data)
        for level, row in self._rows.items():
            count = counts.get(level, 0)
            row.setVisible(has_data and count > 0)
            row.set_value(count, total)


class TrendChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Optional[TimeHistogram] = None
        self._hover = -1
        self.setMinimumHeight(98)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, data: Optional[TimeHistogram]) -> None:
        self._data = data
        self._hover = -1
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(4, 16, max(10, self.width() - 8), max(10, self.height() - 34))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self._plot_rect()
        painter.setPen(QPen(QColor("#EEF3F9"), 1, Qt.DashLine))
        for index in range(1, 4):
            y = rect.top() + rect.height() * index / 4
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))

        data = self._data
        if data is None or not data.counts or sum(data.counts) == 0:
            painter.setFont(font(9.5))
            painter.setPen(QColor(FAINT))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无时间数据")
            return

        counts = data.counts
        peak = max(1, max(counts))
        step_x = rect.width() / max(1, len(counts))
        bottom = rect.bottom()

        def point(index: int) -> QPointF:
            x = rect.left() + (index + 0.5) * step_x
            y = bottom - (counts[index] / peak) * (rect.height() - 2)
            return QPointF(x, y)

        area = QPainterPath()
        area.moveTo(rect.left() + 0.5 * step_x, bottom)
        line = QPainterPath()
        first = point(0)
        line.moveTo(first)
        area.lineTo(first)
        for index in range(1, len(counts)):
            current = point(index)
            line.lineTo(current)
            area.lineTo(current)
        last = point(len(counts) - 1)
        area.lineTo(last.x(), bottom)
        area.closeSubpath()

        gradient = QLinearGradient(0, rect.top(), 0, bottom)
        gradient.setColorAt(0.0, qcolor(ACCENT, 58))
        gradient.setColorAt(1.0, qcolor(ACCENT, 4))
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(area)

        pen = QPen(QColor(ACCENT), 1.8)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(line)

        painter.setFont(font(7.8))
        painter.setPen(QColor(FAINT))
        labels = [0, len(counts) // 2, len(counts) - 1]
        multi_day = data.first.date() != data.last.date()
        label_width = 84 if multi_day and data.step_seconds < 86400 else 64
        for index in labels:
            moment = data.starts[index]
            if multi_day:
                if data.step_seconds >= 86400:
                    text = f"{moment:%m-%d}"
                else:
                    text = f"{moment:%m-%d %H:%M}"
            else:
                text = f"{moment:%H:%M}" if data.step_seconds < 86400 else f"{moment:%m-%d}"
            if index == 0:
                box = QRectF(rect.left(), bottom + 5, label_width, 14)
                align = Qt.AlignLeft
            elif index == len(counts) - 1:
                box = QRectF(rect.right() - label_width, bottom + 5, label_width, 14)
                align = Qt.AlignRight
            else:
                center_x = rect.left() + (index + 0.5) * step_x
                box = QRectF(center_x - label_width / 2, bottom + 5, label_width, 14)
                align = Qt.AlignHCenter
            painter.drawText(box, align | Qt.AlignVCenter, text)

        painter.setFont(mono_font(7.8))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(rect.left(), 0, rect.width(), 14),
            Qt.AlignRight | Qt.AlignVCenter,
            f"峰值 {format_count(peak)}",
        )

        if 0 <= self._hover < len(counts):
            x = rect.left() + (self._hover + 0.5) * step_x
            painter.setPen(QPen(qcolor(ACCENT, 120), 1, Qt.DashLine))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, bottom))
            painter.setPen(QPen(QColor(ACCENT), 1.6))
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(point(self._hover), 3.4, 3.4)

            label = f"{data.starts[self._hover]:%m-%d %H:%M} · {counts[self._hover]:,} 条"
            painter.setFont(font(8.3, QFont.DemiBold))
            metrics = QFontMetrics(painter.font())
            width = metrics.horizontalAdvance(label) + 18
            box = QRectF(x - width / 2, rect.top() - 2, width, 20)
            if box.left() < 2:
                box.moveLeft(2)
            if box.right() > self.width() - 2:
                box.moveRight(self.width() - 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(15, 23, 42, 235))
            painter.drawRoundedRect(box, 6, 6)
            painter.setPen(QColor("#F8FAFC"))
            painter.drawText(box, Qt.AlignCenter, label)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        data = self._data
        if data is None or not data.counts:
            return
        rect = self._plot_rect()
        if not rect.contains(event.pos()):
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        index = int((event.pos().x() - rect.left()) / max(1.0, rect.width() / len(data.counts)))
        index = max(0, min(len(data.counts) - 1, index))
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover != -1:
            self._hover = -1
            self.update()


class TrendCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("时间趋势")
        title.setObjectName("CardTitle")
        self._hint = QLabel("")
        self._hint.setObjectName("CardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._hint)
        layout.addLayout(header)
        self._chart = TrendChart()
        layout.addWidget(self._chart, 1)
        self._missing = QLabel("")
        self._missing.setObjectName("CardHint")
        self._missing.setVisible(False)
        layout.addWidget(self._missing)

    def set_data(self, data: Optional[TimeHistogram], missing: int) -> None:
        self._chart.set_data(data)
        if data is None:
            self._hint.setText("")
            self._missing.setVisible(missing > 0)
            self._missing.setText(f"{format_count(missing)} 条日志无时间戳，未计入趋势")
            return
        self._hint.setText(format_interval(data.step_seconds))
        self._missing.setVisible(missing > 0)
        if missing:
            self._missing.setText(f"{format_count(missing)} 条日志无时间戳，未计入趋势")
        self.setMinimumHeight(150)


class ModuleBars(QWidget):
    moduleClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: Sequence[tuple[str, int]]) -> None:
        self._data = list(data[:6])
        self._hover = -1
        self.setMinimumHeight(max(58, len(self._data) * 24 + (2 if not self._data else 0)))
        self.updateGeometry()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if not self._data:
            painter.setFont(font(9.5))
            painter.setPen(QColor(FAINT))
            painter.drawText(self.rect(), Qt.AlignCenter, "暂无模块数据")
            return

        peak = max(1, max(count for _, count in self._data))
        row_height = 24
        for index, (name, count) in enumerate(self._data):
            top = index * row_height
            row = QRectF(0, top + 1, self.width(), row_height - 3)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#F4F7FB"))
            painter.drawRoundedRect(row, 6, 6)
            ratio = max(0.035, count / peak)
            fill = row.adjusted(0, 0, -row.width() * (1 - ratio), 0)
            painter.setBrush(QColor("#DBEAFE") if index != self._hover else QColor("#C7DDFE"))
            painter.drawRoundedRect(fill, 6, 6)

            painter.setFont(font(8.6, QFont.DemiBold))
            painter.setPen(QColor("#334155"))
            metrics = QFontMetrics(painter.font())
            count_text = format_count(count)
            count_width = metrics.horizontalAdvance(count_text) + 10
            name_text = QFontMetrics(font(8.6)).elidedText(
                name, Qt.ElideRight, max(10, int(row.width() - count_width - 24))
            )
            painter.drawText(
                row.adjusted(10, 0, -count_width - 16, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                name_text,
            )
            painter.setFont(mono_font(7.8, QFont.DemiBold))
            painter.setPen(QColor(ACCENT))
            painter.drawText(
                row.adjusted(0, 0, -10, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                count_text,
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = event.pos().y() // 24
        if index >= len(self._data):
            index = -1
        if index != self._hover:
            self._hover = index
            self.setCursor(Qt.PointingHandCursor if index >= 0 else Qt.ArrowCursor)
            self.setToolTip("点击按该模块筛选" if index >= 0 else "")
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        index = event.pos().y() // 24
        if 0 <= index < len(self._data) and event.button() == Qt.LeftButton:
            self.moduleClicked.emit(self._data[index][0])


class FieldTable(QTreeWidget):
    fieldActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FieldTable")
        self.setColumnCount(2)
        self.setHeaderLabels(["字段 / 次数", "常见示例"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAlternatingRowColors(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setToolTip("双击字段可按该字段的值分组")
        header = self.header()
        header.setFixedHeight(24)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.setColumnWidth(0, 104)
        self.setFixedHeight(196)
        self.setUniformRowHeights(True)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self._placeholder("暂无键值字段")

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        field = item.data(0, Qt.UserRole) if item is not None else None
        if field:
            self.fieldActivated.emit(str(field))

    def _placeholder(self, text: str) -> None:
        self.clear()
        item = QTreeWidgetItem([text, ""])
        item.setFlags(Qt.ItemIsEnabled)
        item.setForeground(0, QColor(FAINT))
        self.addTopLevelItem(item)

    def set_data(self, stats: Sequence[FieldStat]) -> None:
        self.clear()
        if not stats:
            self._placeholder("暂无键值字段")
            return
        for stat in stats:
            sample = stat.values[0][0] if stat.values else "—"
            shape = matrix_shape(stat.name, sample)
            if shape is not None:
                sample = f"{shape[0]}×{shape[1]} 矩阵 · {len(_sequence_tokens(sample))} 值"
            elif len(sample) > 80:
                sample = sample[:77] + "..."
            item = QTreeWidgetItem([f"{stat.name}  {format_count(stat.count)}", sample])
            item.setData(0, Qt.UserRole, stat.name)
            item.setToolTip(0, f"{stat.name}\n双击按该字段的值分组")
            tooltip = "\n".join(
                f"{value}  ×{count}" for value, count in stat.values
            ) or "—"
            item.setToolTip(1, tooltip)
            self.addTopLevelItem(item)


class ModulesCard(QFrame):
    moduleClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("高频模块")
        title.setObjectName("CardTitle")
        self._hint = QLabel("点击筛选")
        self._hint.setObjectName("CardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._hint)
        layout.addLayout(header)
        self._bars = ModuleBars()
        self._bars.moduleClicked.connect(self.moduleClicked)
        layout.addWidget(self._bars)

    def set_data(self, modules: Sequence[tuple[str, int]], total_modules: int) -> None:
        self._bars.set_data(modules)
        self._hint.setText("点击筛选" if modules else "暂无数据")
        self.setToolTip(f"共 {total_modules} 个模块" if total_modules else "")


class FieldsCard(QFrame):
    fieldActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("关键字段")
        title.setObjectName("CardTitle")
        hint = QLabel("双击按值分组")
        hint.setObjectName("CardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)
        self._table = FieldTable()
        self._table.fieldActivated.connect(self.fieldActivated)
        layout.addWidget(self._table)

    def set_data(self, stats: Sequence[FieldStat]) -> None:
        self._table.set_data(stats)


class OverviewCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("概览")
        title.setObjectName("CardTitle")
        self._hint = QLabel("")
        self._hint.setObjectName("CardHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._hint)
        layout.addLayout(header)
        self._stats = StatStrip()
        layout.addWidget(self._stats)

    def set_values(self, total: int, matched: int, errors: int, warnings: int) -> None:
        self._stats.set_values(total, matched, errors, warnings)
        self._hint.setText(f"匹配 {format_count(matched)} / {format_count(total)}")
        
class SourceCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("数据源")
        title.setObjectName("CardTitle")
        self._encoding = QLabel("")
        self._encoding.setObjectName("EncodingPill")
        self._encoding.setVisible(False)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._encoding)
        layout.addLayout(header)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 2, 0, 0)
        file_row.setSpacing(8)
        self._icon = QLabel()
        self._icon.setFixedSize(22, 22)
        self._icon.setPixmap(icon("file", FAINT, 20).pixmap(20, 20))
        file_row.addWidget(self._icon, 0, Qt.AlignTop)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._name = ElidedLabel("尚未加载日志", Qt.ElideRight)
        self._name.setObjectName("SourceName")
        self._path = ElidedLabel("拖入文件或点击“打开日志”", Qt.ElideMiddle)
        self._path.setObjectName("SourcePath")
        text_col.addWidget(self._name)
        text_col.addWidget(self._path)
        file_row.addLayout(text_col, 1)
        layout.addLayout(file_row)

        self._meta = QLabel("")
        self._meta.setObjectName("SourceMeta")
        self._meta.setVisible(False)
        layout.addWidget(self._meta)
        self._range = QLabel("")
        self._range.setObjectName("SourceMeta")
        self._range.setVisible(False)
        layout.addWidget(self._range)

    def set_result(self, result: ParseResult) -> None:
        self._icon.setPixmap(icon("file", ACCENT, 20).pixmap(20, 20))
        self._name.setText(result.path.name)
        self._name.setToolTip(str(result.path))
        self._path.setText(str(result.path.parent))
        self._encoding.setText(result.encoding_label)
        self._encoding.setVisible(True)
        meta = (
            f"{human_size(result.file_size)} · {format_count(result.total_lines)} 行 · "
            f"解析 {result.duration:.2f} s"
        )
        self._meta.setText(meta)
        self._meta.setVisible(True)
        time_range = result.time_range_text
        if time_range:
            self._range.setText(time_range.replace(" → ", "  →  "))
            self._range.setVisible(True)
        else:
            self._range.setVisible(False)

    def clear(self) -> None:
        self._icon.setPixmap(icon("file", FAINT, 20).pixmap(20, 20))
        self._name.setText("尚未加载日志")
        self._path.setText("拖入文件或点击“打开日志”")
        self._encoding.setVisible(False)
        self._meta.setVisible(False)
        self._range.setVisible(False)


class StatsSidebar(QWidget):
    moduleClicked = pyqtSignal(str)
    fieldActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(268)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("SidebarCanvas")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(9)
        self.source = SourceCard()
        self.overview = OverviewCard()
        self.distribution = DistributionCard()
        self.trend = TrendCard()
        self.modules = ModulesCard()
        self.fields = FieldsCard()
        self.modules.moduleClicked.connect(self.moduleClicked)
        self.fields.fieldActivated.connect(self.fieldActivated)
        layout.addWidget(self.source)
        layout.addWidget(self.overview)
        layout.addWidget(self.distribution)
        layout.addWidget(self.trend)
        layout.addWidget(self.modules)
        layout.addWidget(self.fields)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def set_result(self, result: ParseResult) -> None:
        self.source.set_result(result)

    def update_summary(self, summary: Summary) -> None:
        self.overview.set_values(
            summary.total,
            summary.matched,
            summary.error_count,
            summary.warning_count,
        )
        self.distribution.set_counts(summary.level_counts)
        self.trend.set_data(summary.histogram, summary.missing_timestamps)
        self.modules.set_data(summary.top_modules, summary.module_total)
        self.fields.set_data(summary.fields)

    def clear(self) -> None:
        self.source.clear()
        self.overview.set_values(0, 0, 0, 0)
        self.distribution.set_counts({})
        self.trend.set_data(None, 0)
        self.modules.set_data([], 0)
        self.fields.set_data([])


# ---------------------------------------------------------------------------
# 时间范围筛选栏
# ---------------------------------------------------------------------------


def _to_qdate(value: Optional[datetime]) -> QDate:
    if value is None:
        return QDate.currentDate()
    return QDate(value.year, value.month, value.day)


def _to_qtime(value: Optional[datetime]) -> QTime:
    if value is None:
        return QTime.currentTime()
    return QTime(value.hour, value.minute, value.second)


class TimeRangeDialog(QDialog):
    """选择日志时间范围；启用筛选时无时间戳的日志会被排除。"""

    def __init__(
        self,
        parent=None,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        file_start: Optional[datetime] = None,
        file_end: Optional[datetime] = None,
        file_truncated: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("TimeDialog")
        self.setWindowTitle("时间范围")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet(
            "QDialog#TimeDialog { background:#FFFFFF; }"
            "QDateEdit, QTimeEdit { background:#FFFFFF; border:1px solid #D9E2EE;"
            " border-radius:8px; padding:0 8px; color:#334155; }"
        )
        self.cleared = False
        self.since = since
        self.until = until

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(9)

        title = QLabel("按时间筛选日志")
        title.setStyleSheet("font-size:15px;font-weight:700;color:#0F172A;")
        layout.addWidget(title)

        hint_text = (
            "只显示所选时间段内的日志；无时间戳的日志会被排除。"
            "日期可点日历选择，时间可直接输入或使用上下箭头调整。"
        )
        if file_start is not None and file_end is not None:
            hint_text += (
                f"\n文件时间范围：{file_start:%Y-%m-%d %H:%M:%S}"
                f" → {file_end:%Y-%m-%d %H:%M:%S}"
            )
        if file_truncated:
            hint_text += (
                "\n当前仅保留最近 300,000 条；如需更早的时间，"
                "可直接输入更早日期，应用后会按该时间段重新读取文件。"
            )
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11px;color:#64748B;")
        layout.addWidget(hint)

        self._start_date = self._make_date_edit(since or file_start)
        self._start_time = self._make_time_edit(since or file_start)
        self._end_date = self._make_date_edit(until or file_end)
        self._end_time = self._make_time_edit(until or file_end)
        if file_start is not None and file_end is not None:
            start_limit = _to_qdate(file_start)
            end_limit = _to_qdate(file_end)
            if start_limit <= end_limit:
                self._start_date.setDateRange(start_limit, end_limit)
                self._end_date.setDateRange(start_limit, end_limit)

        for text, date_edit, time_edit in (
            ("起始时间", self._start_date, self._start_time),
            ("结束时间", self._end_date, self._end_time),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(text)
            label.setFixedWidth(60)
            label.setStyleSheet("color:#475569;font-size:12px;")
            row.addWidget(label)
            row.addWidget(date_edit, 1)
            row.addWidget(time_edit, 0)
            layout.addLayout(row)

        self._error = QLabel("")
        self._error.setStyleSheet("color:#DC2626;font-size:11px;")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        clear = QPushButton("清除筛选")
        clear.setObjectName("Ghost")
        clear.setFixedHeight(32)
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._on_clear)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setFixedHeight(32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        apply_button = QPushButton("应用")
        apply_button.setObjectName("Primary")
        apply_button.setFixedHeight(32)
        apply_button.setCursor(Qt.PointingHandCursor)
        apply_button.clicked.connect(self._on_apply)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

    def _make_date_edit(self, value: Optional[datetime]) -> QDateEdit:
        edit = QDateEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setFixedHeight(30)
        edit.setDate(_to_qdate(value))
        return edit

    def _make_time_edit(self, value: Optional[datetime]) -> QTimeEdit:
        edit = QTimeEdit()
        edit.setDisplayFormat("HH:mm:ss")
        edit.setFixedHeight(30)
        edit.setFixedWidth(104)
        edit.setTime(_to_qtime(value))
        return edit

    def _on_clear(self) -> None:
        self.cleared = True
        self.accept()

    def _on_apply(self) -> None:
        start = datetime.combine(
            self._start_date.date().toPyDate(), self._start_time.time().toPyTime()
        )
        # 结束时间包含所选秒内的全部日志（日志常带毫秒）
        end = datetime.combine(
            self._end_date.date().toPyDate(), self._end_time.time().toPyTime()
        ).replace(microsecond=999999)
        if start > end:
            self._error.setText("起始时间不能晚于结束时间")
            self._error.setVisible(True)
            return
        self.since = start
        self.until = end
        self.accept()


# ---------------------------------------------------------------------------
# 级别筛选栏
# ---------------------------------------------------------------------------


class LevelFilterBar(QFrame):
    activeLevelsChanged = pyqtSignal(object)
    moduleFilterCleared = pyqtSignal()
    timeFilterRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterBar")
        self._counts: dict[str, int] = {}
        self._active = set(LEVELS)
        self._updating = False
        self._flow = FlowLayout(None, margin=0, hspacing=6, vspacing=5)
        self._flow.setContentsMargins(20, 5, 16, 6)
        self.setLayout(self._flow)
        self._label = QLabel("级别")
        self._label.setObjectName("SectionLabel")
        self._module_chip = QPushButton("")
        self._module_chip.setObjectName("ModuleChip")
        self._module_chip.setCursor(Qt.PointingHandCursor)
        self._module_chip.setFixedHeight(24)
        self._module_chip.setVisible(False)
        self._module_chip.clicked.connect(self.moduleFilterCleared)
        self._time_chip = QPushButton("时间")
        self._time_chip.setObjectName("ModuleChip")
        self._time_chip.setCursor(Qt.PointingHandCursor)
        self._time_chip.setFixedHeight(24)
        self._time_chip.setToolTip("选择时间范围")
        self._time_chip.clicked.connect(lambda: self.timeFilterRequested.emit())
        self._time_since: Optional[datetime] = None
        self._time_until: Optional[datetime] = None
        self._level_widgets: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(35)
        self._build()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_layout()

    def _sync_layout(self) -> None:
        if self.width() <= 0:
            return
        natural = max(35, self._flow.heightForWidth(self.width()))
        if self.height() != natural:
            self.setFixedHeight(natural)
        self._flow.invalidate()
        self._flow.setGeometry(self.rect())

    def _clear_widgets(self) -> None:
        while self._flow.count():
            self._flow.takeAt(0)
        for widget in self._level_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._level_widgets = []
        self._label.setParent(None)
        self._module_chip.setParent(None)
        self._time_chip.setParent(None)

    def _build(self) -> None:
        self._clear_widgets()
        self._flow.addWidget(self._label)
        all_button = QPushButton("全部")
        all_button.setObjectName("LevelChip")
        all_button.setCheckable(True)
        all_button.setFixedHeight(24)
        all_button.setCursor(Qt.PointingHandCursor)
        all_button.setToolTip("显示全部级别")
        all_button.clicked.connect(lambda: self._on_chip(None))
        self._level_widgets.append(all_button)
        self._flow.addWidget(all_button)
        all_button.show()
        self._all_button = all_button

        for level in LEVELS:
            count = self._counts.get(level, 0)
            if count <= 0:
                continue
            button = QPushButton(f"{level}  {format_count(count)}")
            button.setObjectName("LevelChip")
            button.setCheckable(True)
            button.setFixedHeight(24)
            button.setCursor(Qt.PointingHandCursor)
            button.setProperty("chipLevel", level)
            button.setToolTip(f"仅显示 {level} 级别日志")
            button.clicked.connect(lambda _checked=False, value=level: self._on_chip(value))
            self._level_widgets.append(button)
            self._flow.addWidget(button)
            button.show()
        self._flow.addWidget(self._time_chip)
        self._time_chip.show()
        self._flow.addWidget(self._module_chip)
        self._refresh_time_chip()
        self._refresh_checks()
        self._sync_layout()

    def _refresh_checks(self) -> None:
        self._updating = True
        all_active = self._active == set(LEVELS)
        self._all_button.setChecked(all_active)
        for widget in self._level_widgets:
            if widget is self._all_button:
                continue
            level = widget.property("chipLevel")
            widget.setChecked(level in self._active)
        self._updating = False
        for widget in self._level_widgets:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.updateGeometry()

    def _on_chip(self, level: Optional[str]) -> None:
        if self._updating:
            return
        if level is None:
            self._active = set(LEVELS)
        else:
            if self._active == set(LEVELS):
                # 全部选中时点击某一级别 => 只看该级别
                self._active = {level}
            elif self._active == {level}:
                # 再次点击同一级别 => 恢复全部
                self._active = set(LEVELS)
            elif level in self._active:
                self._active.discard(level)
            else:
                self._active.add(level)
        self._refresh_checks()
        self.activeLevelsChanged.emit(frozenset(self._active))

    def set_counts(self, counts: dict[str, int], active: Optional[set[str]] = None) -> None:
        self._counts = dict(counts)
        if active is not None:
            self._active = set(active)
        self._build()

    def set_active(self, active: set[str]) -> None:
        self._active = set(active)
        self._refresh_checks()
        self.activeLevelsChanged.emit(frozenset(self._active))

    def set_module_filter(self, name: Optional[str]) -> None:
        if name:
            display = name if len(name) <= 26 else name[:25] + "…"
            self._module_chip.setText(f"模块 · {display}   ×")
            self._module_chip.setToolTip(f"当前仅显示模块 {name}，点击清除")
            self._module_chip.setVisible(True)
        else:
            self._module_chip.setVisible(False)
        self.updateGeometry()
        self._sync_layout()

    def set_time_filter(
        self, since: Optional[datetime], until: Optional[datetime]
    ) -> None:
        self._time_since = since
        self._time_until = until
        self._refresh_time_chip()
        self.updateGeometry()
        self._sync_layout()

    def _refresh_time_chip(self) -> None:
        since = self._time_since
        until = self._time_until
        if since is not None and until is not None:
            text = f"时间 {since:%m-%d %H:%M:%S} → {until:%m-%d %H:%M:%S}"
            tip = (
                f"当前时间范围：{since:%Y-%m-%d %H:%M:%S}"
                f" → {until:%Y-%m-%d %H:%M:%S}；点击修改"
            )
        elif since is not None:
            text = f"时间 ≥ {since:%m-%d %H:%M:%S}"
            tip = f"当前仅显示 {since:%Y-%m-%d %H:%M:%S} 之后的日志；点击修改"
        elif until is not None:
            text = f"时间 ≤ {until:%m-%d %H:%M:%S}"
            tip = f"当前仅显示 {until:%Y-%m-%d %H:%M:%S} 之前的日志；点击修改"
        else:
            text = "时间"
            tip = "选择时间范围"
        self._time_chip.setText(text)
        self._time_chip.setToolTip(tip)

    def current_active(self) -> set[str]:
        return set(self._active)


# ---------------------------------------------------------------------------
# 日志树
# ---------------------------------------------------------------------------


class LogTreeDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mono = mono_font(8.2)
        self._mono_small = mono_font(7.6)
        self._group_font = font(9.4, QFont.DemiBold)
        self._group_meta_font = font(8.0)
        self._pill_font = font(7.4, QFont.DemiBold)
        self._notice_font = font(8.2)
        self._notice_font.setItalic(True)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if index.data(ROLE_GROUP):
            return QSize(120, 38)
        if index.data(ROLE_NOTICE):
            return QSize(120, 26)
        return QSize(120, 27)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if index.data(ROLE_GROUP):
            if index.column() == 0:
                self._paint_group(painter, option, index)
        elif index.data(ROLE_NOTICE):
            if index.column() == 0:
                self._paint_notice(painter, option, index)
        elif index.sibling(index.row(), 0).data(ROLE_LEVEL) is not None:
            self._paint_entry(painter, option, index)
        else:
            super().paint(painter, option, index)
        painter.restore()

    def _paint_group(self, painter: QPainter, option, index) -> None:
        view = option.widget
        rect = QRect(option.rect)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        background = "#EDF4FF" if selected else ("#F8FBFF" if hovered else "#F7F9FC")
        painter.fillRect(rect, QColor(background))
        painter.setPen(QPen(QColor("#E8EDF5"), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        level = index.data(ROLE_GROUP_LEVEL)
        color = QColor(level_color(level)) if level else QColor(ACCENT)
        expanded = view is not None and view.isExpanded(index)
        self._draw_chevron(painter, QPointF(rect.left() + 16, rect.center().y() + 0.5), expanded)

        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(rect.left() + 30, rect.center().y() - 3.6, 7.2, 7.2))

        title = index.data(Qt.DisplayRole) or ""
        title_x = rect.left() + 45
        meta_width = int(max(116, min(200, rect.width() * 0.34)))
        right_space = meta_width + 18
        available_title = max(24, rect.width() - title_x - right_space)
        painter.setFont(self._group_font)
        metrics = QFontMetrics(self._group_font)
        title_text = metrics.elidedText(title, Qt.ElideRight, available_title)
        title_width = metrics.horizontalAdvance(title_text)
        painter.setPen(QColor(level_color(level)) if level else QColor("#1E293B"))
        painter.drawText(
            QRect(title_x, rect.top(), max(20, title_width + 4), rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            title_text,
        )

        hint = index.data(ROLE_GROUP_HINT) or ""
        remaining = available_title - title_width - 10
        if hint and remaining > 46:
            painter.setFont(self._group_meta_font)
            painter.setPen(QColor(FAINT))
            hint_text = QFontMetrics(self._group_meta_font).elidedText(
                hint, Qt.ElideRight, remaining
            )
            painter.drawText(
                QRect(title_x + title_width + 10, rect.top(), remaining, rect.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                hint_text,
            )

        count = len(index.data(ROLE_GROUP_ENTRIES) or [])
        share = float(index.data(ROLE_GROUP_SHARE) or 0.0)
        meta = f"{format_count(count)} 条 · {share * 100:.1f}%"
        painter.setFont(mono_font(7.9))
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRect(rect.right() - right_space, rect.top(), meta_width, rect.height()),
            Qt.AlignVCenter | Qt.AlignRight,
            meta,
        )

        bar = QRectF(rect.left() + 45, rect.bottom() - 2, max(1.0, rect.width() - 61), 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#E6EDF7"))
        painter.drawRoundedRect(bar, 1, 1)
        painter.setBrush(qcolor(color.name(), 150))
        painter.drawRoundedRect(
            QRectF(bar.left(), bar.top(), max(2.0, bar.width() * share), bar.height()),
            1,
            1,
        )

    def _paint_notice(self, painter: QPainter, option, index) -> None:
        rect = option.rect
        painter.fillRect(rect, QColor("#FFFFFF"))
        painter.setFont(self._notice_font)
        painter.setPen(QColor(FAINT))
        text = index.data(ROLE_NOTICE) or ""
        painter.drawText(
            rect.adjusted(46, 0, -12, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            QFontMetrics(self._notice_font).elidedText(text, Qt.ElideRight, rect.width() - 60),
        )

    def _paint_entry(self, painter: QPainter, option, index) -> None:
        column = index.column()
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        background = "#EAF2FF" if selected else ("#F8FBFF" if hovered else "#FFFFFF")
        painter.fillRect(rect, QColor(background))
        painter.setPen(QPen(QColor("#F2F5FA"), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        base = index.sibling(index.row(), 0)
        if column == 0:
            level = base.data(ROLE_LEVEL) or "OTHER"
            self._paint_level_pill(painter, rect, level)
        elif column == 1:
            text = base.data(ROLE_TS) or "—"
            painter.setFont(self._mono_small)
            painter.setPen(QColor(MUTED))
            painter.drawText(
                rect.adjusted(12, 0, -8, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                text,
            )
        elif column == 2:
            text = base.data(ROLE_MODULE) or "general"
            self._paint_module(painter, rect, text)
        elif column == 3:
            text = base.data(ROLE_MESSAGE) or ""
            spans = base.data(ROLE_SPANS) or []
            self._paint_message(painter, rect.adjusted(12, 0, -10, 0), text, spans, selected)

    def _paint_level_pill(self, painter: QPainter, rect: QRect, level: str) -> None:
        painter.setFont(self._pill_font)
        metrics = QFontMetrics(self._pill_font)
        text_width = metrics.horizontalAdvance(level)
        pill_width = min(rect.width() - 16, max(38, text_width + 14))
        pill = QRectF(
            rect.left() + 12,
            rect.center().y() - 8.5,
            pill_width,
            17,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(level_background(level)))
        painter.drawRoundedRect(pill, 8.5, 8.5)
        painter.setPen(QColor(level_color(level)))
        painter.drawText(pill, Qt.AlignCenter, level)

    def _paint_module(self, painter: QPainter, rect: QRect, text: str) -> None:
        painter.setFont(font(8.1))
        metrics = QFontMetrics(painter.font())
        available = rect.width() - 22
        if available <= 10:
            return
        elided = metrics.elidedText(text, Qt.ElideRight, available)
        width = min(available, metrics.horizontalAdvance(elided) + 14)
        badge = QRectF(rect.left() + 8, rect.center().y() - 8.5, width, 17)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F1F5F9"))
        painter.drawRoundedRect(badge, 5, 5)
        painter.setPen(QColor("#475569"))
        painter.drawText(badge.adjusted(7, 0, -7, 0), Qt.AlignVCenter | Qt.AlignLeft, elided)

    def _paint_message(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        spans: Sequence[tuple[int, int]],
        selected: bool,
    ) -> None:
        painter.setFont(self._mono)
        painter.setPen(QColor("#1F2937"))
        metrics = QFontMetrics(self._mono)
        if not text:
            return
        elided = metrics.elidedText(text, Qt.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        if not spans:
            return
        cut = len(text)
        if elided != text:
            cut = len(elided) - 1 if elided.endswith("…") else len(elided)
        painter.save()
        painter.setClipRect(rect)
        highlight = QColor("#FCD34D") if selected else QColor("#FDE68A")
        highlight_text = QColor("#78350F") if selected else QColor("#92400E")
        for start, end in spans:
            start = min(start, cut)
            end = min(end, cut)
            if end <= start:
                continue
            x1 = rect.left() + metrics.horizontalAdvance(text[:start])
            x2 = rect.left() + metrics.horizontalAdvance(text[:end])
            if x1 >= rect.right():
                break
            x2 = min(x2, rect.right())
            box = QRectF(x1 - 1, rect.center().y() - 8, max(1.0, x2 - x1 + 2), 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(highlight)
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(highlight_text)
            painter.drawText(
                QRectF(x1, rect.top(), x2 - x1, rect.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                text[start:end],
            )
        painter.restore()

    def _draw_chevron(self, painter: QPainter, center: QPointF, expanded: bool) -> None:
        pen = QPen(QColor("#94A3B8"), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        if expanded:
            path.moveTo(center.x() - 4, center.y() - 2)
            path.lineTo(center.x(), center.y() + 2)
            path.lineTo(center.x() + 4, center.y() - 2)
        else:
            path.moveTo(center.x() - 2, center.y() - 4)
            path.lineTo(center.x() + 2, center.y())
            path.lineTo(center.x() - 2, center.y() + 4)
        painter.drawPath(path)


class LogTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogTree")
        self.setColumnCount(4)
        self.setHeaderLabels(["级别", "时间", "模块", "消息"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(False)
        self.setWordWrap(False)
        self.setAnimated(False)
        self.setMouseTracking(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlternatingRowColors(False)
        self.setTextElideMode(Qt.ElideRight)
        header = self.header()
        header.setFixedHeight(34)
        header.setStretchLastSection(True)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.setColumnWidth(0, 92)
        self.setColumnWidth(1, 172)
        self.setColumnWidth(2, 132)
        self.setItemDelegate(LogTreeDelegate(self))
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.refresh_layout)
        header.sectionResized.connect(self._schedule_layout_refresh)

    def _schedule_layout_refresh(self, *_args) -> None:
        self.schedule_layout_refresh()

    def schedule_layout_refresh(self) -> None:
        """延迟到 Qt 完成布局后再重排并整块重绘，避免跨度/行宽使用旧值。"""
        self._layout_timer.start(0)

    def refresh_layout(self) -> None:
        header = self.header()
        header.blockSignals(True)
        try:
            self.doItemsLayout()
        finally:
            header.blockSignals(False)
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.schedule_layout_refresh()


def build_entry_item(entry: LogEntry, query: Query) -> QTreeWidgetItem:
    """创建一条日志的树行（主列表与上下文窗口共用）。"""

    display_message = entry.message.replace("\r", " ").replace("\n", " ⏎ ")
    spans = find_spans(display_message, query) if query.text.strip() else []
    child = QTreeWidgetItem(["", "", "", ""])
    child.setData(0, ROLE_LEVEL, entry.level)
    child.setData(0, ROLE_TS, entry.timestamp_text or "—")
    child.setData(0, ROLE_MODULE, entry.module)
    child.setData(0, ROLE_MESSAGE, display_message)
    child.setData(0, ROLE_SPANS, spans)
    child.setData(0, ROLE_ENTRY, entry)
    tooltip = display_message if len(display_message) < 1500 else display_message[:1500] + "…"
    child.setToolTip(3, tooltip)
    child.setToolTip(0, f"{entry.level} · 第 {entry.line_no:,} 行")
    return child


_CONTEXT_HEADER_HEIGHT = 30
_CONTEXT_RAW_PADDING = 10


class ContextEntryDelegate(QStyledItemDelegate):
    """上下文窗口的日志行：头部元信息 + 完整原始内容（多行原样展示）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pill_font = font(7.4, QFont.DemiBold)
        self._time_font = mono_font(7.8)
        self._module_font = font(8.1)
        self._meta_font = mono_font(7.6)
        self._raw_font = mono_font(8.0)
        self._raw_metrics = QFontMetrics(self._raw_font)
        self._line_height = max(14, self._raw_metrics.height() + 1)

    def entry_size(self, entry: LogEntry) -> QSize:
        lines = (entry.raw or "").splitlines() or [""]
        raw_width = max(
            (
                self._raw_metrics.horizontalAdvance(line.replace("\t", "    "))
                for line in lines
            ),
            default=0,
        )
        module_width = QFontMetrics(self._module_font).horizontalAdvance(entry.module)
        header_width = 14 + 58 + 10 + 180 + 102 + min(module_width, 360) + 20
        width = max(760, raw_width + 32, header_width)
        height = _CONTEXT_HEADER_HEIGHT + len(lines) * self._line_height + _CONTEXT_RAW_PADDING
        return QSize(width, height)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        size = index.data(ROLE_CONTEXT_SIZE)
        if isinstance(size, QSize):
            return size
        return QSize(760, 52)

    def paint(self, painter: QPainter, option, index) -> None:
        entry = index.data(ROLE_ENTRY)
        if entry is None:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect
        anchor = bool(index.data(ROLE_CONTEXT_ANCHOR))
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if anchor:
            background = "#FEF3C7"
        elif selected:
            background = "#EAF2FF"
        elif hovered:
            background = "#F8FBFF"
        else:
            background = "#FFFFFF"
        painter.fillRect(rect, QColor(background))
        if anchor:
            painter.fillRect(
                QRect(rect.left(), rect.top(), 4, rect.height()), QColor("#F59E0B")
            )
        painter.setPen(QPen(QColor("#EEF2F7"), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        level = entry.level
        painter.setFont(self._pill_font)
        pill_metrics = QFontMetrics(self._pill_font)
        pill_width = max(42, pill_metrics.horizontalAdvance(level) + 14)
        pill = QRectF(rect.left() + 14, rect.top() + 6.5, pill_width, 17)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(level_background(level)))
        painter.drawRoundedRect(pill, 8.5, 8.5)
        painter.setPen(QColor(level_color(level)))
        painter.drawText(pill, Qt.AlignCenter, level)

        x = int(pill.right()) + 10
        painter.setFont(self._time_font)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRect(x, rect.top() + 6, 174, 18),
            Qt.AlignVCenter | Qt.AlignLeft,
            entry.timestamp_text or "无时间戳",
        )
        x += 180
        painter.setFont(self._meta_font)
        painter.setPen(QColor(FAINT))
        painter.drawText(
            QRect(x, rect.top() + 6, 96, 18),
            Qt.AlignVCenter | Qt.AlignLeft,
            f"第 {entry.line_no:,} 行",
        )
        x += 102
        painter.setFont(self._module_font)
        painter.setPen(QColor(TEXT_SECONDARY))
        module_width = max(0, rect.right() - 14 - x)
        if module_width > 20:
            module_text = QFontMetrics(self._module_font).elidedText(
                entry.module, Qt.ElideRight, module_width
            )
            painter.drawText(
                QRect(x, rect.top() + 6, module_width, 18),
                Qt.AlignVCenter | Qt.AlignLeft,
                module_text,
            )

        painter.setFont(self._raw_font)
        painter.setPen(QColor("#7C2D12") if anchor else QColor("#334155"))
        y = rect.top() + _CONTEXT_HEADER_HEIGHT
        for line in (entry.raw or "").splitlines() or [""]:
            painter.drawText(
                QRect(rect.left() + 14, y, rect.width() - 28, self._line_height),
                Qt.AlignVCenter | Qt.AlignLeft,
                line.replace("\t", "    "),
            )
            y += self._line_height
        painter.restore()


class ContextDialog(QDialog):
    """双击日志后弹出的上下文窗口：时间正序、完整原文、跨度可调。"""

    def __init__(
        self,
        all_entries: Sequence[LogEntry],
        anchor: LogEntry,
        seconds: int = 30,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ContextDialog")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._all_entries = all_entries
        self._anchor = anchor
        self._seconds = max(1, min(3600, int(seconds)))
        self._entries: list[LogEntry] = []
        self._max_content_width = 760
        self.resize(1080, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("上下文窗口")
        title.setObjectName("CardTitle")
        header.addWidget(title)
        self._summary = QLabel("")
        self._summary.setObjectName("Muted")
        header.addWidget(self._summary)
        header.addStretch(1)
        self.text_button = QToolButton()
        self.text_button.setObjectName("Toggle")
        self.text_button.setText("文本")
        self.text_button.setCheckable(True)
        self.text_button.setFixedSize(54, 28)
        self.text_button.setCursor(Qt.PointingHandCursor)
        self.text_button.setToolTip("切换为直接展示原始日志文本")
        self.text_button.toggled.connect(self._on_text_mode_toggled)
        header.addWidget(self.text_button)
        span_label = QLabel("前后跨度")
        span_label.setObjectName("Muted")
        header.addWidget(span_label)
        self.span_spin = QSpinBox()
        self.span_spin.setObjectName("SpanSpin")
        self.span_spin.setRange(1, 3600)
        self.span_spin.setValue(self._seconds)
        self.span_spin.setSuffix(" 秒")
        self.span_spin.setFixedSize(96, 28)
        self.span_spin.setToolTip("以目标日志为中心，向前、向后各显示该秒数")
        self.span_spin.valueChanged.connect(self._on_span_changed)
        header.addWidget(self.span_spin)
        layout.addLayout(header)

        scope_hint = QLabel("来自全部已加载日志，不受级别 / 模块 / 搜索筛选影响")
        scope_hint.setObjectName("Muted")
        layout.addWidget(scope_hint)

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("ContextTree")
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(False)
        self.tree.setWordWrap(False)
        self.tree.setAnimated(False)
        self.tree.setMouseTracking(True)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tree.setItemDelegate(ContextEntryDelegate(self.tree))
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Fixed)

        self.text_view = QPlainTextEdit()
        self.text_view.setObjectName("ContextText")
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.text_view.setFont(mono_font(8.4))
        self.text_view.setUndoRedoEnabled(False)

        self.view_stack = QStackedWidget(self)
        self.view_stack.addWidget(self.tree)
        self.view_stack.addWidget(self.text_view)
        layout.addWidget(self.view_stack, 1)

        footer = QHBoxLayout()
        self._copy_status = QLabel("")
        self._copy_status.setObjectName("Muted")
        footer.addWidget(self._copy_status)
        footer.addStretch(1)
        self.copy_button = QPushButton("复制全部")
        self.copy_button.setObjectName("Ghost")
        self.copy_button.setIcon(icon("copy", MUTED, 14))
        self.copy_button.setFixedHeight(32)
        self.copy_button.setCursor(Qt.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_all)
        footer.addWidget(self.copy_button)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Primary")
        close_button.setFixedHeight(32)
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self._span_timer = QTimer(self)
        self._span_timer.setSingleShot(True)
        self._span_timer.setInterval(160)
        self._span_timer.timeout.connect(self._reload)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._scroll_to_anchor)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(2000)
        self._status_timer.timeout.connect(self._clear_copy_status)
        self._tree_dirty = True
        self._text_dirty = True
        self._reload()

    def _on_text_mode_toggled(self, checked: bool) -> None:
        self.view_stack.setCurrentIndex(1 if checked else 0)
        self.text_button.setToolTip(
            "切换为平铺视图" if checked else "切换为直接展示原始日志文本"
        )
        if checked and self._text_dirty:
            self._populate_text()
        elif not checked and self._tree_dirty:
            self._populate_tree()

    def _on_span_changed(self, _value: int) -> None:
        self._span_timer.start()

    def _reload(self) -> None:
        self._span_timer.stop()
        self._seconds = self.span_spin.value()
        entries = select_time_context(
            self._all_entries, self._anchor.timestamp, self._seconds
        )
        self._entries = entries
        stamps = [entry.timestamp for entry in entries if entry.timestamp is not None]
        range_text = ""
        if stamps:
            range_text = (
                f"{min(stamps):%Y-%m-%d %H:%M:%S} — {max(stamps):%H:%M:%S} · "
            )
        self._summary.setText(
            f"{range_text}共 {format_count(len(entries))} 条 · 时间正序"
        )
        self.setWindowTitle(
            f"上下文 · {self._anchor.timestamp_text or ''} · 前后 {self._seconds} 秒"
        )

        self.copy_button.setEnabled(bool(entries))
        if self.text_button.isChecked():
            self._populate_text()
            self._tree_dirty = True
        else:
            self._populate_tree()
            self._text_dirty = True

    def _populate_tree(self) -> None:
        entries = self._entries
        tree = self.tree
        delegate = tree.itemDelegate()
        max_width = 760
        anchor_item = None
        tree.setUpdatesEnabled(False)
        try:
            tree.clear()
            for entry in entries:
                item = QTreeWidgetItem()
                item.setData(0, ROLE_ENTRY, entry)
                item.setData(0, ROLE_CONTEXT_ANCHOR, entry is self._anchor)
                size = delegate.entry_size(entry)
                item.setData(0, ROLE_CONTEXT_SIZE, size)
                max_width = max(max_width, size.width())
                tree.addTopLevelItem(item)
                if entry is self._anchor:
                    anchor_item = item
        finally:
            tree.setUpdatesEnabled(True)
        self._max_content_width = max_width
        self._sync_column_width()
        if anchor_item is not None:
            tree.setCurrentItem(anchor_item)
            self._scroll_timer.start(0)
        self._tree_dirty = False

    def _populate_text(self) -> None:
        blocks: list[str] = []
        anchor_start = -1
        anchor_end = -1
        offset = 0
        for entry in self._entries:
            if entry is self._anchor:
                anchor_start = offset
                anchor_end = offset + len(entry.raw)
            blocks.append(entry.raw)
            offset += len(entry.raw) + 1
        text = "\n".join(blocks)
        self.text_view.setPlainText(text)
        self.text_view.setExtraSelections([])
        if anchor_start >= 0:
            cursor = QTextCursor(self.text_view.document())
            cursor.setPosition(anchor_start)
            cursor.setPosition(min(anchor_end, len(text)), QTextCursor.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor("#FEF3C7"))
            selection.format.setForeground(QColor("#7C2D12"))
            self.text_view.setExtraSelections([selection])
            cursor.setPosition(anchor_start)
            self.text_view.setTextCursor(cursor)
            self.text_view.centerCursor()
        else:
            self.text_view.moveCursor(QTextCursor.Start)
        self._text_dirty = False

    def _sync_column_width(self) -> None:
        if not hasattr(self, "tree"):
            return
        width = max(self._max_content_width, self.tree.viewport().width())
        if self.tree.columnWidth(0) != width:
            self.tree.setColumnWidth(0, width)

    def _scroll_to_anchor(self) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, ROLE_CONTEXT_ANCHOR):
                self.tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                self.tree.horizontalScrollBar().setValue(0)
                return

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_column_width()

    def _copy_all(self) -> None:
        if not self._entries:
            return
        QApplication.clipboard().setText(
            "\n".join(entry.raw for entry in self._entries)
        )
        self._copy_status.setText(f"已复制 {format_count(len(self._entries))} 条日志")
        self._status_timer.start()

    def _clear_copy_status(self) -> None:
        self._copy_status.setText("")


# ---------------------------------------------------------------------------
# 详情面板
# ---------------------------------------------------------------------------

_MATRIX_KEY_HINTS = ("tf", "transform", "matrix", "mat", "rot", "rotation")


def _sequence_tokens(value: str) -> list[str]:
    return [token.strip() for token in value.replace(";", ",").split(",") if token.strip()]


def matrix_shape(key: str, value: str) -> Optional[tuple[int, int]]:
    """推断序列字段的矩阵形状；不是矩阵时返回 None。"""

    if "\n" in value:
        rows = [line for line in value.splitlines() if line.strip()]
        counts = {len(_sequence_tokens(line)) for line in rows}
        if len(rows) >= 2 and len(counts) == 1:
            cols = counts.pop()
            if cols >= 2:
                return len(rows), cols
        return None
    tokens = _sequence_tokens(value)
    count = len(tokens)
    if count < 4:
        return None
    side = math.isqrt(count)
    if side * side != count:
        return None
    lowered = key.lower()
    hinted = any(hint in lowered for hint in _MATRIX_KEY_HINTS)
    # 只有字段名像矩阵时才按 n×n 展开；否则 9/16 个值的序列按向量换行，
    # 避免把 qpos 等长向量误判成矩阵。
    if hinted:
        return side, side
    return None


def format_field_value(key: str, value: str) -> str:
    """把序列字段格式化为 n×n 矩阵或逗号分隔的向量。"""

    text = value.strip()
    if not text:
        return value
    if "\n" in text:
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    tokens = _sequence_tokens(text)
    if len(tokens) < 2:
        return text
    shape = matrix_shape(key, text)
    if shape is None:
        return ", ".join(tokens)
    rows, cols = shape
    widths = [
        max(len(tokens[row * cols + col]) for row in range(rows))
        for col in range(cols)
    ]
    return "\n".join(
        "  ".join(
            tokens[row * cols + col].rjust(widths[col]) for col in range(cols)
        )
        for row in range(rows)
    )


class DetailFieldTable(QTreeWidget):
    """详情字段表：矩阵按 n×n 展开，长向量按列宽自动换行。"""

    MIN_HEIGHT = 96
    MAX_HEIGHT = 320

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FieldTable")
        self.setColumnCount(2)
        self.setHeaderLabels(["字段", "值"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setUniformRowHeights(False)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.setFont(mono_font(8.0))
        header = self.header()
        header.setFont(font(8.0, QFont.DemiBold))
        header.setFixedHeight(24)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.sectionResized.connect(self._on_section_resized)
        self.setColumnWidth(0, 92)
        self.setFixedHeight(self.MIN_HEIGHT)
        self._last_width = -1
        self.set_fields({})

    def _on_section_resized(self, _index: int, _old: int, _new: int) -> None:
        self._last_width = -1
        self._fit_height()

    def set_fields(self, fields: dict[str, str]) -> None:
        self.clear()
        if not fields:
            item = QTreeWidgetItem(["—", "未解析到键值字段"])
            item.setFlags(Qt.ItemIsEnabled)
            item.setForeground(1, QColor(FAINT))
            self.addTopLevelItem(item)
        else:
            for key, value in fields.items():
                shape = matrix_shape(key, value)
                display = format_field_value(key, value)
                if shape is not None:
                    label = f"{key}  ·  {shape[0]}×{shape[1]}\n{display}"
                    item = QTreeWidgetItem([label, ""])
                    item.setToolTip(0, f"{key}\n{value}")
                    item.setData(0, Qt.UserRole, shape)
                    self.addTopLevelItem(item)
                    row = self.indexOfTopLevelItem(item)
                    self.setFirstColumnSpanned(row, QModelIndex(), True)
                else:
                    item = QTreeWidgetItem([key, display])
                    item.setToolTip(0, key)
                    item.setToolTip(1, value)
                    self.addTopLevelItem(item)
        self._last_width = -1
        self._fit_height()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self) -> None:
        if self.topLevelItemCount() == 0:
            return
        viewport_width = self.viewport().width()
        if viewport_width <= 0:
            return
        if viewport_width == self._last_width:
            return
        self._last_width = viewport_width
        metrics = QFontMetrics(self.font())
        full_width = max(60, viewport_width - 18)
        value_width = max(60, self.columnWidth(1) - 12)
        total = self.header().height() + 4
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            spanned = bool(item.data(0, Qt.UserRole))
            if spanned:
                text = item.text(0)
                rect = metrics.boundingRect(
                    QRect(0, 0, full_width, 1_000_000), Qt.TextWordWrap, text
                )
                height = max(26, rect.height() + 8)
                item.setSizeHint(0, QSize(0, height))
            else:
                rect = metrics.boundingRect(
                    QRect(0, 0, value_width, 1_000_000), Qt.TextWordWrap, item.text(1)
                )
                height = max(24, rect.height() + 6)
                item.setSizeHint(1, QSize(0, height))
            total += height
        target = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, total))
        if self.height() != target:
            self.setFixedHeight(target)


class DetailPanel(QFrame):
    toast = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumWidth(300)
        self._entry: Optional[LogEntry] = None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(9)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("日志详情")
        title.setObjectName("CardTitle")
        self._copy = QToolButton()
        self._copy.setObjectName("IconButton")
        self._copy.setIcon(icon("copy", MUTED, 17))
        self._copy.setFixedSize(30, 30)
        self._copy.setCursor(Qt.PointingHandCursor)
        self._copy.setToolTip("复制原始日志")
        self._copy.setVisible(False)
        self._copy.clicked.connect(self.copy_raw)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._copy)
        layout.addLayout(header)

        self._stack = QStackedWidget()
        self._placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self._placeholder)
        placeholder_layout.setContentsMargins(12, 0, 12, 0)
        placeholder_layout.setSpacing(8)
        placeholder_layout.addStretch(1)
        placeholder_icon = QLabel()
        placeholder_icon.setPixmap(icon("search", "#CBD5E1", 38).pixmap(38, 38))
        placeholder_icon.setAlignment(Qt.AlignCenter)
        placeholder_title = QLabel("选择一条日志")
        placeholder_title.setAlignment(Qt.AlignCenter)
        placeholder_title.setStyleSheet("font-size:12px;font-weight:600;color:#64748B;")
        placeholder_sub = QLabel("查看完整内容、堆栈与解析字段")
        placeholder_sub.setAlignment(Qt.AlignCenter)
        placeholder_sub.setWordWrap(True)
        placeholder_sub.setStyleSheet("font-size:10px;color:#94A3B8;")
        placeholder_layout.addWidget(placeholder_icon)
        placeholder_layout.addWidget(placeholder_title)
        placeholder_layout.addWidget(placeholder_sub)
        placeholder_layout.addStretch(1)
        self._stack.addWidget(self._placeholder)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(7)

        meta_top = QHBoxLayout()
        meta_top.setContentsMargins(0, 0, 0, 0)
        meta_top.setSpacing(6)
        self._level = QLabel("INFO")
        self._level.setObjectName("DetailLevel")
        self._time = QLabel("")
        self._time.setObjectName("DetailMeta")
        self._time.setFont(mono_font(8.0))
        meta_top.addWidget(self._level, 0)
        meta_top.addWidget(self._time, 1)
        content_layout.addLayout(meta_top)

        meta_bottom = QHBoxLayout()
        meta_bottom.setContentsMargins(0, 0, 0, 0)
        meta_bottom.setSpacing(6)
        self._module = QLabel("")
        self._module.setObjectName("DetailChip")
        self._line = QLabel("")
        self._line.setObjectName("DetailMeta")
        meta_bottom.addWidget(self._module, 0)
        meta_bottom.addStretch(1)
        meta_bottom.addWidget(self._line, 0)
        content_layout.addLayout(meta_bottom)

        raw_title = QLabel("原始日志")
        raw_title.setObjectName("SectionLabel")
        content_layout.addWidget(raw_title)
        self._raw = QPlainTextEdit()
        self._raw.setObjectName("RawLog")
        self._raw.setReadOnly(True)
        self._raw.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._raw.setFont(mono_font(8.2))
        self._raw.setMinimumHeight(150)
        content_layout.addWidget(self._raw, 1)

        fields_title = QLabel("解析字段")
        fields_title.setObjectName("SectionLabel")
        content_layout.addWidget(fields_title)
        self._fields = DetailFieldTable()
        content_layout.addWidget(self._fields)

        self._stack.addWidget(self._content)
        layout.addWidget(self._stack, 1)

    def set_entry(self, entry: LogEntry, query: Query) -> None:
        self._entry = entry
        self._copy.setVisible(True)
        color = level_color(entry.level)
        back = level_background(entry.level)
        self._level.setText(entry.level)
        self._level.setStyleSheet(
            f"background:{back};color:{color};border-radius:9px;"
            "padding:2px 9px;font-size:10px;font-weight:700;"
        )
        self._time.setText(entry.timestamp_text or "无时间戳")
        self._module.setText(entry.module)
        self._module.setToolTip(entry.module)
        self._line.setText(f"第 {entry.line_no:,} 行")
        self._raw.setPlainText(entry.raw)
        self._raw.setExtraSelections([])
        self._raw.moveCursor(QTextCursor.Start)

        if query.text.strip():
            try:
                pattern = build_pattern(query)
            except Exception:
                pattern = None
            if pattern is not None:
                selections = []
                for match in pattern.finditer(entry.raw):
                    if match.start() == match.end():
                        continue
                    cursor = QTextCursor(self._raw.document())
                    cursor.setPosition(match.start())
                    cursor.setPosition(match.end(), QTextCursor.KeepAnchor)
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    fmt = QTextCharFormat()
                    fmt.setBackground(QColor("#FDE68A"))
                    fmt.setForeground(QColor("#7C2D12"))
                    selection.format = fmt
                    selections.append(selection)
                    if len(selections) >= 300:
                        break
                self._raw.setExtraSelections(selections)

        self._fields.set_fields(entry.fields)
        self._stack.setCurrentWidget(self._content)

    def clear(self) -> None:
        self._entry = None
        self._copy.setVisible(False)
        self._stack.setCurrentWidget(self._placeholder)
        self._raw.clear()
        self._fields.set_fields({})

    def current_entry(self) -> Optional[LogEntry]:
        return self._entry

    def copy_raw(self) -> None:
        if self._entry is None:
            return
        QApplication.clipboard().setText(self._entry.raw)
        self.toast.emit("已复制原始日志")


# ---------------------------------------------------------------------------
# 空状态与加载状态
# ---------------------------------------------------------------------------


class MessageState(QWidget):
    actionTriggered = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        action_text: str = "",
        icon_name: str = "search",
        use_logo: bool = False,
        primary: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._use_logo = use_logo
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, Qt.AlignHCenter)
        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet("font-size:15px;font-weight:700;color:#1E293B;")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("font-size:11px;color:#64748B;")
        self._subtitle.setMaximumWidth(460)
        layout.addWidget(self._subtitle, 0, Qt.AlignHCenter)
        layout.addSpacing(8)
        self._button = QPushButton(action_text)
        self._button.setObjectName("Primary" if primary else "Ghost")
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.setFixedHeight(34)
        self._button.setVisible(bool(action_text))
        self._button.clicked.connect(self.actionTriggered)
        layout.addWidget(self._button, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self._apply_icon()
        self._fit_subtitle()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_subtitle()

    def _fit_subtitle(self) -> None:
        """固定换行宽度并按 heightForWidth 分配高度，避免灰字被压成一行。"""
        if self.width() <= 0:
            return
        width = max(160, min(460, self.width() - 56))
        required = self._subtitle.heightForWidth(width)
        if required <= 0:
            required = self._subtitle.fontMetrics().lineSpacing() * 2
        required += 2
        if self._subtitle.width() != width:
            self._subtitle.setFixedWidth(width)
        if self._subtitle.height() != required:
            self._subtitle.setFixedHeight(required)

    def _apply_icon(self) -> None:
        if self._use_logo:
            pixmap = logo_pixmap(64)
        else:
            pixmap = icon(self._icon_name, "#CBD5E1", 46).pixmap(46, 46)
        self._icon.setPixmap(pixmap)

    def configure(
        self,
        title: str,
        subtitle: str,
        action_text: str = "",
        *,
        icon_name: Optional[str] = None,
        use_logo: bool = False,
        primary: bool = False,
    ) -> None:
        self._use_logo = use_logo
        if icon_name:
            self._icon_name = icon_name
        self._apply_icon()
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._fit_subtitle()
        self._button.setText(action_text)
        self._button.setVisible(bool(action_text))
        self._button.setObjectName("Primary" if primary else "Ghost")
        self._button.style().unpolish(self._button)
        self._button.style().polish(self._button)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#DCE5F0"), 1.4, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(16, 16, -16, -16), 14, 14)


class LoadingState(QWidget):
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.addStretch(1)
        icon_label = QLabel()
        icon_label.setPixmap(logo_pixmap(56))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label, 0, Qt.AlignHCenter)
        title = QLabel("正在解析日志")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:15px;font-weight:700;color:#1E293B;")
        layout.addWidget(title)
        self._file = ElidedLabel("", Qt.ElideMiddle)
        self._file.setAlignment(Qt.AlignCenter)
        self._file.setStyleSheet("font-size:10.5px;color:#94A3B8;")
        self._file.setMaximumWidth(420)
        layout.addWidget(self._file, 0, Qt.AlignHCenter)
        layout.addSpacing(14)
        self._progress = QProgressBar()
        self._progress.setObjectName("LoadProgress")
        self._progress.setFixedHeight(8)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedWidth(320)
        layout.addWidget(self._progress, 0, Qt.AlignHCenter)
        self._status = QLabel("准备读取…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("font-size:10px;color:#94A3B8;")
        layout.addWidget(self._status)
        layout.addSpacing(6)
        cancel = QPushButton("取消加载")
        cancel.setObjectName("Ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(32)
        cancel.clicked.connect(self.cancelRequested)
        layout.addWidget(cancel, 0, Qt.AlignHCenter)
        layout.addStretch(1)

    def begin(self, file_name: str) -> None:
        self._file.setText(file_name)
        self._file.setToolTip(file_name)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._status.setText("准备读取…")

    def set_progress(self, read_bytes: int, total_bytes: int, entries: int) -> None:
        if total_bytes > 0:
            percent = max(0, min(100, int(read_bytes / total_bytes * 100)))
            self._progress.setRange(0, 100)
            self._progress.setValue(percent)
            self._status.setText(
                f"已解析 {format_count(entries)} 条日志 · 读取 {percent}%"
            )
        else:
            self._progress.setRange(0, 0)
            self._status.setText(f"已解析 {format_count(entries)} 条日志")
