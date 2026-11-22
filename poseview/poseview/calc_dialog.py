"""数学计算工具对话框：坐标变换、位姿测量、变换链、旋转与数据工具。"""

from __future__ import annotations

import csv
import json
import math
import re

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .math3d import (
    Pose,
    angle_between_vectors,
    axis_angle_from_rotation,
    format_number,
    invert_transform,
    matrix_properties,
    multiply_transform,
    project_vector,
    quaternion_conjugate,
    quaternion_from_rotation,
    quaternion_multiply,
    relative_transform,
    rotation_angle_between,
    rotation_from_quaternion,
    rotation_vector_from_rotation,
    slerp_quaternion,
    transform_point,
    transform_vector,
    vector_cross,
    vector_dot,
    vector_length,
)
from .theme import SUCCESS, mono_font

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def _numbers(text: str) -> list[float]:
    return [float(match.group(0)) for match in _NUMBER_RE.finditer(text)]


def _quaternion_text(quaternion) -> str:
    w, x, y, z = quaternion
    return (
        f"w {format_number(w, 5)}   x {format_number(x, 5)}   "
        f"y {format_number(y, 5)}   z {format_number(z, 5)}"
    )


def _pose_raw_text(label: str, name: str, pose: Pose) -> str:
    values = pose.values
    x, y, z = values.position
    w, qx, qy, qz = values.quaternion
    matrix = "\n".join(
        "  " + line for line in pose.matrix_text().splitlines()
    )
    return (
        f"{label} · {name}\n"
        f"  位置 / m  x {format_number(x, 6)}  y {format_number(y, 6)}  "
        f"z {format_number(z, 6)}\n"
        f"  RPY / °   roll {format_number(values.roll, 4)}  "
        f"pitch {format_number(values.pitch, 4)}  "
        f"yaw {format_number(values.yaw, 4)}\n"
        f"  四元数    w {format_number(w, 6)}  x {format_number(qx, 6)}  "
        f"y {format_number(qy, 6)}  z {format_number(qz, 6)}\n"
        f"  4x4 矩阵\n{matrix}\n"
    )


def _vector_raw_text(label: str, vector) -> str:
    start = vector.start
    end = vector.end
    direction = vector.direction
    length = vector_length(direction)
    return (
        f"{label} · {vector.name}\n"
        f"  起点 / m  ({format_number(start[0], 6)}, "
        f"{format_number(start[1], 6)}, {format_number(start[2], 6)})\n"
        f"  方向      ({format_number(direction[0], 6)}, "
        f"{format_number(direction[1], 6)}, "
        f"{format_number(direction[2], 6)})\n"
        f"  终点 / m  ({format_number(end[0], 6)}, "
        f"{format_number(end[1], 6)}, {format_number(end[2], 6)})\n"
        f"  模长      {format_number(length, 6)}\n"
    )


