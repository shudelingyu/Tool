"""位姿管理面板：输入、列表、姿态解算与相对位姿。"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import dot_icon, icon, primary_icon
from .math3d import (
    MatrixParseError,
    Pose,
    format_number,
    parse_poses,
    relative_transform,
)
from .scene import POSE_COLORS
from .theme import DANGER, MUTED, SUCCESS, mono_font
from .widgets import PoseValuePanel

INPUT_MODES = (
    ("matrix", "齐次矩阵"),
    ("quat", "位置 + 四元数"),
    ("euler", "位置 + 欧拉角"),
    ("rotvec", "位置 + 旋转向量"),
)

MODE_HINTS = {
    "matrix": "支持 3x3 / 3x4 / 4x4；空行或 --- 分隔多个矩阵",
    "quat": "每帧 7 个数：x y z qw qx qy qz；空行或 --- 分隔多帧",
    "euler": "每帧 6 个数：x y z roll pitch yaw（度）；空行或 --- 分隔多帧",
    "rotvec": "每帧 6 个数：x y z rx ry rz（弧度）；空行或 --- 分隔多帧",
}

PLACEHOLDERS = {
    "matrix": (
        "粘贴 3x3 / 3x4 / 4x4 矩阵：\n"
        "1  0  0  0.5\n"
        "0  1  0  0\n"
        "0  0  1  0\n"
        "0  0  0  1"
    ),
    "quat": (
        "粘贴位置 + 四元数，每帧 7 个数：\n"
        "x y z qw qx qy qz\n"
        "0 0 0   1 0 0 0"
    ),
    "euler": (
        "粘贴位置 + 欧拉角，每帧 6 个数：\n"
        "x y z roll pitch yaw\n"
        "0 0 0   0 0 45"
    ),
    "rotvec": (
        "粘贴位置 + 旋转向量，每帧 6 个数：\n"
        "x y z rx ry rz（rad）\n"
        "0 0 0   0 0 1.5708"
    ),
}


@dataclass
class PoseEntry:
    name: str
    color: str
    pose: Pose
    visible: bool = True


class PosePanel(QWidget):
    """输入、管理位姿，查看姿态解算与相对位姿。"""

    poses_changed = pyqtSignal(list)
    selection_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[PoseEntry] = []
        self._mode = "matrix"
        self._default_hint = MODE_HINTS["matrix"]
        self._relative: Pose | None = None
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._reset_hint)
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)
        self._build()
        self._sync_poses()

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
        left.addWidget(self._build_input_card(), 2)
        left.addWidget(self._build_list_card(), 3)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_values_card())
        right.addWidget(self._build_relative_card())
        right.addStretch(1)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

        add_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        add_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        add_shortcut.activated.connect(self._add_from_editor)
        delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self._list)
        delete_shortcut.setContext(Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_selected)

    def _build_input_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("位姿输入")
        title.setObjectName("SectionTitle")
        hint = QLabel("统一转为 4x4 解算")
        hint.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
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
        self._mode_buttons["matrix"].setChecked(True)
        card_layout.addLayout(mode_row)

        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MatrixEditor")
        self._editor.setFont(mono_font(11.5))
        self._editor.setMinimumHeight(150)
        self._editor.setTabChangesFocus(True)
        self._editor.setPlaceholderText(PLACEHOLDERS["matrix"])
        card_layout.addWidget(self._editor, 1)

        self._parse_hint = QLabel(self._default_hint)
        self._parse_hint.setObjectName("CardHint")
        self._parse_hint.setWordWrap(True)
        card_layout.addWidget(self._parse_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_button = QPushButton("添加位姿")
        add_button.setObjectName("Primary")
        add_button.setIcon(primary_icon("plus", 15))
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
        title = QLabel("位姿列表")
        title.setObjectName("SectionTitle")
        self._count_badge = QLabel("0 帧")
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
        self._list.currentRowChanged.connect(self._on_row_changed)
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

    def _build_values_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._value_panel = PoseValuePanel()
        layout.addWidget(self._value_panel)
        return card

    def _build_relative_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("相对位姿")
        title.setObjectName("SectionTitle")
        self._relative_subtitle = QLabel("至少需要两个位姿")
        self._relative_subtitle.setObjectName("CardHint")
        self._copy_button = QToolButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setFixedSize(26, 26)
        self._copy_button.setCursor(Qt.PointingHandCursor)
        self._copy_button.setToolTip("复制 4x4 矩阵与姿态")
        self._copy_button.clicked.connect(self._copy_relative)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._relative_subtitle)
        head.addWidget(self._copy_button)
        card_layout.addLayout(head)

        hint = QLabel("计算 B 在 A 坐标系下的位姿：T_A→B = inv(T_A) · T_B")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        row_a = QHBoxLayout()
        row_a.setSpacing(8)
        label_a = QLabel("坐标系 A")
        label_a.setObjectName("ValueKey")
        label_a.setFixedWidth(56)
        self._combo_a = QComboBox()
        row_a.addWidget(label_a)
        row_a.addWidget(self._combo_a, 1)
        card_layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(8)
        label_b = QLabel("坐标系 B")
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

        matrix_box = QFrame()
        matrix_box.setObjectName("InfoBox")
        matrix_layout = QGridLayout(matrix_box)
        matrix_layout.setContentsMargins(12, 10, 12, 10)
        matrix_layout.setHorizontalSpacing(12)
        matrix_layout.setVerticalSpacing(4)
        self._matrix_labels: list[list[QLabel]] = []
        for row in range(4):
            row_labels = []
            for col in range(4):
                value = QLabel("—")
                value.setFont(mono_font(10.5))
                value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                matrix_layout.addWidget(value, row, col)
                row_labels.append(value)
            self._matrix_labels.append(row_labels)
        for col in range(4):
            matrix_layout.setColumnStretch(col, 1)
        card_layout.addWidget(matrix_box)

        self._relative_position = self._make_value_row(card_layout, "位置 / m")
        self._relative_euler = self._make_value_row(card_layout, "RPY / °")
        self._relative_quaternion = self._make_value_row(card_layout, "四元数")

        self._combo_a.currentIndexChanged.connect(self._recompute_relative)
        self._combo_b.currentIndexChanged.connect(self._recompute_relative)
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
    # 输入
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._editor.setFocus()

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
            poses = parse_poses(self._editor.toPlainText(), mode=self._mode)
        except MatrixParseError as exc:
            self._show_hint(str(exc), DANGER)
            return
        start = len(self._entries)
        for offset, pose in enumerate(poses):
            index = start + offset
            self._entries.append(
                PoseEntry(
                    name=f"Pose {index + 1}",
                    color=POSE_COLORS[index % len(POSE_COLORS)],
                    pose=pose,
                )
            )
        self._sync_poses(select=start)
        self._show_hint(f"已添加 {len(poses)} 个位姿", SUCCESS)

    def _clear_input(self) -> None:
        self._editor.clear()
        self._editor.setFocus()
        self._show_hint(self._default_hint, MUTED)

    def add_pose(
        self, matrix: list[list[float]], name: str = "", visible: bool = True
    ) -> None:
        """由外部工具添加一个位姿。"""
        index = len(self._entries)
        self._entries.append(
            PoseEntry(
                name=name or f"Pose {index + 1}",
                color=POSE_COLORS[index % len(POSE_COLORS)],
                pose=Pose(matrix),
                visible=visible,
            )
        )
        self._sync_poses(select=index)
        self._show_hint(f"已添加 {name or f'Pose {index + 1}'}", SUCCESS)

    def add_poses(self, items: list, visible: bool = True) -> int:
        """批量添加 (name, matrix) 位姿，返回添加数量。"""
        start = len(self._entries)
        for name, matrix in items:
            index = len(self._entries)
            self._entries.append(
                PoseEntry(
                    name=name or f"Pose {index + 1}",
                    color=POSE_COLORS[index % len(POSE_COLORS)],
                    pose=Pose(matrix),
                    visible=visible,
                )
            )
        if len(self._entries) > start:
            self._sync_poses(select=start)
            self._show_hint(f"已导入 {len(self._entries) - start} 个位姿", SUCCESS)
        return len(self._entries) - start

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def select_row(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            self._list.setCurrentRow(index)
            self._sync_selection()

    def _sync_poses(self, select: int = -1) -> None:
        self._rebuild_list(select)
        self._refresh_relative_combos()
        self._recompute_relative()
        self._count_badge.setText(f"{len(self._entries)} 帧")
        self.poses_changed.emit(list(self._entries))
        self._sync_selection()

    def _rebuild_list(self, select: int = -1) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for index, entry in enumerate(self._entries):
            x, y, z = entry.pose.values.position
            item = QListWidgetItem(
                f"{entry.name}    x {format_number(x, 2)}   "
                f"y {format_number(y, 2)}   z {format_number(z, 2)}"
            )
            item.setIcon(dot_icon(entry.color))
            item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            item.setCheckState(Qt.Checked if entry.visible else Qt.Unchecked)
            item.setData(Qt.UserRole, index)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if self._entries:
            select = max(0, min(select, len(self._entries) - 1))
            self._list.setCurrentRow(select)

    def _sync_selection(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            self._value_panel.set_pose(entry.pose, entry.name, entry.color)
            self.selection_changed.emit(row)
        else:
            self._value_panel.clear()
            self.selection_changed.emit(-1)

    def _on_row_changed(self, row: int) -> None:
        self._sync_selection()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        row = self._list.row(item)
        if 0 <= row < len(self._entries):
            self._entries[row].visible = item.checkState() == Qt.Checked
            self.poses_changed.emit(list(self._entries))

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if not (0 <= row < len(self._entries)):
            return
        entry = self._entries.pop(row)
        self._sync_poses(select=min(row, len(self._entries) - 1))
        self._show_hint(f"已删除 {entry.name}", MUTED)

    def _clear_all(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空位姿",
            f"确定清空全部 {len(self._entries)} 个位姿？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._entries.clear()
        self._sync_poses()
        self._show_hint("已清空位姿列表", MUTED)

    # ------------------------------------------------------------------
    # 相对位姿
    # ------------------------------------------------------------------

    def _refresh_relative_combos(self) -> None:
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

    def _recompute_relative(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        if (
            len(self._entries) < 2
            or not (0 <= index_a < len(self._entries))
            or not (0 <= index_b < len(self._entries))
        ):
            self._relative = None
            self._relative_subtitle.setText("至少需要两个位姿")
            for row in self._matrix_labels:
                for label in row:
                    label.setText("—")
            self._relative_position.setText("—")
            self._relative_euler.setText("—")
            self._relative_quaternion.setText("—")
            self._copy_button.setEnabled(False)
            return

        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        relative = relative_transform(entry_a.pose.matrix, entry_b.pose.matrix)
        self._relative = Pose(relative)

        for row in range(4):
            for col in range(4):
                self._matrix_labels[row][col].setText(
                    format_number(relative[row][col], 6)
                )

        values = self._relative.values
        x, y, z = values.position
        self._relative_position.setText(
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   z {format_number(z, 4)}"
        )
        self._relative_euler.setText(
            f"roll {format_number(values.roll, 3)}°   "
            f"pitch {format_number(values.pitch, 3)}°   "
            f"yaw {format_number(values.yaw, 3)}°"
        )
        w, qx, qy, qz = values.quaternion
        self._relative_quaternion.setText(
            f"w {format_number(w, 4)}   x {format_number(qx, 4)}   "
            f"y {format_number(qy, 4)}   z {format_number(qz, 4)}"
        )
        self._relative_subtitle.setText(f"{entry_b.name} 在 {entry_a.name} 中")
        self._copy_button.setEnabled(True)

    def _swap(self) -> None:
        if len(self._entries) < 2:
            return
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        self._combo_a.blockSignals(True)
        self._combo_b.blockSignals(True)
        self._combo_a.setCurrentIndex(index_b)
        self._combo_b.setCurrentIndex(index_a)
        self._combo_a.blockSignals(False)
        self._combo_b.blockSignals(False)
        self._recompute_relative()

    # ------------------------------------------------------------------
    # 复制与提示
    # ------------------------------------------------------------------

    def _copy_relative(self) -> None:
        if self._relative is None:
            return
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        name_a = self._entries[index_a].name
        name_b = self._entries[index_b].name
        text = (
            f"T_A->B: {name_b} in {name_a}\n"
            f"{self._relative.matrix_text()}\n\n"
            f"{self._relative.values.report()}"
        )
        QApplication.clipboard().setText(text)
        self._copy_button.setIcon(icon("check", SUCCESS, 15))
        self._copy_button.setToolTip("已复制")
        self._copy_timer.start(1200)

    def _restore_copy_icon(self) -> None:
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setToolTip("复制 4x4 矩阵与姿态")

    def _show_hint(self, text: str, color: str) -> None:
        self._parse_hint.setText(text)
        self._parse_hint.setStyleSheet(f"color: {color};")
        if text == self._default_hint:
            self._hint_timer.stop()
        else:
            self._hint_timer.start(5000)

    def _reset_hint(self) -> None:
        self._parse_hint.setText(self._default_hint)
        self._parse_hint.setStyleSheet(f"color: {MUTED};")
