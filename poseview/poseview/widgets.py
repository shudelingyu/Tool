"""紧凑版位姿数值面板。"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .math3d import Pose, format_number
from .theme import FAINT, SUCCESS, WARNING, mono_font


class PoseValuePanel(QWidget):
    """展示选中位姿的位置、欧拉角与四元数。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pose: Pose | None = None
        self._name = ""
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)
        self._build()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        title = QLabel("姿态解算")
        title.setObjectName("SectionTitle")
        self._dot = QLabel()
        self._dot.setFixedSize(9, 9)
        self._name_label = QLabel("未选择位姿")
        self._name_label.setObjectName("PoseName")

        self._copy_button = QToolButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setFixedSize(24, 24)
        self._copy_button.setCursor(Qt.PointingHandCursor)
        self._copy_button.setToolTip("复制解算结果与 4x4 矩阵")
        self._copy_button.clicked.connect(self._copy)

        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._dot)
        head.addWidget(self._name_label)
        head.addWidget(self._copy_button)
        layout.addLayout(head)

        self._empty = QLabel("选中位姿后显示位置、欧拉角与四元数")
        self._empty.setObjectName("CardHint")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 1, 0, 0)
        body.setSpacing(3)

        self._position_label = self._make_row(body, "位置 / m")
        self._euler_label = self._make_row(body, "RPY / °")
        self._quaternion_label = self._make_row(body, "四元数")

        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setStyleSheet(f"color: {WARNING};")
        self._warning.hide()
        body.addWidget(self._warning)

        layout.addWidget(self._body)
        layout.addStretch(1)

        self.clear()

    def _make_row(self, layout: QVBoxLayout, key: str) -> QLabel:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        key_label = QLabel(key)
        key_label.setObjectName("ValueKey")
        key_label.setFixedWidth(56)
        key_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        value = QLabel("—")
        value.setFont(mono_font(10))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(key_label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    # ------------------------------------------------------------------
    # 内容更新
    # ------------------------------------------------------------------

    def set_pose(self, pose: Pose, name: str, color: str) -> None:
        self._pose = pose
        self._name = name
        values = pose.values

        self._dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self._name_label.setText(name)
        self._empty.hide()
        self._body.show()
        self._copy_button.setEnabled(True)

        x, y, z = values.position
        position_text = (
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   z {format_number(z, 4)}"
        )
        euler_text = (
            f"roll {format_number(values.roll, 2)}°   "
            f"pitch {format_number(values.pitch, 2)}°   "
            f"yaw {format_number(values.yaw, 2)}°"
        )
        w, qx, qy, qz = values.quaternion
        quaternion_text = (
            f"w {format_number(w, 3)}   x {format_number(qx, 3)}   "
            f"y {format_number(qy, 3)}   z {format_number(qz, 3)}"
        )

        for label, text in (
            (self._position_label, position_text),
            (self._euler_label, euler_text),
            (self._quaternion_label, quaternion_text),
        ):
            label.setText(text)
            label.setToolTip(text)

        if values.orthonormal:
            self._warning.hide()
        else:
            self._warning.setText("旋转矩阵非严格正交，已按正交化结果解算。")
            self._warning.show()

    def clear(self) -> None:
        self._pose = None
        self._name = ""
        self._dot.setStyleSheet(f"background: {FAINT}; border-radius: 4px;")
        self._name_label.setText("未选择位姿")
        self._empty.show()
        self._body.hide()
        self._warning.hide()
        self._copy_button.setEnabled(False)

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------

    def _copy(self) -> None:
        if self._pose is None:
            return
        text = (
            f"{self._name}\n{self._pose.values.report()}\n\n"
            f"4x4 matrix:\n{self._pose.matrix_text()}"
        )
        QApplication.clipboard().setText(text)
        self._copy_button.setIcon(icon("check", SUCCESS, 15))
        self._copy_button.setToolTip("已复制")
        self._copy_timer.start(1200)

    def _restore_copy_icon(self) -> None:
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setToolTip("复制解算结果与 4x4 矩阵")
