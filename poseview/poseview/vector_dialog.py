"""向量绘制与夹角计算面板。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import dot_icon, icon
from .math3d import (
    MatrixParseError,
    angle_between_vectors,
    format_number,
    parse_vectors,
    project_vector,
    vector_cross,
    vector_dot,
    vector_length,
)
from .scene import VECTOR_COLORS, SceneVector
from .theme import DANGER, MUTED, SUCCESS, TEXT, mono_font

INPUT_MODES = (
    ("direction", "起点 + 方向"),
    ("end", "起点 + 终点"),
)

PLACEHOLDERS = {
    "direction": (
        "每行一个向量：起点 x y z + 方向 x y z\n"
        "0 0 0   1 0 0\n"
        "1 0 1   0 0 1"
    ),
    "end": (
        "每行一个向量：起点 x y z + 终点 x y z\n"
        "0 0 0   1 0 0\n"
        "1 0 1   1 0 2"
    ),
}

MODE_HINTS = {
    "direction": "起点处绘制箭头，长度取方向向量的模长；空行或 --- 分隔多个向量",
    "end": "起点处绘制箭头并指向终点；空行或 --- 分隔多个向量",
}


@dataclass
class _VectorEntry:
    name: str
    color: str
    start: tuple[float, float, float]
    direction: tuple[float, float, float]
    visible: bool = True

    @property
    def end(self) -> tuple[float, float, float]:
        return (
            self.start[0] + self.direction[0],
            self.start[1] + self.direction[1],
            self.start[2] + self.direction[2],
        )

    def to_scene(self) -> SceneVector:
        return SceneVector(
            name=self.name,
            color=self.color,
            start=self.start,
            direction=self.direction,
            visible=self.visible,
        )


class VectorPanel(QWidget):
    """绘制带起点的向量，并计算两个向量的夹角。"""

    vectors_changed = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[_VectorEntry] = []
        self._mode = "direction"
        self._next_index = 1
        self._default_hint = MODE_HINTS["direction"]
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)
        self._build()
        self._sync()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(self._build_input_card())
        left.addWidget(self._build_list_card(), 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_angle_card())
        right.addStretch(1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._editor.setFocus()

    def _build_input_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("向量输入")
        title.setObjectName("SectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        head_hint = QLabel("每行 6 个数")
        head_hint.setObjectName("CardHint")
        head.addWidget(head_hint)
        card_layout.addLayout(head)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QToolButton] = {}
        for key, label in INPUT_MODES:
            button = QToolButton()
            button.setObjectName("ModeTab")
            button.setText(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, name=key: self._set_mode(name)
            )
            self._mode_group.addButton(button)
            self._mode_buttons[key] = button
            mode_row.addWidget(button, 1)
        self._mode_buttons["direction"].setChecked(True)
        card_layout.addLayout(mode_row)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MatrixEditor")
        self._editor.setFont(mono_font(11))
        self._editor.setFixedHeight(92)
        self._editor.setTabChangesFocus(True)
        self._editor.setPlaceholderText(PLACEHOLDERS["direction"])
        card_layout.addWidget(self._editor)

        self._hint = QLabel(self._default_hint)
        self._hint.setObjectName("CardHint")
        self._hint.setWordWrap(True)
        card_layout.addWidget(self._hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_button = QPushButton("添加向量")
        add_button.setObjectName("Primary")
        add_button.setIcon(icon("plus", "#FFFFFF", 15))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.clicked.connect(self._add_from_editor)
        clear_input = QPushButton("清空输入")
        clear_input.setObjectName("Ghost")
        clear_input.setIcon(icon("clear", "#475569", 15))
        clear_input.setCursor(Qt.PointingHandCursor)
        clear_input.clicked.connect(self._clear_input)
        buttons.addWidget(add_button, 1)
        buttons.addWidget(clear_input)
        card_layout.addLayout(buttons)
        return card

    def _build_list_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("向量列表")
        title.setObjectName("SectionTitle")
        self._count_badge = QLabel("0 个")
        self._count_badge.setObjectName("CountBadge")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._count_badge)
        card_layout.addLayout(head)

        self._list = QListWidget()
        self._list.setObjectName("PoseList")
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemChanged.connect(self._on_item_changed)
        card_layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        delete_button = QPushButton("删除选中")
        delete_button.setObjectName("Ghost")
        delete_button.setIcon(icon("trash", "#475569", 15))
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.clicked.connect(self._delete_selected)
        clear_button = QPushButton("清空列表")
        clear_button.setObjectName("Ghost")
        clear_button.setIcon(icon("clear", "#475569", 15))
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self._clear_all)
        buttons.addWidget(delete_button, 1)
        buttons.addWidget(clear_button, 1)
        card_layout.addLayout(buttons)
        return card

    def _build_angle_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("夹角计算")
        title.setObjectName("SectionTitle")
        self._subtitle = QLabel()
        self._subtitle.setObjectName("CardHint")
        self._copy_button = QToolButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setFixedSize(26, 26)
        self._copy_button.setCursor(Qt.PointingHandCursor)
        self._copy_button.setToolTip("复制向量与夹角结果")
        self._copy_button.clicked.connect(self._copy)
        self._cross_button = QToolButton()
        self._cross_button.setObjectName("IconButton")
        self._cross_button.setIcon(icon("plus", "#475569", 15))
        self._cross_button.setFixedSize(26, 26)
        self._cross_button.setCursor(Qt.PointingHandCursor)
        self._cross_button.setToolTip("将两向量的叉积加入场景")
        self._cross_button.clicked.connect(self._add_cross_vector)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._subtitle)
        head.addWidget(self._cross_button)
        head.addWidget(self._copy_button)
        card_layout.addLayout(head)

        row_a = QHBoxLayout()
        row_a.setSpacing(8)
        label_a = QLabel("向量 A")
        label_a.setObjectName("ValueKey")
        label_a.setFixedWidth(56)
        self._combo_a = QComboBox()
        row_a.addWidget(label_a)
        row_a.addWidget(self._combo_a, 1)
        card_layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(8)
        label_b = QLabel("向量 B")
        label_b.setObjectName("ValueKey")
        label_b.setFixedWidth(56)
        self._combo_b = QComboBox()
        self._swap_button = QToolButton()
        self._swap_button.setObjectName("IconButton")
        self._swap_button.setIcon(icon("swap", "#475569", 16))
        self._swap_button.setFixedSize(26, 26)
        self._swap_button.setCursor(Qt.PointingHandCursor)
        self._swap_button.setToolTip("交换 A / B")
        self._swap_button.clicked.connect(self._swap)
        row_b.addWidget(label_b)
        row_b.addWidget(self._combo_b, 1)
        row_b.addWidget(self._swap_button)
        card_layout.addLayout(row_b)

        angle_row = QHBoxLayout()
        angle_row.setSpacing(8)
        angle_key = QLabel("夹角 θ")
        angle_key.setObjectName("ValueKey")
        angle_key.setFixedWidth(56)
        self._angle_label = QLabel("—")
        self._angle_label.setStyleSheet(
            f"color: {TEXT}; font-size: 20px; font-weight: 700;"
        )
        self._angle_state = QLabel()
        self._angle_state.setObjectName("CardHint")
        angle_row.addWidget(angle_key)
        angle_row.addWidget(self._angle_label)
        angle_row.addStretch(1)
        angle_row.addWidget(self._angle_state)
        card_layout.addLayout(angle_row)

        self._cos_label = self._make_value_row(card_layout, "cos θ")
        self._length_label = self._make_value_row(card_layout, "模长")
        self._unit_label = self._make_value_row(card_layout, "单位向量")
        self._cross_label = self._make_value_row(card_layout, "叉积")
        self._projection_label = self._make_value_row(card_layout, "投影")

        self._combo_a.currentIndexChanged.connect(self._refresh_angle)
        self._combo_b.currentIndexChanged.connect(self._refresh_angle)
        return card

    def _make_value_row(self, layout: QVBoxLayout, key: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(8)
        key_label = QLabel(key)
        key_label.setObjectName("ValueKey")
        key_label.setFixedWidth(56)
        value = QLabel("—")
        value.setFont(mono_font(10))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(key_label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    # ------------------------------------------------------------------
    # 输入与列表
    # ------------------------------------------------------------------

    def _set_mode(self, key: str) -> None:
        if key not in PLACEHOLDERS:
            return
        button = self._mode_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._mode = key
        self._editor.setPlaceholderText(PLACEHOLDERS[key])
        self._default_hint = MODE_HINTS[key]
        self._show_hint(self._default_hint, MUTED)

    def _add_from_editor(self) -> None:
        try:
            parsed = parse_vectors(self._editor.toPlainText(), self._mode)
        except MatrixParseError as exc:
            self._show_hint(str(exc), DANGER)
            return
        for start, direction in parsed:
            index = self._next_index
            self._next_index += 1
            self._entries.append(
                _VectorEntry(
                    name=f"V{index}",
                    color=VECTOR_COLORS[(index - 1) % len(VECTOR_COLORS)],
                    start=start,
                    direction=direction,
                )
            )
        self._sync(select=len(self._entries) - len(parsed))
        self._show_hint(f"已添加 {len(parsed)} 个向量", SUCCESS)

    def _clear_input(self) -> None:
        self._editor.clear()
        self._editor.setFocus()
        self._show_hint(self._default_hint, MUTED)

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries.pop(row)
        self._sync(select=min(row, len(self._entries) - 1))
        self._show_hint(f"已删除 {entry.name}", MUTED)

    def _clear_all(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空向量",
            f"确定清空全部 {len(self._entries)} 个向量？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._entries.clear()
        self._sync()
        self._show_hint("已清空向量列表", MUTED)

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._entries):
            self._entries[row].visible = item.checkState() == Qt.Checked
            self._emit_changed()

    def _sync(self, select: int = -1) -> None:
        self._refresh_list(select)
        self._refresh_combos()
        self._refresh_angle()
        self._count_badge.setText(f"{len(self._entries)} 个")
        self._emit_changed()

    def _refresh_list(self, select: int = -1) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for index, entry in enumerate(self._entries):
            x, y, z = entry.start
            ex, ey, ez = entry.end
            text = (
                f"{entry.name}   起 ({format_number(x, 3)}, {format_number(y, 3)}, "
                f"{format_number(z, 3)})   终 ({format_number(ex, 3)}, "
                f"{format_number(ey, 3)}, {format_number(ez, 3)})"
            )
            item = QListWidgetItem(text)
            item.setIcon(dot_icon(entry.color))
            item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            item.setCheckState(Qt.Checked if entry.visible else Qt.Unchecked)
            item.setData(Qt.UserRole, index)
            item.setToolTip(
                "起点 ("
                + ", ".join(format_number(value, 4) for value in entry.start)
                + ") · 终点 ("
                + ", ".join(format_number(value, 4) for value in entry.end)
                + ")\n方向 ("
                + ", ".join(format_number(value, 4) for value in entry.direction)
                + ") · 长度 "
                + format_number(vector_length(entry.direction), 4)
            )
            self._list.addItem(item)
        self._list.blockSignals(False)

        if self._entries:
            select = max(0, min(select, len(self._entries) - 1))
            self._list.setCurrentRow(select)

    def _refresh_combos(self) -> None:
        names = [entry.name for entry in self._entries]
        current_a = self._combo_a.currentText()
        current_b = self._combo_b.currentText()
        for combo in (self._combo_a, self._combo_b):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
        if names:
            self._combo_a.setCurrentIndex(
                names.index(current_a) if current_a in names else 0
            )
            if current_b in names:
                index_b = names.index(current_b)
            else:
                index_b = len(names) - 1
            self._combo_b.setCurrentIndex(index_b)
            if len(names) >= 2 and index_b == self._combo_a.currentIndex():
                self._combo_b.setCurrentIndex(
                    (self._combo_a.currentIndex() + 1) % len(names)
                )
        for combo in (self._combo_a, self._combo_b):
            combo.blockSignals(False)
        enabled = len(names) >= 2
        for widget in (self._combo_a, self._combo_b, self._swap_button):
            widget.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 夹角
    # ------------------------------------------------------------------

    def _refresh_angle(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        if (
            len(self._entries) < 2
            or not (0 <= index_a < len(self._entries))
            or not (0 <= index_b < len(self._entries))
            or index_a == index_b
        ):
            if len(self._entries) < 2:
                state = "至少需要两个向量"
            else:
                state = "请选择两个不同的向量"
            self._angle_label.setText("—")
            self._angle_state.setText(state)
            self._cos_label.setText("—")
            self._length_label.setText("—")
            self._unit_label.setText("—")
            self._cross_label.setText("—")
            self._projection_label.setText("—")
            self._cross_button.setEnabled(False)
            self._subtitle.setText("")
            self._copy_button.setEnabled(False)
            return

        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        try:
            angle = angle_between_vectors(entry_a.direction, entry_b.direction)
        except MatrixParseError as exc:
            self._angle_label.setText("—")
            self._angle_state.setText(str(exc))
            self._cos_label.setText("—")
            self._length_label.setText("—")
            self._unit_label.setText("—")
            self._cross_label.setText("—")
            self._projection_label.setText("—")
            self._cross_button.setEnabled(False)
            self._copy_button.setEnabled(False)
            return

        length_a = vector_length(entry_a.direction)
        length_b = vector_length(entry_b.direction)
        dot = vector_dot(entry_a.direction, entry_b.direction)
        cosine = dot / (length_a * length_b)
        state = self._angle_state_text(angle)

        cross = vector_cross(entry_a.direction, entry_b.direction)
        cross_length = vector_length(cross)
        projection = project_vector(entry_a.direction, entry_b.direction)

        self._angle_label.setText(f"{format_number(angle, 2)}°")
        self._angle_state.setText(state)
        self._cos_label.setText(
            f"{format_number(cosine, 5)}   ·   a·b {format_number(dot, 5)}"
        )
        self._length_label.setText(
            f"|a| {format_number(length_a, 5)}   ·   |b| {format_number(length_b, 5)}"
        )
        unit_a = tuple(value / length_a for value in entry_a.direction)
        unit_b = tuple(value / length_b for value in entry_b.direction)
        self._unit_label.setText(
            "a ("
            + ", ".join(format_number(value, 4) for value in unit_a)
            + ")   b ("
            + ", ".join(format_number(value, 4) for value in unit_b)
            + ")"
        )
        self._cross_label.setText(
            "("
            + ", ".join(format_number(value, 4) for value in cross)
            + f")   |a×b| {format_number(cross_length, 4)}"
        )
        self._projection_label.setText(
            "("
            + ", ".join(format_number(value, 4) for value in projection)
            + f")   标量 {format_number(dot / length_b, 4)}"
        )
        self._cross_button.setEnabled(cross_length > 1e-9)
        self._subtitle.setText(f"{entry_a.name} / {entry_b.name}")
        self._copy_button.setEnabled(True)

    def _add_cross_vector(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        if (
            len(self._entries) < 2
            or not (0 <= index_a < len(self._entries))
            or not (0 <= index_b < len(self._entries))
        ):
            return
        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        cross = vector_cross(entry_a.direction, entry_b.direction)
        if vector_length(cross) < 1e-9:
            self._show_hint("两向量平行，叉积为零向量", DANGER)
            return
        index = self._next_index
        self._next_index += 1
        self._entries.append(
            _VectorEntry(
                name=f"V{index}",
                color=VECTOR_COLORS[(index - 1) % len(VECTOR_COLORS)],
                start=entry_a.start,
                direction=cross,
            )
        )
        self._sync(select=len(self._entries) - 1)
        self._show_hint(
            f"已添加叉积 {entry_a.name}×{entry_b.name} 为 V{index}", SUCCESS
        )

    def add_vector(self, start, direction, name: str = "") -> str:
        """由外部工具添加向量，返回实际名称；零向量返回空字符串。"""
        if vector_length(direction) < 1e-9:
            return ""
        index = self._next_index
        self._next_index += 1
        vector_name = name or f"V{index}"
        self._entries.append(
            _VectorEntry(
                name=vector_name,
                color=VECTOR_COLORS[(index - 1) % len(VECTOR_COLORS)],
                start=tuple(start),
                direction=tuple(direction),
            )
        )
        self._sync(select=len(self._entries) - 1)
        return vector_name

    @staticmethod
    def _angle_state_text(angle: float) -> str:
        if angle <= 1e-6:
            return "同向"
        if angle >= 180.0 - 1e-6:
            return "反向"
        if abs(angle - 90.0) <= 1e-6:
            return "垂直"
        return "锐角" if angle < 90.0 else "钝角"

    def _swap(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        self._combo_a.blockSignals(True)
        self._combo_b.blockSignals(True)
        self._combo_a.setCurrentIndex(index_b)
        self._combo_b.setCurrentIndex(index_a)
        self._combo_a.blockSignals(False)
        self._combo_b.blockSignals(False)
        self._refresh_angle()

    # ------------------------------------------------------------------
    # 信号与提示
    # ------------------------------------------------------------------

    def _emit_changed(self) -> None:
        self.vectors_changed.emit([entry.to_scene() for entry in self._entries])

    def _show_hint(self, text: str, color: str) -> None:
        self._hint.setText(text)
        self._hint.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------

    def _copy(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        if not (
            len(self._entries) >= 2
            and 0 <= index_a < len(self._entries)
            and 0 <= index_b < len(self._entries)
            and index_a != index_b
        ):
            return
        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        angle = angle_between_vectors(entry_a.direction, entry_b.direction)
        lines = []
        for entry in (entry_a, entry_b):
            lines.append(
                f"{entry.name}: start=("
                + ", ".join(format_number(value, 6) for value in entry.start)
                + ") direction=("
                + ", ".join(format_number(value, 6) for value in entry.direction)
                + ") end=("
                + ", ".join(format_number(value, 6) for value in entry.end)
                + ")"
            )
        lines.append(
            f"夹角: {format_number(angle, 4)}° ({self._angle_state_text(angle)})"
        )
        lines.append(
            f"cos θ: {format_number(math.cos(math.radians(angle)), 6)}   "
            f"a·b: {format_number(vector_dot(entry_a.direction, entry_b.direction), 6)}"
        )
        cross = vector_cross(entry_a.direction, entry_b.direction)
        lines.append(
            "a×b: ("
            + ", ".join(format_number(value, 6) for value in cross)
            + f")   投影: ("
            + ", ".join(
                format_number(value, 6)
                for value in project_vector(entry_a.direction, entry_b.direction)
            )
            + ")"
        )
        QApplication.clipboard().setText("\n".join(lines))
        self._copy_button.setIcon(icon("check", SUCCESS, 15))
        self._copy_button.setToolTip("已复制")
        self._copy_timer.start(1200)

    def _restore_copy_icon(self) -> None:
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setToolTip("复制向量与夹角结果")
