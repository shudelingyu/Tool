"""机器人关节控制与 IK 校验对话框。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
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
    lock: QCheckBox
    minimum: float
    maximum: float
    label: QLabel
    row: QWidget

    @property
    def is_angular(self) -> bool:
        return self.joint.type in ("revolute", "continuous")

    @property
    def is_mimic(self) -> bool:
        return self.joint.is_mimic

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
    visuals_toggled = pyqtSignal(bool)
    skeleton_toggled = pyqtSignal(bool)
    tool_changed = pyqtSignal(int)
    tool_merge_requested = pyqtSignal()
    trajectory_requested = pyqtSignal()

    def __init__(
        self,
        robot: UrdfRobot,
        values: dict[str, float],
        ee_link: str,
        target: list[list[float]] | None = None,
        show_visuals: bool = True,
        parent=None,
        show_skeleton: bool = True,
        tool_names: list[str] | None = None,
        tool_index: int = -1,
    ) -> None:
        super().__init__(parent)
        self._robot = robot
        self._values = dict(values)
        self._ee_link = ee_link or robot.default_ee_link()
        self._ee_matrix: list[list[float]] | None = None
        self._target_matrix: list[list[float]] | None = None
        self._controls: dict[str, _Control] = {}
        self._joint_scroll: QScrollArea | None = None
        self._joint_rows_layout: QVBoxLayout | None = None
        self._selected_control: _Control | None = None
        self._locked: set[str] = set()
        self._tool_names = list(tool_names or [])
        self._tool_index = (
            tool_index
            if 0 <= tool_index < len(self._tool_names)
            else -1
        )
        self._tool_updating = False
        self._initial_visuals = bool(show_visuals)
        self._initial_skeleton = bool(show_skeleton)
        self._updating = True
        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.timeout.connect(self._restore_copy_icon)

        self.setObjectName("RobotDialog")
        self.setWindowTitle(f"机器人关节 · {robot.name}")
        self.resize(1080, 860)
        self.setMinimumSize(940, 720)
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

        self._subtitle = QLabel()
        self._subtitle.setObjectName("DialogHint")
        layout.addWidget(self._subtitle)
        self._update_subtitle()

        tool_row = QHBoxLayout()
        tool_row.setSpacing(8)
        tool_label = QLabel("工具")
        tool_label.setObjectName("ValueKey")
        tool_label.setFixedWidth(64)
        self._tool_combo = QComboBox()
        self._tool_combo.setMaximumWidth(360)
        self._tool_combo.setToolTip("选择安装在机器人上的工具，切换后末端与外观同步更新")
        self._tool_combo.currentIndexChanged.connect(
            self._on_tool_combo_changed
        )
        self._tool_button = QPushButton("拼接工具…")
        self._tool_button.setObjectName("Ghost")
        self._tool_button.setIcon(icon("link", "#475569", 15))
        self._tool_button.setCursor(Qt.PointingHandCursor)
        self._tool_button.setToolTip("加载工具 URDF 并拼接到机器人上")
        self._tool_button.clicked.connect(self.tool_merge_requested.emit)
        self._trajectory_button = QPushButton("轨迹仿真…")
        self._trajectory_button.setObjectName("Ghost")
        self._trajectory_button.setIcon(icon("path", "#475569", 15))
        self._trajectory_button.setCursor(Qt.PointingHandCursor)
        self._trajectory_button.setToolTip("导入关节角文件并逐帧播放机器人运动")
        self._trajectory_button.clicked.connect(
            self.trajectory_requested.emit
        )
        tool_row.addWidget(tool_label)
        tool_row.addWidget(self._tool_combo, 1)
        tool_row.addWidget(self._tool_button)
        tool_row.addWidget(self._trajectory_button)
        layout.addLayout(tool_row)
        self.set_tool_selection(self._tool_names, self._tool_index)

        ee_row = QHBoxLayout()
        ee_row.setSpacing(8)
        ee_label = QLabel("末端连杆")
        ee_label.setObjectName("ValueKey")
        ee_label.setFixedWidth(64)
        self._ee_combo = QComboBox()
        self._refresh_ee_options()
        self._ee_combo.currentTextChanged.connect(self._on_ee_changed)
        self._ee_combo.setMaximumWidth(360)
        ee_row.addWidget(ee_label)
        ee_row.addWidget(self._ee_combo, 1)
        self._visuals_check = QCheckBox("外观")
        self._visuals_check.setChecked(
            bool(self._robot.visuals) and self._initial_visuals
        )
        self._visuals_check.setEnabled(bool(self._robot.visuals))
        self._visuals_check.setCursor(Qt.PointingHandCursor)
        if self._robot.visuals:
            self._visuals_check.setToolTip("显示 / 隐藏 URDF 外观（box/cylinder/sphere/STL/OBJ）")
        else:
            self._visuals_check.setToolTip(
                "该 URDF 没有可绘制外观（box/cylinder/sphere/STL/OBJ）"
            )
        self._visuals_check.toggled.connect(self.visuals_toggled.emit)
        ee_row.addWidget(self._visuals_check)
        self._skeleton_check = QCheckBox("骨架")
        self._skeleton_check.setChecked(self._initial_skeleton)
        self._skeleton_check.setCursor(Qt.PointingHandCursor)
        self._skeleton_check.setToolTip(
            "显示 / 隐藏骨架、关节轴与各连杆坐标系（外观单独控制）"
        )
        self._skeleton_check.toggled.connect(self.skeleton_toggled.emit)
        ee_row.addWidget(self._skeleton_check)
        ee_row.addStretch(1)
        layout.addLayout(ee_row)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_joint_card(), 1)
        right_column = QVBoxLayout()
        right_column.setSpacing(10)
        right_column.addWidget(self._build_fk_card())
        right_column.addWidget(self._build_target_card(), 1)
        body.addLayout(right_column, 1)
        layout.addLayout(body, 1)

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

    def _update_subtitle(self) -> None:
        robot = self._robot
        text = f"{robot.name} · {len(robot.movable_joints)} 个可动关节"
        text += (
            f" · {len(robot.visuals)} 个外观"
            if robot.visuals
            else " · 仅骨架"
        )
        self._subtitle.setText(text)
        self._subtitle.setToolTip(
            "\n".join(robot.warnings) if robot.warnings else ""
        )

    def _refresh_ee_options(self) -> None:
        blocked = self._ee_combo.blockSignals(True)
        self._ee_combo.clear()
        options = list(self._robot.leaf_links)
        if self._ee_link and self._ee_link not in options:
            options.insert(0, self._ee_link)
        self._ee_combo.addItems(options)
        index = self._ee_combo.findText(self._ee_link)
        if index >= 0:
            self._ee_combo.setCurrentIndex(index)
        self._ee_combo.blockSignals(blocked)

    def _populate_joint_rows(self) -> None:
        layout = self._joint_rows_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._controls.clear()
        self._locked &= {joint.name for joint in self._robot.movable_joints}
        if not self._robot.movable_joints:
            empty = QLabel("该 URDF 没有可动关节")
            empty.setObjectName("CardHint")
            layout.addWidget(empty)
        for joint in self._robot.movable_joints:
            layout.addWidget(self._build_joint_row(joint))
        layout.addStretch(1)
        for name in list(self._locked):
            control = self._controls.get(name)
            if control is None or control.is_mimic:
                continue
            control.lock.setChecked(True)

    def set_tool_selection(self, names: list[str], index: int) -> None:
        """更新工具下拉列表，不触发切换信号。"""
        self._tool_names = list(names)
        self._tool_index = (
            index if 0 <= index < len(self._tool_names) else -1
        )
        self._tool_updating = True
        blocked = self._tool_combo.blockSignals(True)
        self._tool_combo.clear()
        self._tool_combo.addItem("无工具")
        self._tool_combo.addItems(self._tool_names)
        self._tool_combo.setCurrentIndex(self._tool_index + 1)
        self._tool_combo.blockSignals(blocked)
        self._tool_updating = False

    def _on_tool_combo_changed(self, position: int) -> None:
        if self._tool_updating:
            return
        self.tool_changed.emit(position - 1)

    def reload_robot(
        self,
        robot: UrdfRobot,
        values: dict[str, float],
        ee_link: str,
        tool_names: list[str] | None = None,
        tool_index: int = -1,
    ) -> None:
        """模型或工具变化后原地重建关节控件，保留目标与权重设置。"""
        self._robot = robot
        self._values = dict(values)
        self._ee_link = ee_link or robot.default_ee_link()
        self._ee_matrix = None
        self._selected_control = None
        self.setWindowTitle(f"机器人关节 · {robot.name}")
        self._update_subtitle()
        self._refresh_ee_options()
        self._populate_joint_rows()
        self._visuals_check.setEnabled(bool(robot.visuals))
        if robot.visuals:
            self._visuals_check.setToolTip(
                "显示 / 隐藏 URDF 外观（box/cylinder/sphere/STL/OBJ）"
            )
        else:
            self._visuals_check.setToolTip(
                "该 URDF 没有可绘制外观（box/cylinder/sphere/STL/OBJ）"
            )
        self.set_tool_selection(
            tool_names if tool_names is not None else self._tool_names,
            tool_index,
        )
        self._set_ik_status("尚未求解", "#64748B")

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
        scroll.viewport().setObjectName("RobotScrollViewport")
        scroll.viewport().setStyleSheet(
            "QWidget#RobotScrollViewport { background: transparent; }"
        )
        container = QWidget()
        container.setObjectName("RobotScrollContainer")
        container.setStyleSheet(
            "QWidget#RobotScrollContainer { background: transparent; }"
        )
        rows = QVBoxLayout(container)
        rows.setContentsMargins(0, 0, 2, 0)
        rows.setSpacing(6)
        self._joint_rows_layout = rows
        self._populate_joint_rows()

        scroll.setWidget(container)
        scroll.setMinimumHeight(140)
        self._joint_scroll = scroll
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
        name.setFixedWidth(100)
        name.setToolTip(joint.name)

        lock = QCheckBox("锁")
        lock.setToolTip("锁定该关节：滑条不可调，且不参与 IK")
        lock.setCursor(Qt.PointingHandCursor)
        lock.setFixedWidth(36)
        lock.toggled.connect(
            lambda checked, key=joint.name: self._on_lock_toggled(key, checked)
        )

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

        control = _Control(
            joint, slider, spin, lock, minimum, maximum, name, row
        )
        self._controls[joint.name] = control

        display = control.to_display(self._values.get(joint.name, 0.0))
        display = max(minimum, min(maximum, display))
        spin.setValue(display)
        slider.setValue(self._to_slider(control, display))

        if control.is_mimic:
            description = (
                f"跟随 {joint.mimic}（×{joint.mimic_multiplier:g}"
                f" + {joint.mimic_offset:g}），由源关节驱动"
            )
            name.setToolTip(description)
            slider.setToolTip(description)
            spin.setToolTip(description)
            lock.setToolTip("mimic 关节由源关节驱动，不能单独锁定")
            lock.setEnabled(False)
            slider.setEnabled(False)
            spin.setEnabled(False)
            name.setStyleSheet("color: #64748B;")

        slider.valueChanged.connect(
            lambda value, key=joint.name: self._on_slider(key, value)
        )
        spin.valueChanged.connect(
            lambda value, key=joint.name: self._on_spin(key, value)
        )

        row_layout.addWidget(name)
        row_layout.addWidget(lock)
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

        hint = QLabel("设置目标位姿后可一键求解 IK，或校验外部 IK 结果")
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

        weights = QHBoxLayout()
        weights.setSpacing(6)
        position_label = QLabel("位置权重")
        position_label.setObjectName("ValueKey")
        self._position_weight = QDoubleSpinBox()
        self._position_weight.setRange(0.0, 1.0)
        self._position_weight.setDecimals(2)
        self._position_weight.setSingleStep(0.1)
        self._position_weight.setValue(1.0)
        self._position_weight.setFixedWidth(70)
        self._position_weight.setToolTip("IK 中位置误差的权重（0~1）")
        orientation_label = QLabel("姿态权重")
        orientation_label.setObjectName("ValueKey")
        self._orientation_weight = QDoubleSpinBox()
        self._orientation_weight.setRange(0.0, 1.0)
        self._orientation_weight.setDecimals(2)
        self._orientation_weight.setSingleStep(0.1)
        self._orientation_weight.setValue(1.0)
        self._orientation_weight.setFixedWidth(70)
        self._orientation_weight.setToolTip("IK 中姿态误差的权重（0~1）")
        weights.addWidget(position_label)
        weights.addWidget(self._position_weight)
        weights.addStretch(1)
        weights.addWidget(orientation_label)
        weights.addWidget(self._orientation_weight)
        card_layout.addLayout(weights)

        self._solve_button = QPushButton("求解 IK")
        self._solve_button.setObjectName("Primary")
        self._solve_button.setCursor(Qt.PointingHandCursor)
        self._solve_button.setToolTip("以当前目标位姿为输入，求解关节角")
        self._solve_button.clicked.connect(self._solve_ik)
        card_layout.addWidget(self._solve_button)

        self._ik_status = QLabel("尚未求解")
        self._ik_status.setFont(font(10.5))
        self._ik_status.setStyleSheet("color: #64748B;")
        self._ik_status.setWordWrap(True)
        card_layout.addWidget(self._ik_status)

        self._target_status = QLabel("未设置目标")
        self._target_status.setFont(font(10.5))
        self._target_status.setStyleSheet("color: #64748B;")
        self._target_status.setWordWrap(True)
        card_layout.addWidget(self._target_status)
        card_layout.addStretch(1)
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
        if self._updating or name in self._locked:
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
        self._sync_mimic_values()
        self.angles_changed.emit(dict(self._values))

    def _on_spin(self, name: str, display: float) -> None:
        if self._updating or name in self._locked:
            return
        control = self._controls.get(name)
        if control is None or control.is_mimic:
            return
        self._updating = True
        control.slider.setValue(self._to_slider(control, display))
        self._updating = False
        self._values[name] = control.to_base(display)
        self._sync_mimic_values()
        self.angles_changed.emit(dict(self._values))

    def _sync_mimic_values(self) -> None:
        """按源关节刷新 mimic 关节的显示与内部值。"""
        for control in self._controls.values():
            if not control.is_mimic:
                continue
            base = self._robot.effective_value(control.joint, self._values)
            self._values[control.joint.name] = base
            display = control.to_display(base)
            display = max(control.minimum, min(control.maximum, display))
            self._updating = True
            control.spin.setValue(display)
            control.slider.setValue(self._to_slider(control, display))
            self._updating = False

    def _on_lock_toggled(self, name: str, checked: bool) -> None:
        control = self._controls.get(name)
        if control is None:
            return
        if checked:
            self._locked.add(name)
        else:
            self._locked.discard(name)
        control.slider.setEnabled(not checked)
        control.spin.setEnabled(not checked)

    def apply_values(self, values: dict[str, float]) -> None:
        """外部（数据列表滑条）改变关节值时同步界面，不触发信号。"""
        self._values = dict(values)
        self._apply_values(self._values)

    def set_visuals_visible(self, visible: bool) -> None:
        blocked = self._visuals_check.blockSignals(True)
        self._visuals_check.setChecked(bool(visible))
        self._visuals_check.blockSignals(blocked)

    def set_skeleton_visible(self, visible: bool) -> None:
        blocked = self._skeleton_check.blockSignals(True)
        self._skeleton_check.setChecked(bool(visible))
        self._skeleton_check.blockSignals(blocked)

    def select_joint(self, name: str) -> None:
        """从数据列表定位关节：滚动到对应行并高亮。"""
        control = self._controls.get(name)
        if control is None:
            return
        if self._selected_control is not None:
            previous = self._selected_control
            previous.label.setStyleSheet(
                "color: #64748B;" if previous.is_mimic else ""
            )
        control.label.setStyleSheet("color: #4F46E5; font-weight: 600;")
        self._selected_control = control
        if self._joint_scroll is not None:
            self._joint_scroll.ensureWidgetVisible(control.row, 0, 0)
        if control.slider.isEnabled():
            control.slider.setFocus()

    def _set_all_zero(self) -> None:
        self._updating = True
        for control in self._controls.values():
            if control.joint.name in self._locked or control.is_mimic:
                continue
            base = max(control.joint.lower, min(control.joint.upper, 0.0))
            display = control.to_display(base)
            control.spin.setValue(display)
            control.slider.setValue(self._to_slider(control, control.spin.value()))
            self._values[control.joint.name] = control.to_base(control.spin.value())
        self._updating = False
        self._sync_mimic_values()
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
        self._target_matrix = matrix
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
        self._target_matrix = None
        self.target_changed.emit(None)
        self.set_error(None, None)
        self._set_ik_status("尚未求解", "#64748B")

    def _fill_target(self, matrix: list[list[float]]) -> None:
        self._target_matrix = matrix
        values = Pose(matrix).values
        x, y, z = values.position
        self._target_input.setText(
            " ".join(
                format_number(value, 4)
                for value in (x, y, z, values.roll, values.pitch, values.yaw)
            )
        )

    def _solve_ik(self) -> None:
        if self._target_matrix is None:
            self._set_ik_status("请先设置目标位姿", DANGER)
            return
        position_weight = self._position_weight.value()
        orientation_weight = self._orientation_weight.value()
        if position_weight + orientation_weight < 1e-6:
            self._set_ik_status("位置/姿态权重不能同时为 0", DANGER)
            return
        result = self._robot.solve_ik(
            self._values,
            self._ee_link,
            self._target_matrix,
            locked=set(self._locked),
            position_weight=position_weight,
            orientation_weight=orientation_weight,
        )
        self._apply_values(result.values)
        self.angles_changed.emit(dict(self._values))
        text = (
            f"{result.message} · {result.iterations} 次迭代 · "
            f"位置误差 {result.position_error * 1000.0:.2f} mm · "
            f"姿态误差 {result.rotation_error:.2f}°"
        )
        if result.success:
            color = SUCCESS
        elif result.position_error < 0.01 and result.rotation_error < 2.0:
            color = WARNING
        else:
            color = DANGER
        self._set_ik_status(text, color)

    def _apply_values(self, values: dict[str, float]) -> None:
        self._updating = True
        for name, control in self._controls.items():
            base = float(values.get(name, self._values.get(name, 0.0)))
            base = max(control.joint.lower, min(control.joint.upper, base))
            display = max(
                control.minimum,
                min(control.maximum, control.to_display(base)),
            )
            control.spin.setValue(display)
            control.slider.setValue(
                self._to_slider(control, control.spin.value())
            )
            self._values[name] = control.to_base(control.spin.value())
        self._updating = False
        self._sync_mimic_values()

    def _set_ik_status(self, text: str, color: str) -> None:
        self._ik_status.setText(text)
        self._ik_status.setStyleSheet(f"color: {color};")

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
