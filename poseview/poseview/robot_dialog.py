"""机器人关节控制与 IK 校验对话框。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import icon
from .math3d import Pose, format_number, rotation_from_euler
from .theme import DANGER, SUCCESS, WARNING, font, mono_font
from .urdf import UrdfJoint, UrdfRobot

_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


@dataclass
class _Control:
    joint: UrdfJoint
    slider: QSlider
    spin: QDoubleSpinBox
    minimum: float
    maximum: float

    @property
    def is_angular(self) -> bool:
        return self.joint.type in ("revolute", "continuous")

    def to_base(self, display: float) -> float:
        return math.radians(display) if self.is_angular else display

    def to_display(self, base: float) -> float:
        return math.degrees(base) if self.is_angular else base


class RobotDialog(QDialog):
    """关节滑条、FK 结果与目标位姿校验。"""

    angles_changed = pyqtSignal(dict)
    ee_changed = pyqtSignal(str)
    target_changed = pyqtSignal(object)
    clear_requested = pyqtSignal()

    def __init__(
        self,
        robot: UrdfRobot,
        values: dict[str, float],
        ee_link: str,
        target: list[list[float]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._robot = robot
        self._values = dict(values)
        self._ee_link = ee_link or robot.default_ee_link()
        self._ee_matrix: list[list[float]] | None = None
        self._controls: dict[str, _Control] = {}
        self._updating = True
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)

        self.setObjectName("RobotDialog")
        self.setWindowTitle(f"机器人关节 · {robot.name}")
        self.resize(500, 740)
        self.setMinimumSize(440, 560)
        self._build()
        if target is not None:
            self._fill_target(target)
        self._updating = False

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("机器人关节")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            f"{self._robot.name} · {len(self._robot.movable_joints)} 个可动关节"
            " · 仅显示骨架，不加载 mesh"
        )
        subtitle.setObjectName("DialogHint")
        if self._robot.warnings:
            subtitle.setToolTip("\n".join(self._robot.warnings))
        layout.addWidget(subtitle)

        ee_row = QHBoxLayout()
        ee_row.setSpacing(8)
        ee_label = QLabel("末端连杆")
        ee_label.setObjectName("ValueKey")
        ee_label.setFixedWidth(64)
        self._ee_combo = QComboBox()
        options = list(self._robot.leaf_links)
        if self._ee_link and self._ee_link not in options:
            options.insert(0, self._ee_link)
        for name in options:
            self._ee_combo.addItem(name)
        index = self._ee_combo.findText(self._ee_link)
        if index >= 0:
            self._ee_combo.setCurrentIndex(index)
        self._ee_combo.currentTextChanged.connect(self._on_ee_changed)
        ee_row.addWidget(ee_label)
        ee_row.addWidget(self._ee_combo, 1)
        layout.addLayout(ee_row)

        layout.addWidget(self._build_joint_card(), 1)
        layout.addWidget(self._build_fk_card())
        layout.addWidget(self._build_target_card())

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        clear_robot = QPushButton("移除机器人")
        clear_robot.setObjectName("Ghost")
        clear_robot.setIcon(icon("trash", "#475569", 15))
        clear_robot.setCursor(Qt.PointingHandCursor)
        clear_robot.clicked.connect(self.clear_requested.emit)
        close_button = QPushButton("关闭")
        close_button.setObjectName("Ghost")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.close)
        bottom.addWidget(clear_robot)
        bottom.addStretch(1)
        bottom.addWidget(close_button)
        layout.addLayout(bottom)

    def _build_joint_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 11)
        card_layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("关节控制")
        title.setObjectName("SectionTitle")
        reset_button = QPushButton("全部归零")
        reset_button.setObjectName("Ghost")
        reset_button.setCursor(Qt.PointingHandCursor)
        reset_button.clicked.connect(self._set_all_zero)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(reset_button)
        card_layout.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        rows = QVBoxLayout(container)
        rows.setContentsMargins(0, 0, 2, 0)
        rows.setSpacing(6)

        if not self._robot.movable_joints:
            empty = QLabel("该 URDF 没有可动关节")
            empty.setObjectName("CardHint")
            rows.addWidget(empty)
        for joint in self._robot.movable_joints:
            rows.addWidget(self._build_joint_row(joint))
        rows.addStretch(1)

        scroll.setWidget(container)
        scroll.setMinimumHeight(140)
        card_layout.addWidget(scroll, 1)
        return card

    def _build_joint_row(self, joint: UrdfJoint) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        name = QLabel(joint.name)
        name.setObjectName("ValueNum")
        name.setFont(font(11))
        name.setFixedWidth(108)
        name.setToolTip(joint.name)

        if joint.type in ("revolute", "continuous"):
            minimum = math.degrees(joint.lower)
            maximum = math.degrees(joint.upper)
            suffix = " °"
            decimals = 1
            step = 1.0
        else:
            minimum = joint.lower
            maximum = joint.upper
            suffix = " m"
            decimals = 3
            step = 0.01
        if not math.isfinite(minimum) or not math.isfinite(maximum) or maximum - minimum < 1e-9:
            minimum, maximum = (-180.0, 180.0) if joint.type != "prismatic" else (-0.5, 0.5)
            suffix = " °" if joint.type != "prismatic" else " m"

        slider = QSlider(Qt.Horizontal)
        slider.setObjectName("JointSlider")
        slider.setRange(0, 1000)
        slider.setCursor(Qt.PointingHandCursor)

        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setSuffix(suffix)
        spin.setKeyboardTracking(False)
        spin.setAlignment(Qt.AlignRight)
        spin.setFixedWidth(92)

        control = _Control(joint, slider, spin, minimum, maximum)
        self._controls[joint.name] = control

        display = control.to_display(self._values.get(joint.name, 0.0))
        display = max(minimum, min(maximum, display))
        spin.setValue(display)
        slider.setValue(self._to_slider(control, display))

        slider.valueChanged.connect(
            lambda value, key=joint.name: self._on_slider(key, value)
        )
        spin.valueChanged.connect(
            lambda value, key=joint.name: self._on_spin(key, value)
        )

        row_layout.addWidget(name)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(spin)
        return row

    def _build_fk_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 11)
        card_layout.setSpacing(5)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("末端位姿 / FK")
        title.setObjectName("SectionTitle")
        self._copy_button = QToolButton()
        self._copy_button.setObjectName("IconButton")
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setFixedSize(26, 26)
        self._copy_button.setCursor(Qt.PointingHandCursor)
        self._copy_button.setToolTip("复制末端位姿与 4x4 矩阵")
        self._copy_button.clicked.connect(self._copy_fk)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._copy_button)
        card_layout.addLayout(head)

        self._fk_position = self._make_value_row(card_layout, "位置 / m")
        self._fk_euler = self._make_value_row(card_layout, "RPY / °")
        self._fk_quaternion = self._make_value_row(card_layout, "四元数")
        return card

    def _build_target_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 11)
        card_layout.setSpacing(6)

        title = QLabel("IK 目标校验")
        title.setObjectName("SectionTitle")
        card_layout.addWidget(title)

        hint = QLabel("校验外部 IK 结果：目标 x y z roll pitch yaw（度）")
        hint.setObjectName("CardHint")
        card_layout.addWidget(hint)

        self._target_input = QLineEdit()
        self._target_input.setObjectName("PoseInput")
        self._target_input.setPlaceholderText("例如 1.2 0.3 0.8 0 0 45")
        self._target_input.returnPressed.connect(self._set_target)
        card_layout.addWidget(self._target_input)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        set_button = QPushButton("设置目标")
        set_button.setObjectName("Ghost")
        set_button.setCursor(Qt.PointingHandCursor)
        set_button.clicked.connect(self._set_target)
        current_button = QPushButton("取当前末端")
        current_button.setObjectName("Ghost")
        current_button.setCursor(Qt.PointingHandCursor)
        current_button.clicked.connect(self._use_current)
        clear_button = QPushButton("清除目标")
        clear_button.setObjectName("Ghost")
        clear_button.setCursor(Qt.PointingHandCursor)
        clear_button.clicked.connect(self._clear_target)
        buttons.addWidget(set_button)
        buttons.addWidget(current_button)
        buttons.addWidget(clear_button)
        card_layout.addLayout(buttons)

        self._target_status = QLabel("未设置目标")
        self._target_status.setFont(font(10.5))
        self._target_status.setStyleSheet("color: #64748B;")
        self._target_status.setWordWrap(True)
        card_layout.addWidget(self._target_status)
        return card

    def _make_value_row(self, layout: QVBoxLayout, key: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(8)
        key_label = QLabel(key)
        key_label.setObjectName("ValueKey")
        key_label.setFixedWidth(64)
        value = QLabel("—")
        value.setFont(mono_font(10))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(key_label)
        row.addWidget(value, 1)
        layout.addLayout(row)
        return value

    # ------------------------------------------------------------------
    # 关节控制
    # ------------------------------------------------------------------

    @staticmethod
    def _to_slider(control: _Control, display: float) -> int:
        if control.maximum - control.minimum < 1e-9:
            return 0
        ratio = (display - control.minimum) / (control.maximum - control.minimum)
        return max(0, min(1000, round(ratio * 1000)))

    def _on_slider(self, name: str, value: int) -> None:
        if self._updating:
            return
        control = self._controls.get(name)
        if control is None:
            return
        display = control.minimum + (control.maximum - control.minimum) * value / 1000.0
        self._updating = True
        control.spin.setValue(display)
        actual = control.spin.value()
        self._updating = False
        self._values[name] = control.to_base(actual)
        self.angles_changed.emit(dict(self._values))

    def _on_spin(self, name: str, display: float) -> None:
        if self._updating:
            return
        control = self._controls.get(name)
        if control is None:
            return
        self._updating = True
        control.slider.setValue(self._to_slider(control, display))
        self._updating = False
        self._values[name] = control.to_base(display)
        self.angles_changed.emit(dict(self._values))

    def _set_all_zero(self) -> None:
        self._updating = True
        for control in self._controls.values():
            base = max(control.joint.lower, min(control.joint.upper, 0.0))
            display = control.to_display(base)
            control.spin.setValue(display)
            control.slider.setValue(self._to_slider(control, control.spin.value()))
            self._values[control.joint.name] = control.to_base(control.spin.value())
        self._updating = False
        self.angles_changed.emit(dict(self._values))

    def _on_ee_changed(self, name: str) -> None:
        if self._updating:
            return
        self._ee_link = name
        self.ee_changed.emit(name)

    # ------------------------------------------------------------------
    # FK 与目标
    # ------------------------------------------------------------------

    def set_fk(self, matrix: list[list[float]]) -> None:
        self._ee_matrix = matrix
        values = Pose(matrix).values
        x, y, z = values.position
        self._fk_position.setText(
            f"x {format_number(x, 4)}   y {format_number(y, 4)}   z {format_number(z, 4)}"
        )
        self._fk_euler.setText(
            f"roll {format_number(values.roll, 2)}°   "
            f"pitch {format_number(values.pitch, 2)}°   "
            f"yaw {format_number(values.yaw, 2)}°"
        )
        w, qx, qy, qz = values.quaternion
        self._fk_quaternion.setText(
            f"w {format_number(w, 3)}   x {format_number(qx, 3)}   "
            f"y {format_number(qy, 3)}   z {format_number(qz, 3)}"
        )

    def set_error(
        self, position_error: float | None, rotation_error: float | None
    ) -> None:
        if position_error is None or rotation_error is None:
            self._target_status.setText("未设置目标")
            self._target_status.setStyleSheet("color: #64748B;")
            return
        if position_error < 0.01:
            position_text = f"{position_error * 1000.0:.2f} mm"
        else:
            position_text = f"{position_error * 1000.0:.1f} mm"
        rotation_text = f"{rotation_error:.2f}°"
        self._target_status.setText(
            f"目标误差：位置 {position_text} · 姿态 {rotation_text}"
        )
        if position_error <= 0.001 and rotation_error <= 0.1:
            color = SUCCESS
        elif position_error >= 0.05 or rotation_error >= 5.0:
            color = DANGER
        else:
            color = WARNING
        self._target_status.setStyleSheet(f"color: {color};")

    def _set_target(self) -> None:
        numbers = [float(match.group(0)) for match in _NUMBER_RE.finditer(self._target_input.text())]
        if len(numbers) != 6:
            self._target_status.setText("需要 6 个数：x y z roll pitch yaw")
            self._target_status.setStyleSheet(f"color: {DANGER};")
            return
        x, y, z, roll, pitch, yaw = numbers
        rotation = rotation_from_euler(roll, pitch, yaw)
        matrix = [
            [rotation[0][0], rotation[0][1], rotation[0][2], x],
            [rotation[1][0], rotation[1][1], rotation[1][2], y],
            [rotation[2][0], rotation[2][1], rotation[2][2], z],
            [0.0, 0.0, 0.0, 1.0],
        ]
        self.target_changed.emit(matrix)

    def _use_current(self) -> None:
        if self._ee_matrix is None:
            return
        values = Pose(self._ee_matrix).values
        x, y, z = values.position
        self._target_input.setText(
            " ".join(
                format_number(value, 4)
                for value in (x, y, z, values.roll, values.pitch, values.yaw)
            )
        )
        self._set_target()

    def _clear_target(self) -> None:
        self._target_input.clear()
        self.target_changed.emit(None)
        self.set_error(None, None)

    def _fill_target(self, matrix: list[list[float]]) -> None:
        values = Pose(matrix).values
        x, y, z = values.position
        self._target_input.setText(
            " ".join(
                format_number(value, 4)
                for value in (x, y, z, values.roll, values.pitch, values.yaw)
            )
        )

    # ------------------------------------------------------------------
    # 复制
    # ------------------------------------------------------------------

    def _copy_fk(self) -> None:
        if self._ee_matrix is None:
            return
        pose = Pose(self._ee_matrix)
        text = (
            f"{self._robot.name} · {self._ee_link}\n"
            f"{pose.values.report()}\n\n4x4 matrix:\n{pose.matrix_text()}"
        )
        QApplication.clipboard().setText(text)
        self._copy_button.setIcon(icon("check", SUCCESS, 15))
        self._copy_button.setToolTip("已复制")
        self._copy_timer.start(1200)

    def _restore_copy_icon(self) -> None:
        self._copy_button.setIcon(icon("copy", "#475569", 15))
        self._copy_button.setToolTip("复制末端位姿与 4x4 矩阵")