class CalcDialog(QDialog):
    """坐标变换、位姿测量、变换链、旋转四元数与数据工具。"""

    pose_created = pyqtSignal(object, str)
    point_added = pyqtSignal(str, object)
    vector_added = pyqtSignal(str, object, object)
    poses_imported = pyqtSignal(list)
    markers_cleared = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list = []
        self._transform_mode = "point"
        self._transform_result = None
        self._marker_index = 1
        self._chain_checked: set[str] = set()
        self._chain_initialized = False
        self._chain_result: list[list[float]] | None = None
        self._measure_matrix: list[list[float]] | None = None
        self._relative_matrix: list[list[float]] | None = None
        self._vector_entries: list = []
        self._vector_cross: tuple[float, float, float] | None = None
        self._slerp_matrix: list[list[float]] | None = None
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)

        self.setObjectName("CalcDialog")
        self.setWindowTitle("计算工具")
        self.resize(900, 740)
        self.setMinimumSize(820, 640)
        self._build()
        self._refresh_all()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("计算工具")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "坐标变换、位姿测量、相对位姿、向量计算、变换链、旋转与四元数、数据导入导出与轨迹分析。"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        tabs = QTabWidget()
        tabs.setObjectName("CalcTabs")
        tabs.addTab(self._build_transform_tab(), "点位变换")
        tabs.addTab(self._build_measure_tab(), "位姿测量")
        tabs.addTab(self._build_relative_tab(), "相对位姿")
        tabs.addTab(self._build_vector_tab(), "向量")
        tabs.addTab(self._build_chain_tab(), "变换链")
        tabs.addTab(self._build_rotation_tab(), "旋转 / 四元数")
        tabs.addTab(self._build_data_tab(), "数据 / 轨迹")
        layout.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    # ------------------------------------------------------------------
    # 点位变换
    # ------------------------------------------------------------------

    def _build_transform_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("点位 / 向量坐标变换")
        title.setObjectName("SectionTitle")
        hint = QLabel("点：p' = R·p + t；向量：v' = R·v")
        hint.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
        card_layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("坐标系")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._transform_frame = QComboBox()
        row.addWidget(label)
        row.addWidget(self._transform_frame, 1)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("方向")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._transform_direction = QComboBox()
        self._transform_direction.addItem("坐标系 → 世界")
        self._transform_direction.addItem("世界 → 坐标系")
        row.addWidget(label)
        row.addWidget(self._transform_direction, 1)
        card_layout.addLayout(row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self._transform_group = QButtonGroup(self)
        self._transform_group.setExclusive(True)
        self._transform_buttons: dict[str, QToolButton] = {}
        for key, text in (("point", "点"), ("vector", "向量")):
            button = QToolButton()
            button.setObjectName("ModeTab")
            button.setText(text)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(
                lambda _checked=False, name=key: self._set_transform_mode(name)
            )
            self._transform_group.addButton(button)
            self._transform_buttons[key] = button
            mode_row.addWidget(button, 1)
        self._transform_buttons["point"].setChecked(True)
        card_layout.addLayout(mode_row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("输入")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._transform_input = QLineEdit()
        self._transform_input.setObjectName("PoseInput")
        self._transform_input.setPlaceholderText("x y z，例如 1 0 0.5")
        self._transform_input.textChanged.connect(self._recompute_transform)
        row.addWidget(label)
        row.addWidget(self._transform_input, 1)
        card_layout.addLayout(row)

        self._transform_formula = QLabel("")
        self._transform_formula.setObjectName("CardHint")
        card_layout.addWidget(self._transform_formula)

        self._transform_result = self._make_value_row(card_layout, "结果 / m")
        self._transform_norm = self._make_value_row(
            card_layout, "模长 / 距原点", width=90
        )

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._transform_add = QPushButton("加入场景")
        self._transform_add.setObjectName("Primary")
        self._transform_add.setIcon(icon("plus", "#FFFFFF", 15))
        self._transform_add.setCursor(Qt.PointingHandCursor)
        self._transform_add.clicked.connect(self._add_transform_result)
        self._transform_add.setEnabled(False)
        clear_markers = QPushButton("清除标注")
        clear_markers.setObjectName("Ghost")
        clear_markers.setIcon(icon("clear", "#475569", 15))
        clear_markers.setCursor(Qt.PointingHandCursor)
        clear_markers.clicked.connect(self.markers_cleared.emit)
        buttons.addWidget(self._transform_add, 1)
        buttons.addWidget(clear_markers)
        card_layout.addLayout(buttons)

        layout.addWidget(card)
        layout.addStretch(1)

        self._transform_frame.currentIndexChanged.connect(self._recompute_transform)
        self._transform_direction.currentIndexChanged.connect(
            self._recompute_transform
        )
        return tab

    def _set_transform_mode(self, key: str) -> None:
        button = self._transform_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._transform_mode = key
        self._recompute_transform()

    def _transform_matrix(self) -> list[list[float]]:
        index = self._transform_frame.currentIndex()
        matrix = _IDENTITY
        if index > 0 and index - 1 < len(self._entries):
            matrix = self._entries[index - 1].pose.matrix
        if self._transform_direction.currentIndex() == 1:
            return invert_transform(matrix)
        return matrix

    def _recompute_transform(self) -> None:
        values = _numbers(self._transform_input.text())
        if len(values) != 3:
            self._transform_result.setText("—")
            self._transform_norm.setText("—")
            self._transform_formula.setText("输入 3 个数：x y z")
            self._transform_add.setEnabled(False)
            return
        vector = (values[0], values[1], values[2])
        matrix = self._transform_matrix()
        if self._transform_mode == "point":
            result = transform_point(matrix, vector)
            if self._transform_direction.currentIndex() == 0:
                formula = "p' = T·p"
            else:
                formula = "p' = T⁻¹·p"
        else:
            result = transform_vector(matrix, vector)
            if self._transform_direction.currentIndex() == 0:
                formula = "v' = R·v"
            else:
                formula = "v' = Rᵀ·v"
        norm = math.sqrt(sum(value * value for value in result))
        self._transform_result.setText(
            f"x {format_number(result[0], 5)}   y {format_number(result[1], 5)}   "
            f"z {format_number(result[2], 5)}"
        )
        self._transform_norm.setText(format_number(norm, 5))
        self._transform_formula.setText(formula)
        self._transform_result.setToolTip(self._transform_result.text())
        self._transform_add.setEnabled(True)

    def _add_transform_result(self) -> None:
        values = _numbers(self._transform_input.text())
        if len(values) != 3:
            return
        vector = (values[0], values[1], values[2])
        matrix = self._transform_matrix()
        if self._transform_mode == "point":
            result = transform_point(matrix, vector)
            name = f"P{self._marker_index}"
            self._marker_index += 1
            self.point_added.emit(name, result)
        else:
            result = transform_vector(matrix, vector)
            index = self._transform_frame.currentIndex()
            if index <= 0 or index - 1 >= len(self._entries):
                origin = (0.0, 0.0, 0.0)
            else:
                origin = self._entries[index - 1].pose.values.position
            self.vector_added.emit("", origin, result)

    # ------------------------------------------------------------------
    # 位姿测量
    # ------------------------------------------------------------------

    def _build_measure_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("位姿测量")
        title.setObjectName("SectionTitle")
        self._measure_subtitle = QLabel("至少需要两个位姿")
        self._measure_subtitle.setObjectName("CardHint")
        self._measure_copy = QToolButton()
        self._measure_copy.setObjectName("IconButton")
        self._measure_copy.setIcon(icon("copy", "#475569", 15))
        self._measure_copy.setFixedSize(26, 26)
        self._measure_copy.setCursor(Qt.PointingHandCursor)
        self._measure_copy.setToolTip("复制测量结果")
        self._measure_copy.clicked.connect(self._copy_measure)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._measure_subtitle)
        head.addWidget(self._measure_copy)
        card_layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("位姿 A")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._measure_a = QComboBox()
        row.addWidget(label)
        row.addWidget(self._measure_a, 1)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("位姿 B")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._measure_b = QComboBox()
        self._measure_swap = QToolButton()
        self._measure_swap.setObjectName("IconButton")
        self._measure_swap.setIcon(icon("swap", "#475569", 16))
        self._measure_swap.setFixedSize(26, 26)
        self._measure_swap.setCursor(Qt.PointingHandCursor)
        self._measure_swap.setToolTip("交换 A / B")
        self._measure_swap.clicked.connect(self._swap_measure)
        row.addWidget(label)
        row.addWidget(self._measure_b, 1)
        row.addWidget(self._measure_swap)
        card_layout.addLayout(row)

        self._measure_delta = self._make_value_row(
            card_layout, "位置差 / m", width=78
        )
        self._measure_distance = self._make_value_row(
            card_layout, "距离 / m", width=78
        )
        self._measure_angle = self._make_value_row(
            card_layout, "姿态夹角", width=78
        )
        self._measure_axis = self._make_value_row(
            card_layout, "转轴 (A)", width=78
        )
        self._measure_relative = self._make_value_row(
            card_layout, "相对平移 (A)", width=78
        )

        layout.addWidget(card)
        layout.addStretch(1)

        self._measure_a.currentIndexChanged.connect(self._recompute_measure)
        self._measure_b.currentIndexChanged.connect(self._recompute_measure)
        return tab

    # ------------------------------------------------------------------
    # 相对位姿
    # ------------------------------------------------------------------

    def _build_relative_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

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
        self._relative_copy = QToolButton()
        self._relative_copy.setObjectName("IconButton")
        self._relative_copy.setIcon(icon("copy", "#475569", 15))
        self._relative_copy.setFixedSize(26, 26)
        self._relative_copy.setCursor(Qt.PointingHandCursor)
        self._relative_copy.setToolTip("复制 4x4 矩阵与姿态")
        self._relative_copy.clicked.connect(self._copy_relative)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._relative_subtitle)
        head.addWidget(self._relative_copy)
        card_layout.addLayout(head)

        hint = QLabel("计算 B 在 A 坐标系下的位姿：T_A→B = inv(T_A) · T_B")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("坐标系 A")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._relative_a = QComboBox()
        row.addWidget(label)
        row.addWidget(self._relative_a, 1)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("坐标系 B")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._relative_b = QComboBox()
        self._relative_swap = QToolButton()
        self._relative_swap.setObjectName("IconButton")
        self._relative_swap.setIcon(icon("swap", "#475569", 16))
        self._relative_swap.setFixedSize(26, 26)
        self._relative_swap.setCursor(Qt.PointingHandCursor)
        self._relative_swap.setToolTip("交换 A / B")
        self._relative_swap.clicked.connect(self._swap_relative)
        row.addWidget(label)
        row.addWidget(self._relative_b, 1)
        row.addWidget(self._relative_swap)
        card_layout.addLayout(row)

        self._relative_labels = self._make_matrix_box(card_layout)
        self._relative_position = self._make_value_row(
            card_layout, "位置 / m", width=70
        )
        self._relative_euler = self._make_value_row(
            card_layout, "RPY / °", width=70
        )
        self._relative_quaternion = self._make_value_row(
            card_layout, "四元数", width=70
        )

        raw_head = QHBoxLayout()
        raw_head.setSpacing(8)
        raw_title = QLabel("原始数据")
        raw_title.setObjectName("ValueKey")
        self._relative_raw_copy = QToolButton()
        self._relative_raw_copy.setObjectName("IconButton")
        self._relative_raw_copy.setIcon(icon("copy", "#475569", 15))
        self._relative_raw_copy.setFixedSize(26, 26)
        self._relative_raw_copy.setCursor(Qt.PointingHandCursor)
        self._relative_raw_copy.setToolTip("复制 A / B 的原始参数")
        self._relative_raw_copy.clicked.connect(self._copy_relative_raw)
        raw_head.addWidget(raw_title)
        raw_head.addStretch(1)
        raw_head.addWidget(self._relative_raw_copy)
        card_layout.addLayout(raw_head)

        self._relative_raw = QPlainTextEdit()
        self._relative_raw.setObjectName("RawData")
        self._relative_raw.setReadOnly(True)
        self._relative_raw.setFont(mono_font(9.5))
        self._relative_raw.setFixedHeight(150)
        self._relative_raw.setPlaceholderText("选择两个位姿后显示 A / B 的原始参数")
        card_layout.addWidget(self._relative_raw)

        layout.addWidget(card)
        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._relative_a.currentIndexChanged.connect(
            self._recompute_relative
        )
        self._relative_b.currentIndexChanged.connect(
            self._recompute_relative
        )
        return tab

    def _refresh_relative_combos(self) -> None:
        names = [entry.name for entry in self._entries]
        for combo, fallback_last in (
            (self._relative_a, False),
            (self._relative_b, True),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if names:
                combo.setCurrentIndex(
                    names.index(current)
                    if current in names
                    else (len(names) - 1 if fallback_last else 0)
                )
            combo.blockSignals(False)
            combo.setEnabled(len(names) >= 2)
        self._relative_swap.setEnabled(len(names) >= 2)
        self._recompute_relative()

    def _recompute_relative(self) -> None:
        index_a = self._relative_a.currentIndex()
        index_b = self._relative_b.currentIndex()
        if (
            len(self._entries) < 2
            or not (0 <= index_a < len(self._entries))
            or not (0 <= index_b < len(self._entries))
        ):
            self._relative_matrix = None
            self._relative_subtitle.setText("至少需要两个位姿")
            for row in self._relative_labels:
                for label in row:
                    label.setText("—")
            self._relative_position.setText("—")
            self._relative_euler.setText("—")
            self._relative_quaternion.setText("—")
            self._relative_raw.clear()
            self._relative_copy.setEnabled(False)
            self._relative_raw_copy.setEnabled(False)
            return

        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        relative = relative_transform(
            entry_a.pose.matrix, entry_b.pose.matrix
        )
        self._relative_matrix = relative
        for row in range(4):
            for col in range(4):
                self._relative_labels[row][col].setText(
                    format_number(relative[row][col], 6)
                )
        values = Pose(relative).values
        x, y, z = values.position
        self._relative_position.setText(
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   "
            f"z {format_number(z, 4)}"
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
        self._relative_raw.setPlainText(
            _pose_raw_text("坐标系 A", entry_a.name, entry_a.pose)
            + "\n"
            + _pose_raw_text("坐标系 B", entry_b.name, entry_b.pose)
        )
        self._relative_copy.setEnabled(True)
        self._relative_raw_copy.setEnabled(True)

    def _swap_relative(self) -> None:
        if len(self._entries) < 2:
            return
        index_a = self._relative_a.currentIndex()
        index_b = self._relative_b.currentIndex()
        self._relative_a.blockSignals(True)
        self._relative_b.blockSignals(True)
        self._relative_a.setCurrentIndex(index_b)
        self._relative_b.setCurrentIndex(index_a)
        self._relative_a.blockSignals(False)
        self._relative_b.blockSignals(False)
        self._recompute_relative()

    def _copy_relative(self) -> None:
        if self._relative_matrix is None:
            return
        index_a = self._relative_a.currentIndex()
        index_b = self._relative_b.currentIndex()
        name_a = self._entries[index_a].name
        name_b = self._entries[index_b].name
        relative = Pose(self._relative_matrix)
        QApplication.clipboard().setText(
            f"T_A->B: {name_b} in {name_a}\n"
            f"{relative.matrix_text()}\n\n"
            f"{relative.values.report()}"
        )
        self._relative_copy.setIcon(icon("check", SUCCESS, 15))
        self._relative_copy.setToolTip("已复制")
        QTimer.singleShot(1200, self._restore_relative_copy_icon)

    def _restore_relative_copy_icon(self) -> None:
        self._relative_copy.setIcon(icon("copy", "#475569", 15))
        self._relative_copy.setToolTip("复制 4x4 矩阵与姿态")

    def _copy_relative_raw(self) -> None:
        text = self._relative_raw.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._relative_raw_copy.setIcon(icon("check", SUCCESS, 15))
        self._relative_raw_copy.setToolTip("已复制")
        QTimer.singleShot(1200, self._restore_relative_raw_copy_icon)

    def _restore_relative_raw_copy_icon(self) -> None:
        self._relative_raw_copy.setIcon(icon("copy", "#475569", 15))
        self._relative_raw_copy.setToolTip("复制 A / B 的原始参数")

    # ------------------------------------------------------------------
    # 向量计算
    # ------------------------------------------------------------------

    def _build_vector_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("向量计算")
        title.setObjectName("SectionTitle")
        self._vector_subtitle = QLabel("从向量树选择两个向量")
        self._vector_subtitle.setObjectName("CardHint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._vector_subtitle)
        card_layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("向量 A")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._vector_a = QComboBox()
        row.addWidget(label)
        row.addWidget(self._vector_a, 1)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("向量 B")
        label.setObjectName("ValueKey")
        label.setFixedWidth(56)
        self._vector_b = QComboBox()
        self._vector_swap = QToolButton()
        self._vector_swap.setObjectName("IconButton")
        self._vector_swap.setIcon(icon("swap", "#475569", 16))
        self._vector_swap.setFixedSize(26, 26)
        self._vector_swap.setCursor(Qt.PointingHandCursor)
        self._vector_swap.setToolTip("交换 A / B")
        self._vector_swap.clicked.connect(self._swap_vector)
        row.addWidget(label)
        row.addWidget(self._vector_b, 1)
        row.addWidget(self._vector_swap)
        card_layout.addLayout(row)

        self._vector_angle = self._make_value_row(
            card_layout, "夹角 / °", width=76
        )
        self._vector_cosine = self._make_value_row(
            card_layout, "cos θ", width=76
        )
        self._vector_dot = self._make_value_row(
            card_layout, "点积", width=76
        )
        self._vector_len_a = self._make_value_row(
            card_layout, "模长 A", width=76
        )
        self._vector_len_b = self._make_value_row(
            card_layout, "模长 B", width=76
        )
        self._vector_unit_a = self._make_value_row(
            card_layout, "单位向量 A", width=76
        )
        self._vector_unit_b = self._make_value_row(
            card_layout, "单位向量 B", width=76
        )
        self._vector_cross_label = self._make_value_row(
            card_layout, "叉积 A×B", width=76
        )
        self._vector_projection = self._make_value_row(
            card_layout, "A 在 B 上投影", width=76
        )

        self._vector_add_cross = QPushButton("叉积加入场景")
        self._vector_add_cross.setObjectName("Ghost")
        self._vector_add_cross.setCursor(Qt.PointingHandCursor)
        self._vector_add_cross.setToolTip("以原点为起点添加 A×B 向量")
        self._vector_add_cross.clicked.connect(self._add_vector_cross)
        card_layout.addWidget(self._vector_add_cross)

        raw_head = QHBoxLayout()
        raw_head.setSpacing(8)
        raw_title = QLabel("原始数据")
        raw_title.setObjectName("ValueKey")
        self._vector_raw_copy = QToolButton()
        self._vector_raw_copy.setObjectName("IconButton")
        self._vector_raw_copy.setIcon(icon("copy", "#475569", 15))
        self._vector_raw_copy.setFixedSize(26, 26)
        self._vector_raw_copy.setCursor(Qt.PointingHandCursor)
        self._vector_raw_copy.setToolTip("复制 A / B 的原始参数")
        self._vector_raw_copy.clicked.connect(self._copy_vector_raw)
        raw_head.addWidget(raw_title)
        raw_head.addStretch(1)
        raw_head.addWidget(self._vector_raw_copy)
        card_layout.addLayout(raw_head)

        self._vector_raw = QPlainTextEdit()
        self._vector_raw.setObjectName("RawData")
        self._vector_raw.setReadOnly(True)
        self._vector_raw.setFont(mono_font(9.5))
        self._vector_raw.setFixedHeight(120)
        self._vector_raw.setPlaceholderText("选择两个向量后显示 A / B 的原始参数")
        card_layout.addWidget(self._vector_raw)

        layout.addWidget(card)
        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._vector_a.currentIndexChanged.connect(self._recompute_vector)
        self._vector_b.currentIndexChanged.connect(self._recompute_vector)
        return tab

    def set_vector_entries(self, vectors: list) -> None:
        self._vector_entries = list(vectors)
        self._refresh_vector_combos()

    def _refresh_vector_combos(self) -> None:
        names = [vector.name for vector in self._vector_entries]
        for combo, fallback_last in (
            (self._vector_a, False),
            (self._vector_b, True),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if names:
                combo.setCurrentIndex(
                    names.index(current)
                    if current in names
                    else (len(names) - 1 if fallback_last else 0)
                )
            combo.blockSignals(False)
            combo.setEnabled(len(names) >= 2)
        self._vector_swap.setEnabled(len(names) >= 2)
        self._recompute_vector()

    def _recompute_vector(self) -> None:
        index_a = self._vector_a.currentIndex()
        index_b = self._vector_b.currentIndex()
        rows = (
            self._vector_angle,
            self._vector_cosine,
            self._vector_dot,
            self._vector_len_a,
            self._vector_len_b,
            self._vector_unit_a,
            self._vector_unit_b,
            self._vector_cross_label,
            self._vector_projection,
        )
        if (
            len(self._vector_entries) < 2
            or not (0 <= index_a < len(self._vector_entries))
            or not (0 <= index_b < len(self._vector_entries))
        ):
            self._vector_cross = None
            self._vector_subtitle.setText("至少需要两个向量")
            for row in rows:
                row.setText("—")
            self._vector_raw.clear()
            self._vector_add_cross.setEnabled(False)
            self._vector_raw_copy.setEnabled(False)
            return

        first = self._vector_entries[index_a]
        second = self._vector_entries[index_b]
        a = first.direction
        b = second.direction
        length_a = vector_length(a)
        length_b = vector_length(b)
        dot = vector_dot(a, b)
        angle = angle_between_vectors(a, b)
        cosine = dot / (length_a * length_b)
        cross = vector_cross(a, b)
        projection = project_vector(a, b)
        self._vector_cross = cross

        self._vector_angle.setText(f"{angle:.4f}")
        self._vector_cosine.setText(f"{cosine:.6f}")
        self._vector_dot.setText(f"{dot:.6f}")
        self._vector_len_a.setText(f"{length_a:.6f}")
        self._vector_len_b.setText(f"{length_b:.6f}")
        if length_a > 1e-12:
            self._vector_unit_a.setText(
                f"({a[0] / length_a:.4f}, {a[1] / length_a:.4f}, "
                f"{a[2] / length_a:.4f})"
            )
        else:
            self._vector_unit_a.setText("—")
        if length_b > 1e-12:
            self._vector_unit_b.setText(
                f"({b[0] / length_b:.4f}, {b[1] / length_b:.4f}, "
                f"{b[2] / length_b:.4f})"
            )
        else:
            self._vector_unit_b.setText("—")
        self._vector_cross_label.setText(
            f"({cross[0]:.4f}, {cross[1]:.4f}, {cross[2]:.4f})"
        )
        self._vector_projection.setText(
            f"({projection[0]:.4f}, {projection[1]:.4f}, "
            f"{projection[2]:.4f})"
        )
        self._vector_subtitle.setText(f"{first.name} 与 {second.name}")
        self._vector_raw.setPlainText(
            _vector_raw_text("向量 A", first)
            + "\n"
            + _vector_raw_text("向量 B", second)
        )
        self._vector_raw_copy.setEnabled(True)
        self._vector_add_cross.setEnabled(vector_length(cross) > 1e-9)

    def _swap_vector(self) -> None:
        if len(self._vector_entries) < 2:
            return
        index_a = self._vector_a.currentIndex()
        index_b = self._vector_b.currentIndex()
        self._vector_a.blockSignals(True)
        self._vector_b.blockSignals(True)
        self._vector_a.setCurrentIndex(index_b)
        self._vector_b.setCurrentIndex(index_a)
        self._vector_a.blockSignals(False)
        self._vector_b.blockSignals(False)
        self._recompute_vector()

    def _add_vector_cross(self) -> None:
        if self._vector_cross is None:
            return
        if vector_length(self._vector_cross) < 1e-9:
            return
        self.vector_added.emit(
            "A×B", (0.0, 0.0, 0.0), self._vector_cross
        )

    def _copy_vector_raw(self) -> None:
        text = self._vector_raw.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._vector_raw_copy.setIcon(icon("check", SUCCESS, 15))
        self._vector_raw_copy.setToolTip("已复制")
        QTimer.singleShot(1200, self._restore_vector_raw_copy_icon)

    def _restore_vector_raw_copy_icon(self) -> None:
        self._vector_raw_copy.setIcon(icon("copy", "#475569", 15))
        self._vector_raw_copy.setToolTip("复制 A / B 的原始参数")

    def _swap_measure(self) -> None:
        if len(self._entries) < 2:
            return
        index_a = self._measure_a.currentIndex()
        index_b = self._measure_b.currentIndex()
        self._measure_a.blockSignals(True)
        self._measure_b.blockSignals(True)
        self._measure_a.setCurrentIndex(index_b)
        self._measure_b.setCurrentIndex(index_a)
        self._measure_a.blockSignals(False)
        self._measure_b.blockSignals(False)
        self._recompute_measure()

    def _recompute_measure(self) -> None:
        index_a = self._measure_a.currentIndex()
        index_b = self._measure_b.currentIndex()
        if (
            len(self._entries) < 2
            or not (0 <= index_a < len(self._entries))
            or not (0 <= index_b < len(self._entries))
        ):
            self._measure_matrix = None
            self._measure_subtitle.setText("至少需要两个位姿")
            for label in (
                self._measure_delta,
                self._measure_distance,
                self._measure_angle,
                self._measure_axis,
                self._measure_relative,
            ):
                label.setText("—")
            self._measure_copy.setEnabled(False)
            return

        entry_a = self._entries[index_a]
        entry_b = self._entries[index_b]
        matrix_a = entry_a.pose.matrix
        matrix_b = entry_b.pose.matrix
        ax, ay, az = entry_a.pose.values.position
        bx, by, bz = entry_b.pose.values.position
        dx, dy, dz = bx - ax, by - ay, bz - az
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        angle = rotation_angle_between(
            entry_a.pose.values.rotation, entry_b.pose.values.rotation
        )
        relative = relative_transform(matrix_a, matrix_b)
        relative_rotation = [row[:3] for row in relative[:3]]
        axis, _ = axis_angle_from_rotation(relative_rotation)

        self._measure_matrix = relative
        self._measure_delta.setText(
            f"Δx {format_number(dx, 5)}   Δy {format_number(dy, 5)}   "
            f"Δz {format_number(dz, 5)}"
        )
        self._measure_distance.setText(format_number(distance, 5))
        self._measure_angle.setText(f"{format_number(angle, 3)}°")
        self._measure_axis.setText(
            f"({format_number(axis[0], 4)}, {format_number(axis[1], 4)}, "
            f"{format_number(axis[2], 4)})（A 坐标系）"
        )
        rx, ry, rz = relative[0][3], relative[1][3], relative[2][3]
        self._measure_relative.setText(
            f"x {format_number(rx, 5)}   y {format_number(ry, 5)}   "
            f"z {format_number(rz, 5)}"
        )
        self._measure_subtitle.setText(f"{entry_b.name} 相对 {entry_a.name}")
        self._measure_copy.setEnabled(True)

    def _copy_measure(self) -> None:
        if self._measure_matrix is None:
            return
        index_a = self._measure_a.currentIndex()
        index_b = self._measure_b.currentIndex()
        name_a = self._entries[index_a].name
        name_b = self._entries[index_b].name
        text = (
            f"{name_b} 相对 {name_a}\n"
            f"{self._measure_delta.text()}\n"
            f"距离: {self._measure_distance.text()} m\n"
            f"姿态夹角: {self._measure_angle.text()}\n"
            f"转轴: {self._measure_axis.text()}\n"
            f"相对平移: {self._measure_relative.text()}\n\n"
            f"T_A->B:\n"
            + "\n".join(
                "  ".join(format_number(value, 6).rjust(11) for value in row)
                for row in self._measure_matrix
            )
        )
        QApplication.clipboard().setText(text)
        self._measure_copy.setIcon(icon("check", SUCCESS, 15))
        self._copy_timer.start(1200)

    def _restore_copy_icon(self) -> None:
        self._measure_copy.setIcon(icon("copy", "#475569", 15))
        self._chain_copy.setIcon(icon("copy", "#475569", 15))

    # ------------------------------------------------------------------
    # 变换链
    # ------------------------------------------------------------------

    def _build_chain_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 12, 14, 13)
        left_layout.setSpacing(8)

        title = QLabel("位姿链")
        title.setObjectName("SectionTitle")
        left_layout.addWidget(title)
        hint = QLabel("按列表顺序左乘：T = T1 · T2 · … · Tn")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)

        self._chain_list = QListWidget()
        self._chain_list.setObjectName("PoseList")
        self._chain_list.setSelectionMode(QAbstractItemView.NoSelection)
        self._chain_list.setUniformItemSizes(True)
        self._chain_list.itemChanged.connect(self._recompute_chain)
        left_layout.addWidget(self._chain_list, 1)

        self._chain_reverse = QCheckBox("反向顺序（Tn · … · T1）")
        self._chain_reverse.setCursor(Qt.PointingHandCursor)
        self._chain_reverse.stateChanged.connect(self._recompute_chain)
        left_layout.addWidget(self._chain_reverse)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._chain_add = QPushButton("加入为位姿")
        self._chain_add.setObjectName("Primary")
        self._chain_add.setIcon(icon("plus", "#FFFFFF", 15))
        self._chain_add.setCursor(Qt.PointingHandCursor)
        self._chain_add.clicked.connect(self._add_chain_pose)
        self._chain_add.setEnabled(False)
        self._chain_clear = QPushButton("全不选")
        self._chain_clear.setObjectName("Ghost")
        self._chain_clear.setCursor(Qt.PointingHandCursor)
        self._chain_clear.clicked.connect(self._clear_chain)
        buttons.addWidget(self._chain_add, 1)
        buttons.addWidget(self._chain_clear)
        left_layout.addLayout(buttons)
        layout.addWidget(left, 1)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 12, 14, 13)
        right_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("链式结果")
        title.setObjectName("SectionTitle")
        self._chain_subtitle = QLabel("未选择位姿")
        self._chain_subtitle.setObjectName("CardHint")
        self._chain_copy = QToolButton()
        self._chain_copy.setObjectName("IconButton")
        self._chain_copy.setIcon(icon("copy", "#475569", 15))
        self._chain_copy.setFixedSize(26, 26)
        self._chain_copy.setCursor(Qt.PointingHandCursor)
        self._chain_copy.setToolTip("复制 4x4 矩阵与姿态")
        self._chain_copy.clicked.connect(self._copy_chain)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._chain_subtitle)
        head.addWidget(self._chain_copy)
        right_layout.addLayout(head)

        self._chain_matrix_labels = self._make_matrix_box(right_layout)
        pose_title = QLabel("姿态解算")
        pose_title.setObjectName("MiniTitle")
        right_layout.addWidget(pose_title)
        self._chain_position = self._make_value_row(right_layout, "位置 / m")
        self._chain_euler = self._make_value_row(right_layout, "RPY / °")
        self._chain_quaternion = self._make_value_row(right_layout, "四元数")
        self._chain_props = self._make_value_row(right_layout, "矩阵性质")
        right_layout.addStretch(1)
        layout.addWidget(right, 1)
        return tab

    def _refresh_chain_list(self) -> None:
        names = [entry.name for entry in self._entries]
        self._chain_list.blockSignals(True)
        self._chain_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            checked = name in self._chain_checked
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self._chain_list.addItem(item)
        self._chain_list.blockSignals(False)
        if not self._chain_initialized and names:
            for index in range(min(2, self._chain_list.count())):
                self._chain_list.item(index).setCheckState(Qt.Checked)
            self._chain_initialized = True
        self._recompute_chain()

    def _chain_selection(self) -> list:
        selected = []
        for index in range(self._chain_list.count()):
            item = self._chain_list.item(index)
            if item.checkState() == Qt.Checked and index < len(self._entries):
                selected.append(self._entries[index])
        if self._chain_reverse.isChecked():
            selected.reverse()
        return selected

    def _recompute_chain(self) -> None:
        self._chain_checked = {
            item.text()
            for item in (
                self._chain_list.item(index)
                for index in range(self._chain_list.count())
            )
            if item.checkState() == Qt.Checked
        }
        selected = self._chain_selection()
        if not selected:
            self._chain_result = None
            self._chain_subtitle.setText("未选择位姿")
            for row in self._chain_matrix_labels:
                for label in row:
                    label.setText("—")
            self._chain_position.setText("—")
            self._chain_euler.setText("—")
            self._chain_quaternion.setText("—")
            self._chain_props.setText("—")
            self._chain_add.setEnabled(False)
            self._chain_copy.setEnabled(False)
            return

        result = [row[:] for row in _IDENTITY]
        for entry in selected:
            result = multiply_transform(result, entry.pose.matrix)
        self._chain_result = result
        pose = Pose(result)
        for row in range(4):
            for col in range(4):
                self._chain_matrix_labels[row][col].setText(
                    format_number(result[row][col], 6)
                )

        x, y, z = pose.values.position
        self._chain_position.setText(
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   z {format_number(z, 4)}"
        )
        self._chain_euler.setText(
            f"roll {format_number(pose.values.roll, 3)}°   "
            f"pitch {format_number(pose.values.pitch, 3)}°   "
            f"yaw {format_number(pose.values.yaw, 3)}°"
        )
        self._chain_quaternion.setText(_quaternion_text(pose.values.quaternion))
        determinant, error, trace = matrix_properties(result)
        self._chain_props.setText(
            f"det {format_number(determinant, 5)}   "
            f"正交误差 {format_number(error, 6)}   trace {format_number(trace, 5)}"
        )
        self._chain_subtitle.setText(" · ".join(entry.name for entry in selected))
        self._chain_add.setEnabled(True)
        self._chain_copy.setEnabled(True)

    def _clear_chain(self) -> None:
        for index in range(self._chain_list.count()):
            self._chain_list.item(index).setCheckState(Qt.Unchecked)

    def _add_chain_pose(self) -> None:
        if self._chain_result is None:
            return
        self.pose_created.emit([row[:] for row in self._chain_result], "链式位姿")

    def _copy_chain(self) -> None:
        if self._chain_result is None:
            return
        pose = Pose(self._chain_result)
        text = (
            f"{self._chain_subtitle.text()}\n"
            f"{pose.matrix_text()}\n\n{pose.values.report()}"
        )
        QApplication.clipboard().setText(text)
        self._chain_copy.setIcon(icon("check", SUCCESS, 15))
        self._copy_timer.start(1200)

    # ------------------------------------------------------------------
    # 旋转 / 四元数
    # ------------------------------------------------------------------

    def _build_rotation_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        properties_card = QFrame()
        properties_card.setObjectName("Card")
        card_layout = QVBoxLayout(properties_card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        title = QLabel("轴角与矩阵性质")
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("位姿")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._rotation_pose = QComboBox()
        row.addWidget(label)
        row.addWidget(self._rotation_pose, 1)
        card_layout.addLayout(row)

        self._rotation_axis = self._make_value_row(card_layout, "转轴 / °")
        self._rotation_rotvec = self._make_value_row(card_layout, "旋转向量")
        self._rotation_props = self._make_value_row(card_layout, "矩阵性质")
        layout.addWidget(properties_card)

        quaternion_card = QFrame()
        quaternion_card.setObjectName("Card")
        card_layout = QVBoxLayout(quaternion_card)
        card_layout.setContentsMargins(14, 12, 14, 13)
        card_layout.setSpacing(8)

        title = QLabel("四元数运算与插值")
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("四元数 A")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._quat_a = QComboBox()
        row.addWidget(label)
        row.addWidget(self._quat_a, 1)
        card_layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("四元数 B")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._quat_b = QComboBox()
        row.addWidget(label)
        row.addWidget(self._quat_b, 1)
        card_layout.addLayout(row)

        self._quat_a_text = self._make_value_row(card_layout, "qA")
        self._quat_b_text = self._make_value_row(card_layout, "qB")
        self._quat_product = self._make_value_row(card_layout, "qA⊗qB")
        self._quat_conjugate = self._make_value_row(card_layout, "qA*")

        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)
        label = QLabel("slerp t")
        label.setObjectName("ValueKey")
        label.setFixedWidth(64)
        self._slerp_slider = QSlider(Qt.Horizontal)
        self._slerp_slider.setObjectName("JointSlider")
        self._slerp_slider.setRange(0, 1000)
        self._slerp_slider.setValue(500)
        self._slerp_slider.setCursor(Qt.PointingHandCursor)
        self._slerp_value = QLabel("0.500")
        self._slerp_value.setFont(mono_font(10))
        slider_row.addWidget(label)
        slider_row.addWidget(self._slerp_slider, 1)
        slider_row.addWidget(self._slerp_value)
        card_layout.addLayout(slider_row)

        self._slerp_quaternion_text = self._make_value_row(card_layout, "插值 q")
        self._slerp_pose_text = self._make_value_row(card_layout, "插值位姿")
        self._slerp_add = QPushButton("插值位姿加入场景")
        self._slerp_add.setObjectName("Ghost")
        self._slerp_add.setIcon(icon("plus", "#475569", 15))
        self._slerp_add.setCursor(Qt.PointingHandCursor)
        self._slerp_add.clicked.connect(self._add_slerp_pose)
        card_layout.addWidget(self._slerp_add)
        layout.addWidget(quaternion_card)
        layout.addStretch(1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._rotation_pose.currentIndexChanged.connect(self._recompute_rotation)
        self._quat_a.currentIndexChanged.connect(self._recompute_rotation)
        self._quat_b.currentIndexChanged.connect(self._recompute_rotation)
        self._slerp_slider.valueChanged.connect(self._recompute_rotation)
        return tab

    def _recompute_rotation(self) -> None:
        index = self._rotation_pose.currentIndex()
        if 0 <= index < len(self._entries):
            pose = self._entries[index].pose
            axis, angle = axis_angle_from_rotation(pose.values.rotation)
            rotvec = rotation_vector_from_rotation(pose.values.rotation)
            determinant, error, trace = matrix_properties(pose.matrix)
            self._rotation_axis.setText(
                f"({format_number(axis[0], 4)}, {format_number(axis[1], 4)}, "
                f"{format_number(axis[2], 4)})   {format_number(angle, 3)}°"
            )
            self._rotation_rotvec.setText(
                "("
                + ", ".join(format_number(value, 5) for value in rotvec)
                + ") rad"
            )
            self._rotation_props.setText(
                f"det {format_number(determinant, 5)}   "
                f"正交误差 {format_number(error, 6)}   "
                f"trace {format_number(trace, 5)}"
            )
        else:
            self._rotation_axis.setText("—")
            self._rotation_rotvec.setText("—")
            self._rotation_props.setText("—")

        index_a = self._quat_a.currentIndex()
        index_b = self._quat_b.currentIndex()
        if not (
            0 <= index_a < len(self._entries)
            and 0 <= index_b < len(self._entries)
        ):
            self._quat_a_text.setText("—")
            self._quat_b_text.setText("—")
            self._quat_product.setText("—")
            self._quat_conjugate.setText("—")
            self._slerp_quaternion_text.setText("—")
            self._slerp_pose_text.setText("—")
            self._slerp_add.setEnabled(False)
            self._slerp_slider.setEnabled(False)
            self._slerp_matrix = None
            return

        pose_a = self._entries[index_a].pose
        pose_b = self._entries[index_b].pose
        quaternion_a = pose_a.values.quaternion
        quaternion_b = pose_b.values.quaternion
        product = quaternion_multiply(quaternion_a, quaternion_b)
        conjugate = quaternion_conjugate(quaternion_a)

        self._quat_a_text.setText(_quaternion_text(quaternion_a))
        self._quat_b_text.setText(_quaternion_text(quaternion_b))
        self._quat_product.setText(_quaternion_text(product))
        self._quat_conjugate.setText(_quaternion_text(conjugate))

        t = self._slerp_slider.value() / 1000.0
        self._slerp_value.setText(f"{t:.3f}")
        interpolated = slerp_quaternion(quaternion_a, quaternion_b, t)
        rotation = rotation_from_quaternion(*interpolated)
        position = tuple(
            pose_a.values.position[i]
            + (pose_b.values.position[i] - pose_a.values.position[i]) * t
            for i in range(3)
        )
        matrix = [
            [rotation[0][0], rotation[0][1], rotation[0][2], position[0]],
            [rotation[1][0], rotation[1][1], rotation[1][2], position[1]],
            [rotation[2][0], rotation[2][1], rotation[2][2], position[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]
        self._slerp_matrix = matrix
        pose = Pose(matrix)
        self._slerp_quaternion_text.setText(_quaternion_text(interpolated))
        self._slerp_pose_text.setText(
            f"x {format_number(pose.values.position[0], 4)}   "
            f"y {format_number(pose.values.position[1], 4)}   "
            f"z {format_number(pose.values.position[2], 4)}   "
            f"yaw {format_number(pose.values.yaw, 2)}°"
        )
        self._slerp_slider.setEnabled(True)
        self._slerp_add.setEnabled(True)

    def _add_slerp_pose(self) -> None:
        if self._slerp_matrix is None:
            return
        t = self._slerp_slider.value() / 1000.0
        self.pose_created.emit(
            [row[:] for row in self._slerp_matrix], f"Slerp {t:.2f}"
        )

    # ------------------------------------------------------------------
    # 数据 / 轨迹
    # ------------------------------------------------------------------

    def _build_data_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        export_card = QFrame()
        export_card.setObjectName("Card")
        export_layout = QVBoxLayout(export_card)
        export_layout.setContentsMargins(14, 12, 14, 13)
        export_layout.setSpacing(8)

        title = QLabel("导入 / 导出")
        title.setObjectName("SectionTitle")
        export_layout.addWidget(title)
        hint = QLabel(
            "CSV：name + 16 个矩阵元素；JSON：{\"poses\": [{\"name\", \"matrix\"}]}。"
        )
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        export_layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        for text, slot in (
            ("导出 CSV", self._export_csv),
            ("导出 JSON", self._export_json),
            ("导入 JSON", self._import_json),
            ("导入 CSV", self._import_csv),
        ):
            button = QPushButton(text)
            button.setObjectName("Ghost")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            buttons.addWidget(button, 1)
        export_layout.addLayout(buttons)
        layout.addWidget(export_card)

        trajectory_card = QFrame()
        trajectory_card.setObjectName("Card")
        trajectory_layout = QVBoxLayout(trajectory_card)
        trajectory_layout.setContentsMargins(14, 12, 14, 13)
        trajectory_layout.setSpacing(8)

        title = QLabel("轨迹分析")
        title.setObjectName("SectionTitle")
        trajectory_layout.addWidget(title)

        self._trajectory_count = self._make_value_row(
            trajectory_layout, "位姿数", width=90
        )
        self._trajectory_length = self._make_value_row(
            trajectory_layout, "总路程 / m", width=90
        )
        self._trajectory_rotation = self._make_value_row(
            trajectory_layout, "总转角", width=90
        )
        self._trajectory_displacement = self._make_value_row(
            trajectory_layout, "首末位移 / m", width=90
        )

        self._trajectory_table = QTableWidget(0, 5)
        self._trajectory_table.setObjectName("TrajectoryTable")
        self._trajectory_table.setHorizontalHeaderLabels(
            ["段", "从", "到", "距离 / m", "转角"]
        )
        self._trajectory_table.verticalHeader().setVisible(False)
        self._trajectory_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self._trajectory_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        trajectory_layout.addWidget(self._trajectory_table, 1)

        layout.addWidget(trajectory_card, 1)
        return tab

    def _refresh_trajectory(self) -> None:
        count = len(self._entries)
        self._trajectory_count.setText(str(count))
        if count < 2:
            self._trajectory_length.setText("—")
            self._trajectory_rotation.setText("—")
            self._trajectory_displacement.setText("—")
            self._trajectory_table.setRowCount(0)
            return

        total_length = 0.0
        total_rotation = 0.0
        rows = []
        for index in range(count - 1):
            entry_a = self._entries[index]
            entry_b = self._entries[index + 1]
            ax, ay, az = entry_a.pose.values.position
            bx, by, bz = entry_b.pose.values.position
            distance = math.sqrt(
                (bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2
            )
            angle = rotation_angle_between(
                entry_a.pose.values.rotation, entry_b.pose.values.rotation
            )
            total_length += distance
            total_rotation += angle
            rows.append(
                (str(index + 1), entry_a.name, entry_b.name, distance, angle)
            )

        first = self._entries[0].pose.values.position
        last = self._entries[-1].pose.values.position
        displacement = math.sqrt(
            (last[0] - first[0]) ** 2
            + (last[1] - first[1]) ** 2
            + (last[2] - first[2]) ** 2
        )
        self._trajectory_length.setText(format_number(total_length, 4))
        self._trajectory_rotation.setText(f"{format_number(total_rotation, 2)}°")
        self._trajectory_displacement.setText(format_number(displacement, 4))

        self._trajectory_table.setRowCount(len(rows))
        for row_index, (segment, name_a, name_b, distance, angle) in enumerate(rows):
            values = (
                segment,
                name_a,
                name_b,
                format_number(distance, 4),
                f"{format_number(angle, 2)}°",
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_index >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._trajectory_table.setItem(row_index, col_index, item)

    def _export_csv(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "导出 CSV", "当前没有位姿可导出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出位姿 CSV", "poses.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["name"]
                    + [f"m{row}{col}" for row in range(4) for col in range(4)]
                )
                for entry in self._entries:
                    writer.writerow(
                        [entry.name]
                        + [
                            format_number(entry.pose.matrix[row][col], 9)
                            for row in range(4)
                            for col in range(4)
                        ]
                    )
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出 CSV", f"已导出 {len(self._entries)} 个位姿。")

    def _export_json(self) -> None:
        if not self._entries:
            QMessageBox.information(self, "导出 JSON", "当前没有位姿可导出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出位姿 JSON", "poses.json", "JSON 文件 (*.json)"
        )
        if not path:
            return
        payload = {
            "poses": [
                {"name": entry.name, "matrix": entry.pose.matrix}
                for entry in self._entries
            ]
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出 JSON", f"已导出 {len(self._entries)} 个位姿。")

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入位姿 JSON", "", "JSON 文件 (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        items = data.get("poses", []) if isinstance(data, dict) else data
        imported = []
        errors = 0
        if isinstance(items, list):
            for item in items:
                try:
                    if isinstance(item, dict):
                        matrix = item.get("matrix")
                        name = str(item.get("name", ""))
                    else:
                        matrix = item
                        name = ""
                    valid = self._validate_matrix(matrix)
                    if valid is None:
                        errors += 1
                        continue
                    imported.append((name, valid))
                except (TypeError, ValueError):
                    errors += 1
        if imported:
            self.poses_imported.emit(imported)
        QMessageBox.information(
            self,
            "导入 JSON",
            f"已导入 {len(imported)} 个位姿"
            + (f"，跳过 {errors} 条无效数据。" if errors else "。"),
        )

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入位姿 CSV", "", "CSV 文件 (*.csv)"
        )
        if not path:
            return
        imported = []
        errors = 0
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.reader(handle))
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        for row in rows:
            cells = [cell.strip() for cell in row if cell.strip()]
            if not cells:
                continue
            numeric = []
            for cell in cells:
                try:
                    numeric.append(float(cell))
                except ValueError:
                    continue
            if len(numeric) < 16:
                if len(numeric) > 0:
                    errors += 1
                continue
            values = numeric[:16]
            matrix = [values[index * 4 : index * 4 + 4] for index in range(4)]
            valid = self._validate_matrix(matrix)
            if valid is None:
                errors += 1
                continue
            try:
                name = cells[0] if float(cells[0]) != numeric[0] else ""
            except (ValueError, IndexError):
                name = cells[0]
            imported.append((name, valid))
        if imported:
            self.poses_imported.emit(imported)
        QMessageBox.information(
            self,
            "导入 CSV",
            f"已导入 {len(imported)} 个位姿"
            + (f"，跳过 {errors} 条无效数据。" if errors else "。"),
        )

    @staticmethod
    def _validate_matrix(matrix) -> list[list[float]] | None:
        if not isinstance(matrix, list) or len(matrix) != 4:
            return None
        rows = []
        for row in matrix:
            if not isinstance(row, list) or len(row) != 4:
                return None
            try:
                rows.append([float(value) for value in row])
            except (TypeError, ValueError):
                return None
        if any(abs(rows[3][index] - target) > 1e-6 for index, target in enumerate((0, 0, 0, 1))):
            return None
        return rows

    # ------------------------------------------------------------------
    # 控件辅助
    # ------------------------------------------------------------------

    def _make_value_row(
        self, layout: QVBoxLayout, key: str, width: int = 64
    ) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(8)
        key_label = QLabel(key)
        key_label.setObjectName("ValueKey")
        key_label.setFixedWidth(width)
        value = QLabel("—")
        value.setFont(mono_font(10))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(key_label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    def _make_matrix_box(
        self, layout: QVBoxLayout
    ) -> list[list[QLabel]]:
        box = QFrame()
        box.setObjectName("InfoBox")
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        labels: list[list[QLabel]] = []
        for row in range(4):
            row_labels = []
            for col in range(4):
                value = QLabel("—")
                value.setFont(mono_font(10))
                value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(value, row, col)
                row_labels.append(value)
            labels.append(row_labels)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        layout.addWidget(box)
        return labels

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------

    def set_pose_entries(self, entries: list) -> None:
        self._entries = list(entries)
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._refresh_transform_frames()
        self._refresh_measure_combos()
        self._refresh_relative_combos()
        self._refresh_vector_combos()
        self._refresh_chain_list()
        self._refresh_rotation_combos()
        self._refresh_trajectory()
        self._recompute_chain()
        self._recompute_rotation()

    def _refresh_transform_frames(self) -> None:
        current = self._transform_frame.currentText()
        self._transform_frame.blockSignals(True)
        self._transform_frame.clear()
        self._transform_frame.addItem("世界坐标系")
        for entry in self._entries:
            self._transform_frame.addItem(entry.name)
        if current:
            index = self._transform_frame.findText(current)
            if index >= 0:
                self._transform_frame.setCurrentIndex(index)
        self._transform_frame.blockSignals(False)
        self._recompute_transform()

    def _refresh_measure_combos(self) -> None:
        names = [entry.name for entry in self._entries]
        for combo, fallback_last in ((self._measure_a, False), (self._measure_b, True)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if names:
                combo.setCurrentIndex(
                    names.index(current)
                    if current in names
                    else (len(names) - 1 if fallback_last else 0)
                )
            combo.blockSignals(False)
            combo.setEnabled(len(names) >= 2)
        self._measure_swap.setEnabled(len(names) >= 2)
        self._recompute_measure()

    def _refresh_rotation_combos(self) -> None:
        names = [entry.name for entry in self._entries]
        for combo, fallback_last in (
            (self._rotation_pose, False),
            (self._quat_a, False),
            (self._quat_b, True),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if names:
                combo.setCurrentIndex(
                    names.index(current)
                    if current in names
                    else (len(names) - 1 if fallback_last else 0)
                )
            combo.blockSignals(False)
        enabled = len(names) >= 2
        self._slerp_slider.setEnabled(enabled)
        self._slerp_add.setEnabled(enabled and self._slerp_matrix is not None)
