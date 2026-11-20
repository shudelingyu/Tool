"""相对位姿计算对话框。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from .icons import icon
from .math3d import Pose, format_number, relative_transform
from .theme import SUCCESS, mono_font


class RelativePoseDialog(QDialog):
    """计算 B 在 A 坐标系下的位姿。"""

    def __init__(
        self,
        entries: list[tuple[str, list[list[float]]]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._entries = entries
        self._relative: Pose | None = None
        self._name_a = ""
        self._name_b = ""
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)

        self.setObjectName("RelativeDialog")
        self.setWindowTitle("相对位姿计算")
        self.resize(580, 660)
        self.setMinimumWidth(520)
        self._build()
        self._recompute()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("相对位姿计算")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "计算 B 在 A 坐标系下的位姿：T_A→B = inv(T_A) · T_B。\n"
            "适用于手眼标定、传感器外参、工具坐标系排查。"
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        selector = QFrame()
        selector.setObjectName("Card")
        selector_layout = QVBoxLayout(selector)
        selector_layout.setContentsMargins(14, 12, 14, 12)
        selector_layout.setSpacing(8)

        self._combo_a = QComboBox()
        self._combo_b = QComboBox()
        for name, _matrix in self._entries:
            self._combo_a.addItem(name)
            self._combo_b.addItem(name)
        self._combo_a.setCurrentIndex(0)
        self._combo_b.setCurrentIndex(len(self._entries) - 1)

        row_a = QHBoxLayout()
        row_a.setSpacing(8)
        label_a = QLabel("坐标系 A")
        label_a.setObjectName("ValueKey")
        label_a.setFixedWidth(64)
        row_a.addWidget(label_a)
        row_a.addWidget(self._combo_a, 1)
        selector_layout.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(8)
        label_b = QLabel("坐标系 B")
        label_b.setObjectName("ValueKey")
        label_b.setFixedWidth(64)
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
        selector_layout.addLayout(row_b)

        layout.addWidget(selector)

        result = QFrame()
        result.setObjectName("Card")
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(14, 12, 14, 14)
        result_layout.setSpacing(8)

        result_head = QHBoxLayout()
        result_head.setSpacing(8)
        result_title = QLabel("计算结果")
        result_title.setObjectName("SectionTitle")
        self._subtitle = QLabel()
        self._subtitle.setObjectName("CardHint")
        self._copy_button = QToolButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setFixedSize(26, 26)
        self._copy_button.setCursor(Qt.PointingHandCursor)
        self._copy_button.setToolTip("复制 4x4 矩阵与姿态")
        self._copy_button.clicked.connect(self._copy)
        result_head.addWidget(result_title)
        result_head.addStretch(1)
        result_head.addWidget(self._subtitle)
        result_head.addWidget(self._copy_button)
        result_layout.addLayout(result_head)

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
                value.setMinimumWidth(66)
                matrix_layout.addWidget(value, row, col)
                row_labels.append(value)
            self._matrix_labels.append(row_labels)
        for col in range(4):
            matrix_layout.setColumnStretch(col, 1)
        result_layout.addWidget(matrix_box)

        self._position_label = self._make_value_row(result_layout, "位置 / m")
        self._euler_label = self._make_value_row(result_layout, "RPY / °")
        self._quaternion_label = self._make_value_row(result_layout, "四元数")
        layout.addWidget(result)

        layout.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

        self._combo_a.currentIndexChanged.connect(self._recompute)
        self._combo_b.currentIndexChanged.connect(self._recompute)

    def _make_value_row(self, layout: QVBoxLayout, key: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(8)
        key_label = QLabel(key)
        key_label.setObjectName("ValueKey")
        key_label.setFixedWidth(64)
        value = QLabel("—")
        value.setFont(mono_font(10.5))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(key_label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    # ------------------------------------------------------------------
    # 计算
    # ------------------------------------------------------------------

    def _recompute(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        if not (0 <= index_a < len(self._entries) and 0 <= index_b < len(self._entries)):
            return
        self._name_a, matrix_a = self._entries[index_a]
        self._name_b, matrix_b = self._entries[index_b]
        relative = relative_transform(matrix_a, matrix_b)
        self._relative = Pose(relative)

        for row in range(4):
            for col in range(4):
                self._matrix_labels[row][col].setText(format_number(relative[row][col], 6))

        values = self._relative.values
        x, y, z = values.position
        self._position_label.setText(
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   z {format_number(z, 4)}"
        )
        self._euler_label.setText(
            f"roll {format_number(values.roll, 3)}°   "
            f"pitch {format_number(values.pitch, 3)}°   "
            f"yaw {format_number(values.yaw, 3)}°"
        )
        w, qx, qy, qz = values.quaternion
        self._quaternion_label.setText(
            f"w {format_number(w, 4)}   x {format_number(qx, 4)}   "
            f"y {format_number(qy, 4)}   z {format_number(qz, 4)}"
        )
        self._subtitle.setText(f"{self._name_b} 在 {self._name_a} 中")

    def _swap(self) -> None:
        index_a = self._combo_a.currentIndex()
        index_b = self._combo_b.currentIndex()
        self._combo_a.blockSignals(True)
        self._combo_b.blockSignals(True)
        self._combo_a.setCurrentIndex(index_b)
        self._combo_b.setCurrentIndex(index_a)
        self._combo_a.blockSignals(False)
        self._combo_b.blockSignals(False)
        self._recompute()

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------

    def _copy(self) -> None:
        if self._relative is None:
            return
        text = (
            f"T_A->B: {self._name_b} in {self._name_a}\n"
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
